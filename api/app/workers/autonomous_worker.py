"""ARQ worker function for the Autonomous Session execution pipeline — M4-A2.

The autonomous session API endpoint (future M4 task) will create an
:class:`~app.models.autonomous.AutonomousSession` row and enqueue this
job onto the shared playbook queue (``arq:m3a6`` — the autonomous
executor shares the durable worker at lower priority than interactive
use, per PRD §3.10 NFR; no separate queue until contention warrants it).

The worker picks up the job, resolves a :class:`GatewayClient`, opens
its own session via the standard factory, and dispatches to
:func:`~app.autonomous.executor.run_autonomous_session`. The executor
manages the lifecycle (running → completed | failed) internally; this
function's responsibility is the orchestration layer around it (the
BaseException cancellation-path bookkeeping that matches the
:func:`~app.workers.tabular_worker.tabular_execution_job` pattern).

Note: the shared :attr:`~app.workers.arq_setup.WorkerSettings.job_timeout`
is currently 900s. Autonomous sessions may run significantly longer than
playbook executions (multi-phase, multi-tool). A per-job timeout
mechanism is not a standard arq 0.25 feature; if autonomous sessions
routinely exceed 900s in production, the right fix is raising the shared
timeout or splitting autonomous work onto its own worker container.
This is a known concern deferred to post-M4-A2.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import update

from app.autonomous.executor import run_autonomous_session
from app.db.session import get_session_factory
from app.models.autonomous import AutonomousSession

if TYPE_CHECKING:
    from app.clients.gateway import GatewayClient

logger = logging.getLogger(__name__)


# Function name registered on the worker — must match the constant used
# by the API-side enqueue helper (future M4 task) so jobs land on the
# right function in the shared playbook queue.
AUTONOMOUS_SESSION_JOB_NAME = "autonomous_session_job"


async def autonomous_session_job(ctx: dict[str, Any], session_id: str) -> dict[str, Any]:
    """ARQ job — run the Autonomous Session pipeline for one session row.

    Lifecycle (delegated to :func:`~app.autonomous.executor.run_autonomous_session`):

    * On entry: session row is expected to be at ``status='running'``.
    * On success: executor sets ``status='completed'`` via the delivery node.
    * On in-graph exception: executor sets ``status='failed'`` + ``error``.

    This wrapper additionally handles:

    * Missing row — graceful early return.
    * BaseException (ARQ ``job_timeout`` cancellation) — writes the
      failed terminal state then re-raises so arq's shutdown machinery
      still sees the cancel. Matches the
      :func:`~app.workers.tabular_worker.tabular_execution_job` pattern.

    Returns a small dict for arq's result-tracking. All real state lives
    on the session row.
    """

    session_uuid = uuid.UUID(session_id)
    logger.info(
        "autonomous_worker: job start",
        extra={
            "event": "autonomous_worker_start",
            "session_id": session_id,
        },
    )

    factory = get_session_factory()
    gateway = _gateway_from_ctx(ctx)

    async with factory() as db:
        session = await db.get(AutonomousSession, session_uuid)
        if session is None:
            logger.warning(
                "autonomous_worker: row not found; nothing to do",
                extra={
                    "event": "autonomous_worker_row_missing",
                    "session_id": session_id,
                },
            )
            return {"session_id": session_id, "status": "missing"}

        try:
            await run_autonomous_session(
                db,
                session_id=session_uuid,
                gateway=gateway,
            )
        except BaseException as exc:
            # The executor catches Exception subclasses internally but
            # not BaseException (CancelledError, SystemExit). On those
            # paths, write a failed terminal state ourselves so the row
            # doesn't get stuck at 'running' indefinitely.
            logger.exception(
                "autonomous_worker: pipeline failed at orchestration layer",
                extra={
                    "event": "autonomous_worker_orchestration_error",
                    "session_id": session_id,
                    "error_type": type(exc).__name__,
                },
            )
            await db.execute(
                update(AutonomousSession)
                .where(AutonomousSession.id == session_uuid)
                .values(
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}"[:2000],
                    completed_at=datetime.now(UTC),
                )
            )
            await db.commit()
            # Re-raise BaseException subclasses after bookkeeping so
            # arq's shutdown machinery still sees the cancel.
            if not isinstance(exc, Exception):
                raise
            return {
                "session_id": session_id,
                "status": "failed",
                "error": str(exc),
            }

    logger.info(
        "autonomous_worker: job complete",
        extra={
            "event": "autonomous_worker_complete",
            "session_id": session_id,
        },
    )
    return {"session_id": session_id, "status": "completed"}


def _gateway_from_ctx(ctx: dict[str, Any]) -> GatewayClient:
    """Resolve a :class:`~app.clients.gateway.GatewayClient` from the arq worker ``ctx``.

    Mirrors :func:`~app.workers.tabular_worker._gateway_from_ctx` — builds
    one on demand via the api's standard factory if the worker didn't
    pre-populate ``ctx['gateway']`` at startup.
    """

    from app.clients.gateway import GatewayClient, get_gateway_client

    existing = ctx.get("gateway")
    if isinstance(existing, GatewayClient):
        return existing
    return get_gateway_client()
