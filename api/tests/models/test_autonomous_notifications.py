"""Model + migration tests for the in-app notification substrate — M4-A3.2.

Covers the single table created by migration
``0040_autonomous_notifications.py`` ([PRD §3.10](docs/PRD.md#310-autonomous-layer-m4),
Decision M4-8 / DE-312):

* :class:`AutonomousNotification` — a durable in-app notification written by
  the ``notify`` chokepoint handler (A3.3). Email transport, the read/dismiss
  API, the web surface, and webhook dispatch stay in M4-C1.

The acceptance contract for this task:

* CRUD round-trip — defaults materialize (``channel='in_app'``, ``read_at IS NULL``).
* Hard per-user isolation: insert without ``user_id`` fails; two users' rows
  don't cross-read.
* ``channel`` CHECK rejects a bogus value and accepts all three valid values.
* ``channel`` server default materializes to ``'in_app'``.
* ``ON DELETE CASCADE``: deleting the parent session (or user) removes the
  notification row.
* The table exists on disk after migration (pg_tables smoke test).

Tests run against the SAVEPOINT-rolled-back per-test session from
``tests/conftest.py``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.autonomous import AutonomousNotification, AutonomousSession
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


async def _make_session(db: AsyncSession, *, owner: User) -> AutonomousSession:
    sess = AutonomousSession(user_id=owner.id, trigger_kind="manual")
    db.add(sess)
    await db.flush()
    return sess


# ---------------------------------------------------------------------------
# CRUD round-trip + defaults
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_notification_round_trip_and_defaults(db_session: AsyncSession) -> None:
    """Insert + read returns a notification with defaults materialized."""
    user = await _make_user(db_session)
    sess = await _make_session(db_session, owner=user)

    notif = AutonomousNotification(
        user_id=user.id,
        session_id=sess.id,
        title="NDA review complete",
        body="Session reviewed 3 clauses. See receipt /receipts/abc123.",
    )
    db_session.add(notif)
    await db_session.flush()
    await db_session.refresh(notif)

    assert isinstance(notif.id, uuid.UUID)
    assert notif.user_id == user.id
    assert notif.session_id == sess.id
    assert notif.channel == "in_app"
    assert notif.title == "NDA review complete"
    assert notif.body == "Session reviewed 3 clauses. See receipt /receipts/abc123."
    assert notif.payload is None
    assert notif.read_at is None
    assert notif.created_at is not None
    assert notif.updated_at is not None


@pytest.mark.integration
async def test_notification_with_payload(db_session: AsyncSession) -> None:
    """Optional JSONB payload stores structured counts/types/IDs."""
    user = await _make_user(db_session)
    sess = await _make_session(db_session, owner=user)

    payload = {"clause_count": 5, "session_id": str(sess.id)}
    notif = AutonomousNotification(
        user_id=user.id,
        session_id=sess.id,
        title="MSA review complete",
        body="Session reviewed 5 clauses.",
        payload=payload,
    )
    db_session.add(notif)
    await db_session.flush()
    await db_session.refresh(notif)

    assert notif.payload == payload


# ---------------------------------------------------------------------------
# Hard per-user isolation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_notification_requires_user_id(db_session: AsyncSession) -> None:
    """user_id is NOT NULL — per-user isolation is enforced at the column."""
    user = await _make_user(db_session)
    sess = await _make_session(db_session, owner=user)

    notif = AutonomousNotification(
        user_id=None,  # type: ignore[arg-type]
        session_id=sess.id,
        title="x",
        body="y",
    )
    db_session.add(notif)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.integration
async def test_notification_user_isolation(db_session: AsyncSession) -> None:
    """Two users' notifications don't cross-read when filtering by user_id."""
    alice = await _make_user(db_session)
    bob = await _make_user(db_session)
    alice_sess = await _make_session(db_session, owner=alice)
    bob_sess = await _make_session(db_session, owner=bob)

    db_session.add_all(
        [
            AutonomousNotification(
                user_id=alice.id,
                session_id=alice_sess.id,
                title="alice-1",
                body="b",
            ),
            AutonomousNotification(
                user_id=bob.id,
                session_id=bob_sess.id,
                title="bob-1",
                body="b",
            ),
            AutonomousNotification(
                user_id=bob.id,
                session_id=bob_sess.id,
                title="bob-2",
                body="b",
            ),
        ]
    )
    await db_session.flush()

    alice_rows = (
        (
            await db_session.execute(
                select(AutonomousNotification).where(AutonomousNotification.user_id == alice.id)
            )
        )
        .scalars()
        .all()
    )
    bob_rows = (
        (
            await db_session.execute(
                select(AutonomousNotification).where(AutonomousNotification.user_id == bob.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(alice_rows) == 1
    assert len(bob_rows) == 2
    assert all(r.user_id == alice.id for r in alice_rows)
    assert all(r.user_id == bob.id for r in bob_rows)


# ---------------------------------------------------------------------------
# channel CHECK constraint
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_notification_channel_default_is_in_app(db_session: AsyncSession) -> None:
    """The channel server default materializes to 'in_app'."""
    user = await _make_user(db_session)
    sess = await _make_session(db_session, owner=user)

    notif = AutonomousNotification(
        user_id=user.id,
        session_id=sess.id,
        title="x",
        body="y",
        # channel not set — must default to 'in_app'
    )
    db_session.add(notif)
    await db_session.flush()
    await db_session.refresh(notif)
    assert notif.channel == "in_app"


@pytest.mark.integration
async def test_notification_channel_accepts_email(db_session: AsyncSession) -> None:
    """channel='email' is valid per the CHECK constraint."""
    user = await _make_user(db_session)
    sess = await _make_session(db_session, owner=user)

    notif = AutonomousNotification(
        user_id=user.id,
        session_id=sess.id,
        title="x",
        body="y",
        channel="email",
    )
    db_session.add(notif)
    await db_session.flush()
    await db_session.refresh(notif)
    assert notif.channel == "email"


@pytest.mark.integration
async def test_notification_channel_accepts_webhook(db_session: AsyncSession) -> None:
    """channel='webhook' is valid per the CHECK constraint (reserved, DE-312)."""
    user = await _make_user(db_session)
    sess = await _make_session(db_session, owner=user)

    notif = AutonomousNotification(
        user_id=user.id,
        session_id=sess.id,
        title="x",
        body="y",
        channel="webhook",
    )
    db_session.add(notif)
    await db_session.flush()
    await db_session.refresh(notif)
    assert notif.channel == "webhook"


@pytest.mark.integration
async def test_notification_channel_check_rejects_bogus(db_session: AsyncSession) -> None:
    """channel CHECK constraint rejects values outside the allowed set."""
    user = await _make_user(db_session)
    sess = await _make_session(db_session, owner=user)

    notif = AutonomousNotification(
        user_id=user.id,
        session_id=sess.id,
        title="x",
        body="y",
        channel="telepathy",
    )
    db_session.add(notif)
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ---------------------------------------------------------------------------
# ON DELETE CASCADE
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_notification_cascade_on_session_delete(db_session: AsyncSession) -> None:
    """Deleting the parent session hard-deletes its notifications (ON DELETE CASCADE)."""
    user = await _make_user(db_session)
    sess = await _make_session(db_session, owner=user)

    notif = AutonomousNotification(
        user_id=user.id,
        session_id=sess.id,
        title="x",
        body="y",
    )
    db_session.add(notif)
    await db_session.flush()
    notif_id = notif.id

    await db_session.delete(sess)
    await db_session.flush()
    db_session.expire_all()

    remaining = (
        (
            await db_session.execute(
                select(AutonomousNotification).where(AutonomousNotification.id == notif_id)
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []


@pytest.mark.integration
async def test_notification_cascade_on_user_delete(db_session: AsyncSession) -> None:
    """Deleting the user hard-deletes their notifications (ON DELETE CASCADE)."""
    user = await _make_user(db_session)
    sess = await _make_session(db_session, owner=user)

    notif = AutonomousNotification(
        user_id=user.id,
        session_id=sess.id,
        title="x",
        body="y",
    )
    db_session.add(notif)
    await db_session.flush()
    notif_id = notif.id

    await db_session.delete(user)
    await db_session.flush()
    db_session.expire_all()

    remaining = (
        (
            await db_session.execute(
                select(AutonomousNotification).where(AutonomousNotification.id == notif_id)
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []


# ---------------------------------------------------------------------------
# Schema-level smoke
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_autonomous_notifications_table_exists_on_disk(
    db_session: AsyncSession,
) -> None:
    """The table exists in pg_tables after migration 0040 runs."""
    result = await db_session.execute(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename = 'autonomous_notifications'"
        )
    )
    assert result.scalar() == "autonomous_notifications"


@pytest.mark.unit
def test_autonomous_notification_registered_with_metadata() -> None:
    """Importing the models module registers autonomous_notifications with the Base."""
    from app.db.base import Base

    assert "autonomous_notifications" in Base.metadata.tables


@pytest.mark.unit
def test_autonomous_notification_columns_match_migration() -> None:
    """The ORM model columns line up with the migration's column set."""
    from sqlalchemy import inspect

    assert {c.name for c in inspect(AutonomousNotification).columns} == {
        "id",
        "user_id",
        "session_id",
        "channel",
        "title",
        "body",
        "payload",
        "read_at",
        "created_at",
        "updated_at",
    }
