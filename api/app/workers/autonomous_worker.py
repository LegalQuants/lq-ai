"""ARQ worker functions for the Autonomous Session pipeline — M4-A2 + M4-A4-ii.

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

M4-A4-ii adds :func:`autonomous_idle_watchdog`, a per-minute arq cron
that reaps sessions that have gone idle. The core transition logic lives
in :func:`_run_idle_sweep` so tests can drive it directly via the
conftest ``db_session`` fixture without opening a separate factory session.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select, update

from app.autonomous.audit import autonomous_audit
from app.autonomous.cron import next_run_after
from app.autonomous.executor import run_autonomous_session
from app.config import get_settings
from app.db.session import get_session_factory
from app.models.autonomous import AutonomousSchedule, AutonomousSession
from app.models.user import User
from app.workers.queue import enqueue_autonomous_session_job

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


async def _run_idle_sweep(
    db: Any,  # AsyncSession — typed as Any to avoid heavy import at call sites
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Core idle-halt transition logic — testable without arq context.

    Called both by :func:`autonomous_idle_watchdog` (with a factory-owned
    session) and directly by tests (with the conftest SAVEPOINT session).

    Two-tick semantics (order is intentional — paused→halted FIRST):

    1. **paused → halted**: sessions with ``status='running'``,
       ``halt_state='paused'``, and
       ``last_activity_at < now - (2 * idle_halt_minutes) minutes``.
       Sets ``halt_state='halted'``, ``status='halted'``,
       ``completed_at=now``, and writes a ``halted`` audit row with
       ``reason='idle_timeout'``.

    2. **running → paused**: sessions with ``status='running'``,
       ``halt_state='running'``, and
       ``last_activity_at < now - idle_halt_minutes minutes``.
       Sets ``halt_state='paused'``.

    Doing (1) before (2) guarantees a session freshly paused in step (2)
    is NOT also halted in step (1) within the same tick — it would need
    to survive a *later* sweep with the 2x threshold still exceeded.

    Per-session ``idle_halt_minutes`` is used for both thresholds via
    ``func.make_interval(0, 0, 0, 0, 0, idle_halt_minutes)`` (positional
    Postgres ``make_interval(years, months, weeks, days, hours, mins)``)
    so the Postgres planner can use the partial index
    ``idx_autonomous_sessions_active``.

    Returns a summary dict ``{"paused": n, "halted": n}`` for the arq
    result log.
    """

    effective_now: datetime = now if now is not None else datetime.now(UTC)

    halted_count = 0
    paused_count = 0

    # ------------------------------------------------------------------
    # Tick 1: paused → halted (must run BEFORE running → paused)
    # ------------------------------------------------------------------
    # Candidate: status='running', halt_state='paused',
    #             last_activity_at < now - (2 * idle_halt_minutes minutes)
    # make_interval positional: (years, months, weeks, days, hours, mins)
    # SQLAlchemy's func proxy passes kwargs directly to the SQL function which
    # Postgres supports as named args only in its own SQL syntax — use positional
    # form instead so the expression compiles correctly across all SA versions.
    paused_candidates_stmt = select(AutonomousSession).where(
        AutonomousSession.status == "running",
        AutonomousSession.halt_state == "paused",
        AutonomousSession.last_activity_at
        < effective_now
        - func.make_interval(0, 0, 0, 0, 0, AutonomousSession.idle_halt_minutes * 2),
    )
    paused_result = await db.execute(paused_candidates_stmt)
    paused_candidates = paused_result.scalars().all()

    for sess in paused_candidates:
        sess.halt_state = "halted"
        sess.status = "halted"
        sess.completed_at = effective_now
        db.add(sess)
        await autonomous_audit(db, sess, "halted", reason="idle_timeout")
        halted_count += 1

    # ------------------------------------------------------------------
    # Tick 2: running → paused
    # ------------------------------------------------------------------
    # Candidate: status='running', halt_state='running',
    #             last_activity_at < now - idle_halt_minutes minutes
    running_candidates_stmt = select(AutonomousSession).where(
        AutonomousSession.status == "running",
        AutonomousSession.halt_state == "running",
        AutonomousSession.last_activity_at
        < effective_now - func.make_interval(0, 0, 0, 0, 0, AutonomousSession.idle_halt_minutes),
    )
    running_result = await db.execute(running_candidates_stmt)
    running_candidates = running_result.scalars().all()

    for sess in running_candidates:
        sess.halt_state = "paused"
        db.add(sess)
        paused_count += 1

    await db.flush()

    logger.info(
        "autonomous_idle_watchdog: sweep complete",
        extra={
            "event": "autonomous_idle_watchdog_sweep",
            "paused": paused_count,
            "halted": halted_count,
        },
    )
    return {"paused": paused_count, "halted": halted_count}


async def autonomous_idle_watchdog(ctx: dict[str, Any]) -> dict[str, Any]:
    """ARQ cron job — reap idle autonomous sessions every minute.

    Registered on :attr:`~app.workers.arq_setup.WorkerSettings.cron_jobs`
    via ``cron(autonomous_idle_watchdog, second=0)`` (top of every minute).

    Opens its own DB session via :func:`~app.db.session.get_session_factory`
    (mirrors the pattern in :func:`autonomous_session_job`), delegates to
    :func:`_run_idle_sweep`, commits, and returns a summary dict for arq's
    result-tracking.

    The core logic lives in :func:`_run_idle_sweep` so unit tests can drive
    it directly inside the conftest SAVEPOINT without needing a factory.
    """

    logger.info(
        "autonomous_idle_watchdog: starting sweep",
        extra={"event": "autonomous_idle_watchdog_start"},
    )

    factory = get_session_factory()
    async with factory() as db:
        result = await _run_idle_sweep(db)
        await db.commit()

    logger.info(
        "autonomous_idle_watchdog: done",
        extra={
            "event": "autonomous_idle_watchdog_done",
            "paused": result["paused"],
            "halted": result["halted"],
        },
    )
    return result


async def _run_schedule_sweep(
    db: Any,  # AsyncSession — typed as Any to avoid heavy import at call sites
    *,
    now: datetime | None = None,
    enqueue: Callable[[uuid.UUID], Awaitable[bool]] | None = None,
) -> dict[str, int]:
    """Core schedule-dispatch logic — testable without arq context (M4-B3).

    Called both by :func:`autonomous_schedule_dispatcher` (with a
    factory-owned session) and directly by tests (with the conftest
    SAVEPOINT session, ``now`` and ``enqueue`` injected).

    For each schedule with ``enabled AND deleted_at IS NULL AND
    next_run_at <= effective_now`` (the scan the partial index
    ``idx_autonomous_schedules_due`` serves), it:

    1. Creates an :class:`~app.models.autonomous.AutonomousSession` with
       ``trigger_kind='schedule'``, ``trigger_ref`` = the schedule id,
       ``status='running'``, ``current_phase='intake'``, and ``params``
       carrying the non-null subset of the schedule's target
       (``kb_id`` ← ``target_kb_id``, ``playbook_id``, ``skill_ref``).
    2. Flushes to obtain the session id, then ``await enqueue(id)`` —
       best-effort; a failed enqueue leaves the row at ``running`` for
       manual re-enqueue (matching the queue-helper posture).
    3. Advances ``schedule.last_run_at = effective_now`` and
       ``schedule.next_run_at = next_run_after(cron_expr, effective_now)``.

    Returns ``{"spawned": n}`` for the arq result log. ``next_run_at IS
    NULL`` schedules are not picked up (the ``<=`` predicate excludes
    NULL) — a freshly-created schedule always has ``next_run_at`` set by
    the create endpoint, so this only excludes legacy rows.
    """

    effective_now: datetime = now if now is not None else datetime.now(UTC)
    enqueue_fn = enqueue if enqueue is not None else enqueue_autonomous_session_job
    settings = get_settings()

    due_stmt = (
        select(AutonomousSchedule)
        .join(User, User.id == AutonomousSchedule.user_id)
        .where(
            AutonomousSchedule.enabled.is_(True),
            AutonomousSchedule.deleted_at.is_(None),
            AutonomousSchedule.next_run_at.is_not(None),
            AutonomousSchedule.next_run_at <= effective_now,
            User.autonomous_enabled.is_(True),
        )
    )
    due = (await db.execute(due_stmt)).scalars().all()

    spawned = 0
    for schedule in due:
        # Defense-in-depth: isolate each schedule so one bad/pre-existing row
        # (e.g. an unsatisfiable cron whose next_run_after raises, or an
        # enqueue failure) cannot abort the whole tick. validate_cron_expr now
        # keeps poison out of the DB at create/patch time; this is the safety
        # net for any pre-existing row. On error we log and `continue` —
        # leaving the schedule enabled. An orphaned 'running' session (created
        # before the error) is reaped by the idle watchdog; what matters is
        # that the other due schedules still dispatch.
        try:
            # Capture the PRIOR last_run_at BEFORE we advance it below, so
            # params["since"] carries the timestamp of the previous tick
            # (NOT the timestamp we're about to set for THIS tick). Task 10's
            # intake_node reads this to scope retrieve_chunks to docs since
            # the last successful run; None means "first tick — no prior
            # baseline".
            previous_last_run_at = schedule.last_run_at

            # Build the trigger→target params carrying only the non-null keys
            # (Decision B3-a). target_kb_id maps to the executor's kb_id state.
            # ``since`` is always included (None on first tick) so consumers
            # can branch on its presence vs. absence cleanly.
            params: dict[str, Any] = {
                "since": previous_last_run_at.isoformat()
                if previous_last_run_at is not None
                else None,
            }
            if schedule.target_kb_id is not None:
                params["kb_id"] = str(schedule.target_kb_id)
            if schedule.playbook_id is not None:
                params["playbook_id"] = str(schedule.playbook_id)
            if schedule.skill_ref is not None:
                params["skill_ref"] = schedule.skill_ref

            session = AutonomousSession(
                user_id=schedule.user_id,
                project_id=schedule.project_id,
                trigger_kind="schedule",
                trigger_ref=schedule.id,
                status="running",
                current_phase="intake",
                # Per-trigger cap when set, else the config default; never
                # None so R4 (economic brake) can trip on every spawned
                # session.
                max_cost_usd=schedule.max_cost_usd
                if schedule.max_cost_usd is not None
                else settings.autonomous_default_max_cost_usd,
                params=params,
            )
            db.add(session)
            await db.flush()

            await enqueue_fn(session.id)

            schedule.last_run_at = effective_now
            schedule.next_run_at = next_run_after(schedule.cron_expr, effective_now)
            db.add(schedule)
            spawned += 1
        except Exception as exc:
            logger.warning(
                "autonomous_schedule_dispatcher: schedule dispatch failed; skipping",
                extra={
                    "event": "autonomous_schedule_dispatch_error",
                    "schedule_id": str(schedule.id),
                    "error_type": type(exc).__name__,
                },
            )
            continue

    await db.flush()

    logger.info(
        "autonomous_schedule_dispatcher: sweep complete",
        extra={
            "event": "autonomous_schedule_dispatcher_sweep",
            "spawned": spawned,
        },
    )
    return {"spawned": spawned}


async def autonomous_schedule_dispatcher(ctx: dict[str, Any]) -> dict[str, Any]:
    """ARQ cron job — spawn sessions for due schedules every minute (M4-B3).

    Registered on :attr:`~app.workers.arq_setup.WorkerSettings.cron_jobs`
    via ``cron(autonomous_schedule_dispatcher, second=0)`` (top of every
    minute).

    Opens its own DB session via :func:`~app.db.session.get_session_factory`
    (mirrors :func:`autonomous_idle_watchdog`), delegates to
    :func:`_run_schedule_sweep`, commits, and returns a summary dict for
    arq's result-tracking. The core logic lives in
    :func:`_run_schedule_sweep` so unit tests can drive it directly inside
    the conftest SAVEPOINT without needing a factory.
    """

    logger.info(
        "autonomous_schedule_dispatcher: starting sweep",
        extra={"event": "autonomous_schedule_dispatcher_start"},
    )

    factory = get_session_factory()
    async with factory() as db:
        result = await _run_schedule_sweep(db)
        await db.commit()

    logger.info(
        "autonomous_schedule_dispatcher: done",
        extra={
            "event": "autonomous_schedule_dispatcher_done",
            "spawned": result["spawned"],
        },
    )
    return result


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
