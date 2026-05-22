"""ARQ worker function for the Tabular Review execution pipeline — M3-C2.

The ``POST /api/v1/tabular/execute`` handler creates a
:class:`TabularExecution` row at ``status='pending'`` and enqueues this
job (via :func:`app.workers.queue.enqueue_tabular_execution_job`) onto
the shared playbook queue (``arq:m3a6`` — see Decision C-3 in the
Phase C prep doc; the queue stays shared with Easy Playbook generation
to avoid splitting one workload across two worker containers).

The worker picks up the job, resolves a :class:`GatewayClient`, opens
its own session via the standard factory, and dispatches to
:func:`app.tabular.executor.run_tabular_execution`. The executor
manages the lifecycle (running → completed | failed) internally; this
function's responsibility is the orchestration layer around it (the
BaseException cancellation-path bookkeeping that matches the
M3-A6 ``easy_playbook_generation_job`` pattern).

Per the M3-C2 quality bar, the assembled grid is itself a starting
point the user-attorney reviews. Worker "success" means the executor
produced a structurally-valid ``tabular_executions.results`` payload
— not that the extractions are correct, complete, or fit for use
without review.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import update

from app.db.session import get_session_factory
from app.models.tabular import TabularExecution
from app.tabular.executor import run_tabular_execution

if TYPE_CHECKING:
    from app.clients.gateway import GatewayClient

logger = logging.getLogger(__name__)


# Function name registered on the worker — must match the constant in
# :mod:`app.workers.queue` so the api-side enqueue helper targets the
# right function on the shared playbook queue.
TABULAR_EXECUTION_JOB_NAME = "tabular_execution_job"


async def tabular_execution_job(ctx: dict[str, Any], execution_id_str: str) -> dict[str, Any]:
    """ARQ job — run the Tabular Review pipeline for one execution row.

    Lifecycle (delegated to :func:`run_tabular_execution`):

    * On entry: ``pending → running``; sets ``started_at``.
    * On success: ``running → completed``; sets ``completed_at`` +
      writes ``results`` JSONB and ``cost_actual_usd`` via the
      aggregate node.
    * On in-graph exception: ``running → failed``; sets
      ``error_text`` + ``completed_at``.

    This wrapper additionally handles:

    * Missing row — graceful early return.
    * BaseException (ARQ ``job_timeout`` cancellation) — writes the
      failed terminal state then re-raises so arq's shutdown
      machinery still sees the cancel. Matches the
      :func:`app.workers.easy_playbook_worker.easy_playbook_generation_job`
      pattern.

    Returns a small dict for arq's result-tracking. All real state
    lives on the execution row.
    """

    execution_id = uuid.UUID(execution_id_str)
    logger.info(
        "tabular_worker: job start",
        extra={
            "event": "tabular_worker_start",
            "execution_id": execution_id_str,
        },
    )

    factory = get_session_factory()
    gateway = _gateway_from_ctx(ctx)

    async with factory() as session:
        execution = await session.get(TabularExecution, execution_id)
        if execution is None:
            logger.warning(
                "tabular_worker: row not found; nothing to do",
                extra={
                    "event": "tabular_worker_row_missing",
                    "execution_id": execution_id_str,
                },
            )
            return {"execution_id": execution_id_str, "status": "missing"}

        try:
            await run_tabular_execution(
                session,
                execution_id=execution_id,
                gateway=gateway,
            )
        except BaseException as exc:
            # The executor catches Exception subclasses internally but
            # not BaseException (CancelledError, SystemExit). On those
            # paths, write a failed terminal state ourselves so the
            # row doesn't get stuck at 'running' indefinitely.
            logger.exception(
                "tabular_worker: pipeline failed at orchestration layer",
                extra={
                    "event": "tabular_worker_orchestration_error",
                    "execution_id": execution_id_str,
                    "error_type": type(exc).__name__,
                },
            )
            await session.execute(
                update(TabularExecution)
                .where(TabularExecution.id == execution_id)
                .values(
                    status="failed",
                    error_text=f"{type(exc).__name__}: {exc}"[:2000],
                    completed_at=datetime.now(UTC),
                )
            )
            await session.commit()
            # Re-raise BaseException subclasses after bookkeeping so
            # arq's shutdown machinery still sees the cancel.
            if not isinstance(exc, Exception):
                raise
            return {
                "execution_id": execution_id_str,
                "status": "failed",
                "error": str(exc),
            }

        logger.info(
            "tabular_worker: job complete",
            extra={
                "event": "tabular_worker_complete",
                "execution_id": execution_id_str,
            },
        )
        return {"execution_id": execution_id_str, "status": "completed"}


def _gateway_from_ctx(ctx: dict[str, Any]) -> GatewayClient:
    """Resolve a :class:`GatewayClient` from the arq worker ``ctx``.

    Mirrors :func:`app.workers.easy_playbook_worker._gateway_from_ctx`
    — builds one on demand via the api's standard factory if the worker
    didn't pre-populate ``ctx['gateway']`` at startup. Future
    optimization: hoist into ``on_startup`` so every job reuses one
    client.
    """

    # Lazy import — keeps the worker module importable in environments
    # where the gateway client isn't yet configured.
    from app.clients.gateway import GatewayClient, get_gateway_client

    existing = ctx.get("gateway")
    if isinstance(existing, GatewayClient):
        return existing
    return get_gateway_client()
