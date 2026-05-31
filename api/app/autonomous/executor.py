"""Autonomous executor — builds the LangGraph workflow and runs it.

Public surface: :func:`run_autonomous_session`. The arq worker
(:mod:`app.workers.autonomous_worker`) calls it after dequeuing an
``autonomous_session_job``.

Graph shape
-----------

intake → analysis → drafting → ethics_review → delivery → END

All five nodes are sequential (no conditional branching in the M4-A2
skeleton). The LangGraph runtime is the right substrate because:

* Subsequent M4 tasks (A3+) add per-phase tool dispatch and cost /
  halt checking without restructuring this graph.
* The node-level decomposition keeps each phase testable in isolation.
* A future per-node checkpointing pass (resume on worker restart)
  drops in without restructuring the workflow.

The executor catches exceptions at the graph-invocation boundary and
writes ``status='failed'`` to the row so polling callers always see a
terminal state. :class:`AutonomousExecutorError` is raised only for
can't-even-start failures (missing session row); in-graph failures are
caught and persisted rather than re-raised.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.nodes import (
    make_analysis_node,
    make_delivery_node,
    make_drafting_node,
    make_ethics_review_node,
    make_intake_node,
)
from app.autonomous.receipt import build_receipt_safe
from app.autonomous.state import AutonomousSessionState
from app.clients.gateway import GatewayClient
from app.errors import AutonomousBrake, ToolNotGranted
from app.models.autonomous import AutonomousSession
from app.observability_helpers import get_tracer, record_attributes

logger = logging.getLogger(__name__)


class AutonomousExecutorError(Exception):
    """Raised when the executor cannot start (e.g., session row missing).

    Distinct from in-graph failures (which surface via ``status='failed'``
    on the :class:`~app.models.autonomous.AutonomousSession` row).
    """


async def run_autonomous_session(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    gateway: GatewayClient,
) -> None:
    """Run the autonomous session identified by ``session_id``.

    Updates ``autonomous_sessions.status`` from ``running`` on entry,
    then either ``completed`` (delivery node sets it) or ``failed``
    (exception handler sets it) on exit.

    Raises :class:`AutonomousExecutorError` if the session row is
    missing (the job was enqueued for a non-existent or already-deleted
    session). Otherwise, in-graph failures are caught and persisted
    rather than re-raised — the arq worker runs this as a job; an
    uncaught exception would crash the worker process.

    Args:
        db: An async ORM session. The delivery node commits on success;
            the exception handler and error-state check commit on failure.
            The worker's ``async with`` context manager sees an already-
            committed (or already-failed) transaction on exit.
        session_id: The UUID of the :class:`~app.models.autonomous.AutonomousSession`
            row to execute.
        gateway: A :class:`~app.clients.gateway.GatewayClient` instance.
            Not used in the M4-A2 skeleton (no tool calls); passed
            through for M4-A3+ which wire the tool dispatch.
    """

    session = await db.get(AutonomousSession, session_id)
    if session is None:
        raise AutonomousExecutorError(f"AutonomousSession {session_id} not found")

    try:
        initial_state: dict[str, Any] = {
            "session_id": str(session_id),
            "user_id": str(session.user_id),
            "current_phase": str(session.current_phase),
            "halt_state": str(session.halt_state),
            "cost_total_usd": float(session.cost_total_usd),
            "max_cost_usd": float(session.max_cost_usd)
            if session.max_cost_usd is not None
            else None,
            "findings": [],
            "proposed_memory": [],
            "error": None,
            # Trigger→target seam (M4-B3): the kb_id/query for this run come
            # from session.params, populated by whichever trigger created the
            # session (schedule dispatcher, watch enqueue, manual). Other
            # param keys (playbook_id, skill_ref) stay in session.params for
            # the nodes to consume — they are not AutonomousSessionState keys.
            "kb_id": session.params.get("kb_id"),
            "query": session.params.get("query"),
            "retrieved_chunks": None,
        }

        tracer = get_tracer()
        with tracer.start_as_current_span("autonomous.execute") as span:
            record_attributes(
                span,
                **{
                    "autonomous.session_id": str(session_id),
                    "autonomous.trigger_kind": str(session.trigger_kind),
                    "autonomous.halt_state": str(session.halt_state),
                },
            )
            graph = _build_graph(db=db, gateway=gateway)
            final_state = await graph.ainvoke(initial_state)

        # Critical-2: LangGraph returns normally even when a node populates
        # ``state["error"]`` — the ``except Exception`` handler below never
        # fires in that case.  Inspect the returned state and persist the
        # failed terminal status so the row never stays at ``running``.
        if final_state.get("error"):
            session.status = "failed"
            session.error = str(final_state["error"])[:2000]
            session.completed_at = datetime.now(UTC)
            await db.commit()

    except AutonomousBrake as brake:
        # AutonomousBrake subclasses (SessionHalted / CostCapReached /
        # ToolNotGranted) propagate here.  The chokepoint already flushed
        # the halt-state latch + audit row; db.commit() below persists them.
        #
        # Terminal-status mapping (A3.3b):
        # - SessionHalted / CostCapReached → "halted"  (expected stop)
        # - ToolNotGranted                 → "failed"  (programming error:
        #     a node requested an intent not in its phase-grant set)
        status = "failed" if isinstance(brake, ToolNotGranted) else "halted"
        logger.warning(
            "autonomous executor brake: %s → %s",
            type(brake).__name__,
            status,
            extra={
                "event": "autonomous_executor_brake",
                "session_id": str(session_id),
                "brake_type": type(brake).__name__,
                "terminal_status": status,
            },
        )
        session.status = status
        session.error = f"{type(brake).__name__}: {brake}"[:2000]
        session.completed_at = datetime.now(UTC)
        # R4/R5 halted sessions get an honest receipt so the dashboard +
        # API surface terminal_reason (cost_cap_reached / external_halt).
        # The chokepoint already flushed the terminal audit row before
        # raising, so build_receipt derives terminal_reason correctly.
        # ToolNotGranted (status="failed") is intentionally excluded — a
        # failed-session receipt is a separate, deferred decision.
        if status == "halted":
            session.result = await build_receipt_safe(session, db)
        await db.commit()

    except Exception as exc:
        # Any in-graph exception: persist the failure and don't re-raise.
        # The arq worker already accepted the job; the caller polls the row.
        logger.exception(
            "autonomous executor crashed mid-graph",
            extra={
                "event": "autonomous_executor_crash",
                "session_id": str(session_id),
                "error_type": type(exc).__name__,
            },
        )
        session.status = "failed"
        session.error = f"{type(exc).__name__}: {exc}"[:2000]
        session.completed_at = datetime.now(UTC)
        await db.commit()


def _build_graph(
    *,
    db: AsyncSession,
    gateway: GatewayClient,
) -> Any:
    """Compile a LangGraph workflow for one autonomous session execution.

    Returns the compiled ``StateGraph``; its ``ainvoke`` method runs the
    five phase nodes sequentially against the initial state.

    ``gateway`` is passed to all node factories so inference tool calls
    route through the gateway client.
    """

    graph = StateGraph(AutonomousSessionState)

    graph.add_node("intake", make_intake_node(db, gateway))
    graph.add_node("analysis", make_analysis_node(db, gateway))
    graph.add_node("drafting", make_drafting_node(db, gateway))
    graph.add_node("ethics_review", make_ethics_review_node(db, gateway))
    graph.add_node("delivery", make_delivery_node(db, gateway))

    graph.add_edge("intake", "analysis")
    graph.add_edge("analysis", "drafting")
    graph.add_edge("drafting", "ethics_review")
    graph.add_edge("ethics_review", "delivery")
    graph.add_edge("delivery", END)
    graph.set_entry_point("intake")

    return graph.compile()
