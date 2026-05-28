"""Tests for M4 Task 5 — spawn paths always set ``session.max_cost_usd``.

Both the KB-arrival watch trigger (:func:`app.autonomous.watch_trigger.fire_watches_for_kb`)
and the schedule sweep (:func:`app.workers.autonomous_worker._run_schedule_sweep`)
MUST thread a non-NULL ``max_cost_usd`` onto every spawned
:class:`~app.models.autonomous.AutonomousSession`:

* Per-trigger when the watch/schedule has ``max_cost_usd`` set.
* Falls back to ``settings.autonomous_default_max_cost_usd`` (default $5.00)
  when the trigger's ``max_cost_usd`` is NULL.

This closes the gap where spawned sessions had ``max_cost_usd=None`` —
making R4 (the economic brake) toothless in production.

The schedule sweep additionally threads the schedule's PRIOR
``last_run_at`` value into ``params["since"]`` so Task 10's intake_node
can scope retrieve_chunks to docs since the last successful tick.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.autonomous import (
    AutonomousSchedule,
    AutonomousSession,
    AutonomousWatch,
)
from app.models.knowledge import KnowledgeBase
from app.models.user import User
from app.security import hash_password

# ---------------------------------------------------------------------------
# Inline fixtures — mirror the test_watches.py / test_schedules.py pattern
# (the conftest does NOT define opted_in_user / test_kb / test_file).
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession, *, suffix: str = "") -> User:
    user = User(
        email=f"spawn-cap-test-{suffix or uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Spawn Cap Test User {suffix}".strip(),
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
        autonomous_enabled=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_kb(db: AsyncSession, *, owner: User, name: str = "watched") -> KnowledgeBase:
    kb = KnowledgeBase(owner_id=owner.id, name=name)
    db.add(kb)
    await db.flush()
    await db.refresh(kb)
    return kb


# ===========================================================================
# Watch spawn path — fire_watches_for_kb
# ===========================================================================


@pytest.mark.integration
async def test_watch_spawn_threads_per_trigger_max_cost(
    db_session: AsyncSession,
) -> None:
    """A watch with max_cost_usd set spawns a session with that cap."""
    from app.autonomous.watch_trigger import fire_watches_for_kb

    user = await _make_user(db_session, suffix="watch-cap")
    kb = await _make_kb(db_session, owner=user)
    watch = AutonomousWatch(
        user_id=user.id,
        knowledge_base_id=kb.id,
        enabled=True,
        max_cost_usd=Decimal("0.10"),
    )
    db_session.add(watch)
    await db_session.flush()

    enqueue = AsyncMock(return_value=True)
    count = await fire_watches_for_kb(
        db_session, kb_id=kb.id, file_id=uuid.uuid4(), enqueue=enqueue
    )
    assert count == 1

    sessions = (
        (
            await db_session.execute(
                select(AutonomousSession).where(AutonomousSession.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(sessions) == 1
    assert sessions[0].max_cost_usd == Decimal("0.10")


@pytest.mark.integration
async def test_watch_spawn_falls_back_to_default_when_unset(
    db_session: AsyncSession,
) -> None:
    """A watch with max_cost_usd=NULL spawns a session with the config default; never None."""
    from app.autonomous.watch_trigger import fire_watches_for_kb

    user = await _make_user(db_session, suffix="watch-default")
    kb = await _make_kb(db_session, owner=user)
    watch = AutonomousWatch(
        user_id=user.id,
        knowledge_base_id=kb.id,
        enabled=True,
        max_cost_usd=None,
    )
    db_session.add(watch)
    await db_session.flush()

    enqueue = AsyncMock(return_value=True)
    await fire_watches_for_kb(db_session, kb_id=kb.id, file_id=uuid.uuid4(), enqueue=enqueue)
    session = (
        await db_session.execute(
            select(AutonomousSession).where(AutonomousSession.user_id == user.id)
        )
    ).scalar_one()
    # Default from settings; matches Task 2's default of $5.00.
    assert session.max_cost_usd == Decimal("5.00")
    assert session.max_cost_usd is not None


# ===========================================================================
# Schedule spawn path — _run_schedule_sweep
# ===========================================================================


@pytest.mark.integration
async def test_schedule_spawn_threads_per_trigger_max_cost(
    db_session: AsyncSession,
) -> None:
    """A schedule with max_cost_usd set spawns a session with that cap."""
    from app.workers.autonomous_worker import _run_schedule_sweep

    user = await _make_user(db_session, suffix="sched-cap")
    now = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    schedule = AutonomousSchedule(
        user_id=user.id,
        cron_expr="*/5 * * * *",
        enabled=True,
        next_run_at=now - timedelta(minutes=1),
        max_cost_usd=Decimal("0.25"),
    )
    db_session.add(schedule)
    await db_session.flush()

    enqueue = AsyncMock(return_value=True)
    result = await _run_schedule_sweep(db_session, now=now, enqueue=enqueue)
    assert result == {"spawned": 1}

    session = (
        await db_session.execute(
            select(AutonomousSession).where(AutonomousSession.user_id == user.id)
        )
    ).scalar_one()
    assert session.max_cost_usd == Decimal("0.25")


@pytest.mark.integration
async def test_schedule_spawn_falls_back_to_default_when_unset(
    db_session: AsyncSession,
) -> None:
    """A schedule with max_cost_usd=NULL spawns a session with the config default; never None."""
    from app.workers.autonomous_worker import _run_schedule_sweep

    user = await _make_user(db_session, suffix="sched-default")
    now = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    schedule = AutonomousSchedule(
        user_id=user.id,
        cron_expr="*/5 * * * *",
        enabled=True,
        next_run_at=now - timedelta(minutes=1),
        max_cost_usd=None,
    )
    db_session.add(schedule)
    await db_session.flush()

    enqueue = AsyncMock(return_value=True)
    await _run_schedule_sweep(db_session, now=now, enqueue=enqueue)
    session = (
        await db_session.execute(
            select(AutonomousSession).where(AutonomousSession.user_id == user.id)
        )
    ).scalar_one()
    assert session.max_cost_usd == Decimal("5.00")
    assert session.max_cost_usd is not None


# ===========================================================================
# Schedule spawn path — params["since"] carries PRIOR last_run_at
# ===========================================================================


@pytest.mark.integration
async def test_schedule_spawn_threads_prior_last_run_at_into_since(
    db_session: AsyncSession,
) -> None:
    """The session's params['since'] must carry the schedule's PRIOR last_run_at —
    NOT the timestamp we're about to set for THIS tick. This is what
    Task 10's intake_node uses to scope retrieve_chunks to docs since the
    last successful run.
    """
    from app.workers.autonomous_worker import _run_schedule_sweep

    user = await _make_user(db_session, suffix="sched-since")
    now = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    prior_last_run = datetime(2026, 5, 25, 9, 0, 0, tzinfo=UTC)
    schedule = AutonomousSchedule(
        user_id=user.id,
        cron_expr="*/5 * * * *",
        enabled=True,
        next_run_at=now - timedelta(minutes=1),
        last_run_at=prior_last_run,
    )
    db_session.add(schedule)
    await db_session.flush()

    enqueue = AsyncMock(return_value=True)
    await _run_schedule_sweep(db_session, now=now, enqueue=enqueue)
    session = (
        await db_session.execute(
            select(AutonomousSession).where(AutonomousSession.user_id == user.id)
        )
    ).scalar_one()
    # params['since'] is the PRIOR last_run_at, NOT `now`.
    assert session.params["since"] == prior_last_run.isoformat()

    # And the schedule's last_run_at HAS been advanced to now.
    await db_session.refresh(schedule)
    assert schedule.last_run_at == now


@pytest.mark.integration
async def test_schedule_spawn_since_is_none_on_first_tick(
    db_session: AsyncSession,
) -> None:
    """A schedule that has never run before (last_run_at is NULL) spawns
    a session with params['since']=None — Task 10 treats None as 'no
    prior baseline; intake_node retrieves over the entire KB'.
    """
    from app.workers.autonomous_worker import _run_schedule_sweep

    user = await _make_user(db_session, suffix="sched-first-tick")
    now = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    schedule = AutonomousSchedule(
        user_id=user.id,
        cron_expr="*/5 * * * *",
        enabled=True,
        next_run_at=now - timedelta(minutes=1),
        last_run_at=None,
    )
    db_session.add(schedule)
    await db_session.flush()

    enqueue = AsyncMock(return_value=True)
    await _run_schedule_sweep(db_session, now=now, enqueue=enqueue)
    session = (
        await db_session.execute(
            select(AutonomousSession).where(AutonomousSession.user_id == user.id)
        )
    ).scalar_one()
    assert "since" in session.params
    assert session.params["since"] is None
