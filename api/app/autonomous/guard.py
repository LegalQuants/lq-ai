"""The guarded_tool_call chokepoint — M4-A3.3a/b.

Every tool invocation in the autonomous executor MUST flow through
:func:`guarded_tool_call`.  It enforces three brakes in a load-bearing
order before dispatching the actual tool:

R5 temporal
    Read the session's current ``halt_state`` from the DB
    (``db.refresh``).  If ``halt_requested``, transition to ``halted``
    and raise :exc:`~app.errors.SessionHalted`.

R6 contextual
    Check that ``intent`` is in :data:`~app.autonomous.enums.PHASE_GRANTS`
    for the session's current phase.  If not, raise
    :exc:`~app.errors.ToolNotGranted`.

R4 economic
    Project the USD cost of the call via
    :func:`~app.autonomous.cost.estimate_tool_cost`.  If
    ``max_cost_usd`` is set and the projected total would exceed it,
    latch ``cost_cap_reached``, transition to ``halted``, and raise
    :exc:`~app.errors.CostCapReached`.

The chokepoint does NOT commit; the caller (executor/delivery node) owns
the commit boundary — matching the A2 pattern where the delivery node
commits.  All intermediate state is flushed via ``autonomous_audit``.

.. warning::
    When a brake raises, the chokepoint has already **mutated the session**
    (``halt_state``/``cost_cap_reached``) and **flushed an audit row** — but
    not committed.  The brake propagates as an exception.  Any caller that
    catches an :exc:`~app.errors.AutonomousBrake` **must commit** so the
    halt-state latch and the audit row persist; catching a brake and
    returning without committing silently drops both (the A2 data-loss
    class).  A3.3b nodes therefore let brakes propagate to the executor's
    terminal handler, which commits.

Local handlers implemented here (A3.3a)
----------------------------------------
``emit_finding``    — echoes the ``finding`` param as data; zero cost; no
                      DB row.
``propose_memory``  — writes a ``proposed`` :class:`~app.models.autonomous.AutonomousMemory`
                      row; zero cost.
``propose_precedent`` — upserts a :class:`~app.models.autonomous.PrecedentEntry`
                      row (increments ``observed_count`` on recurrence,
                      else inserts); zero cost. Never touches ``projects``.
``notify``          — writes an ``in_app``
                      :class:`~app.models.autonomous.AutonomousNotification` row;
                      zero cost.

Inference/retrieval handlers (A3.3b)
--------------------------------------
``retrieve_chunks`` — calls :func:`~app.knowledge.retrieval.hybrid_search`;
                      zero cost (local retrieval); returns IDs/counts/offsets
                      in ``data`` (never raw chunk text).
``run_skill``       — gateway chat-completion call; cost = the single M2-E2
                      estimate computed for R4 (no double-charge);
                      ``anonymize=True`` by default.
``run_playbook``    — same gateway pattern as ``run_skill``.

Cost contract (A3.3b)
----------------------
The ``estimated_cost`` kwarg is forwarded from the chokepoint into
``_dispatch`` so inference handlers use the SAME ``Decimal`` value that
R4 already computed — preventing any divergence between what R4 checked
and what the session is charged.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.audit import autonomous_audit
from app.autonomous.cost import estimate_tool_cost
from app.autonomous.enums import PHASE_GRANTS, HaltState, Phase, ToolIntent
from app.autonomous.notify_email import send_notification_email
from app.errors import CostCapReached, SessionHalted, ToolNotGranted
from app.models.autonomous import (
    AutonomousFinding,
    AutonomousMemory,
    AutonomousNotification,
    AutonomousSession,
    PrecedentEntry,
)
from app.models.user import User
from app.observability_helpers import get_tracer, record_attributes

log = logging.getLogger(__name__)

_tracer = get_tracer(__name__)

_DEFAULT_RETRIEVE_TOP_K: int = 4
_DEFAULT_RETRIEVE_ALPHA: float = 0.5


@dataclass
class ToolResult:
    """Return value from the guarded tool chokepoint.

    ``cost_usd`` accumulates onto the session's ``cost_total_usd`` after a
    successful dispatch.  ``data`` carries tool-specific structured output
    (e.g. the echoed finding dict for ``emit_finding``, a memory/notification
    id for the write intents).
    """

    cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    data: Any = None
    outcome: str = "success"
    """The audit/span outcome label for the dispatch. Defaults to
    ``"success"``; an inference handler that attempted the call but hit a
    gateway transport/parse failure sets ``"gateway_error"`` so the audit
    trail does not record a failed inference as a success (the call is still
    charged the R4 estimate, but its outcome is honest)."""


async def guarded_tool_call(
    session: AutonomousSession,
    intent: ToolIntent,
    params: dict[str, Any],
    db: AsyncSession,
    gateway: Any,
) -> ToolResult:
    """Single chokepoint for every autonomous tool invocation.

    Enforces R5 → R6 → R4 in that order before dispatching the tool.
    Opens an OTel span first so all brake outcomes are traced uniformly.

    The chokepoint flushes (via ``autonomous_audit``) but does NOT
    commit — the executor owns the commit boundary.

    Args:
        session: The :class:`~app.models.autonomous.AutonomousSession`
            driving this run.
        intent: The :class:`~app.autonomous.enums.ToolIntent` being
            requested.
        params: Keyword arguments for the tool (forwarded to
            :func:`_dispatch`).
        db: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
        gateway: The Inference Gateway client (used by A3.3b inference
            handlers; not used by local-intent handlers).

    Returns:
        A :class:`ToolResult` on success.

    Raises:
        SessionHalted: If ``halt_state == 'halt_requested'`` on the
            pre-call refresh (R5).
        ToolNotGranted: If ``intent`` is not in the phase-grant set
            for the current phase (R6).
        CostCapReached: If the projected cost would exceed
            ``max_cost_usd`` (R4).
    """
    with _tracer.start_as_current_span("autonomous.tool_call") as span:
        # COUNTS + TYPES ONLY — never raw values or document text
        record_attributes(
            span,
            **{
                "autonomous.session_id": str(session.id),
                "autonomous.phase": str(session.current_phase),
                "autonomous.tool": str(intent),  # the intent label, NOT params
                "autonomous.halt_state": str(session.halt_state),
            },
        )

        # ── R5 temporal ─────────────────────────────────────────────────────
        # Re-read halt_state from the DB so an external signal that arrives
        # after the executor started is honoured at the next tool boundary.
        await db.refresh(session, ["halt_state"])
        if session.halt_state == HaltState.halt_requested:
            session.halt_state = str(HaltState.halted)
            await autonomous_audit(db, session, "halted", reason="external_halt")
            record_attributes(span, **{"autonomous.outcome": "external_halt"})
            raise SessionHalted("session halted externally", reason="external_halt")

        # ── R6 contextual ───────────────────────────────────────────────────
        # Compare intent against the grant set for the current phase.
        # session.current_phase is stored as a str; coerce to Phase enum
        # so PHASE_GRANTS lookup is type-safe.
        if intent not in PHASE_GRANTS[Phase(session.current_phase)]:
            await autonomous_audit(
                db,
                session,
                "tool_call",
                tool=str(intent),
                outcome="tool_not_granted",
            )
            record_attributes(span, **{"autonomous.outcome": "tool_not_granted"})
            raise ToolNotGranted(
                "tool intent not granted in current phase",
                intent=str(intent),
                phase=str(session.current_phase),
            )

        # ── R4 economic ─────────────────────────────────────────────────────
        # Estimate cost ONCE here — used both for the cap check AND passed
        # into _dispatch so inference handlers use the same Decimal value
        # that R4 checked.  This prevents any divergence between what R4
        # permitted and what the session is charged (no double-charge).
        estimate = await estimate_tool_cost(intent, params, db)
        projected = session.cost_total_usd + estimate
        if session.max_cost_usd is not None and projected > session.max_cost_usd:
            session.cost_cap_reached = True
            session.halt_state = str(HaltState.halted)
            await autonomous_audit(
                db,
                session,
                "cost_cap_reached",
                projected_usd=float(projected),
            )
            record_attributes(span, **{"autonomous.outcome": "cost_cap_reached"})
            raise CostCapReached(
                "projected cost would exceed session cap",
                projected_usd=float(projected),
            )

        # ── dispatch ────────────────────────────────────────────────────────
        await autonomous_audit(db, session, "tool_call", tool=str(intent), outcome="started")
        result = await _dispatch(
            intent, params, gateway=gateway, db=db, session=session, estimated_cost=estimate
        )

        # ── record cost + outcome ────────────────────────────────────────────
        session.cost_total_usd += result.cost_usd
        session.last_activity_at = datetime.now(UTC)  # feeds R5 idle watchdog (M4-A4)
        record_attributes(
            span,
            **{
                "autonomous.cost_usd": float(result.cost_usd),
                "autonomous.outcome": result.outcome,
            },
        )
        await autonomous_audit(
            db,
            session,
            "tool_call",
            tool=str(intent),
            outcome=result.outcome,
            cost_usd=float(result.cost_usd),
        )
        return result


async def _dispatch(
    intent: ToolIntent,
    params: dict[str, Any],
    *,
    gateway: Any,
    db: AsyncSession,
    session: AutonomousSession,
    estimated_cost: Decimal,
) -> ToolResult:
    """Route a granted, in-budget tool intent to its handler.

    Local intents (``emit_finding``, ``propose_memory``,
    ``propose_precedent``, ``notify``) are zero-cost and return
    ``cost_usd=Decimal("0")``.

    Inference/retrieval intents use the ``estimated_cost`` kwarg forwarded
    from the chokepoint — the SAME ``Decimal`` value that R4 already
    checked — so there is no double-charge and no divergence between what
    R4 permitted and what the session is charged.

    Args:
        intent: The :class:`~app.autonomous.enums.ToolIntent`.
        params: Tool-specific keyword arguments.
        gateway: Inference Gateway client (used for ``run_skill`` /
            ``run_playbook`` gateway chat-completion calls).
        db: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
        session: The active :class:`~app.models.autonomous.AutonomousSession`.
        estimated_cost: The cost projected by R4 for this call; inference
            handlers return this value as ``cost_usd`` so the session is
            charged exactly what R4 approved.

    Returns:
        A :class:`ToolResult` with ``cost_usd`` and tool-specific ``data``.
    """
    if intent == ToolIntent.emit_finding:
        # Local, zero-cost: persist the finding row, then echo the payload
        # (plus the new row id) back as data. The calling node still appends
        # the finding to state["findings"] and computes findings_count — that
        # transient-state behavior is unchanged; this only ADDS durable
        # persistence so a run's findings can be read back later.
        # Missing "finding" key is a programming error at the call site;
        # KeyError is acceptable here (unreachable via the executor) and is
        # consistent with the propose_memory/notify required-param access —
        # a silent None finding must never propagate into state["findings"].
        # The finding dict may omit keys (LLM structured output) — the
        # `.get(...) or default` guards keep non-null DB columns satisfied.
        finding = params["finding"]
        finding_row = AutonomousFinding(
            session_id=session.id,
            severity=str(finding.get("severity") or "info"),
            title=str(finding.get("title") or "(untitled)"),
            content=str(finding.get("summary") or ""),
        )
        db.add(finding_row)
        await db.flush()
        return ToolResult(
            cost_usd=Decimal("0"), data={**finding, "finding_id": str(finding_row.id)}
        )

    if intent == ToolIntent.propose_memory:
        # Local, zero-cost: write a proposed autonomous_memory row.
        mem = AutonomousMemory(
            user_id=session.user_id,
            state="proposed",
            category=params["category"],
            content=params["content"],
            source_session_id=session.id,
        )
        db.add(mem)
        await db.flush()
        return ToolResult(cost_usd=Decimal("0"), data={"memory_id": str(mem.id)})

    if intent == ToolIntent.propose_precedent:
        # Local, zero-cost: race-safe upsert-on-recurrence into
        # precedent_entries via INSERT ... ON CONFLICT. The arq worker runs
        # up to 10 concurrent jobs with no per-user single-flight, so a
        # SELECT-then-INSERT-or-increment would race (two sessions both miss
        # the SELECT → two INSERTs → split observed_count). The atomic
        # ON CONFLICT against the partial unique index
        # `uq_precedent_entries_user_kind_summary_active`
        # (user_id, pattern_kind, md5(summary)) WHERE dismissed_at IS NULL
        # collapses that to one row: a recurrence increments observed_count;
        # a dismissed precedent does NOT conflict (a post-dismissal
        # observation inserts a fresh row). index_elements + index_where
        # below MUST match that index exactly or Postgres won't infer the
        # arbiter.
        #
        # This handler MUST NEVER touch the `projects` table — promotion into a
        # Project's context is a separate, user-authorized proposal lifecycle
        # (M4-B2, ADR 0013 D5). Missing required params raise KeyError, the
        # accepted failure mode consistent with propose_memory.
        stmt = (
            pg_insert(PrecedentEntry)
            .values(
                user_id=session.user_id,
                pattern_kind=params["pattern_kind"],
                summary=params["summary"],
                observed_count=1,
                source_session_id=session.id,
            )
            .on_conflict_do_update(
                index_elements=[
                    PrecedentEntry.user_id,
                    PrecedentEntry.pattern_kind,
                    sa.text("md5(summary)"),
                ],
                index_where=PrecedentEntry.dismissed_at.is_(None),
                set_={
                    "observed_count": PrecedentEntry.observed_count + 1,
                    "updated_at": sa.text("now()"),
                },
            )
            .returning(PrecedentEntry.id, PrecedentEntry.observed_count)
        )
        row = (await db.execute(stmt)).one()
        await db.flush()
        return ToolResult(
            cost_usd=Decimal("0"),
            data={"precedent_id": str(row.id), "observed_count": row.observed_count},
        )

    if intent == ToolIntent.notify:
        # Local, zero-cost: write a durable in-app autonomous_notifications
        # row — this is the RECORD OF TRUTH. Email is a best-effort transport
        # copy (M4-C1); webhook dispatch stays reserved for DE-312.
        note = AutonomousNotification(
            user_id=session.user_id,
            session_id=session.id,
            channel="in_app",
            title=params["title"],
            body=params["body"],
            payload=params.get("payload"),
        )
        db.add(note)
        await db.flush()

        # Best-effort email transport (M4-C1): send the SAME counts/IDs/
        # receipt-link body to the session user. A clean no-op when SMTP is
        # unconfigured; the whole attempt is wrapped so a transport failure
        # NEVER breaks the handler or the session. No second notification row
        # is written — the one in-app row above is the record; email/webhook
        # channel values remain the reserved seam.
        try:
            user = await db.get(User, session.user_id)
            await send_notification_email(
                to_addr=user.email if user else None,
                subject=params["title"],
                body=params["body"],
            )
        except Exception:
            log.warning(
                "autonomous_notify_email_error",
                extra={"event": "autonomous_notify_email_error"},
                exc_info=True,
            )

        return ToolResult(cost_usd=Decimal("0"), data={"notification_id": str(note.id)})

    if intent == ToolIntent.retrieve_chunks:
        return await _handle_retrieve_chunks(params, db=db)

    if intent in (ToolIntent.run_skill, ToolIntent.run_playbook):
        return await _handle_gateway_inference(
            intent, params, gateway=gateway, estimated_cost=estimated_cost
        )

    # Should be unreachable: PHASE_GRANTS + R6 prevent unknown intents.
    raise ValueError(f"_dispatch: unhandled intent {intent!r}")


async def _handle_retrieve_chunks(
    params: dict[str, Any],
    *,
    db: AsyncSession,
) -> ToolResult:
    """Handle ``retrieve_chunks`` — hybrid KB search OR file-scoped OR
    since-scoped fetch.  Zero cost (local retrieval).

    Three modes (mutually exclusive at the top level):

    1. ``query`` (+ optional ``query_embedding``, ``top_k``, ``alpha``) —
       hybrid semantic+FTS search via :func:`hybrid_search`.  Existing
       path, unchanged.
    2. ``file_id`` (+ ``kb_id`` for safety/audit) — return the file's
       chunks directly (no semantic ranking), in
       ``char_offset_start`` order.  Used by watch-triggered intake to
       fetch the arriving document's chunks.
    3. ``since`` + ``kb_id`` (no ``query``) — return chunks of files in
       the KB whose
       :attr:`~app.models.knowledge.KnowledgeBaseFile.attached_at` >
       ``since`` (ISO-8601 string or aware datetime), in
       ``attached_at`` order.  Used by schedule-triggered intake for
       the "new since ``last_run_at``" path.

    All three modes return the same shape: ``data["summary"]``
    (counts + IDs + offsets, audit-safe — the chokepoint's audit row
    only logs the summary) and ``data["chunks"]`` (full text for the
    node's LLM use).

    Args:
        params: One of three top-level mode keys must be present:

            - ``query`` (str): semantic+FTS hybrid search.
              Required: ``kb_id``.
              Optional: ``top_k`` (default 4), ``alpha`` (default 0.5),
              ``query_embedding`` (list[float] | None).
            - ``file_id`` (str | UUID): file-scoped chunk fetch.
              ``kb_id``, if also provided, is **silently ignored** in
              this mode (no KB join performed, no audit/log emitted).
            - ``since`` (str | datetime) + ``kb_id``: KB-scoped fetch
              of chunks whose owning file was attached after ``since``.

        db: Active async ORM session.

    Raises:
        ValueError: If no mode applies (none of ``query``, ``file_id``,
            or ``since``+``kb_id`` provided).
    """
    file_id_raw = params.get("file_id")
    since_raw = params.get("since")
    kb_id_raw = params.get("kb_id")
    query = params.get("query")

    # Mode 2: file-scoped fetch.
    if file_id_raw is not None:
        return await _handle_retrieve_chunks_by_file(file_id_raw, db=db)

    # Mode 3: since + kb_id scoped fetch.
    if since_raw is not None and kb_id_raw is not None:
        return await _handle_retrieve_chunks_since(since_raw, kb_id_raw, db=db)

    # Mode 1: query-based hybrid search (existing path — unchanged).
    if query is None:
        raise ValueError(
            "_handle_retrieve_chunks: provide one of `query` (hybrid search), "
            "`file_id` (file-scoped fetch), or `since` + `kb_id` "
            "(KB-scoped fetch of files attached after a cutoff)."
        )
    return await _handle_retrieve_chunks_query(params, db=db)


async def _handle_retrieve_chunks_query(
    params: dict[str, Any],
    *,
    db: AsyncSession,
) -> ToolResult:
    """Mode 1: hybrid semantic+FTS search via :func:`hybrid_search`.

    This is the existing query-path, unchanged.  Returns IDs/counts/
    offsets in ``data["summary"]`` for span/audit safety, and full
    chunk text in ``data["chunks"]`` for the node's LLM use.

    Args:
        params: Must contain ``kb_id`` (str | UUID) and ``query`` (str).
            Optional: ``top_k`` (int, default 4), ``alpha`` (float,
            default 0.5), ``query_embedding`` (list[float] | None).
        db: Active async ORM session.
    """
    from app.knowledge.retrieval import hybrid_search

    kb_id_raw = params["kb_id"]
    kb_id = uuid.UUID(str(kb_id_raw))
    query: str = params["query"]
    top_k: int = int(params.get("top_k", _DEFAULT_RETRIEVE_TOP_K))
    alpha: float = float(params.get("alpha", _DEFAULT_RETRIEVE_ALPHA))
    query_embedding: list[float] | None = params.get("query_embedding")

    results = await hybrid_search(
        db,
        kb_id=kb_id,
        query=query,
        query_embedding=query_embedding,
        top_k=top_k,
        alpha=alpha,
    )

    return _format_chunks_result(
        [
            {
                "chunk_id": r.chunk_id,
                "document_id": r.document_id,
                "file_id": r.file_id,
                "file_name": r.file_name,
                "content": r.content,
                "page_start": r.page_start,
                "page_end": r.page_end,
                "char_offset_start": r.char_offset_start,
                "char_offset_end": r.char_offset_end,
                "hybrid_score": r.hybrid_score,
            }
            for r in results
        ]
    )


async def _handle_retrieve_chunks_by_file(
    file_id_raw: Any,
    *,
    db: AsyncSession,
) -> ToolResult:
    """Mode 2: return all chunks of a single file in chunk-order.

    The ``file_id`` input is :attr:`~app.models.file.File.id` — the
    files.id value.  ``DocumentChunk`` has no direct ``file_id``
    column; the join walks ``document_chunks → documents → files``.
    The 1:1 ``files.id`` ↔ ``documents.file_id`` relationship is
    enforced by a unique constraint on :attr:`Document.file_id`.

    Soft-deleted files (``files.deleted_at IS NOT NULL``) are excluded
    so a deleted source never leaks back via the autonomous loop —
    matching the same predicate used by :func:`hybrid_search`.

    Args:
        file_id_raw: ``files.id`` as ``str`` or :class:`uuid.UUID`.
        db: Active async ORM session.
    """
    from sqlalchemy import select

    from app.models.document import Document, DocumentChunk
    from app.models.file import File as FileModel

    file_id = uuid.UUID(str(file_id_raw))

    rows = (
        (
            await db.execute(
                select(
                    DocumentChunk.id.label("chunk_id"),
                    DocumentChunk.document_id.label("document_id"),
                    FileModel.id.label("file_id"),
                    FileModel.filename.label("file_name"),
                    DocumentChunk.content.label("content"),
                    DocumentChunk.page_start.label("page_start"),
                    DocumentChunk.page_end.label("page_end"),
                    DocumentChunk.char_offset_start.label("char_offset_start"),
                    DocumentChunk.char_offset_end.label("char_offset_end"),
                )
                .join(Document, Document.id == DocumentChunk.document_id)
                .join(FileModel, FileModel.id == Document.file_id)
                .where(FileModel.id == file_id)
                .where(FileModel.deleted_at.is_(None))
                .order_by(DocumentChunk.char_offset_start)
            )
        )
        .mappings()
        .all()
    )

    return _format_chunks_result([dict(row) for row in rows])


async def _handle_retrieve_chunks_since(
    since_raw: Any,
    kb_id_raw: Any,
    *,
    db: AsyncSession,
) -> ToolResult:
    """Mode 3: return chunks of files in KB ``kb_id`` attached after ``since``.

    Walks ``document_chunks → documents → files → knowledge_base_files``,
    filtering to ``kbf.kb_id == kb_id`` AND
    ``kbf.attached_at > since``.  Order is
    (``attached_at`` ascending, then ``char_offset_start`` ascending) so
    chunks within a file stay in document-order but newer files come
    later — matching the "new since I last ran" digest semantics.

    Soft-deleted files (``files.deleted_at IS NOT NULL``) are excluded
    so a deleted source never leaks back via the autonomous loop.

    Args:
        since_raw: cutoff as ISO-8601 ``str`` or aware
            :class:`datetime.datetime`.  Naive datetimes are NOT
            accepted (Postgres timestamps are timezone-aware on this
            stack; comparing naive to aware would raise at query time).
        kb_id_raw: :attr:`KnowledgeBase.id` as ``str`` or
            :class:`uuid.UUID`.
        db: Active async ORM session.
    """
    from sqlalchemy import select

    from app.models.document import Document, DocumentChunk
    from app.models.file import File as FileModel
    from app.models.knowledge import KnowledgeBaseFile

    if isinstance(since_raw, str):
        since_dt = datetime.fromisoformat(since_raw)
    elif isinstance(since_raw, datetime):
        since_dt = since_raw
    else:
        raise ValueError(
            f"_handle_retrieve_chunks: `since` must be ISO-8601 str or datetime, "
            f"got {type(since_raw).__name__}"
        )

    if since_dt.tzinfo is None or since_dt.tzinfo.utcoffset(since_dt) is None:
        raise ValueError(
            "_handle_retrieve_chunks: `since` must be timezone-aware "
            "(got naive datetime — Postgres timestamps are tz-aware on this stack)"
        )

    kb_id = uuid.UUID(str(kb_id_raw))

    rows = (
        (
            await db.execute(
                select(
                    DocumentChunk.id.label("chunk_id"),
                    DocumentChunk.document_id.label("document_id"),
                    FileModel.id.label("file_id"),
                    FileModel.filename.label("file_name"),
                    DocumentChunk.content.label("content"),
                    DocumentChunk.page_start.label("page_start"),
                    DocumentChunk.page_end.label("page_end"),
                    DocumentChunk.char_offset_start.label("char_offset_start"),
                    DocumentChunk.char_offset_end.label("char_offset_end"),
                )
                .join(Document, Document.id == DocumentChunk.document_id)
                .join(FileModel, FileModel.id == Document.file_id)
                .join(KnowledgeBaseFile, KnowledgeBaseFile.file_id == FileModel.id)
                .where(KnowledgeBaseFile.kb_id == kb_id)
                .where(KnowledgeBaseFile.attached_at > since_dt)
                .where(FileModel.deleted_at.is_(None))
                .order_by(
                    KnowledgeBaseFile.attached_at,
                    DocumentChunk.char_offset_start,
                )
            )
        )
        .mappings()
        .all()
    )

    return _format_chunks_result([dict(row) for row in rows])


def _format_chunks_result(rows: list[dict[str, Any]]) -> ToolResult:
    """Build the ``(summary, chunks)`` payload uniformly across all modes.

    Centralising this guarantees mode 2 and mode 3 produce the SAME
    shape as the existing query path, so downstream consumers (the
    intake_node LLM step) are mode-agnostic.

    ``hybrid_score`` is preserved when present (mode 1) and reported as
    ``None`` for the unranked modes (2, 3) — the node sees a stable
    key whose value carries the right "no rank available" signal.

    The summary carries only IDs/counts/offsets — never the raw chunk
    text — so the chokepoint's audit row can log
    ``result.data["summary"]`` without leaking document content.
    """
    summary = {
        "chunk_count": len(rows),
        "chunk_ids": [str(r["chunk_id"]) for r in rows],
        "offsets": [
            {
                "chunk_id": str(r["chunk_id"]),
                "char_offset_start": r["char_offset_start"],
                "char_offset_end": r["char_offset_end"],
                "page_start": r["page_start"],
                "page_end": r["page_end"],
            }
            for r in rows
        ],
    }
    chunks = [
        {
            "chunk_id": str(r["chunk_id"]),
            "document_id": str(r["document_id"]),
            "file_id": str(r["file_id"]) if r.get("file_id") is not None else None,
            "file_name": r["file_name"],
            "content": r["content"],
            "hybrid_score": r.get("hybrid_score"),
            "char_offset_start": r["char_offset_start"],
            "char_offset_end": r["char_offset_end"],
        }
        for r in rows
    ]
    return ToolResult(
        cost_usd=Decimal("0"),
        data={
            "summary": summary,
            "chunks": chunks,
        },
    )


async def _handle_gateway_inference(
    intent: ToolIntent,
    params: dict[str, Any],
    *,
    gateway: Any,
    estimated_cost: Decimal,
) -> ToolResult:
    """Handle ``run_skill`` and ``run_playbook`` via a gateway chat-completion.

    Mirrors :func:`app.playbooks.nodes._dispatch_structured_call`.

    ``anonymize`` defaults ``True`` — the autonomous flow may carry
    privileged context; routing through the gateway with anonymize=True
    gets pseudonymization + tier-floor for free.  Override only by
    passing ``anonymize=False`` explicitly in ``params`` (e.g. for a
    session that has already stripped PII upstream).

    Cost = ``estimated_cost`` from the chokepoint (the SAME value R4
    checked); no re-estimation, no double-charge.

    Args:
        intent: ``run_skill`` or ``run_playbook``.
        params: Must contain ``model`` (str) and ``messages``
            (list[dict] with ``role``/``content``).  Optional:
            ``max_tokens`` (int), ``anonymize`` (bool, default True).
        gateway: Gateway client.
        estimated_cost: Pre-computed R4 estimate; returned as cost_usd.

    Returns:
        :class:`ToolResult` with ``cost_usd=estimated_cost`` and
        ``data`` carrying ``content`` (text for node), ``token_counts``
        (prompt + completion), and ``intent`` (for routing logs).
        On gateway transport error, ``data["error"]`` is set and the
        call is still charged ``estimated_cost`` (the call was attempted).
    """
    from app.schemas.gateway import ChatCompletionMessage, ChatCompletionRequest

    model: str = params["model"]
    raw_messages: list[dict[str, Any]] = params["messages"]
    max_tokens: int | None = params.get("max_tokens")
    anonymize: bool = bool(params.get("anonymize", True))

    messages = [ChatCompletionMessage(role=m["role"], content=m["content"]) for m in raw_messages]

    request = ChatCompletionRequest(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        anonymize=anonymize,
        lq_ai_purpose="autonomous_executor",
    )

    try:
        response = await gateway.chat_completion(request)
    except Exception as exc:
        log.warning(
            "autonomous gateway inference error for %s: %s",
            intent,
            exc,
            extra={
                "event": "autonomous_gateway_inference_error",
                "intent": str(intent),
                "error_type": type(exc).__name__,
            },
        )
        # The call was attempted — charge the estimate so R4's budget
        # accounting is not gamed by a flaky gateway.
        return ToolResult(
            cost_usd=estimated_cost,
            outcome="gateway_error",
            data={
                "intent": str(intent),
                "error": f"{type(exc).__name__}: {exc}",
                "content": None,
                "token_counts": {"prompt_tokens": 0, "completion_tokens": 0},
            },
        )

    try:
        choices = response.choices
        content = choices[0].message.content if choices else None
        usage = response.usage
        token_counts = {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
        }
    except (AttributeError, IndexError) as exc:
        log.warning(
            "autonomous gateway inference: malformed response for %s: %s",
            intent,
            exc,
            extra={
                "event": "autonomous_gateway_inference_parse_error",
                "intent": str(intent),
            },
        )
        return ToolResult(
            cost_usd=estimated_cost,
            outcome="gateway_error",
            data={
                "intent": str(intent),
                "error": f"malformed_response: {exc}",
                "content": None,
                "token_counts": {"prompt_tokens": 0, "completion_tokens": 0},
            },
        )

    return ToolResult(
        cost_usd=estimated_cost,
        data={
            "intent": str(intent),
            "content": content,
            "token_counts": token_counts,
        },
    )
