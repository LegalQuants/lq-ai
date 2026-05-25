"""LangGraph nodes for the Autonomous executor — M4-A2.

Five phase nodes run sequentially:

1. :func:`make_intake_node` — intake phase: orient the session,
   retrieve any immediately needed context.
2. :func:`make_analysis_node` — analysis phase: evaluate the
   incoming trigger against retrieved chunks, run skills / playbooks.
3. :func:`make_drafting_node` — drafting phase: produce work product
   (findings, proposed edits, memory proposals).
4. :func:`make_ethics_review_node` — ethics-review phase: validate
   the proposed output for privilege sensitivity, scope creep, etc.
5. :func:`make_delivery_node` — delivery phase: notify the user /
   downstream system and wrap up the session.

**Skeleton scope (M4-A2):** the nodes advance the phase machine and
write audit rows via :func:`~app.autonomous.phases.run_phase_transition`,
but they do NOT invoke any real tools. Every code path that would invoke
a tool MUST go through :func:`guarded_tool_call`. The stub defined in
this module raises :exc:`NotImplementedError` to prove no tool path
bypasses the chokepoint-to-be (which lands in M4-A3).

**Brake-commit contract (A3.3b):** when A3.3b wires these nodes to call
:func:`app.autonomous.guard.guarded_tool_call`, an
:exc:`~app.errors.AutonomousBrake` (SessionHalted / CostCapReached /
ToolNotGranted) must be allowed to **propagate to the executor's terminal
handler**, which commits and persists the halt-state latch + audit rows
the chokepoint flushed. A node that catches a brake locally MUST commit
before returning, or the latch and audit row are silently lost (the A2
data-loss class — see :mod:`app.autonomous.guard`).

Factory-closure style: each ``make_*_node`` function returns an async
callable bound to the resources it needs (``db``, ``gateway``) so the
LangGraph node functions remain pure-ish over the state dict and
:class:`~langgraph.graph.StateGraph` merge semantics stay clean.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.phases import run_phase_transition
from app.autonomous.state import AutonomousSessionState
from app.models.autonomous import AutonomousSession
from app.schemas.autonomous import Phase

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Chokepoint stub — replaced by the real implementation in M4-A3
# ---------------------------------------------------------------------------


def guarded_tool_call(
    intent: str,
    /,
    **kwargs: Any,
) -> Any:
    """Chokepoint for all autonomous tool invocations.

    Every tool path in the executor MUST route through this function.
    In M4-A2 it is a stub that raises :exc:`NotImplementedError` to
    prove no tool path bypasses the gate. M4-A3 replaces the body with
    the real phase-grant check + brake check + call dispatch.

    Args:
        intent: A :class:`~app.autonomous.enums.ToolIntent` member (or
            its string value) identifying the requested operation.
        **kwargs: Tool-specific arguments (forwarded in M4-A3).

    Raises:
        NotImplementedError: Always — this is a stub.
    """

    raise NotImplementedError("guarded_tool_call lands in M4-A3")


# ---------------------------------------------------------------------------
# Phase node factories
# ---------------------------------------------------------------------------


def make_intake_node(
    db: AsyncSession,
) -> Callable[[AutonomousSessionState], Awaitable[dict[str, Any]]]:
    """Build the intake-phase node bound to a DB session.

    The intake node transitions the session to :attr:`Phase.intake`
    (it is already there at graph entry, but the transition audit row
    documents when the graph first ran this phase). Any tool calls in
    the intake phase MUST go through :func:`guarded_tool_call` with
    :attr:`~app.autonomous.enums.ToolIntent.retrieve_chunks`.

    In the M4-A2 skeleton no tools are actually called.
    """

    async def intake_node(state: AutonomousSessionState) -> dict[str, Any]:
        session_id = state["session_id"]
        session = await db.get(AutonomousSession, session_id)
        if session is None:
            logger.error(
                "autonomous.intake_node: session not found",
                extra={"event": "autonomous_intake_session_missing", "session_id": session_id},
            )
            return {"error": f"session {session_id} not found in intake_node"}

        logger.info(
            "autonomous.intake_node: entering",
            extra={"event": "autonomous_intake_enter", "session_id": session_id},
        )
        await run_phase_transition(session, Phase.intake, db)
        await db.flush()

        return {"current_phase": str(Phase.intake)}

    return intake_node


def make_analysis_node(
    db: AsyncSession,
) -> Callable[[AutonomousSessionState], Awaitable[dict[str, Any]]]:
    """Build the analysis-phase node bound to a DB session.

    The analysis node transitions the session to :attr:`Phase.analysis`.
    Any tool calls in this phase MUST go through :func:`guarded_tool_call`
    with one of the analysis-phase grants:
    ``retrieve_chunks``, ``run_skill``, ``run_playbook``.

    In the M4-A2 skeleton no tools are actually called.
    """

    async def analysis_node(state: AutonomousSessionState) -> dict[str, Any]:
        if state.get("error"):
            return {}

        session_id = state["session_id"]
        session = await db.get(AutonomousSession, session_id)
        if session is None:
            return {"error": f"session {session_id} not found in analysis_node"}

        logger.info(
            "autonomous.analysis_node: entering",
            extra={"event": "autonomous_analysis_enter", "session_id": session_id},
        )
        await run_phase_transition(session, Phase.analysis, db)
        await db.flush()

        return {"current_phase": str(Phase.analysis)}

    return analysis_node


def make_drafting_node(
    db: AsyncSession,
) -> Callable[[AutonomousSessionState], Awaitable[dict[str, Any]]]:
    """Build the drafting-phase node bound to a DB session.

    The drafting node transitions the session to :attr:`Phase.drafting`.
    Any tool calls in this phase MUST go through :func:`guarded_tool_call`
    with one of the drafting-phase grants:
    ``run_skill``, ``emit_finding``, ``propose_memory``.

    In the M4-A2 skeleton no tools are actually called.
    """

    async def drafting_node(state: AutonomousSessionState) -> dict[str, Any]:
        if state.get("error"):
            return {}

        session_id = state["session_id"]
        session = await db.get(AutonomousSession, session_id)
        if session is None:
            return {"error": f"session {session_id} not found in drafting_node"}

        logger.info(
            "autonomous.drafting_node: entering",
            extra={"event": "autonomous_drafting_enter", "session_id": session_id},
        )
        await run_phase_transition(session, Phase.drafting, db)
        await db.flush()

        return {"current_phase": str(Phase.drafting)}

    return drafting_node


def make_ethics_review_node(
    db: AsyncSession,
) -> Callable[[AutonomousSessionState], Awaitable[dict[str, Any]]]:
    """Build the ethics-review-phase node bound to a DB session.

    The ethics-review node transitions the session to
    :attr:`Phase.ethics_review`. The only tool intent permitted in this
    phase is ``emit_finding``.

    In the M4-A2 skeleton no tools are actually called.
    """

    async def ethics_review_node(state: AutonomousSessionState) -> dict[str, Any]:
        if state.get("error"):
            return {}

        session_id = state["session_id"]
        session = await db.get(AutonomousSession, session_id)
        if session is None:
            return {"error": f"session {session_id} not found in ethics_review_node"}

        logger.info(
            "autonomous.ethics_review_node: entering",
            extra={"event": "autonomous_ethics_review_enter", "session_id": session_id},
        )
        await run_phase_transition(session, Phase.ethics_review, db)
        await db.flush()

        return {"current_phase": str(Phase.ethics_review)}

    return ethics_review_node


def make_delivery_node(
    db: AsyncSession,
) -> Callable[[AutonomousSessionState], Awaitable[dict[str, Any]]]:
    """Build the delivery-phase node bound to a DB session.

    The delivery node transitions the session to :attr:`Phase.delivery`
    and marks the session row as completed. The only tool intent
    permitted in this phase is ``notify``.

    In the M4-A2 skeleton no tools are actually called.
    """

    async def delivery_node(state: AutonomousSessionState) -> dict[str, Any]:
        if state.get("error"):
            return {}

        session_id = state["session_id"]
        session = await db.get(AutonomousSession, session_id)
        if session is None:
            return {"error": f"session {session_id} not found in delivery_node"}

        logger.info(
            "autonomous.delivery_node: entering",
            extra={"event": "autonomous_delivery_enter", "session_id": session_id},
        )
        await run_phase_transition(session, Phase.delivery, db)
        session.status = "completed"
        session.completed_at = datetime.now(UTC)
        await db.commit()

        return {"current_phase": str(Phase.delivery)}

    return delivery_node
