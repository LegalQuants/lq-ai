"""Caselaw quote verification (P1-A1, P1-B1b, P1-B1c).

Extracts blockquote passages from an assistant answer, locates each verbatim in
a consulted CourtListener opinion's stored plaintext, runs the existing citation
cascade (deterministic stages 1-2), and persists verified rows.

P1-B1b adds a SUPPORTED judge pass: passages that did not match verbatim are
judged against the whole opinion text (cost-gated). A judge-accepted passage
persists a paraphrase_judge row (gate -> supported_only).

P1-B1c adds attribution-aware FAIL rows: passages confidently attributed to a
single consulted case (via ``### `` heading match) are judged against that one
opinion only. A real judge rejection writes an unverified FAIL row
(verified=False, verification_method=NULL), which flows through the unchanged
ledger/gate to a ``flagged`` turn status. Over-budget attributed passages also
write an unverified FAIL row. Transient gateway errors on ALL opinions of an
attributed passage → drop (no row). Unattributed passages keep B1b's
all-opinions SUPPORTED-or-drop behavior (strict additive guarantee).

See docs/superpowers/specs/2026-06-24-p1a1-external-caselaw-quote-verification-design.md.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tool_loop import ToolSourceRecord
from app.citation.case_content_judge import (
    CASE_CONTENT_JUDGE_BUDGET_USD,
    _build_prompt as _build_case_content_prompt,
    estimate_case_content_cost_usd,
    judge_case_content,
)
from app.citation.verification import _JudgeGatewayProtocol, _parse_judge_response, verify
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.research import ResearchClusterMetadata, ResearchOpinionMetadata
from app.research.service import read_opinion


@dataclass(slots=True)
class AttributedPassage:
    """A blockquote passage paired with the case name of its nearest ``### `` heading.

    ``case_name`` is the text of the most recent ``### `` heading above the
    blockquote, taken up to the first comma (the case-law-research skill renders
    headings as ``### [Case Name], [Court], [Year] ([Citation])``). ``None`` when
    no ``### `` heading precedes the blockquote — the attribution false-positive
    guard: an unattributed passage never produces a FAIL row.
    """

    passage: str
    case_name: str | None


def attribute_passages(answer_text: str) -> list[AttributedPassage]:
    """Return each markdown blockquote paired with its nearest ``### `` case heading.

    Consecutive blockquote lines (``> ...``) join into one passage; a
    non-blockquote line ends the current passage. Each closed passage is paired
    with the case name parsed from the most recent ``### `` heading seen so far.
    """
    result: list[AttributedPassage] = []
    current: list[str] = []
    current_case: str | None = None

    def _flush() -> None:
        nonlocal current
        joined = " ".join(p for p in current if p).strip()
        if joined:
            result.append(AttributedPassage(passage=joined, case_name=current_case))
        current = []

    for line in answer_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(">"):
            current.append(stripped[1:].strip())
            continue
        if current:
            _flush()
        # Only level-3 (``### ``) headings carry case attribution. ``##``/``#``
        # (and ``####``) do not — guard with an exact "### " prefix that is not
        # also "#### ".
        if stripped.startswith("### ") and not stripped.startswith("#### "):
            heading = stripped[4:].strip()
            current_case = heading.split(",", 1)[0].strip() or None
    if current:
        _flush()
    return result


def normalize_case_name(name: str) -> str:
    """Normalize a case name for attribution matching.

    Lowercases, strips a trailing ``(...)`` citation parenthetical, strips
    trailing punctuation/whitespace, and collapses internal whitespace runs to
    single spaces. Conservative: only a normalized-exact match attributes.
    """
    text = name.strip()
    # Drop a trailing parenthetical citation, e.g. "(410 U.S. 113)".
    text = re.sub(r"\s*\([^()]*\)\s*$", "", text)
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip().rstrip(",;: ")


def match_case_name(parsed: str, clusters: Sequence[tuple[int, str]]) -> int | None:
    """Return the cluster_id iff exactly one cluster's case_name matches ``parsed``.

    Normalized-exact, single-match only (the false-positive guard). Zero matches,
    two-or-more matches, or clusters with an empty case_name → ``None`` →
    the passage stays on the B1b path (never produces a FAIL row).
    """
    target = normalize_case_name(parsed)
    if not target:
        return None
    matches = [cid for cid, name in clusters if name and normalize_case_name(name) == target]
    return matches[0] if len(matches) == 1 else None


def extract_blockquote_passages(answer_text: str) -> list[str]:
    """Return the text of each markdown blockquote in ``answer_text`` (flat list).

    Retained for existing callers/tests; equivalent to the passages produced by
    :func:`attribute_passages`.
    """
    return [a.passage for a in attribute_passages(answer_text)]


# Stable namespace so a given opinion_id maps to a deterministic synthetic id.
_OPINION_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")


@dataclass(slots=True)
class _OpinionVerificationTarget:
    """Adapts a stored opinion to the verifier's document protocol (no DB row)."""

    id: uuid.UUID
    normalized_content: str
    was_ocrd: bool = False


@dataclass(slots=True)
class _CaselawCandidate:
    """A located quote span, shaped for the verifier's candidate protocol."""

    source_offset_start: int
    source_offset_end: int
    source_text: str
    source_document_id: uuid.UUID


def opinion_target(opinion_id: int, text: str) -> _OpinionVerificationTarget:
    return _OpinionVerificationTarget(
        id=uuid.uuid5(_OPINION_NS, str(opinion_id)),
        normalized_content=text,
        was_ocrd=False,
    )


def locate_passage(passage: str, opinion_text: str) -> tuple[int, int] | None:
    """Exact-substring offsets of ``passage`` in ``opinion_text``, or None.

    v1 locates verbatim spans only; the cascade confirms them as ``exact_match``.
    A whitespace-tolerant locator (feeding stage-2) is a noted follow-on.
    """
    needle = passage.strip()
    if not needle:
        return None
    idx = opinion_text.find(needle)
    if idx < 0:
        return None
    return idx, idx + len(needle)


# ---------------------------------------------------------------------------
# Private helpers (FAIL tier — P1-B1c)
# ---------------------------------------------------------------------------

log = logging.getLogger(__name__)


def _fail_row(
    message_id: uuid.UUID, opinion_id: int, cluster_id: int, passage: str
) -> MessageCaselawCitation:
    """Build an unverified caselaw FAIL row (gate -> flagged).

    Offsets are a documented placeholder: a FAIL passage has no verified span in
    the opinion, but the CHECK requires offset_end > offset_start >= 0. The ledger
    and trace never read caselaw offsets (ledger.py:78-91).
    """
    return MessageCaselawCitation(
        message_id=message_id,
        opinion_id=opinion_id,
        cluster_id=cluster_id,
        source_offset_start=0,
        source_offset_end=len(passage),
        source_text=passage,
        verified=False,
        verification_method=None,
        verification_confidence=None,
        partial=False,
    )


def _judge_returned_explicit_no(response: Any) -> bool:
    """True only if the judge returned a parseable ``{"verdict": "no"}``.

    A reject must be an *explicit* "no". Non-substantive failures — truncated or
    non-JSON output (the judge caps at 400 tokens), an unknown verdict, or a
    "yes"/"partial" with an unrecognized confidence — all collapse to the same
    _MISS in _parse_judge_response, but they are NOT rejections: treating them as
    FAIL would flag good work product on judge-output noise (the exact
    false-positive this tier exists to avoid). Those cases drop, like a transient
    error.
    """
    try:
        choices = response.choices
        if not choices:
            return False
        content = choices[0].message.content
        if not content:
            return False
        payload = json.loads(content)
    except (AttributeError, json.JSONDecodeError, TypeError):
        return False
    return isinstance(payload, dict) and payload.get("verdict") == "no"


async def _judge_attributed_passage(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    passage: str,
    cluster_id: int,
    opinions: list[tuple[int, str]],
    gateway: _JudgeGatewayProtocol,
    judge_model: str,
    spent: Decimal,
) -> tuple[Decimal, MessageCaselawCitation | None]:
    """Judge an attributed passage against its cluster's opinion(s) only.

    Returns (updated_spent, row_or_None):
      * accept            -> SUPPORTED row (paraphrase_judge)
      * judge reject      -> FAIL row (verified=False, method NULL)
      * over budget       -> unverified FAIL row (verified=False, method NULL)
      * all transient err -> None (drop; no row)
    """
    saw_reject = False
    first_opinion_id = opinions[0][0]
    for opinion_id, text in opinions:
        est = await estimate_case_content_cost_usd(db, judge_model=judge_model, opinion_text=text)
        if spent + est > CASE_CONTENT_JUDGE_BUDGET_USD:
            log.info(
                "case-content judge: attributed passage over budget; flagging unverified",
                extra={"event": "caselaw_fail_over_budget", "cluster_id": cluster_id},
            )
            return spent, _fail_row(message_id, opinion_id, cluster_id, passage)
        spent += est
        # Call the gateway directly (not via judge_case_content) so transient errors
        # propagate as exceptions. judge_case_content swallows all errors and returns
        # _MISS, making "real rejection" and "transient error" indistinguishable — but
        # the attribution FAIL tier needs to distinguish them (transient → drop, not FAIL).
        try:
            request = _build_case_content_prompt(passage, text, judge_model=judge_model)
            response = await gateway.chat_completion(request)
            result = _parse_judge_response(response)
            explicit_no = _judge_returned_explicit_no(response)
        except Exception as exc:
            log.warning("case-content judge error on opinion %s: %r", opinion_id, exc)
            continue  # transient on this opinion -> try the next
        if result.verified:
            return spent, MessageCaselawCitation(
                message_id=message_id,
                opinion_id=opinion_id,
                cluster_id=cluster_id,
                source_offset_start=0,
                source_offset_end=len(text),
                source_text=passage,
                verified=True,
                verification_method="paraphrase_judge",
                verification_confidence=result.confidence,
                partial=True,
            )
        if explicit_no:
            saw_reject = True  # an explicit "no" from the judge -> reject
        # else: non-substantive output (unparseable/unknown verdict/missing
        # confidence) -> drop this opinion, like a transient error.
    if saw_reject:
        log.info(
            "case-content judge: attributed passage rejected; flagging FAIL",
            extra={"event": "caselaw_fail_judge_rejected", "cluster_id": cluster_id},
        )
        return spent, _fail_row(message_id, first_opinion_id, cluster_id, passage)
    return spent, None  # every opinion errored transiently -> drop


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

_LoadOpinionText = Callable[[AsyncSession, int], Awaitable[str]]


async def _default_load_opinion_text(db: AsyncSession, opinion_id: int) -> str:
    result: dict[str, Any] = await read_opinion(db, opinion_id=opinion_id)
    return result["text"]


async def verify_and_persist_caselaw_citations(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    assistant_text: str,
    tool_sources: Sequence[ToolSourceRecord],
    load_opinion_text: _LoadOpinionText = _default_load_opinion_text,
    gateway: _JudgeGatewayProtocol | None = None,
    judge_model: str = "fast",
) -> int:
    """Verify caselaw quotes in ``assistant_text`` and persist verified rows.

    Stage 1: verbatim locate + deterministic cascade (stages 1-2). Stage 2
    (P1-B1b, SUPPORTED): passages that produced no verbatim row are judged
    against the whole opinion text (cost-gated, additive-only).

    ``gateway=None`` (default) runs the verbatim path only — behaviour is
    byte-for-byte identical to the pre-P1-B1b implementation.

    Returns the total row count. Never raises on a per-opinion failure
    (conservative posture): a load miss is logged and skipped, and the turn
    proceeds with whatever verified.
    """
    cluster_ids = {
        int(r.external_ref)
        for r in tool_sources
        if r.source_kind == "caselaw" and r.external_ref and r.external_ref.isdigit()
    }
    if not cluster_ids:
        return 0
    passages = extract_blockquote_passages(assistant_text)
    if not passages:
        return 0
    opinions = (
        (
            await db.execute(
                select(ResearchOpinionMetadata).where(
                    ResearchOpinionMetadata.cluster_id.in_(cluster_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    if not opinions:
        return 0

    # Read each consulted opinion's text once (skip unreadable).
    texts: list[tuple[ResearchOpinionMetadata, str]] = []
    for op in opinions:
        try:
            texts.append((op, await load_opinion_text(db, op.opinion_id)))
        except Exception as exc:  # storage miss / not-fetched — never fatal
            log.warning("caselaw verify: could not load opinion %s: %r", op.opinion_id, exc)

    rows: list[MessageCaselawCitation] = []

    # --- Verbatim loop (stages 1-2) ----------------------------------------
    # Track which passages were resolved verbatim so the judge pass can skip them.
    verbatim_matched: set[str] = set()
    for passage in passages:
        for op, text in texts:
            loc = locate_passage(passage, text)
            if loc is None:
                continue
            start, end = loc
            target = opinion_target(op.opinion_id, text)
            candidate = _CaselawCandidate(
                source_offset_start=start,
                source_offset_end=end,
                source_text=passage,
                source_document_id=target.id,
            )
            result = await verify(candidate, target, gateway=None)
            if not result.verified:
                continue
            rows.append(
                MessageCaselawCitation(
                    message_id=message_id,
                    opinion_id=op.opinion_id,
                    cluster_id=op.cluster_id,
                    source_offset_start=start,
                    source_offset_end=end,
                    source_text=passage,
                    verified=True,
                    verification_method=result.method,
                    verification_confidence=result.confidence,
                    partial=result.partial,
                )
            )
            verbatim_matched.add(passage)
            break  # one verified row per passage (first matching opinion wins)

    # --- Attribution-aware judge pass (P1-B1c) --------------------------------
    # Confidently-attributed passages are judged against their one opinion:
    #   reject -> FAIL row; over-budget -> unverified FAIL row; transient error
    #   -> drop. Unattributed passages keep B1b's all-opinions SUPPORTED-or-drop
    #   behavior. FAIL is strictly additive: only attributed passages can FAIL.
    if gateway is not None:
        # Case names for the consulted clusters (for H3 attribution).
        cluster_metas = (
            (
                await db.execute(
                    select(ResearchClusterMetadata).where(
                        ResearchClusterMetadata.cluster_id.in_(cluster_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        clusters: list[tuple[int, str]] = [
            (c.cluster_id, c.case_name) for c in cluster_metas if c.case_name
        ]
        # cluster_id -> [(opinion_id, text)] from the already-loaded opinion texts.
        cluster_texts: dict[int, list[tuple[int, str]]] = {}
        for op, text in texts:
            cluster_texts.setdefault(op.cluster_id, []).append((op.opinion_id, text))

        # Resolve attribution per still-unverified passage; judge attributed
        # passages FIRST so the per-turn budget is spent on FAIL-bearing checks.
        pending = [
            a for a in attribute_passages(assistant_text) if a.passage not in verbatim_matched
        ]

        def _attributed_cluster(a: AttributedPassage) -> int | None:
            if a.case_name is None:
                return None
            cid = match_case_name(a.case_name, clusters)
            if cid is None or cid not in cluster_texts:
                return None  # no confident match, or named-but-not-fetched
            return cid

        annotated = [(a, _attributed_cluster(a)) for a in pending]
        annotated.sort(key=lambda t: t[1] is None)  # attributed (cid not None) first

        spent: Decimal = Decimal("0")
        for a, cid in annotated:
            if cid is not None:
                spent, row = await _judge_attributed_passage(
                    db,
                    message_id=message_id,
                    passage=a.passage,
                    cluster_id=cid,
                    opinions=cluster_texts[cid],
                    gateway=gateway,
                    judge_model=judge_model,
                    spent=spent,
                )
                if row is not None:
                    rows.append(row)
                continue
            # --- Unattributed: B1b all-opinions SUPPORTED-or-drop ------------
            for op, text in texts:
                est = await estimate_case_content_cost_usd(
                    db, judge_model=judge_model, opinion_text=text
                )
                if spent + est > CASE_CONTENT_JUDGE_BUDGET_USD:
                    break  # budget reached -> drop remaining unattributed work
                spent += est
                try:
                    result = await judge_case_content(
                        passage=a.passage,
                        opinion_text=text,
                        gateway=gateway,
                        judge_model=judge_model,
                    )
                except Exception as exc:
                    log.warning("case-content judge error on opinion %s: %r", op.opinion_id, exc)
                    continue
                if not result.verified:
                    continue
                rows.append(
                    MessageCaselawCitation(
                        message_id=message_id,
                        opinion_id=op.opinion_id,
                        cluster_id=op.cluster_id,
                        source_offset_start=0,
                        source_offset_end=len(text),
                        source_text=a.passage,
                        verified=True,
                        verification_method="paraphrase_judge",
                        verification_confidence=result.confidence,
                        partial=True,
                    )
                )
                break

    # --- Persist (single add_all / flush) -----------------------------------
    if rows:
        db.add_all(rows)
        await db.flush()
    return len(rows)
