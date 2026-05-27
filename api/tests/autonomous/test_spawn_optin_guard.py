"""Watches/schedules owned by opted-out users do not spawn sessions (M4-C2).

Covers the two background spawn paths:
- ``fire_watches_for_kb``: KB-arrival watch trigger.
- ``_run_schedule_sweep``: arq cron schedule dispatcher.

For each path: opted-out owner → 0 sessions; opted-in owner → 1 session.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.autonomous import AutonomousSchedule, AutonomousWatch
from app.models.knowledge import KnowledgeBase
from app.models.user import User
from app.security import hash_password

# ---------------------------------------------------------------------------
# Helpers — mirrors test_watches.py / test_schedules.py
# ---------------------------------------------------------------------------


async def _make_user(
    db: AsyncSession,
    *,
    suffix: str = "",
    autonomous_enabled: bool,
) -> User:
    user = User(
        email=f"optin-guard-{suffix or uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Opt-in Guard Test User {suffix}".strip(),
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
        autonomous_enabled=autonomous_enabled,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_kb(db: AsyncSession, *, owner: User, name: str = "guarded") -> KnowledgeBase:
    kb = KnowledgeBase(owner_id=owner.id, name=name)
    db.add(kb)
    await db.flush()
    await db.refresh(kb)
    return kb


async def _make_watch(
    db: AsyncSession,
    *,
    user: User,
    kb: KnowledgeBase,
) -> AutonomousWatch:
    watch = AutonomousWatch(
        user_id=user.id,
        knowledge_base_id=kb.id,
        enabled=True,
        deleted_at=None,
    )
    db.add(watch)
    await db.flush()
    await db.refresh(watch)
    return watch


async def _make_due_schedule(
    db: AsyncSession,
    *,
    user: User,
    now: datetime,
) -> AutonomousSchedule:
    sched = AutonomousSchedule(
        user_id=user.id,
        cron_expr="*/5 * * * *",
        enabled=True,
        next_run_at=now - timedelta(minutes=1),
        deleted_at=None,
    )
    db.add(sched)
    await db.flush()
    await db.refresh(sched)
    return sched


# ===========================================================================
# Watch spawn — opted-out owner
# ===========================================================================


@pytest.mark.integration
async def test_watch_skips_opted_out_owner(db_session: AsyncSession) -> None:
    """An enabled watch whose owner has autonomous_enabled=False must not spawn."""
    from app.autonomous.watch_trigger import fire_watches_for_kb

    owner = await _make_user(db_session, suffix="out", autonomous_enabled=False)
    kb = await _make_kb(db_session, owner=owner)
    await _make_watch(db_session, user=owner, kb=kb)

    enqueue = AsyncMock(return_value=True)
    count = await fire_watches_for_kb(
        db_session,
        kb_id=kb.id,
        file_id=uuid.uuid4(),
        enqueue=enqueue,
    )

    assert count == 0
    enqueue.assert_not_awaited()


# ===========================================================================
# Watch spawn — opted-in owner
# ===========================================================================


@pytest.mark.integration
async def test_watch_fires_for_opted_in_owner(db_session: AsyncSession) -> None:
    """An enabled watch whose owner has autonomous_enabled=True spawns one session."""
    from app.autonomous.watch_trigger import fire_watches_for_kb

    owner = await _make_user(db_session, suffix="in", autonomous_enabled=True)
    kb = await _make_kb(db_session, owner=owner)
    await _make_watch(db_session, user=owner, kb=kb)

    enqueue = AsyncMock(return_value=True)
    count = await fire_watches_for_kb(
        db_session,
        kb_id=kb.id,
        file_id=uuid.uuid4(),
        enqueue=enqueue,
    )

    assert count == 1
    enqueue.assert_awaited_once()


# ===========================================================================
# Schedule sweep — opted-out owner
# ===========================================================================


@pytest.mark.integration
async def test_schedule_sweep_skips_opted_out_owner(db_session: AsyncSession) -> None:
    """A due schedule whose owner has autonomous_enabled=False must not spawn."""
    from app.workers.autonomous_worker import _run_schedule_sweep

    now = datetime(2026, 5, 26, 10, 0, 0, tzinfo=UTC)
    owner = await _make_user(db_session, suffix="out-sched", autonomous_enabled=False)
    await _make_due_schedule(db_session, user=owner, now=now)

    enqueue = AsyncMock(return_value=True)
    result = await _run_schedule_sweep(db_session, now=now, enqueue=enqueue)

    assert result == {"spawned": 0}
    enqueue.assert_not_awaited()


# ===========================================================================
# Schedule sweep — opted-in owner
# ===========================================================================


@pytest.mark.integration
async def test_schedule_sweep_fires_for_opted_in_owner(db_session: AsyncSession) -> None:
    """A due schedule whose owner has autonomous_enabled=True spawns one session."""
    from app.workers.autonomous_worker import _run_schedule_sweep

    now = datetime(2026, 5, 26, 10, 0, 0, tzinfo=UTC)
    owner = await _make_user(db_session, suffix="in-sched", autonomous_enabled=True)
    await _make_due_schedule(db_session, user=owner, now=now)

    enqueue = AsyncMock(return_value=True)
    result = await _run_schedule_sweep(db_session, now=now, enqueue=enqueue)

    assert result == {"spawned": 1}
    enqueue.assert_awaited_once()
