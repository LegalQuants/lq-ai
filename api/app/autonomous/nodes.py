"""LangGraph nodes for the Autonomous executor — M4-A2/A3.

Five phase nodes run sequentially:

1. :func:`make_intake_node` — intake phase: retrieve context from KB
   when ``kb_id`` is provided in state.
2. :func:`make_analysis_node` — analysis phase: evaluate the
   incoming trigger against retrieved chunks, run skills / playbooks.
3. :func:`make_drafting_node` — drafting phase: emit an orientation
   finding via the chokepoint.
4. :func:`make_ethics_review_node` — ethics-review phase: validate
   the proposed output for privilege sensitivity, scope creep, etc.
5. :func:`make_delivery_node` — delivery phase: notify the user /
   downstream system and wrap up the session.

**A3.3b wiring:** nodes call the real
:func:`~app.autonomous.guard.guarded_tool_call` from
:mod:`app.autonomous.guard`. The old stub in this module is removed.

**Brake-commit contract:** :exc:`~app.errors.AutonomousBrake`
(SessionHalted / CostCapReached / ToolNotGranted) propagates from
:func:`~app.autonomous.guard.guarded_tool_call` to the executor's
terminal handler, which commits and persists the halt-state latch +
audit rows the chokepoint flushed. A node that catches a brake locally
MUST commit before returning, or the latch and audit row are silently
lost (the A2 data-loss class — see :mod:`app.autonomous.guard`).

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

from app.autonomous.enums import ToolIntent
from app.autonomous.guard import guarded_tool_call
from app.autonomous.phases import run_phase_transition
from app.autonomous.receipt import build_receipt
from app.autonomous.state import AutonomousSessionState
from app.models.autonomous import AutonomousSession
from app.schemas.autonomous import Phase

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase node factories
# ---------------------------------------------------------------------------


def make_intake_node(
    db: AsyncSession,
    gateway: Any = None,
) -> Callable[[AutonomousSessionState], Awaitable[dict[str, Any]]]:
    """Build the intake-phase node bound to a DB session.

    The intake node transitions the session to :attr:`Phase.intake`
    then dispatches on the session's ``params`` to call
    :func:`~app.autonomous.guard.guarded_tool_call` with
    :attr:`~app.autonomous.enums.ToolIntent.retrieve_chunks` in the
    mode matching the trigger that spawned the session (M4 Tasks 9/10):

    * Watch path — ``params["file_id"]`` present: scope to the arriving
      file's chunks via mode 2 of ``_handle_retrieve_chunks``.
    * Schedule path — ``params["kb_id"]`` + ``params["since"]``: scope
      to docs attached to the KB after ``since`` (the schedule's prior
      ``last_run_at``) via mode 3.
    * Schedule first-tick — ``params["kb_id"]`` with no ``since``: no
      baseline yet; skip retrieval and set
      ``first_tick_no_baseline=True`` so downstream nodes know the
      empty input is intentional.
    * No-target — neither ``file_id`` nor ``kb_id``: stay empty;
      delivery still completes with an empty-findings notification.

    Brakes (:exc:`~app.errors.AutonomousBrake`) propagate to the
    executor's terminal handler per the brake-commit contract.
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

        updates: dict[str, Any] = {"current_phase": str(Phase.intake)}

        params = session.params or {}
        kb_id = params.get("kb_id")
        file_id = params.get("file_id")
        since = params.get("since")

        if file_id:
            # Watch path: scope to the arriving file's chunks (mode 2).
            result = await guarded_tool_call(
                session,
                ToolIntent.retrieve_chunks,
                {
                    "kb_id": str(kb_id) if kb_id else None,
                    "file_id": str(file_id),
                },
                db,
                gateway,
            )
            updates["retrieved_chunks"] = result.data.get("chunks", []) if result.data else []
        elif kb_id and since:
            # Schedule path: scope to docs attached after `since` (mode 3).
            result = await guarded_tool_call(
                session,
                ToolIntent.retrieve_chunks,
                {"kb_id": str(kb_id), "since": since},
                db,
                gateway,
            )
            updates["retrieved_chunks"] = result.data.get("chunks", []) if result.data else []
        elif kb_id and not since and not file_id:
            # First-tick schedule (last_run_at was NULL at spawn): no
            # baseline yet — record the marker and skip retrieval.
            updates["retrieved_chunks"] = []
            updates["first_tick_no_baseline"] = True
        else:
            # No target at all — degenerate session (test/manual). Stay
            # empty; delivery will still complete with an empty-findings
            # notification.
            updates["retrieved_chunks"] = []

        return updates

    return intake_node


def make_analysis_node(
    db: AsyncSession,
    gateway: Any = None,
) -> Callable[[AutonomousSessionState], Awaitable[dict[str, Any]]]:
    """Build the analysis-phase node bound to a DB session.

    The analysis node transitions the session to :attr:`Phase.analysis`.
    Any tool calls in this phase MUST go through
    :func:`~app.autonomous.guard.guarded_tool_call` with one of the
    analysis-phase grants: ``retrieve_chunks``, ``run_skill``,
    ``run_playbook``.

    In the current skeleton no inference tools are called; the node
    advances the phase machine and records the audit row.
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
    gateway: Any = None,
) -> Callable[[AutonomousSessionState], Awaitable[dict[str, Any]]]:
    """Build the drafting-phase node bound to a DB session.

    The drafting node transitions the session to :attr:`Phase.drafting`
    and emits an orientation finding via
    :func:`~app.autonomous.guard.guarded_tool_call` with
    :attr:`~app.autonomous.enums.ToolIntent.emit_finding`.

    Brakes propagate to the executor's terminal handler per the
    brake-commit contract.
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

        # Emit an orientation finding through the chokepoint so the
        # drafting phase always exercises the chokepoint path — no tool
        # call bypasses the gate.
        finding_result = await guarded_tool_call(
            session,
            ToolIntent.emit_finding,
            {"finding": {"phase": "drafting", "status": "oriented"}},
            db,
            gateway,
        )
        findings = list(state.get("findings") or [])
        if finding_result.data is not None:
            findings.append(finding_result.data)

        return {"current_phase": str(Phase.drafting), "findings": findings}

    return drafting_node


def make_ethics_review_node(
    db: AsyncSession,
    gateway: Any = None,
) -> Callable[[AutonomousSessionState], Awaitable[dict[str, Any]]]:
    """Build the ethics-review-phase node bound to a DB session.

    The ethics-review node transitions the session to
    :attr:`Phase.ethics_review`. The only tool intent permitted in this
    phase is ``emit_finding``.

    In the current skeleton no tools are called; the node advances the
    phase machine and records the audit row.
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
    gateway: Any = None,
) -> Callable[[AutonomousSessionState], Awaitable[dict[str, Any]]]:
    """Build the delivery-phase node bound to a DB session.

    The delivery node transitions the session to :attr:`Phase.delivery`,
    calls :func:`~app.autonomous.guard.guarded_tool_call` with
    :attr:`~app.autonomous.enums.ToolIntent.notify` to write the
    in-app notification row, then marks the session as completed and
    commits.

    Brakes propagate to the executor's terminal handler per the
    brake-commit contract.
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

        # Notify the user via the chokepoint — this is the canonical tool
        # call in the delivery phase; it must not bypass the gate.
        finding_count = len(state.get("findings") or [])
        await guarded_tool_call(
            session,
            ToolIntent.notify,
            {
                "title": "Autonomous session complete",
                "body": f"Session completed with {finding_count} finding(s).",
                "payload": {"finding_count": finding_count},
            },
            db,
            gateway,
        )

        session.status = "completed"
        session.completed_at = datetime.now(UTC)
        # Persist the receipt into result BEFORE the commit so the JSONB
        # column is populated atomically with the terminal status update.
        # build_receipt reads audit rows that were flushed during the run
        # and are visible in the same session/transaction.
        session.result = await build_receipt(session, db)
        await db.commit()

        return {"current_phase": str(Phase.delivery)}

    return delivery_node
