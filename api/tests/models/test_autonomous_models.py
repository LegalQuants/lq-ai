"""Model + migration tests for the Autonomous-layer substrate — M4-A1.

Covers the five tables created by migration ``0039_autonomous_layer.py``
([PRD §3.10](docs/PRD.md#310-autonomous-layer-m4), ADR-0013):

* :class:`AutonomousSession` — the brake-bearing run record.
* :class:`AutonomousSchedule` — cron-triggered run definitions.
* :class:`AutonomousWatch` — KB-change-triggered run definitions.
* :class:`AutonomousMemory` — proposed/kept/dismissed memory notes.
* :class:`PrecedentEntry` — observed precedent patterns.

The acceptance contract for this task:

* CRUD round-trip on each of the five tables.
* Hard per-user isolation: every table carries a non-null ``user_id``
  FK (insert without ``user_id`` fails) and two users' rows don't
  cross-read.
* CHECK constraints pin the enums at the storage layer.
* The brake defaults on ``autonomous_sessions`` materialize.
* The spec's named indexes exist on disk after migration.

Tests run against the SAVEPOINT-rolled-back per-test session from
``tests/conftest.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.autonomous import (
    AutonomousMemory,
    AutonomousSchedule,
    AutonomousSession,
    AutonomousWatch,
    PrecedentEntry,
)
from app.models.knowledge import KnowledgeBase
from app.models.user import User
from app.security import hash_password


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


async def _make_kb(db: AsyncSession, *, owner: User) -> KnowledgeBase:
    kb = KnowledgeBase(
        owner_id=owner.id,
        name=f"kb-{uuid.uuid4().hex[:8]}",
    )
    db.add(kb)
    await db.flush()
    return kb


# ---------------------------------------------------------------------------
# autonomous_sessions
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_session_round_trip_and_brake_defaults(db_session: AsyncSession) -> None:
    """Insert + read returns a session with all brake defaults materialized."""
    user = await _make_user(db_session)
    sess = AutonomousSession(user_id=user.id, trigger_kind="manual")
    db_session.add(sess)
    await db_session.flush()
    await db_session.refresh(sess)

    assert isinstance(sess.id, uuid.UUID)
    assert sess.current_phase == "intake"
    assert sess.halt_state == "running"
    assert sess.status == "running"
    assert sess.cost_total_usd == 0
    assert sess.cost_cap_reached is False
    assert sess.idle_halt_minutes == 5
    assert sess.last_activity_at is not None
    assert sess.created_at is not None
    assert sess.updated_at is not None
    assert sess.completed_at is None


@pytest.mark.integration
async def test_session_custom_brake_knobs_round_trip(db_session: AsyncSession) -> None:
    """Non-default brake knobs persist — locks the Numeric(10,4)/Integer storage M4-A2 sets."""
    user = await _make_user(db_session)
    sess = AutonomousSession(
        user_id=user.id,
        trigger_kind="manual",
        max_cost_usd=Decimal("2.5000"),
        idle_halt_minutes=10,
    )
    db_session.add(sess)
    await db_session.flush()
    await db_session.refresh(sess)

    assert sess.max_cost_usd == Decimal("2.5000")
    assert sess.idle_halt_minutes == 10


@pytest.mark.integration
async def test_session_requires_user_id(db_session: AsyncSession) -> None:
    """user_id is NOT NULL — per-user isolation is enforced at the column."""
    sess = AutonomousSession(user_id=None, trigger_kind="manual")  # type: ignore[arg-type]
    db_session.add(sess)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.integration
async def test_session_trigger_kind_check_constraint(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    sess = AutonomousSession(user_id=user.id, trigger_kind="telepathy")
    db_session.add(sess)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.integration
async def test_session_phase_check_constraint(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    sess = AutonomousSession(user_id=user.id, trigger_kind="manual", current_phase="wandering")
    db_session.add(sess)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.integration
async def test_session_halt_state_check_constraint(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    sess = AutonomousSession(user_id=user.id, trigger_kind="manual", halt_state="exploded")
    db_session.add(sess)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.integration
async def test_session_status_check_constraint(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    sess = AutonomousSession(user_id=user.id, trigger_kind="manual", status="warp_speed")
    db_session.add(sess)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.integration
async def test_session_result_jsonb_round_trip(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    payload = {"deliverable": "redline.docx", "positions_flagged": 3}
    sess = AutonomousSession(
        user_id=user.id,
        trigger_kind="schedule",
        status="completed",
        result=payload,
        cost_total_usd=1.2345,
        completed_at=datetime.now(UTC),
    )
    db_session.add(sess)
    await db_session.flush()
    await db_session.refresh(sess)
    assert sess.result == payload
    assert float(sess.cost_total_usd) == pytest.approx(1.2345)


@pytest.mark.integration
async def test_session_user_isolation(db_session: AsyncSession) -> None:
    """Two users' sessions don't cross-read when filtering by user_id."""
    alice = await _make_user(db_session)
    bob = await _make_user(db_session)
    db_session.add_all(
        [
            AutonomousSession(user_id=alice.id, trigger_kind="manual"),
            AutonomousSession(user_id=bob.id, trigger_kind="manual"),
            AutonomousSession(user_id=bob.id, trigger_kind="schedule"),
        ]
    )
    await db_session.flush()

    alice_rows = (
        (
            await db_session.execute(
                select(AutonomousSession).where(AutonomousSession.user_id == alice.id)
            )
        )
        .scalars()
        .all()
    )
    bob_rows = (
        (
            await db_session.execute(
                select(AutonomousSession).where(AutonomousSession.user_id == bob.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(alice_rows) == 1
    assert len(bob_rows) == 2
    assert all(r.user_id == alice.id for r in alice_rows)
    assert all(r.user_id == bob.id for r in bob_rows)


@pytest.mark.integration
async def test_session_cascade_on_user_delete(db_session: AsyncSession) -> None:
    """Deleting the user hard-deletes their sessions (ON DELETE CASCADE)."""
    user = await _make_user(db_session)
    sess = AutonomousSession(user_id=user.id, trigger_kind="manual")
    db_session.add(sess)
    await db_session.flush()
    sess_id = sess.id

    await db_session.delete(user)
    await db_session.flush()
    db_session.expire_all()

    remaining = (
        (await db_session.execute(select(AutonomousSession).where(AutonomousSession.id == sess_id)))
        .scalars()
        .all()
    )
    assert remaining == []


# ---------------------------------------------------------------------------
# autonomous_schedules
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_schedule_round_trip(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    sched = AutonomousSchedule(
        user_id=user.id,
        name="Nightly NDA sweep",
        cron_expr="0 2 * * *",
    )
    db_session.add(sched)
    await db_session.flush()
    await db_session.refresh(sched)

    assert isinstance(sched.id, uuid.UUID)
    assert sched.enabled is True
    assert sched.cron_expr == "0 2 * * *"
    assert sched.last_run_at is None
    assert sched.next_run_at is None
    assert sched.deleted_at is None
    assert sched.created_at is not None


@pytest.mark.integration
async def test_schedule_requires_user_id(db_session: AsyncSession) -> None:
    sched = AutonomousSchedule(user_id=None, cron_expr="0 2 * * *")  # type: ignore[arg-type]
    db_session.add(sched)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.integration
async def test_schedule_kb_fk(db_session: AsyncSession) -> None:
    """target_kb_id resolves to a real knowledge_bases row."""
    user = await _make_user(db_session)
    kb = await _make_kb(db_session, owner=user)
    sched = AutonomousSchedule(
        user_id=user.id,
        cron_expr="0 * * * *",
        target_kb_id=kb.id,
    )
    db_session.add(sched)
    await db_session.flush()
    await db_session.refresh(sched)
    assert sched.target_kb_id == kb.id


# ---------------------------------------------------------------------------
# autonomous_watches
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_watch_round_trip(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    kb = await _make_kb(db_session, owner=user)
    watch = AutonomousWatch(user_id=user.id, knowledge_base_id=kb.id)
    db_session.add(watch)
    await db_session.flush()
    await db_session.refresh(watch)

    assert isinstance(watch.id, uuid.UUID)
    assert watch.knowledge_base_id == kb.id
    assert watch.enabled is True
    assert watch.deleted_at is None


@pytest.mark.integration
async def test_watch_requires_user_id(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    kb = await _make_kb(db_session, owner=user)
    watch = AutonomousWatch(user_id=None, knowledge_base_id=kb.id)  # type: ignore[arg-type]
    db_session.add(watch)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.integration
async def test_watch_requires_knowledge_base_id(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    watch = AutonomousWatch(user_id=user.id, knowledge_base_id=None)  # type: ignore[arg-type]
    db_session.add(watch)
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ---------------------------------------------------------------------------
# autonomous_memory
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_memory_round_trip(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    note = AutonomousMemory(
        user_id=user.id,
        state="proposed",
        category="drafting_preference",
        content="User prefers governing law = Delaware.",
    )
    db_session.add(note)
    await db_session.flush()
    await db_session.refresh(note)

    assert isinstance(note.id, uuid.UUID)
    assert note.state == "proposed"
    assert note.kept_at is None
    assert note.deleted_at is None


@pytest.mark.integration
async def test_memory_state_check_constraint(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    note = AutonomousMemory(
        user_id=user.id,
        state="enlightened",
        category="x",
        content="y",
    )
    db_session.add(note)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.integration
async def test_memory_source_session_fk(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    sess = AutonomousSession(user_id=user.id, trigger_kind="suggestion")
    db_session.add(sess)
    await db_session.flush()
    note = AutonomousMemory(
        user_id=user.id,
        state="kept",
        category="x",
        content="y",
        source_session_id=sess.id,
        kept_at=datetime.now(UTC),
    )
    db_session.add(note)
    await db_session.flush()
    await db_session.refresh(note)
    assert note.source_session_id == sess.id


@pytest.mark.integration
async def test_memory_requires_user_id(db_session: AsyncSession) -> None:
    note = AutonomousMemory(user_id=None, state="proposed", category="x", content="y")  # type: ignore[arg-type]
    db_session.add(note)
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ---------------------------------------------------------------------------
# precedent_entries
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_precedent_round_trip(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    entry = PrecedentEntry(
        user_id=user.id,
        pattern_kind="liability_cap",
        summary="User consistently accepts 12-month fee caps.",
    )
    db_session.add(entry)
    await db_session.flush()
    await db_session.refresh(entry)

    assert isinstance(entry.id, uuid.UUID)
    assert entry.observed_count == 1
    assert entry.dismissed_at is None


@pytest.mark.integration
async def test_precedent_requires_user_id(db_session: AsyncSession) -> None:
    entry = PrecedentEntry(user_id=None, pattern_kind="x", summary="y")  # type: ignore[arg-type]
    db_session.add(entry)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.integration
async def test_precedent_user_isolation(db_session: AsyncSession) -> None:
    alice = await _make_user(db_session)
    bob = await _make_user(db_session)
    db_session.add_all(
        [
            PrecedentEntry(user_id=alice.id, pattern_kind="a", summary="s"),
            PrecedentEntry(user_id=bob.id, pattern_kind="b", summary="s"),
        ]
    )
    await db_session.flush()
    alice_rows = (
        (await db_session.execute(select(PrecedentEntry).where(PrecedentEntry.user_id == alice.id)))
        .scalars()
        .all()
    )
    assert len(alice_rows) == 1
    assert alice_rows[0].user_id == alice.id


# ---------------------------------------------------------------------------
# ON DELETE SET NULL — source_session_id survives a session delete
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_source_session_set_null_on_session_delete(db_session: AsyncSession) -> None:
    """Deleting the source session nulls source_session_id but keeps the rows.

    Contrast with test_session_cascade_on_user_delete: a user delete CASCADEs
    the rows away, but a session delete only SET NULLs the back-reference —
    the memory note and precedent entry survive with source_session_id IS NULL.
    """
    user = await _make_user(db_session)
    sess = AutonomousSession(user_id=user.id, trigger_kind="suggestion")
    db_session.add(sess)
    await db_session.flush()
    sess_id = sess.id

    note = AutonomousMemory(
        user_id=user.id,
        state="kept",
        category="drafting_preference",
        content="User prefers Delaware governing law.",
        source_session_id=sess_id,
    )
    entry = PrecedentEntry(
        user_id=user.id,
        pattern_kind="liability_cap",
        summary="User accepts 12-month fee caps.",
        source_session_id=sess_id,
    )
    db_session.add_all([note, entry])
    await db_session.flush()
    note_id = note.id
    entry_id = entry.id

    await db_session.delete(sess)
    await db_session.flush()
    db_session.expire_all()

    surviving_note = (
        await db_session.execute(select(AutonomousMemory).where(AutonomousMemory.id == note_id))
    ).scalar_one()
    surviving_entry = (
        await db_session.execute(select(PrecedentEntry).where(PrecedentEntry.id == entry_id))
    ).scalar_one()

    assert surviving_note.source_session_id is None
    assert surviving_entry.source_session_id is None


# ---------------------------------------------------------------------------
# Schema-level smoke
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_autonomous_indexes_present_on_disk(db_session: AsyncSession) -> None:
    """The spec's named indexes exist after migration."""
    result = await db_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = current_schema() "
            "AND indexname IN ("
            "'idx_autonomous_sessions_user_created',"
            "'idx_autonomous_sessions_active',"
            "'idx_autonomous_watches_kb_enabled',"
            "'idx_autonomous_memory_user_state',"
            "'idx_precedent_entries_user_kind'"
            ")"
        )
    )
    present = {row[0] for row in result.all()}
    assert present == {
        "idx_autonomous_sessions_user_created",
        "idx_autonomous_sessions_active",
        "idx_autonomous_watches_kb_enabled",
        "idx_autonomous_memory_user_state",
        "idx_precedent_entries_user_kind",
    }


@pytest.mark.unit
def test_autonomous_models_registered_with_metadata() -> None:
    """Importing the models module registers all five tables with the Base."""
    from app.db.base import Base

    table_names = set(Base.metadata.tables.keys())
    assert {
        "autonomous_sessions",
        "autonomous_schedules",
        "autonomous_watches",
        "autonomous_memory",
        "precedent_entries",
    } <= table_names


@pytest.mark.unit
def test_autonomous_columns_match_migration() -> None:
    """The ORM model columns line up with the migration's column set."""
    assert {c.name for c in inspect(AutonomousSession).columns} == {
        "id",
        "user_id",
        "project_id",
        "trigger_kind",
        "trigger_ref",
        "params",
        "current_phase",
        "halt_state",
        "max_cost_usd",
        "cost_total_usd",
        "cost_cap_reached",
        "idle_halt_minutes",
        "last_activity_at",
        "status",
        "result",
        "error",
        "created_at",
        "updated_at",
        "completed_at",
    }
    assert {c.name for c in inspect(AutonomousSchedule).columns} == {
        "id",
        "user_id",
        "project_id",
        "name",
        "cron_expr",
        "playbook_id",
        "skill_ref",
        "target_kb_id",
        "max_cost_usd",
        "enabled",
        "last_run_at",
        "next_run_at",
        "deleted_at",
        "created_at",
        "updated_at",
    }
    assert {c.name for c in inspect(AutonomousWatch).columns} == {
        "id",
        "user_id",
        "project_id",
        "knowledge_base_id",
        "playbook_id",
        "skill_ref",
        "max_cost_usd",
        "enabled",
        "deleted_at",
        "created_at",
        "updated_at",
    }
    assert {c.name for c in inspect(AutonomousMemory).columns} == {
        "id",
        "user_id",
        "state",
        "category",
        "content",
        "source_session_id",
        "kept_at",
        "deleted_at",
        "created_at",
        "updated_at",
    }
    assert {c.name for c in inspect(PrecedentEntry).columns} == {
        "id",
        "user_id",
        "pattern_kind",
        "summary",
        "observed_count",
        "source_session_id",
        "dismissed_at",
        "created_at",
        "updated_at",
    }
