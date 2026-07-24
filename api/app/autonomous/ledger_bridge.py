"""WS-D PR2 — bridge a matter session's structured citations into the chat-path
ledger + fiduciary gate.

Reuses the character-fidelity verifier cascade (exact/tolerant/paraphrase)
and assembles ``MessageCitation`` rows in the same shape the chat path uses,
with no duplication of verification logic.

Only the citation-candidate front-end is session-specific: instead of
extracting citations from assistant text + retrieved chunks (the chat path),
here the planner hands us explicit ``(quote, chunk_id)`` pairs resolved
during the autonomous analysis turn.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.authority import (
    _AuthorityCandidate,
    authority_target,
    load_authority_text as _default_load_authority_text,
)
from app.citation.authority_content_judge import (
    AUTHORITY_CONTENT_JUDGE_BUDGET_USD,
    estimate_authority_content_cost_usd,
    judge_authority_content,
)
from app.citation.caselaw import _CaselawCandidate, locate_passage, opinion_target
from app.citation.extraction import CitationCandidate, locate_in_chunk
from app.citation.gate import compute_and_record_gate
from app.citation.ledger import assemble_ledger_entries
from app.citation.verification import VerificationResult, verify
from app.models.autonomous import AutonomousSession
from app.models.chat import Chat, Message, MessageCitation
from app.models.document import Document, DocumentChunk
from app.models.message_authority_citation import MessageAuthorityCitation
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.research import ResearchOpinionMetadata
from app.research.service import read_opinion as _default_read_opinion

log = logging.getLogger(__name__)


async def build_kb_citations(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    citations: list[tuple[str, str]],  # (quote, chunk_id)
    gateway: Any,
    judge_model: str = "fast",
) -> int:
    """Resolve, verify, and persist KB structured citations into the ledger.

    For each ``(quote, chunk_id)`` pair:

    1. Fetch the ``DocumentChunk`` by ``chunk_id``.
    2. Locate ``quote`` inside ``chunk.content`` via :func:`locate_in_chunk`
       (exact, then fuzzy).  Miss → drop without a row.
    3. Fetch the ``Document`` the chunk belongs to.
    4. Build a :class:`CitationCandidate` with byte-precise offsets into
       ``normalized_content`` (``chunk.char_offset_start + in_chunk_offset``).
    5. Run the verifier cascade via :func:`verify`.  MISS → drop without a
       row (honest-degradation invariant).
    6. ``db.add`` a ``MessageCitation`` row; accumulate the count.

    ``db.flush()`` is called once at the end so callers can roll back the
    entire block as a unit if needed.

    Returns the number of rows added (0 when every citation was unverifiable
    or the chunk / document was not found).  Never fabricates rows.

    Note on lazy-relationship avoidance: ``chunk.document`` is NOT accessed
    (it is a lazy SQLAlchemy relationship that raises ``MissingGreenlet``
    inside an async session).  ``doc.file_id`` is read from the separately
    fetched ``Document`` row instead.
    """
    added = 0

    for quote, chunk_id_str in citations:
        if not quote.strip():
            log.debug(
                "kb citation build: empty quote, skipping",
                extra={"event": "autonomous_kb_citation_skip"},
            )
            continue
        try:
            chunk_uuid = uuid.UUID(str(chunk_id_str))
        except ValueError:
            log.warning(
                "kb citation build: invalid chunk_id",
                extra={"event": "autonomous_kb_citation_skip", "chunk_id": chunk_id_str},
            )
            continue

        try:
            chunk = (
                await db.execute(select(DocumentChunk).where(DocumentChunk.id == chunk_uuid))
            ).scalar_one_or_none()
            if chunk is None:
                log.warning(
                    "kb citation build: chunk not found",
                    extra={"event": "autonomous_kb_citation_skip", "chunk_id": chunk_id_str},
                )
                continue

            span = locate_in_chunk(quote, chunk.content)
            if span is None:
                # Quote not found in chunk — honest drop; no row.
                log.debug(
                    "kb citation build: locate miss",
                    extra={"event": "autonomous_kb_citation_skip", "chunk_id": chunk_id_str},
                )
                continue
            in_start, in_end = span

            doc = (
                await db.execute(select(Document).where(Document.id == chunk.document_id))
            ).scalar_one_or_none()
            if doc is None:
                log.warning(
                    "kb citation build: document not found",
                    extra={
                        "event": "autonomous_kb_citation_skip",
                        "document_id": str(chunk.document_id),
                    },
                )
                continue

            # Use doc.file_id directly — never access chunk.document (lazy
            # relationship; raises MissingGreenlet in async sessions).
            candidate = CitationCandidate(
                source_file_id=doc.file_id,
                source_document_id=chunk.document_id,
                source_offset_start=chunk.char_offset_start + in_start,
                source_offset_end=chunk.char_offset_start + in_end,
                source_page=chunk.page_start,
                source_text=quote,
            )

            # Pass raw Document — it satisfies _DocumentProtocol directly
            # (has id, normalized_content, was_ocrd).  Mirrors what
            # _persist_message_citations in chats.py does.
            result = await verify(candidate, doc, gateway=gateway, judge_model=judge_model)
            if not result.verified:
                # Every stage rejected — honest drop; no row.
                continue

            db.add(
                MessageCitation(
                    message_id=message_id,
                    source_file_id=candidate.source_file_id,
                    source_offset_start=candidate.source_offset_start,
                    source_offset_end=candidate.source_offset_end,
                    source_page=candidate.source_page,
                    source_text=quote,
                    verified=True,
                    verification_method=result.method,
                    verification_confidence=result.confidence,
                    partial=result.partial,
                    tier_envelope=result.tier_envelope,
                )
            )
            added += 1

        except Exception:
            # One bad citation must not sink the rest (per honest-degradation
            # invariant).  Log and continue so the remaining citations still
            # get a chance.
            log.warning(
                "kb citation build: unexpected error, skipping citation",
                extra={"event": "autonomous_kb_citation_skip", "chunk_id": chunk_id_str},
                exc_info=True,
            )

    await db.flush()
    return added


# ---------------------------------------------------------------------------
# Caselaw structured-citation builder
# ---------------------------------------------------------------------------

_LoadOpinion = Callable[..., Awaitable[dict[str, Any]]]

# ---------------------------------------------------------------------------
# Authority structured-citation builder (WS-E PR1b)
# ---------------------------------------------------------------------------

_LoadAuthorityText = Callable[..., Awaitable[str | None]]


class _AuthorityItem(NamedTuple):
    """One authority citation extracted from the findings/evidence pair.

    ``carried_text`` is the evidence body carried inline in the evidence dict
    (``ev["content"]``); it serves as a non-fatal fallback when the durable
    cache miss is a cache miss.
    """

    quote: str
    source: str
    external_ref: str
    content_kind: str
    carried_text: str


async def build_caselaw_citations(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    citations: list[tuple[str, str]],  # (quote, cluster_id)
    gateway: Any,
    judge_model: str = "fast",
    load_opinion_text: _LoadOpinion = _default_read_opinion,
) -> int:
    """Resolve, verify, and persist caselaw structured citations into the ledger.

    For each ``(quote, cluster_id)`` pair:

    1. Guard: skip empty / whitespace-only quotes (prevents the poisoned-flush
       class: ``locate_passage`` returns ``None`` for empty needles, but the
       guard fires before any DB lookup for clarity and defense-in-depth).
    2. Resolve ``ResearchOpinionMetadata`` by ``cluster_id``.  Unknown → skip.
    3. Load opinion text via ``load_opinion_text(db, opinion_id=...)``.
    4. Locate ``quote`` in opinion text via :func:`locate_passage`.  Miss → skip.
    5. Build an :class:`_OpinionVerificationTarget` and a
       :class:`_CaselawCandidate`.
    6. Run the verifier cascade via :func:`verify`.  Miss → skip (honest-
       degradation invariant — no fabrication).
    7. ``db.add`` a verified ``MessageCaselawCitation`` row; accumulate count.

    ``db.flush()`` is called once at the end so callers can roll back the
    entire block as a unit.

    Returns the number of rows added (0 when every citation was unverifiable,
    the cluster was unknown, or the passage was not found in the opinion text).
    Never fabricates rows.
    """
    added = 0

    for quote, cluster_id_str in citations:
        if not quote.strip():
            log.debug(
                "caselaw citation build: empty quote, skipping",
                extra={"event": "autonomous_caselaw_citation_skip"},
            )
            continue

        try:
            meta = (
                (
                    await db.execute(
                        select(ResearchOpinionMetadata).where(
                            ResearchOpinionMetadata.cluster_id == int(cluster_id_str)
                        )
                    )
                )
                .scalars()
                .first()
            )
            if meta is None:
                log.debug(
                    "caselaw citation build: no metadata for cluster, skipping",
                    extra={
                        "event": "autonomous_caselaw_citation_skip",
                        "cluster_id": cluster_id_str,
                    },
                )
                continue

            opinion = await load_opinion_text(db, opinion_id=meta.opinion_id)
            text = str((opinion or {}).get("text") or "")

            span = locate_passage(quote, text)
            if span is None:
                log.debug(
                    "caselaw citation build: locate miss, skipping",
                    extra={
                        "event": "autonomous_caselaw_citation_skip",
                        "cluster_id": cluster_id_str,
                    },
                )
                continue

            start, end = span
            target = opinion_target(meta.opinion_id, text)
            candidate = _CaselawCandidate(
                source_offset_start=start,
                source_offset_end=end,
                source_text=quote,
                source_document_id=target.id,
            )

            result = await verify(candidate, target, gateway=gateway, judge_model=judge_model)
            if not result.verified:
                continue

            db.add(
                MessageCaselawCitation(
                    message_id=message_id,
                    opinion_id=meta.opinion_id,
                    cluster_id=meta.cluster_id,
                    source_offset_start=start,
                    source_offset_end=end,
                    source_text=quote,
                    verified=True,
                    verification_method=result.method,
                    verification_confidence=result.confidence,
                    partial=result.partial,
                )
            )
            added += 1

        except Exception:
            # One bad citation must not sink the rest (per honest-degradation
            # invariant). Log and continue so remaining citations still get a chance.
            log.warning(
                "caselaw citation build: unexpected error, skipping citation",
                extra={
                    "event": "autonomous_caselaw_citation_skip",
                    "cluster_id": cluster_id_str,
                },
                exc_info=True,
            )

    await db.flush()
    return added


async def build_authority_citations(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    items: list[_AuthorityItem],
    load_authority_text: _LoadAuthorityText = _default_load_authority_text,
    gateway: Any,
    judge_model: str = "fast",
) -> int:
    """Resolve, verify, and persist authority structured citations into the ledger.

    For each ``_AuthorityItem(quote, source, external_ref, content_kind, carried_text)``:

    1. Guard: skip empty / whitespace-only quotes.
    2. Load body from the durable cache via ``load_authority_text``; if absent
       (cache miss or stale), fall back to ``item.carried_text``.  If still
       falsy → skip (non-fatal; no body means no target to verify against).
    3. Build an :class:`_AuthorityVerificationTarget` via
       :func:`authority_target`.
    4. Locate ``quote`` in the body via :func:`locate_passage`.
       **Miss → budgeted whole-body paraphrase judge (DE-371), then FAIL.**
       When a ``gateway`` is available, the quote is judged against the
       attributed authority's whole body via
       :func:`app.citation.authority_content_judge.judge_authority_content`
       under the same per-turn budget chat's Pass B uses
       (``AUTHORITY_CONTENT_JUDGE_BUDGET_USD``, pre-flight
       ``estimate_authority_content_cost_usd`` accounting).  A supporting
       verdict writes a SUPPORTED row (``verified=True,
       verification_method="paraphrase_judge", partial=True``) with
       whole-body placeholder offsets (``start=0, end=len(body)``) exactly
       like chat's Pass B rows.  A non-supporting verdict, judge error,
       budget exhaustion, or ``gateway=None`` keeps the FAIL row
       (``verified=False, method=None``) — unlike caselaw's ledger bridge, a
       no-locate authority quote MUST surface to the gate so fabricated
       statute/regulation quotes are never silently passed.  FAIL rows mirror
       :func:`app.citation.caselaw._fail_row`'s offset convention
       (``start=0, end=len(quote)``).  The judge tier can grant at most
       SUPPORTED — it never upgrades to PASS.
    5. On locate hit: build an :class:`_AuthorityCandidate` and run the
       verifier cascade via :func:`verify` with ``gateway=None`` (a located
       span always exact/tolerant-matches, so the judge stage is
       structurally unreachable there — see chat's Pass A in
       :mod:`app.citation.authority`).  Write a ``MessageAuthorityCitation``
       row carrying ``result.verified``; the gate buckets it PASS or FAIL.

    ``db.add_all(rows)`` + ``db.flush()`` once at the end.  Never commits.

    Returns the number of rows added (verified + FAIL).  Best-effort: a
    per-item exception is logged and skipped so one bad citation does not abort
    the whole pass or poison the ``AsyncSession``.
    """
    rows: list[MessageAuthorityCitation] = []
    judge_spent: Decimal = Decimal("0")

    for item in items:
        if not item.quote.strip():
            log.debug(
                "authority citation build: empty quote, skipping",
                extra={"event": "autonomous_authority_citation_skip"},
            )
            continue

        try:
            body = await load_authority_text(
                db, source_type=item.source, external_ref=item.external_ref
            )
            if body is None:
                body = item.carried_text
            if not body:
                log.debug(
                    "authority citation build: no body available, skipping",
                    extra={
                        "event": "autonomous_authority_citation_skip",
                        "external_ref": item.external_ref,
                    },
                )
                continue

            target = authority_target(item.source, item.external_ref, body)
            off = locate_passage(item.quote, target.normalized_content)

            if off is None:
                # Locate miss. DE-371: the autonomous path is attributed by
                # construction (item.source/item.external_ref name the
                # authority), so before failing, give the quote one budgeted
                # whole-body paraphrase-judge chance against the attributed
                # body — the SUPPORTED tier, mirroring chat's Pass B in
                # verify_and_persist_authority_citations. The judge can grant
                # at most SUPPORTED, never PASS. Any non-supporting outcome
                # (no verdict, judge error, budget exhaustion, gateway=None)
                # falls through to the FAIL row — fail-closed default.
                judged: VerificationResult | None = None
                if gateway is not None:
                    body_text = target.normalized_content
                    est = await estimate_authority_content_cost_usd(
                        db, judge_model=judge_model, authority_text=body_text
                    )
                    if judge_spent + est > AUTHORITY_CONTENT_JUDGE_BUDGET_USD:
                        log.info(
                            "authority citation build: judge budget exhausted — keeping FAIL",
                            extra={
                                "event": "autonomous_authority_citation_judge_budget_exhausted",
                                "external_ref": item.external_ref,
                            },
                        )
                    else:
                        judge_spent += est
                        jres: VerificationResult | None
                        try:
                            jres = await judge_authority_content(
                                passage=item.quote,
                                authority_text=body_text,
                                gateway=gateway,
                                judge_model=judge_model,
                            )
                        except Exception:
                            # judge_authority_content is documented never to
                            # raise, but a raise must still keep the FAIL row.
                            log.warning(
                                "authority citation build: judge raised — keeping FAIL",
                                extra={
                                    "event": "autonomous_authority_citation_judge_miss",
                                    "external_ref": item.external_ref,
                                },
                                exc_info=True,
                            )
                            jres = None
                        if jres is not None and jres.verified:
                            judged = jres
                        elif jres is not None:
                            log.debug(
                                "authority citation build: judge did not support — keeping FAIL",
                                extra={
                                    "event": "autonomous_authority_citation_judge_miss",
                                    "external_ref": item.external_ref,
                                },
                            )

                if judged is not None:
                    # SUPPORTED row: whole-body placeholder offsets exactly
                    # like chat's Pass B rows (start=0, end=len(body)).
                    log.debug(
                        "authority citation build: judge supported — SUPPORTED row added",
                        extra={
                            "event": "autonomous_authority_citation_judge_supported",
                            "external_ref": item.external_ref,
                        },
                    )
                    rows.append(
                        MessageAuthorityCitation(
                            message_id=message_id,
                            source_type=item.source,
                            external_ref=item.external_ref,
                            content_kind=item.content_kind,
                            source_offset_start=0,
                            source_offset_end=len(target.normalized_content),
                            source_text=item.quote,
                            verified=True,
                            verification_method="paraphrase_judge",
                            verification_confidence=judged.confidence,
                            partial=True,
                        )
                    )
                    continue

                # FAIL row: fabricated authority quote must surface to the gate.
                # Offsets are a documented placeholder (mirrors caselaw._fail_row):
                # start=0, end=len(quote) satisfies CHECK(end > start >= 0).
                log.debug(
                    "authority citation build: locate miss — FAIL row added",
                    extra={
                        "event": "autonomous_authority_citation_fail",
                        "external_ref": item.external_ref,
                    },
                )
                rows.append(
                    MessageAuthorityCitation(
                        message_id=message_id,
                        source_type=item.source,
                        external_ref=item.external_ref,
                        content_kind=item.content_kind,
                        source_offset_start=0,
                        source_offset_end=len(item.quote),
                        source_text=item.quote,
                        verified=False,
                        verification_method=None,
                        verification_confidence=None,
                        partial=False,
                    )
                )
                continue

            start, end = off
            cand = _AuthorityCandidate(
                source_offset_start=start,
                source_offset_end=end,
                source_text=item.quote,
                source_document_id=target.id,
            )
            # gateway=None: verbatim-only here. locate_passage is a byte-exact
            # substring finder — a located span always exact/tolerant-matches,
            # so verify()'s judge stage is structurally unreachable in this
            # branch and passing the gateway through would be dishonest.
            # Mirrors chat's Pass A comment in app.citation.authority.
            result = await verify(cand, target, gateway=None, judge_model=judge_model)
            rows.append(
                MessageAuthorityCitation(
                    message_id=message_id,
                    source_type=item.source,
                    external_ref=item.external_ref,
                    content_kind=item.content_kind,
                    source_offset_start=start,
                    source_offset_end=end,
                    source_text=item.quote,
                    verified=result.verified,
                    verification_method=result.method,
                    verification_confidence=result.confidence,
                    partial=result.partial,
                )
            )

        except Exception:
            log.warning(
                "authority citation build: unexpected error, skipping citation",
                extra={
                    "event": "autonomous_authority_citation_skip",
                    "external_ref": item.external_ref,
                },
                exc_info=True,
            )

    db.add_all(rows)
    await db.flush()
    return len(rows)


# ---------------------------------------------------------------------------
# Session-level bridge (WS-D PR2 Task 7)
# ---------------------------------------------------------------------------


async def build_session_ledger(
    db: AsyncSession,
    *,
    session: AutonomousSession,
    work_product_text: str,
    findings: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    gateway: Any,
    judge_model: str = "fast",
) -> dict[str, Any] | None:
    """Manufacture a hidden chat+message, build citation rows, and compute the gate.

    Splits each finding's ``citations`` (``{quote, source}``) by the evidence
    registry entry's ``kind`` (``"kb"`` vs ``"caselaw"``) into ``(quote, ref)``
    tuples, then delegates to :func:`build_kb_citations` and
    :func:`build_caselaw_citations` (Tasks 5/6).  Runs
    :func:`~app.citation.ledger.assemble_ledger_entries` and
    :func:`~app.citation.gate.compute_and_record_gate` on the manufactured
    message.

    Returns a ``dict`` with ``gate_status``, ``pass_count``, ``supported_count``,
    ``fail_count``, ``total_assertions``, and ``confidence`` when at least one
    citation is ledgerable, or ``None`` when there are no citable citations
    (so no hidden chat is manufactured and the caller's transaction is
    untouched).

    This function only flushes; it never commits.  The caller is responsible
    for wrapping it in a SAVEPOINT (``async with db.begin_nested()``) so a
    flush error cannot poison the outer transaction.
    """
    # Build index: evidence n → evidence entry (n is always an int per EvidenceItem).
    by_n: dict[int, dict[str, Any]] = {
        int(e["n"]): e for e in evidence if isinstance(e.get("n"), int)
    }

    # Split citations by kind using the evidence registry.
    kb: list[tuple[str, str]] = []
    cl: list[tuple[str, str]] = []
    authority_items: list[_AuthorityItem] = []
    for f in findings:
        for c in f.get("citations") or []:
            ev = by_n.get(c.get("source"))
            if ev is None or not isinstance(c.get("quote"), str):
                continue
            if ev["kind"] == "kb":
                kb.append((c["quote"], ev["ref"]))
            elif ev["kind"] == "caselaw":
                cl.append((c["quote"], ev["ref"]))
            elif ev["kind"] == "authority":
                authority_items.append(
                    _AuthorityItem(
                        quote=c["quote"],
                        source=ev.get("source") or "govinfo",
                        external_ref=ev["ref"],
                        # Carry the real content_kind threaded onto the evidence
                        # item by collect_evidence (WS-E PR1b: statute/regulation;
                        # PR2a: sec_filing). Only fall back to "unknown" when it
                        # is genuinely absent (e.g. a legacy evidence dict
                        # predating PR1b) — NEVER assume "statute", which would
                        # be a confident mislabel for a non-govinfo source
                        # (anti-overclaiming, per PRD §1.3).
                        content_kind=ev.get("content_kind") or "unknown",
                        carried_text=ev.get("content") or "",
                    )
                )

    # Nothing citable → no manufactured chat, no gate, no transaction writes.
    if not kb and not cl and not authority_items:
        return None

    # Manufacture the hidden chat + assistant message.
    chat = Chat(
        owner_id=session.user_id,
        project_id=session.project_id,
        title=f"Matter session {session.id}",
        autonomous_session_id=session.id,
    )
    db.add(chat)
    await db.flush()

    message = Message(chat_id=chat.id, role="assistant", content=work_product_text)
    db.add(message)
    await db.flush()

    # Build citation rows (Tasks 5/6/WS-E).  Each builder flushes once internally.
    await build_kb_citations(
        db, message_id=message.id, citations=kb, gateway=gateway, judge_model=judge_model
    )
    await build_caselaw_citations(
        db, message_id=message.id, citations=cl, gateway=gateway, judge_model=judge_model
    )
    await build_authority_citations(
        db,
        message_id=message.id,
        items=authority_items,
        gateway=gateway,
        judge_model=judge_model,
    )

    # Assemble the ledger index + compute the gate verdict.
    await assemble_ledger_entries(db, message_id=message.id)
    gate = await compute_and_record_gate(db, message_id=message.id)
    if gate is None:
        raise RuntimeError(
            "compute_and_record_gate returned None for a freshly-manufactured message"
        )

    return {
        "gate_status": gate.gate_status,
        "pass_count": gate.pass_count,
        "supported_count": gate.supported_count,
        "fail_count": gate.fail_count,
        "total_assertions": gate.total_assertions,
        "confidence": float(gate.confidence) if gate.confidence is not None else None,
    }
