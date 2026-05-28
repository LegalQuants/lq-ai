"""Tests for M4 Task 3 — ``max_cost_usd`` on AutonomousWatch + AutonomousSchedule.

Covers:

* Pydantic ``AutonomousWatchCreate`` accepts ``max_cost_usd`` (Decimal) and
  defaults to ``None``.
* Pydantic ``AutonomousScheduleCreate`` accepts ``max_cost_usd`` (Decimal).
* ORM round-trip — set ``max_cost_usd`` on an ``AutonomousWatch``, flush +
  refresh, value comes back equal (mirrors the existing
  ``autonomous_sessions.max_cost_usd`` NUMERIC(10,4) column).

Migration ``0045_autonomous_per_trigger_max_cost.py`` adds the columns; the
conftest's per-run test DB auto-runs migrations to head before any test
opens a session, so the round-trip exercises the real column.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.autonomous import AutonomousWatch
from app.models.knowledge import KnowledgeBase
from app.models.user import User
from app.schemas.autonomous import (
    AutonomousScheduleCreate,
    AutonomousWatchCreate,
)
from app.security import hash_password


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"max-cost-test-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Max Cost Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
        autonomous_enabled=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.mark.unit
def test_watch_create_schema_accepts_max_cost_usd() -> None:
    body = AutonomousWatchCreate(
        knowledge_base_id=uuid.uuid4(),
        max_cost_usd=Decimal("0.50"),
    )
    assert body.max_cost_usd == Decimal("0.50")


@pytest.mark.unit
def test_watch_create_schema_default_max_cost_is_none() -> None:
    body = AutonomousWatchCreate(knowledge_base_id=uuid.uuid4())
    assert body.max_cost_usd is None


@pytest.mark.unit
def test_schedule_create_schema_accepts_max_cost_usd() -> None:
    body = AutonomousScheduleCreate(
        cron_expr="*/5 * * * *",
        max_cost_usd=Decimal("0.10"),
    )
    assert body.max_cost_usd == Decimal("0.10")


@pytest.mark.integration
async def test_watch_model_round_trips_max_cost_usd(
    db_session: AsyncSession,
    test_user: User,
) -> None:
    """A real KB is required — FK to knowledge_bases.id with ON DELETE CASCADE."""
    kb = KnowledgeBase(owner_id=test_user.id, name="max-cost-kb")
    db_session.add(kb)
    await db_session.flush()
    await db_session.refresh(kb)

    watch = AutonomousWatch(
        user_id=test_user.id,
        knowledge_base_id=kb.id,
        enabled=True,
        max_cost_usd=Decimal("0.25"),
    )
    db_session.add(watch)
    await db_session.flush()
    await db_session.refresh(watch)
    assert watch.max_cost_usd == Decimal("0.25")
