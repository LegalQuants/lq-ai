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
``emit_artifact``   — persists a document-grade artifact into the run's
                      target KB: upload-first to object storage, then
                      File + Document + chunks + direct KB attach +
                      an ``autonomous_artifacts`` reference; zero cost.
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

import hashlib
import json
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
    AutonomousArtifact,
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

# emit_artifact: hard ceiling on artifact content length. LLM-emitted
# content is clamped (truncated, flagged in the result data) rather than
# rejected — a partial memo in the KB beats a lost run.
_ARTIFACT_MAX_CHARS: int = 1_000_000

# External-tool intents (PR5a): these reach OUTSIDE the operator's environment
# through the gateway, so they are governed per-call by
# ``governed_tool_invocation`` (a ``tool_call_log`` row + the egress-tier
# pre-check + span annotation). Every OTHER intent is a local write or a local
# retrieval and stays on ``autonomous_audit`` only — no ``tool_call_log`` noise.
_EXTERNAL_TOOL_INTENTS: frozenset[ToolIntent] = frozenset(
    {ToolIntent.retrieve_caselaw, ToolIntent.call_mcp_tool, ToolIntent.retrieve_authority}
)


def _args_digest(params: dict[str, Any]) -> str:
    """Return a short, stable digest of *params* for the audit row.

    COUNTS/TYPES ONLY — never the raw args. The digest is a sha256 over a
    canonical (sorted-key) JSON projection of the param TYPES and the
    top-level KEY NAMES, never the values; values that are not JSON-stable
    fall back to their type name. Truncated to 16 hex chars — enough to
    correlate two identical calls without ever reconstructing the payload.
    """
    shape = {k: type(v).__name__ for k, v in sorted(params.items())}
    blob = json.dumps(shape, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


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
        if intent in _EXTERNAL_TOOL_INTENTS:
            # External tools reach outside the operator's environment via the
            # gateway, so they flow through the shared governance substrate:
            # a tool_call_log row + the egress-tier pre-check + span
            # annotation. The single R4 estimate computed above is forwarded
            # as estimated_cost — the helper NEVER re-estimates (single-estimate
            # invariant). The dispatch closure runs the same per-intent handler
            # every other intent uses; this only ADDS the external-tool audit.
            result = await _governed_external_dispatch(
                intent,
                params,
                db=db,
                session=session,
                gateway=gateway,
                estimate=estimate,
                span=span,
            )
        else:
            # Local writes (emit_finding/propose_memory/…) and local retrieval
            # (retrieve_chunks) are NOT external tool calls — they stay on
            # autonomous_audit only, exactly as before. No tool_call_log row.
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


async def _resolve_external_call(
    intent: ToolIntent,
    params: dict[str, Any],
    gateway: Any,
) -> tuple[str, str]:
    """Resolve the ``(provider, tool)`` marker for a governed external call.

    For ``retrieve_caselaw`` the provider is the configured CourtListener
    provider name (resolved via the research service's provider-resolution
    helper — PR3b retired the hardcoded name) and the ``tool`` is the research
    op (e.g. ``"search_case_law"``).  For ``call_mcp_tool`` the provider/tool
    come straight from the params the model supplied.  For
    ``retrieve_authority`` the provider is resolved via the live content-source
    registry (``resolve_available_sources``) filtered to enabled sources only
    (ADR 0021 D5 / WS-E PR1a); a disabled or unknown source raises
    :exc:`ValueError` BEFORE ``governed_tool_invocation`` writes any audit row
    (validation-before-side-effect invariant).

    These markers are the ``provider``/``tool`` columns on the ``tool_call_log``
    row and the key into ``resolve_provider_tier`` — counts/types only, never
    raw args.

    Args:
        intent: The external :class:`~app.autonomous.enums.ToolIntent`.
        params: The call params dict.
        gateway: The Inference Gateway client; required for
            ``retrieve_authority`` to call ``resolve_available_sources``.
    """
    if intent == ToolIntent.retrieve_caselaw:
        from app.research import service as research_service

        provider = await research_service._resolve_provider()
        op = str(params.get("op") or "")
        return provider, op
    if intent == ToolIntent.call_mcp_tool:
        return str(params["provider"]), str(params["tool"])
    if intent == ToolIntent.retrieve_authority:
        # WS-E PR1a: resolve the GovInfo provider name via the live registry.
        # Validation-before-side-effect: raise ValueError for unknown/disabled
        # source BEFORE governed_tool_invocation writes any tool_call_log row,
        # so a bad model-supplied source never poisons the session state.
        from app.research.registry import resolve_available_sources

        source_type = str(params.get("source") or "")
        sources = await resolve_available_sources(gateway)
        matching = [s for s in sources if s.type == source_type and s.enabled]
        if not matching:
            raise ValueError(
                f"retrieve_authority: source {source_type!r} not available or disabled"
            )
        return str(matching[0].name), str(params.get("op") or "")
    raise ValueError(f"_resolve_external_call: not an external intent {intent!r}")


async def _governed_external_dispatch(
    intent: ToolIntent,
    params: dict[str, Any],
    *,
    db: AsyncSession,
    session: AutonomousSession,
    gateway: Any,
    estimate: Decimal,
    span: Any,
) -> ToolResult:
    """Route an external-tool intent through ``governed_tool_invocation``.

    Resolves ``provider``/``tool`` + ``provider_tier``, then delegates the
    tier-check → ``tool_call_log`` row → dispatch → record primitives to the
    shared helper, annotating the caller-owned ``autonomous.tool_call`` span
    (D-a1).  The ``estimate`` from R4 is forwarded verbatim as
    ``estimated_cost`` (single-estimate invariant — the helper never
    re-estimates).  ``max_allowed_tier=None`` because an
    :class:`~app.models.autonomous.AutonomousSession` carries no per-session
    tier ceiling in v1 (the gateway still enforces the ceiling on the actual
    call — defence in depth).  ``origin="autonomous"`` and there is no
    per-user OAuth token (D-a5).
    """
    # Local import: governance.py imports ToolResult from this module, so a
    # top-level import here would be circular.
    from app.tools.governance import governed_tool_invocation, resolve_provider_tier

    provider, tool = await _resolve_external_call(intent, params, gateway)
    provider_tier = await resolve_provider_tier(provider)

    async def _dispatch_closure() -> ToolResult:
        return await _dispatch(
            intent, params, gateway=gateway, db=db, session=session, estimated_cost=estimate
        )

    return await governed_tool_invocation(
        db,
        origin="autonomous",
        provider=provider,
        tool=tool,
        intent=intent,
        provider_tier=provider_tier,
        max_allowed_tier=None,  # AutonomousSession has no tier ceiling in v1
        estimated_cost=estimate,  # single-estimate — forwarded, never re-estimated
        dispatch=_dispatch_closure,
        span=span,
        user_id=session.user_id,
        session_id=session.id,
        args_digest=_args_digest(params),
        denied_on=(ToolNotGranted,),  # D4 policy refusals → outcome="denied", not "error"
    )


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

    if intent == ToolIntent.emit_artifact:
        return await _handle_emit_artifact(params, db=db, session=session)

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

    if intent in (ToolIntent.run_skill, ToolIntent.run_playbook, ToolIntent.plan):
        return await _handle_gateway_inference(
            intent, params, gateway=gateway, estimated_cost=estimated_cost
        )

    if intent == ToolIntent.retrieve_caselaw:
        return await _handle_retrieve_caselaw(params, db=db)

    if intent == ToolIntent.call_mcp_tool:
        return await _handle_call_mcp_tool(params, db=db)

    if intent == ToolIntent.retrieve_authority:
        return await _handle_retrieve_authority(params, db=db, gateway=gateway)

    # Should be unreachable: PHASE_GRANTS + R6 prevent unknown intents.
    raise ValueError(f"_dispatch: unhandled intent {intent!r}")


async def _handle_retrieve_caselaw(
    params: dict[str, Any],
    *,
    db: AsyncSession,
) -> ToolResult:
    """Handle ``retrieve_caselaw`` — gateway-brokered case-law research (PR5a).

    Routes ``params["op"]`` to the already-built research service
    (:mod:`app.research.service`, ADR 0014: the backend never calls
    CourtListener directly — every op goes through the gateway):

    - ``verify_citations`` → ``{text}``
    - ``search_case_law``  → ``{args}`` (or the remaining params as the search args)
    - ``get_cluster``      → ``{cluster_id}``
    - ``read_opinion``     → ``{opinion_id}``
    - ``find_in_case``     → ``{opinion_id, query[, max_matches]}``

    Realized cost is resolved via the per-provider cost model (DE-344);
    falls back to ``Decimal("0")`` if resolution fails (non-fatal).
    The provider/tool/tier audit was already written by
    ``governed_tool_invocation``; this handler only does the call.

    Raises:
        ValueError: if ``op`` is missing or not a recognised research op.
            (Unreachable via the executor, which only emits valid ops.)
    """
    from app.research import service as research_service

    op = str(params.get("op") or "")
    if op == "verify_citations":
        data = await research_service.verify_citations(params["text"])
    elif op == "search_case_law":
        args = params.get("args")
        if args is None:
            args = {k: v for k, v in params.items() if k != "op"}
        data = await research_service.search_case_law(args)
    elif op == "get_cluster":
        data = await research_service.get_cluster(db, cluster_id=int(params["cluster_id"]))
    elif op == "read_opinion":
        data = await research_service.read_opinion(db, opinion_id=int(params["opinion_id"]))
    elif op == "find_in_case":
        matches = await research_service.find_in_case(
            db,
            opinion_id=int(params["opinion_id"]),
            query=str(params["query"]),
            max_matches=int(params.get("max_matches", 3)),
        )
        data = {"matches": matches}
    else:
        raise ValueError(f"_handle_retrieve_caselaw: unknown research op {op!r}")

    # ── DE-344: realized cost from per-provider cost model ──────────────────
    # Local import avoids circular: governance.py → guard.py → cost.py.
    # Non-fatal: any failure defaults to Decimal("0").
    realized_cost: Decimal = Decimal("0")
    try:
        from app.tools.governance import resolve_provider_cost

        provider = await research_service._resolve_provider()
        realized_cost = await resolve_provider_cost(provider)
    except Exception:
        pass

    return ToolResult(cost_usd=realized_cost, data=data)


async def _handle_call_mcp_tool(
    params: dict[str, Any],
    *,
    db: AsyncSession,
) -> ToolResult:
    """Handle ``call_mcp_tool`` — a gateway-brokered MCP tool call (PR5a).

    **ADR 0015 D4 enforcement (FIRST, before any gateway call):** load the
    cached :class:`~app.models.mcp.MCPToolCache` row for
    ``(params["provider"], params["tool"])``.  If the row is **missing**, or
    its ``destructive`` is true, or its ``requires_confirmation`` is true, or
    its ``enabled`` is false (operator-disabled toggle), raise
    :exc:`~app.errors.ToolNotGranted` and make NO gateway call — the
    autonomous layer in v1 NEVER fires a human-gated, operator-disabled, or
    unknown tool.

    Otherwise call the gateway's
    :meth:`~app.clients.gateway.GatewayClient.call_tool` with no per-user
    OAuth token (D-a5: the autonomous layer has no interactive user; an
    ``auth: oauth`` MCP server therefore raises
    :exc:`~app.errors.MCPAuthorizationRequired` from the gateway adapter,
    which is left to propagate — correct, autonomous cannot use per-user-OAuth
    servers).  ``max_allowed_tier=None`` (no per-session ceiling in v1; the
    gateway still enforces its configured ceiling).

    Zero cost in v1 (D-a3 / DE-344).

    Raises:
        ToolNotGranted: the tool is unknown to the cache, ``destructive``,
            ``requires_confirmation``, or operator-disabled (``enabled=False``)
            (D4 — no gateway call is made).
    """
    provider = str(params["provider"])
    tool = str(params["tool"])
    args: dict[str, Any] = params.get("args") or {}

    # ── D4: load cached metadata FIRST; refuse before any gateway call ──────
    from app.models.mcp import MCPToolCache

    cached = await db.get(MCPToolCache, (provider, tool))
    if cached is None or cached.destructive or cached.requires_confirmation or not cached.enabled:
        # Counts/types only in the reason — never the args.
        if cached is None:
            reason = "tool_not_cached"
        elif cached.destructive:
            reason = "destructive"
        elif cached.requires_confirmation:
            reason = "requires_confirmation"
        else:
            reason = "tool_disabled"
        raise ToolNotGranted(
            "MCP tool refused for the autonomous layer (D4)",
            intent=str(ToolIntent.call_mcp_tool),
            phase="analysis",
            details={"provider": provider, "tool": tool, "reason": reason},
        )

    # ── gateway call — no per-user OAuth token (D-a5) ───────────────────────
    # call_tool carries no per-user token (D-a5); auth:oauth MCP servers
    # therefore fail at the gateway.
    from app.clients.gateway import get_gateway_client

    result = await get_gateway_client().call_tool(provider, tool, args, max_allowed_tier=None)

    # ── DE-344: realized cost from per-provider cost model ──────────────────
    # Local import avoids circular: governance.py → guard.py → cost.py.
    # Non-fatal: any failure defaults to Decimal("0").
    realized_cost: Decimal = Decimal("0")
    try:
        from app.tools.governance import resolve_provider_cost

        realized_cost = await resolve_provider_cost(provider)
    except Exception:
        pass

    return ToolResult(cost_usd=realized_cost, data=result.get("payload"))


async def _handle_retrieve_authority(
    params: dict[str, Any],
    *,
    db: AsyncSession,
    gateway: Any,
) -> ToolResult:
    """Handle ``retrieve_authority`` — GovInfo authority retrieval via gateway.

    Fetches a US federal statute or regulation through the Inference Gateway
    (ADR 0014: the backend never calls GovInfo directly; every op goes through
    the gateway egress).  The response is normalised by
    :class:`~app.research.adapters.GovInfoAdapter` into a
    :class:`~app.research.adapters.FetchedAuthority` and returned as
    ``ToolResult.data["authority"]`` (text, external_ref, label, url,
    content_kind).

    Validation order (before any gateway call or DB write):

    1. Resolve available sources via the live registry
       (:func:`~app.research.registry.resolve_available_sources`); raise
       :exc:`ValueError` if the requested source is absent or disabled
       (ADR 0021 D5 — honest unavailability; belt-and-suspenders after
       ``_resolve_external_call`` already checked).
    2. Check the requested op is in the source's registered ops; raise
       :exc:`ValueError` if not.

    Provenance note (PR1a adaptation)
    ----------------------------------
    The brief specifies writing a ``MessageToolSource`` provenance row here.
    This is architecturally impossible in the autonomous context:
    ``message_tool_sources.message_id`` is ``NOT NULL FK → messages.id``, and
    no ``message_id`` exists in the autonomous executor.  The
    ``retrieve_caselaw`` handler (the closest prior analog) also does NOT write
    a ``MessageToolSource`` row.  Provenance is captured instead in:

    - ``ToolResult.data["authority"]`` (text, external_ref, label, url,
      content_kind) — returned to the caller for further use.
    - The ``tool_call_log`` row written by ``governed_tool_invocation``
      (provider, tool, intent, tier, outcome) — durable external-call audit.

    Character-fidelity verification and ledger-backing are PR1b (out of scope
    here).  No migration is added in PR1a.

    Zero cost in v1 (D-a3: no provider-inference tokens; per-provider
    external-tool cost model deferred to DE-344 / Task 7).

    Args:
        params: Must contain ``"source"`` (str, SOURCE_REGISTRY type key),
            ``"op"`` (str, one of the source's registered ops), and optionally
            ``"args"`` (dict — defaults to ``{}`` if absent or None).
        db: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.  Not used
            for writes in PR1a (no provenance row); reserved for PR1b.
        gateway: The Inference Gateway client.  Used for
            ``resolve_available_sources`` (provider discovery) and
            ``call_tool`` (the actual egress call).

    Returns:
        :class:`ToolResult` with ``cost_usd=Decimal("0")`` and
        ``data={"authority": {text, external_ref, label, url, content_kind}}``.

    Raises:
        ValueError: If the source is unknown/disabled, or the op is not
            registered for that source.  These are clean model-arg errors —
            the WS-D agentic loop treats them as non-fatal failed observations.
    """
    from app.research.registry import SOURCE_REGISTRY, resolve_available_sources

    source_type = str(params.get("source") or "")
    op = str(params.get("op") or "")
    args: dict[str, Any] = params.get("args") or {}

    # ── Validate: source enabled (belt-and-suspenders; _resolve_external_call
    # already checked, but validate again before the gateway call so a race
    # or param-mutation between the two can never bypass source validation).
    sources = await resolve_available_sources(gateway)
    enabled_map = {s.type: s for s in sources if s.enabled}
    source = enabled_map.get(source_type)
    if source is None:
        raise ValueError(
            f"_handle_retrieve_authority: source {source_type!r} not available or disabled"
        )

    # ── Validate: op ∈ source's registered ops ──────────────────────────────
    spec = SOURCE_REGISTRY.get(source_type)
    if spec is None or op not in spec.ops:
        raise ValueError(
            f"_handle_retrieve_authority: op {op!r} not in registered ops for "
            f"source {source_type!r}"
        )

    # ── One egress (ADR 0014): call through gateway only ────────────────────
    provider_name = str(source.name)
    result: dict[str, Any] = await gateway.call_tool(provider_name, op, args)
    # GatewayClient.call_tool returns the envelope {provider, tool, payload, tier};
    # the actual GovInfo fields live under result["payload"].  Match the
    # sibling convention in _handle_call_mcp_tool and research/service.py.
    payload: dict[str, Any] = result.get("payload") or {}

    # ── Normalise via adapter ────────────────────────────────────────────────
    if spec.adapter is None:
        raise ValueError(
            f"_handle_retrieve_authority: source {source_type!r} has no response adapter"
        )
    authority = spec.adapter.from_response(op, payload)

    # ── PR1b: build authority dict with source threaded in ───────────────────
    authority_data: dict[str, Any] = {
        "text": authority.citable_text,
        "external_ref": authority.external_ref,
        "label": authority.label,
        "url": authority.url,
        "content_kind": authority.content_kind,
        "source": params["source"],  # registry source name, for delivery verification
    }

    # ── PR1b: non-fatal cache write ──────────────────────────────────────────
    # Best-effort: any failure (including ValueError for a bad external_ref)
    # must not abort the fetch or poison the AsyncSession (WS-D PR1 C1 lesson).
    try:
        from app.citation.authority import store_authority_text

        await store_authority_text(
            db,
            source_type=params["source"],
            external_ref=authority.external_ref,
            text=authority.citable_text,
        )
    except Exception:
        log.warning(
            "autonomous.retrieve_authority: cache write failed; "
            "verification will fall back to carried evidence text",
            extra={"event": "authority_cache_write_failed"},
            exc_info=True,
        )

    # ── DE-344: realized cost from per-provider cost model ──────────────────
    # Local import avoids circular: governance.py → guard.py → cost.py.
    # Non-fatal: any failure defaults to Decimal("0").
    realized_cost: Decimal = Decimal("0")
    try:
        from app.tools.governance import resolve_provider_cost

        realized_cost = await resolve_provider_cost(provider_name)
    except Exception:
        pass

    return ToolResult(
        cost_usd=realized_cost,
        data={"authority": authority_data},
    )


def _sanitize_artifact_name(raw: Any) -> str:
    """Normalize an LLM-emitted artifact name into a safe filename.

    Strips NUL bytes and path separators/backslashes (basename), collapses
    whitespace, clamps to ≤255 chars (the extensionless stem is clamped to
    252 BEFORE the ``.md`` append so the guarantee actually holds), and
    guarantees a file extension (``.md`` when none is present). Never
    returns an empty string.
    """
    # Strip NUL bytes: valid JSON (LLM-emittable) but rejected by Postgres
    # TEXT at flush.
    name = str(raw or "artifact.md").replace("\x00", "")
    # Basename: an LLM-emitted "../../etc/passwd" must never become a
    # path-bearing filename.
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    # Collapse internal whitespace runs; trim edges.
    name = " ".join(name.split())
    if not name:
        name = "artifact.md"
    # Ensure a file extension so KB listings render sanely; clamp the stem
    # to 252 BEFORE appending ".md" so the ≤255 guarantee actually holds.
    name = f"{name[:252]}.md" if "." not in name else name[:255]
    return name


async def _handle_emit_artifact(
    params: dict[str, Any],
    *,
    db: AsyncSession,
    session: AutonomousSession,
) -> ToolResult:
    """Handle ``emit_artifact`` — persist a document-grade artifact into
    the run's target KB as a REAL document.  Zero cost (local writes).

    Order of operations is load-bearing:

    1. Skip honestly when the session has no target KB or the artifact
       content is empty — no rows, no upload.
    2. Upload the bytes to object storage FIRST (client-generated
       ``file_id`` as the key, per ADR 0005's bare-UUID scheme).  On any
       storage failure, return an honest ``storage_error`` outcome with
       NO DB rows (the gateway_error honesty pattern).
    3. Only then write File + Document + chunks + KB attach +
       ``autonomous_artifacts`` reference — all flushed, never committed
       (the executor owns the commit boundary).
    4. Best-effort embed enqueue; lazy embed-on-read covers the gap.

    Args:
        params: Must contain ``"artifact"`` — a dict with ``content``
            and optional ``name`` / ``mime``.  Missing ``"artifact"`` is
            a programming error at the call site; KeyError is acceptable
            here (the emit_finding/propose_memory/notify convention).
            The dict's inner keys are LLM-emitted, so they get tolerant
            ``.get(...) or default`` guards.
        db: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
        session: The active :class:`~app.models.autonomous.AutonomousSession`;
            the session supplies the target KB (``session.params["kb_id"]``),
            the owner, and the project scope.
    """
    import hashlib

    from app.models.document import Document, DocumentChunk
    from app.models.file import File as FileModel
    from app.models.knowledge import KnowledgeBaseFile
    from app.pipeline.chunker import chunk_document
    from app.pipeline.parsers import PageSpan, ParsedDocument
    from app.storage import upload_bytes
    from app.workers.queue import enqueue_embed_job

    # Missing "artifact" key → KeyError, the established programming-error
    # convention for local handlers (see emit_finding above).
    artifact = params["artifact"]

    # ── target KB ────────────────────────────────────────────────────────
    # No target KB → honest skip, no rows, no upload. The drafting node
    # surfaces this to the user via an explanatory finding (Task 3).
    kb_id = (session.params or {}).get("kb_id")
    if not kb_id:
        return ToolResult(
            cost_usd=Decimal("0"), outcome="skipped", data={"skipped": "no_target_kb"}
        )
    # Parse BEFORE the upload: a malformed kb_id must fail here, not at the
    # KB-attach insert after the bytes have already landed in MinIO (orphan).
    kb_uuid = uuid.UUID(str(kb_id))

    # ── extract + sanitize (inner keys are LLM-emitted) ──────────────────
    # Strip NUL bytes: "\u0000" is valid JSON (LLM-emittable) but Postgres
    # TEXT rejects \x00 at flush — post-upload, that's an orphan + failed run.
    content = str(artifact.get("content") or "").replace("\x00", "")
    if not content:
        return ToolResult(
            cost_usd=Decimal("0"), outcome="skipped", data={"skipped": "empty_content"}
        )

    truncated = len(content) > _ARTIFACT_MAX_CHARS
    if truncated:
        content = content[:_ARTIFACT_MAX_CHARS]

    name = _sanitize_artifact_name(artifact.get("name"))
    mime = str(artifact.get("mime") or "text/markdown")

    # size_bytes / hash are computed from THE ENCODED BYTES — what object
    # storage actually holds — not the character count.
    body = content.encode("utf-8")

    # Client-generated id so the upload can happen BEFORE any DB state
    # exists (per ADR 0005 the storage key IS the bare file UUID string).
    file_id = uuid.uuid4()

    # ── upload FIRST — no DB rows on storage failure ─────────────────────
    # Mirrors the gateway_error honesty pattern: an artifact the user
    # cannot download must never appear as a File row. A failed-late
    # orphan MinIO object is acceptable — the same non-reaped class as
    # ADR 0005's soft-deleted file bytes.
    try:
        await upload_bytes(storage_path=str(file_id), body=body, content_type=mime)
    except Exception as exc:
        log.warning(
            "emit_artifact: storage upload failed; no DB rows written",
            extra={
                "event": "autonomous_artifact_storage_error",
                "session_id": str(session.id),
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        return ToolResult(
            cost_usd=Decimal("0"),
            outcome="storage_error",
            data={"error": f"{type(exc).__name__}: {exc}"},
        )

    # ── File row ─────────────────────────────────────────────────────────
    # ingestion_status='ready' immediately: the Document + chunks are
    # written synchronously below, so the readiness the KB attach API's
    # rule guards (chunks exist and are queryable) holds at flush time.
    file_row = FileModel(
        id=file_id,
        owner_id=session.user_id,
        project_id=session.project_id,
        filename=name,
        mime_type=mime,
        size_bytes=len(body),
        hash_sha256=hashlib.sha256(body).hexdigest(),
        storage_path=str(file_id),
        ingestion_status="ready",
    )
    db.add(file_row)
    await db.flush()

    # ── Document + chunks (direct-text sibling of the ingest pipeline) ──
    # Synthetic single-page ParsedDocument over the artifact text — no PDF
    # parser involved; parser/parser_version are honest about that.
    parsed = ParsedDocument(
        canonical_text=content,
        pages=[PageSpan(page_number=1, char_start=0, char_end=len(content))],
        page_count=1,
        parser="autonomous-artifact",
        parser_version="1",
        structured_content=None,
    )
    chunks = chunk_document(parsed)

    # Persisted EXACTLY in the ingest idiom (_persist_document_and_chunks):
    # normalized_content is the same string the chunker sliced, so the
    # M2-A1 re-read invariant holds for every chunk —
    # chunk.content == normalized_content[char_offset_start:char_offset_end].
    doc = Document(
        file_id=file_row.id,
        parser=parsed.parser,
        parser_version=parsed.parser_version,
        page_count=parsed.page_count,
        character_count=len(parsed.canonical_text),
        structured_content=parsed.structured_content,
        normalized_content=parsed.canonical_text,
        was_ocrd=False,
    )
    db.add(doc)
    await db.flush()  # populate doc.id

    for chunk in chunks:
        db.add(
            DocumentChunk(
                document_id=doc.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                char_offset_start=chunk.char_offset_start,
                char_offset_end=chunk.char_offset_end,
                tokens=None,
                metadata_json=chunk.metadata,
            )
        )

    # ── KB attach — DIRECT insert on purpose ─────────────────────────────
    # fire_watches_for_kb only fires from the attach-file API handler, so
    # a direct KnowledgeBaseFile insert cannot spawn a watch-triggered
    # run — this is the loop-prevention design (a run's own memo must
    # never trigger the watch that spawned it). No duplicate-attach
    # concern: file_id is brand new.
    db.add(KnowledgeBaseFile(kb_id=kb_uuid, file_id=file_row.id))

    # ── artifact reference ───────────────────────────────────────────────
    artifact_row = AutonomousArtifact(
        session_id=session.id,
        file_id=file_row.id,
        name=name,
        mime=mime,
        size_bytes=len(body),
    )
    db.add(artifact_row)
    await db.flush()

    # ── best-effort embed enqueue ────────────────────────────────────────
    # enqueue_embed_job already swallows transport errors, but wrap anyway
    # (the notify-email belt-and-suspenders precedent). There is also a
    # pre-commit race: the worker may dequeue the job before the executor
    # commits, see no rows, and no-op — lazy embed-on-read at query time
    # covers that gap (and any transport failure) either way.
    try:
        await enqueue_embed_job(file_row.id)
    except Exception:
        log.warning(
            "emit_artifact: embed enqueue failed; embed-on-read covers the gap",
            extra={
                "event": "autonomous_artifact_embed_enqueue_error",
                "file_id": str(file_row.id),
            },
            exc_info=True,
        )

    data: dict[str, Any] = {
        "artifact_id": str(artifact_row.id),
        "file_id": str(file_row.id),
        "document_id": str(doc.id),
        "name": name,
        "size_bytes": len(body),
    }
    if truncated:
        data["truncated"] = True
    return ToolResult(cost_usd=Decimal("0"), data=data)


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

    Files referenced by ``autonomous_artifacts`` are ALSO excluded —
    a schedule's next tick retrieves "files attached since last run",
    and a prior run's own memo lands in the KB as exactly such a file;
    without the exclusion every tick re-analyzes the previous tick's
    output (self-ingestion echo).  Query-mode (mode 1) and chat RAG
    deliberately still see artifacts.

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
                # Self-ingestion-echo guard: a prior run's emit_artifact memo
                # is attached to this KB as a real file; "new since last run"
                # must not feed it back into the next run (mode 1 / chat RAG
                # deliberately still see artifacts).
                .where(
                    ~FileModel.id.in_(
                        select(AutonomousArtifact.file_id).where(
                            AutonomousArtifact.file_id.is_not(None)
                        )
                    )
                )
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
