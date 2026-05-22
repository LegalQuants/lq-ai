"""Tabular Review executor — builds the LangGraph workflow and runs it.

Public surface: :func:`run_tabular_execution`. The ARQ worker
(``app.workers.tabular_worker.tabular_execution_job``) calls it after
pulling a ``tabular_executions`` row by id.

Graph shape
-----------

load_documents → extract_cells → aggregate → END

All nodes are sequential; per-cell parallelism is a v0.3.x follow-on
if the 200 x 10 latency case forces it (Decision C-3 + risk row 1).
The LangGraph runtime is the right substrate because:

* It already runs in-process inside the existing arq-worker container.
* The same shape pattern as the M3-A2 Playbook executor keeps the two
  workflows mentally cheap to maintain.
* A future per-node checkpointing pass drops in without restructuring.

The executor catches exceptions at the graph-invocation boundary and
writes ``status='failed'`` to the row so the kick-off endpoint's
caller always sees a terminal state on poll.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tabular import TabularExecution
from app.tabular.nodes import (
    make_aggregate_node,
    make_extract_cells_node,
    make_load_documents_node,
)
from app.tabular.state import TabularExecutionState

if TYPE_CHECKING:
    from app.clients.gateway import GatewayClient

logger = logging.getLogger(__name__)

# Default judge-model alias for cell extraction. Matches the
# M3-A2 playbook executor's posture — a per-execution model override
# is a v0.3.x follow-on if operators ask for one.
DEFAULT_JUDGE_MODEL = "smart"


class TabularExecutorError(Exception):
    """Raised when the executor cannot start (e.g., row missing).

    Distinct from in-graph failures (which surface via
    ``status='failed'`` + ``error_text`` on the
    ``tabular_executions`` row).
    """


async def run_tabular_execution(
    db: AsyncSession,
    *,
    execution_id: uuid.UUID,
    gateway: GatewayClient,
    judge_model: str = DEFAULT_JUDGE_MODEL,
) -> None:
    """Run the tabular execution identified by ``execution_id``.

    Lifecycle:

    * ``pending → running`` on entry; sets ``started_at``.
    * On graph success: aggregate node writes ``results``,
      ``cost_actual_usd``, flips status to ``completed`` (or
      ``failed`` if a node set ``state['error']``), sets
      ``completed_at``.
    * On uncaught exception (executor pre-start failure): flips row to
      ``failed`` + populates ``error_text``; raises only the
      pre-start :class:`TabularExecutorError` (in-graph exceptions
      are caught and persisted).

    Raises :class:`TabularExecutorError` if the row is missing.
    Otherwise in-graph failures are caught and persisted rather than
    re-raised — the kick-off endpoint runs this via ARQ; an uncaught
    exception would crash the worker task.
    """

    execution = await db.get(TabularExecution, execution_id)
    if execution is None:
        raise TabularExecutorError(f"TabularExecution {execution_id} not found")

    # Move to running so the UI can poll for mid-flight status rather
    # than seeing 'pending' indefinitely.
    from datetime import UTC, datetime

    execution.status = "running"
    execution.started_at = datetime.now(UTC)
    await db.commit()

    try:
        # The columns + document_ids are already snapshotted on the row
        # at request time (per Decision C-1's snapshotting posture).
        document_ids = [uuid.UUID(str(did)) for did in execution.document_ids]
        columns_state = list(execution.columns)

        initial_state: dict[str, Any] = {
            "execution_id": str(execution_id),
            "columns": columns_state,
            "judge_model": judge_model,
            "documents": [],
            "per_cell_results": [],
            "error": None,
        }

        graph = _build_graph(
            db=db,
            gateway=gateway,
            document_ids=document_ids,
            judge_model=judge_model,
        )
        await graph.ainvoke(initial_state)

    except TabularExecutorError:
        # Pre-start failure — flip the row to failed and re-raise.
        await _mark_failed(db, execution, "executor: unable to start")
        raise
    except Exception as exc:
        # Any in-graph exception: persist the failure and don't re-raise.
        logger.exception(
            "tabular executor crashed mid-graph",
            extra={
                "event": "tabular_executor_crash",
                "execution_id": str(execution_id),
            },
        )
        await _mark_failed(db, execution, f"{type(exc).__name__}: {exc}")


def _build_graph(
    *,
    db: AsyncSession,
    gateway: GatewayClient,
    document_ids: list[uuid.UUID],
    judge_model: str,
) -> Any:
    """Compile the LangGraph workflow for one tabular execution.

    Three nodes sequentially: load_documents → extract_cells → aggregate.
    """

    graph = StateGraph(TabularExecutionState)
    graph.add_node("load_documents", make_load_documents_node(db, document_ids))
    graph.add_node(
        "extract_cells",
        make_extract_cells_node(db=db, gateway=gateway, judge_model=judge_model),
    )
    graph.add_node("aggregate", make_aggregate_node(db))

    graph.add_edge("load_documents", "extract_cells")
    graph.add_edge("extract_cells", "aggregate")
    graph.add_edge("aggregate", END)
    graph.set_entry_point("load_documents")

    return graph.compile()


async def _mark_failed(
    db: AsyncSession,
    execution: TabularExecution,
    error_text: str,
) -> None:
    """Best-effort write of the failed terminal state."""

    from datetime import UTC, datetime

    execution.status = "failed"
    execution.error_text = error_text[:2000]
    execution.completed_at = datetime.now(UTC)
    try:
        await db.commit()
    except Exception as exc:  # pragma: no cover - DB best-effort
        logger.warning(
            "tabular executor: failed-state write failed: %s",
            exc,
            extra={"event": "tabular_executor_persist_failed_error"},
        )


__all__ = [
    "DEFAULT_JUDGE_MODEL",
    "TabularExecutorError",
    "run_tabular_execution",
]
