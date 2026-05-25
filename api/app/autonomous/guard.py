"""The guarded_tool_call chokepoint — M4-A3.3a.

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
``notify``          — writes an ``in_app``
                      :class:`~app.models.autonomous.AutonomousNotification` row;
                      zero cost.

Deferred to A3.3b
------------------
``retrieve_chunks``, ``run_skill``, ``run_playbook`` — real inference /
retrieval handlers, executor wiring, and the privacy-guard test all land
in M4-A3.3b.  Calling any of these intents currently raises
:exc:`NotImplementedError`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.audit import autonomous_audit
from app.autonomous.cost import estimate_tool_cost
from app.autonomous.enums import PHASE_GRANTS, HaltState, Phase, ToolIntent
from app.errors import CostCapReached, SessionHalted, ToolNotGranted
from app.models.autonomous import (
    AutonomousMemory,
    AutonomousNotification,
    AutonomousSession,
)
from app.observability_helpers import get_tracer, record_attributes

_tracer = get_tracer(__name__)


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
        NotImplementedError: If ``intent`` is one of the A3.3b deferred
            handlers (``retrieve_chunks``, ``run_skill``,
            ``run_playbook``).
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
        # Estimate cost BEFORE dispatch — unconditional estimate, but the cap
        # COMPARISON is gated on max_cost_usd is not None (no cap → never trips).
        projected = session.cost_total_usd + await estimate_tool_cost(intent, params, db)
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
        result = await _dispatch(intent, params, gateway=gateway, db=db, session=session)

        # ── record cost + outcome ────────────────────────────────────────────
        session.cost_total_usd += result.cost_usd
        session.last_activity_at = datetime.now(UTC)  # feeds R5 idle watchdog (M4-A4)
        record_attributes(
            span,
            **{
                "autonomous.cost_usd": float(result.cost_usd),
                "autonomous.outcome": "success",
            },
        )
        await autonomous_audit(
            db,
            session,
            "tool_call",
            tool=str(intent),
            outcome="success",
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
) -> ToolResult:
    """Route a granted, in-budget tool intent to its handler.

    Local intents (``emit_finding``, ``propose_memory``, ``notify``) are
    fully implemented here.

    Inference/retrieval intents (``retrieve_chunks``, ``run_skill``,
    ``run_playbook``) raise :exc:`NotImplementedError`; their handlers,
    executor wiring, and the privacy-guard test land in M4-A3.3b.

    Args:
        intent: The :class:`~app.autonomous.enums.ToolIntent`.
        params: Tool-specific keyword arguments.
        gateway: Inference Gateway client (unused for local intents).
        db: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
        session: The active :class:`~app.models.autonomous.AutonomousSession`.

    Returns:
        A :class:`ToolResult` with ``cost_usd`` and tool-specific ``data``.

    Raises:
        NotImplementedError: For ``retrieve_chunks``, ``run_skill``,
            ``run_playbook`` (A3.3b).
    """
    if intent == ToolIntent.emit_finding:
        # Local, zero-cost: echo the finding payload back as data.
        # The calling node appends it to state["findings"].
        # Missing "finding" key is a programming error at the call site;
        # KeyError is acceptable here (unreachable via the executor) and is
        # consistent with the propose_memory/notify required-param access —
        # a silent None finding must never propagate into state["findings"].
        return ToolResult(cost_usd=Decimal("0"), data=params["finding"])

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

    if intent == ToolIntent.notify:
        # Local, zero-cost: write an in-app autonomous_notifications row.
        # Email transport and webhook dispatch are reserved for M4-C1 (DE-312).
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
        return ToolResult(cost_usd=Decimal("0"), data={"notification_id": str(note.id)})

    # retrieve_chunks / run_skill / run_playbook — real handlers land in A3.3b
    raise NotImplementedError(f"_dispatch for {intent!r} lands in M4-A3.3b")
