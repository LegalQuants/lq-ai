"""TDD tests for the idle-halt watchdog cron — M4-A4-ii.

RED phase: tests written against the not-yet-implemented
``_run_idle_sweep`` helper and ``autonomous_idle_watchdog`` cron.

Two-tick idle semantics under test:
- Tick 1 (running → paused):  sessions that have been idle past
  ``idle_halt_minutes`` get ``halt_state='paused'``; ``status`` stays
  ``running``.
- Tick 2 (paused → halted): sessions that have been idle past
  ``2 * idle_halt_minutes`` (a full second interval after reaching
  paused) get ``halt_state='halted'``, ``status='halted'``,
  ``completed_at`` set, and a ``halted`` audit row with
  ``reason='idle_timeout'``.
- A session paused in the SAME tick is NOT immediately halted
  (two-tick ordering guarantee).
- Recently-active sessions are untouched.
- Non-running sessions (completed, halted, failed) are never touched.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.user import User
from app.security import hash_password

# ---------------------------------------------------------------------------
# Helpers — mirror test_brakes.py
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession) -> User:
    user = User(
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_session(
    db: AsyncSession,
    *,
    user: User,
    status: str = "running",
    halt_state: str = "running",
    idle_halt_minutes: int = 5,
    last_activity_at: datetime | None = None,
) -> AutonomousSession:
    """Create an AutonomousSession row for testing.

    ``last_activity_at`` defaults to now() (server default) unless
    explicitly supplied; callers backdate it to simulate idle sessions.
    """
    sess = AutonomousSession(
        user_id=user.id,
        trigger_kind="manual",
        current_phase="intake",
        halt_state=halt_state,
        status=status,
        idle_halt_minutes=idle_halt_minutes,
    )
    if last_activity_at is not None:
        sess.last_activity_at = last_activity_at
    db.add(sess)
    await db.flush()
    await db.refresh(sess)
    return sess


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_idle_running_session_becomes_paused(db_session: AsyncSession) -> None:
    """A running session idle past idle_halt_minutes → paused after one sweep.

    status remains 'running'; halt_state becomes 'paused'; no halted
    audit row is written (that's a second-tick event).
    """
    from app.workers.autonomous_worker import _run_idle_sweep

    user = await _make_user(db_session)
    now = datetime.now(UTC)
    # Backdate past 1x idle_halt_minutes (5 min)
    stale_activity = now - timedelta(minutes=6)
    sess = await _make_session(
        db_session,
        user=user,
        status="running",
        halt_state="running",
        idle_halt_minutes=5,
        last_activity_at=stale_activity,
    )

    result = await _run_idle_sweep(db_session, now=now)

    await db_session.refresh(sess)
    assert sess.halt_state == "paused", "expected paused after one sweep"
    assert sess.status == "running", "status must still be running after first tick"

    # No halted audit row — that only happens on the second tick.
    halted_rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_session.halted")
                .where(AuditLog.resource_id == str(sess.id))
            )
        )
        .scalars()
        .all()
    )
    assert halted_rows == [], "no halted audit row on first tick"

    assert result["paused"] >= 1


@pytest.mark.integration
async def test_paused_session_past_double_interval_becomes_halted(
    db_session: AsyncSession,
) -> None:
    """A paused session idle past 2xidle_halt_minutes → halted after one sweep.

    Verifies: halt_state='halted', status='halted', completed_at set,
    and a 'halted' audit row with reason='idle_timeout'.
    """
    from app.workers.autonomous_worker import _run_idle_sweep

    user = await _make_user(db_session)
    now = datetime.now(UTC)
    # Backdate past 2x idle_halt_minutes (10 min)
    stale_activity = now - timedelta(minutes=11)
    sess = await _make_session(
        db_session,
        user=user,
        status="running",
        halt_state="paused",
        idle_halt_minutes=5,
        last_activity_at=stale_activity,
    )

    result = await _run_idle_sweep(db_session, now=now)

    await db_session.refresh(sess)
    assert sess.halt_state == "halted", "expected halted after second tick"
    assert sess.status == "halted", "status must be halted"
    assert sess.completed_at is not None, "completed_at must be set"

    # halted audit row with reason='idle_timeout'
    halted_rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_session.halted")
                .where(AuditLog.resource_id == str(sess.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(halted_rows) == 1, "exactly one halted audit row"
    assert halted_rows[0].details is not None
    assert halted_rows[0].details["reason"] == "idle_timeout"

    assert result["halted"] >= 1


@pytest.mark.integration
async def test_freshly_paused_is_not_halted_in_same_tick(db_session: AsyncSession) -> None:
    """A session paused in the running→paused scan is NOT halted in the same sweep.

    last_activity_at is backdated past 1x interval but NOT 2x — it would
    be caught by the running→paused scan but must not be caught by the
    paused→halted scan (which requires 2x interval to elapse).
    """
    from app.workers.autonomous_worker import _run_idle_sweep

    user = await _make_user(db_session)
    now = datetime.now(UTC)
    # Idle for 7 minutes with idle_halt_minutes=5: crosses 1x (5) but not 2x (10)
    stale_activity = now - timedelta(minutes=7)
    sess = await _make_session(
        db_session,
        user=user,
        status="running",
        halt_state="running",
        idle_halt_minutes=5,
        last_activity_at=stale_activity,
    )

    await _run_idle_sweep(db_session, now=now)

    await db_session.refresh(sess)
    # Should be paused (crossed 1x interval) but NOT halted (not 2x interval)
    assert sess.halt_state == "paused", "should be paused after first tick"
    assert sess.status == "running", "status still running — not halted in same tick"


@pytest.mark.integration
async def test_recently_active_session_is_untouched(db_session: AsyncSession) -> None:
    """A running session with recent activity (now) is not paused or halted."""
    from app.workers.autonomous_worker import _run_idle_sweep

    user = await _make_user(db_session)
    now = datetime.now(UTC)
    # Very recent: within the idle window
    sess = await _make_session(
        db_session,
        user=user,
        status="running",
        halt_state="running",
        idle_halt_minutes=5,
        last_activity_at=now - timedelta(seconds=30),
    )

    await _run_idle_sweep(db_session, now=now)

    await db_session.refresh(sess)
    assert sess.halt_state == "running", "recently-active session must not be paused"
    assert sess.status == "running"


@pytest.mark.integration
async def test_completed_session_is_not_touched(db_session: AsyncSession) -> None:
    """Sessions with status='completed' are filtered out regardless of last_activity_at."""
    from app.workers.autonomous_worker import _run_idle_sweep

    user = await _make_user(db_session)
    now = datetime.now(UTC)
    sess = await _make_session(
        db_session,
        user=user,
        status="completed",
        halt_state="running",
        idle_halt_minutes=5,
        last_activity_at=now - timedelta(days=1),
    )

    await _run_idle_sweep(db_session, now=now)

    await db_session.refresh(sess)
    assert sess.status == "completed"
    assert sess.halt_state == "running"


@pytest.mark.integration
async def test_already_halted_session_is_not_touched(db_session: AsyncSession) -> None:
    """Sessions with status='halted' are filtered out."""
    from app.workers.autonomous_worker import _run_idle_sweep

    user = await _make_user(db_session)
    now = datetime.now(UTC)
    sess = await _make_session(
        db_session,
        user=user,
        status="halted",
        halt_state="halted",
        idle_halt_minutes=5,
        last_activity_at=now - timedelta(days=1),
    )

    await _run_idle_sweep(db_session, now=now)

    await db_session.refresh(sess)
    assert sess.status == "halted"
    assert sess.halt_state == "halted"


@pytest.mark.integration
async def test_failed_session_is_not_touched(db_session: AsyncSession) -> None:
    """Sessions with status='failed' are filtered out."""
    from app.workers.autonomous_worker import _run_idle_sweep

    user = await _make_user(db_session)
    now = datetime.now(UTC)
    sess = await _make_session(
        db_session,
        user=user,
        status="failed",
        halt_state="running",
        idle_halt_minutes=5,
        last_activity_at=now - timedelta(days=1),
    )

    await _run_idle_sweep(db_session, now=now)

    await db_session.refresh(sess)
    assert sess.status == "failed"
    assert sess.halt_state == "running"


@pytest.mark.integration
async def test_single_sweep_does_not_take_running_to_halted(db_session: AsyncSession) -> None:
    """One sweep cannot transition a running session all the way to halted.

    Even if last_activity_at is backdated past 2x idle_halt_minutes, a
    running session must go through paused first. The paused→halted scan
    only targets sessions already in halt_state='paused'. So after one
    sweep the session is paused, not halted.
    """
    from app.workers.autonomous_worker import _run_idle_sweep

    user = await _make_user(db_session)
    now = datetime.now(UTC)
    # Backdate past 2x interval — but halt_state starts at 'running'
    stale_activity = now - timedelta(minutes=20)
    sess = await _make_session(
        db_session,
        user=user,
        status="running",
        halt_state="running",
        idle_halt_minutes=5,
        last_activity_at=stale_activity,
    )

    await _run_idle_sweep(db_session, now=now)

    await db_session.refresh(sess)
    # Must only be paused after one sweep — not halted in the same tick
    assert sess.halt_state == "paused", "must only advance one tick per sweep"
    assert sess.status == "running", "status still running after first tick"


@pytest.mark.integration
async def test_two_sweeps_takes_running_to_halted(db_session: AsyncSession) -> None:
    """Two sweeps complete the running → paused → halted lifecycle.

    First sweep: running → paused (last_activity_at past 1x).
    Second sweep (with updated now): paused → halted (past 2x).
    """
    from app.workers.autonomous_worker import _run_idle_sweep

    user = await _make_user(db_session)
    now = datetime.now(UTC)
    # Backdate past 2x interval
    stale_activity = now - timedelta(minutes=12)
    sess = await _make_session(
        db_session,
        user=user,
        status="running",
        halt_state="running",
        idle_halt_minutes=5,
        last_activity_at=stale_activity,
    )

    # Tick 1: running → paused
    result1 = await _run_idle_sweep(db_session, now=now)
    await db_session.refresh(sess)
    assert sess.halt_state == "paused"
    assert sess.status == "running"
    assert result1["paused"] >= 1
    assert result1["halted"] == 0

    # Tick 2: paused → halted (same stale last_activity_at, now advanced slightly)
    result2 = await _run_idle_sweep(db_session, now=now + timedelta(minutes=1))
    await db_session.refresh(sess)
    assert sess.halt_state == "halted"
    assert sess.status == "halted"
    assert sess.completed_at is not None
    assert result2["halted"] >= 1
    assert result2["paused"] == 0  # Nothing new to pause

    # Audit trail: exactly one halted row
    halted_audit = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_session.halted")
                .where(AuditLog.resource_id == str(sess.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(halted_audit) == 1
    assert halted_audit[0].details["reason"] == "idle_timeout"


@pytest.mark.integration
async def test_per_session_idle_halt_minutes_respected(db_session: AsyncSession) -> None:
    """Each session's own idle_halt_minutes is used, not a global constant.

    Session A has idle_halt_minutes=2 — idle for 3 min → should be paused.
    Session B has idle_halt_minutes=10 — idle for 3 min → should be untouched.
    """
    from app.workers.autonomous_worker import _run_idle_sweep

    user = await _make_user(db_session)
    now = datetime.now(UTC)
    stale_3min = now - timedelta(minutes=3)

    sess_short = await _make_session(
        db_session,
        user=user,
        status="running",
        halt_state="running",
        idle_halt_minutes=2,
        last_activity_at=stale_3min,
    )
    sess_long = await _make_session(
        db_session,
        user=user,
        status="running",
        halt_state="running",
        idle_halt_minutes=10,
        last_activity_at=stale_3min,
    )

    await _run_idle_sweep(db_session, now=now)

    await db_session.refresh(sess_short)
    await db_session.refresh(sess_long)

    assert sess_short.halt_state == "paused", "short-threshold session should be paused"
    assert sess_long.halt_state == "running", "long-threshold session should be untouched"


@pytest.mark.unit
def test_cron_registered_in_worker_settings() -> None:
    """autonomous_idle_watchdog appears in WorkerSettings.cron_jobs."""
    from arq.cron import CronJob

    from app.workers.arq_setup import WorkerSettings

    assert hasattr(WorkerSettings, "cron_jobs"), "WorkerSettings must have cron_jobs"
    cron_jobs: list[CronJob] = WorkerSettings.cron_jobs  # type: ignore[attr-defined]
    cron_names = [cj.coroutine.__name__ for cj in cron_jobs]
    assert "autonomous_idle_watchdog" in cron_names, (
        f"autonomous_idle_watchdog not in cron_jobs; found: {cron_names}"
    )
    # Verify it targets second=0 (every-minute schedule).
    # arq stores the scalar value as-is (int 0) when a single value is passed;
    # the cron runner normalises it to a set internally. Check for 0 (int) here.
    watchdog_cron = next(
        cj for cj in cron_jobs if cj.coroutine.__name__ == "autonomous_idle_watchdog"
    )
    assert watchdog_cron.second in (0, {0}), (
        f"expected second=0 (every-minute schedule), got {watchdog_cron.second!r}"
    )
