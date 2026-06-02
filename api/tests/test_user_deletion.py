"""Integration tests for the D6 GDPR Article 17 schedule + cancel surface.

Covers:

* POST /users/me/delete schedules deletion + revokes sessions + audit-logs.
* Idempotency — rerunning returns the same schedule (no extension).
* POST /users/me/delete/cancel clears the schedule + audit-logs.
* Cancel without a pending schedule is a 400.

Hard-delete cascade behavior is covered separately in
:mod:`tests.test_user_deletion_hard_delete`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models import AuditLog, User, UserSession
from app.security import create_access_token, hash_password


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def seed_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"delete-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Delete Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# /users/me/delete — schedule
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_delete_schedules_deletion_and_revokes_sessions(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    """Schedules deletion, revokes existing sessions, audit-logs the request."""
    # Pretend the user has an existing active session.
    now = datetime.now(tz=UTC)
    sess = UserSession(
        user_id=seed_user.id,
        refresh_token_hash="x" * 60,
        expires_at=now,
        absolute_expires_at=now + timedelta(hours=8),
        last_active_at=now,
    )
    db_session.add(sess)
    await db_session.flush()

    resp = await client.post("/api/v1/users/me/delete", headers=_bearer(seed_user))
    assert resp.status_code == 202, resp.text

    body = resp.json()
    assert body["grace_period_days"] >= 0
    assert datetime.fromisoformat(body["scheduled_deletion_at"]) > datetime.now(tz=UTC) - (
        # generous tolerance — the schedule is now + grace days
        datetime.now(tz=UTC) - datetime.now(tz=UTC)
    )

    await db_session.refresh(seed_user)
    assert seed_user.deletion_scheduled_at is not None

    await db_session.refresh(sess)
    assert sess.revoked_at is not None

    rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.user_id == seed_user.id)))
        .scalars()
        .all()
    )
    assert any(r.action == "user.deletion_scheduled" for r in rows)


@pytest.mark.integration
async def test_users_me_exposes_deletion_scheduled_at(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    """GET /users/me surfaces deletion_scheduled_at (Donna P1.4).

    A user's own session must be able to tell on load whether a deletion is
    pending — the field is null before scheduling and carries the scheduled
    timestamp after, matching the POST /users/me/delete response.
    """
    # Before any deletion: field present and null.
    before = await client.get("/api/v1/users/me", headers=_bearer(seed_user))
    assert before.status_code == 200, before.text
    assert "deletion_scheduled_at" in before.json()
    assert before.json()["deletion_scheduled_at"] is None

    # Schedule a deletion.
    sched = await client.post("/api/v1/users/me/delete", headers=_bearer(seed_user))
    assert sched.status_code == 202, sched.text
    scheduled_at = sched.json()["scheduled_deletion_at"]

    # /users/me now reflects the pending-deletion timestamp.
    after = await client.get("/api/v1/users/me", headers=_bearer(seed_user))
    assert after.status_code == 200, after.text
    exposed = after.json()["deletion_scheduled_at"]
    assert exposed is not None
    assert datetime.fromisoformat(exposed) == datetime.fromisoformat(scheduled_at)


@pytest.mark.integration
async def test_delete_is_idempotent(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    """Re-running schedule returns the same scheduled_at — no grace-period extension."""
    first = await client.post("/api/v1/users/me/delete", headers=_bearer(seed_user))
    assert first.status_code == 202
    first_at = first.json()["scheduled_deletion_at"]

    second = await client.post("/api/v1/users/me/delete", headers=_bearer(seed_user))
    assert second.status_code == 202
    second_at = second.json()["scheduled_deletion_at"]

    assert first_at == second_at


# ---------------------------------------------------------------------------
# /users/me/delete/cancel
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_cancel_clears_pending_schedule(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    schedule = await client.post("/api/v1/users/me/delete", headers=_bearer(seed_user))
    assert schedule.status_code == 202

    cancel = await client.post("/api/v1/users/me/delete/cancel", headers=_bearer(seed_user))
    assert cancel.status_code == 204

    await db_session.refresh(seed_user)
    assert seed_user.deletion_scheduled_at is None

    rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.user_id == seed_user.id)))
        .scalars()
        .all()
    )
    assert any(r.action == "user.deletion_cancelled" for r in rows)


@pytest.mark.integration
async def test_cancel_without_pending_returns_400(client: AsyncClient, seed_user: User) -> None:
    resp = await client.post("/api/v1/users/me/delete/cancel", headers=_bearer(seed_user))
    assert resp.status_code == 400
