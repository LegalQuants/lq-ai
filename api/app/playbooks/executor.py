"""Playbook executor — builds the LangGraph workflow and runs it.

Public surface: :func:`run_playbook_execution`. The endpoint layer
(``app.api.playbooks``) calls it from a FastAPI ``BackgroundTask`` so
the kick-off endpoint can return immediately with a 202 while the
workflow runs out-of-band.

Graph shape
-----------

retrieve → classify → redline → compile → END

All nodes are sequential; conditional branching isn't required for
the M3-A2 skeleton. The LangGraph runtime is still the right
substrate because:

* M3-C2 (Tabular Review) reuses the same runtime with a different
  graph shape (per-document x per-column instead of per-position).
* The node-level decomposition keeps each step testable in isolation.
* A future per-node checkpointing pass (resume on worker restart)
  drops in without restructuring the workflow.

The executor catches exceptions at the graph-invocation boundary and
writes ``status='error'`` to the row so the kick-off endpoint's
caller always sees a terminal state on poll.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients.gateway import GatewayClient
from app.models.document import Document
from app.models.playbook import Playbook, PlaybookExecution
from app.playbooks.nodes import (
    make_classify_node,
    make_compile_node,
    make_redline_node,
    make_retrieve_node,
)
from app.playbooks.state import PlaybookExecutionState

logger = logging.getLogger(__name__)

# Default judge-model alias for the classify + redline LLM calls.
# Matches the M3-A2 spec's lack of per-execution model selection — a
# future enhancement can take the alias from
# ``project.minimum_inference_tier`` / playbook-level config.
DEFAULT_JUDGE_MODEL = "smart"


class PlaybookExecutorError(Exception):
    """Raised when the executor cannot start (e.g., playbook or document missing).

    Distinct from in-graph failures (which surface via the
    ``error`` field on the ``playbook_executions`` row).
    """


async def run_playbook_execution(
    db: AsyncSession,
    *,
    execution_id: uuid.UUID,
    gateway: GatewayClient,
    judge_model: str = DEFAULT_JUDGE_MODEL,
) -> None:
    """Run the playbook execution identified by ``execution_id``.

    Updates ``playbook_executions.status`` from ``pending`` → ``running``
    on entry, then either ``completed`` (with ``results`` JSON populated)
    or ``error`` (with ``error`` text populated) on exit.

    Raises :class:`PlaybookExecutorError` if the execution row is
    missing or the referenced playbook / target document cannot be
    loaded. Otherwise, in-graph failures are caught and persisted
    rather than re-raised — the kick-off endpoint runs this as a
    background task; an uncaught exception would otherwise vanish
    into the FastAPI event loop.
    """

    execution = await db.get(PlaybookExecution, execution_id)
    if execution is None:
        raise PlaybookExecutorError(f"PlaybookExecution {execution_id} not found")

    # Move to running before the workflow starts so the UI can poll
    # for status mid-flight rather than seeing 'pending' indefinitely.
    execution.status = "running"
    await db.commit()

    try:
        playbook = await _load_playbook_with_positions(db, execution.playbook_id)
        if playbook is None:
            raise PlaybookExecutorError(
                f"Playbook {execution.playbook_id} not found for execution {execution_id}"
            )

        document = await db.get(Document, execution.target_document_id)
        if document is None:
            raise PlaybookExecutorError(
                f"Document {execution.target_document_id} not found for execution {execution_id}"
            )

        # Build the initial state dict — the keys match
        # PlaybookExecutionState's TypedDict shape but we keep the local
        # binding as plain ``dict`` so the position-conversion list
        # comprehension's element type doesn't require a TypedDict
        # cast at every site. Runtime shape is identical.
        initial_state: dict[str, Any] = {
            "execution_id": str(execution_id),
            "playbook_id": str(playbook.id),
            "target_document_id": str(document.id),
            "positions": [_position_to_dict(p) for p in playbook.positions],
            "document_normalized_content": document.normalized_content,
            "judge_model": judge_model,
            "retrievals": [],
            "per_position_results": [],
            "error": None,
        }

        graph = _build_graph(db=db, gateway=gateway, judge_model=judge_model)
        await graph.ainvoke(initial_state)

    except PlaybookExecutorError:
        # The executor couldn't even start — flip the row to error
        # and re-raise so the kick-off caller can surface a 404 / 500.
        execution.status = "error"
        execution.error = "executor: unable to start"
        await db.commit()
        raise
    except Exception as exc:
        # Any in-graph exception: persist the failure and don't re-raise.
        # The kick-off endpoint already returned 202; the client polls.
        logger.exception(
            "playbook executor crashed mid-graph",
            extra={"event": "playbook_executor_crash", "execution_id": str(execution_id)},
        )
        execution.status = "error"
        execution.error = f"{type(exc).__name__}: {exc}"[:2000]
        await db.commit()


def _build_graph(
    *,
    db: AsyncSession,
    gateway: GatewayClient,
    judge_model: str,
) -> Any:
    """Compile a LangGraph workflow for one playbook execution.

    Returned value is the LangGraph ``CompiledStateGraph``; its
    ``ainvoke`` method runs the four nodes sequentially against the
    initial state.
    """
    graph = StateGraph(PlaybookExecutionState)
    graph.add_node("retrieve", make_retrieve_node(db))
    graph.add_node(
        "classify",
        make_classify_node(gateway=gateway, judge_model=judge_model),
    )
    graph.add_node(
        "redline",
        make_redline_node(gateway=gateway, judge_model=judge_model),
    )
    graph.add_node("compile", make_compile_node(db))

    graph.add_edge("retrieve", "classify")
    graph.add_edge("classify", "redline")
    graph.add_edge("redline", "compile")
    graph.add_edge("compile", END)
    graph.set_entry_point("retrieve")

    return graph.compile()


async def _load_playbook_with_positions(
    db: AsyncSession,
    playbook_id: uuid.UUID,
) -> Playbook | None:
    """Eager-load the playbook + positions in one round-trip.

    The ``positions`` relationship's ``order_by`` clause hands back
    rows in ``position_order`` ASC so the executor's per-position
    walk is deterministic.
    """
    stmt = (
        select(Playbook).where(Playbook.id == playbook_id).options(selectinload(Playbook.positions))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def _position_to_dict(pos: Any) -> dict[str, Any]:
    """Serialize a PlaybookPosition ORM row to the executor's state shape."""
    return {
        "id": str(pos.id),
        "issue": pos.issue,
        "description": pos.description,
        "standard_language": pos.standard_language,
        "fallback_tiers": pos.fallback_tiers or [],
        "redline_strategy": pos.redline_strategy,
        "severity_if_missing": pos.severity_if_missing,
        "detection_keywords": pos.detection_keywords or [],
        "detection_examples": pos.detection_examples or [],
        "position_order": pos.position_order,
    }
