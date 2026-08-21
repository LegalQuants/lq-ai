"""Integration tests for user provisioning — POST /api/v1/admin/users and
POST /api/v1/admin/users/{user_id}/reset-password.

Covers:
* 201 returns the generated plaintext exactly once; only the bcrypt hash lands
  in the DB and the plaintext never appears in the audit row.
* The created user is forced through password rotation (must_change_password).
* ``is_admin`` is derived from ``role`` (True iff role='admin').
* 409 on a duplicate email, including a case-variant one (``email`` is CITEXT).
* 422 on an unknown role; 403 for non-admin callers.
* Reset mints a new password, re-arms must_change_password, and revokes every
  active refresh session for the target user.
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
from app.models.audit import AuditLog
from app.models.user import User, UserSession
from app.security import create_access_token, hash_password, verify_password

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


def _make_user(*, email: str, is_admin: bool = False, role: str = "member") -> User:
    return User(
        email=email,
        display_name=email.split("@")[0].capitalize(),
        hashed_password=hash_password("s3cr3t-battery-staple"),
        is_admin=is_admin,
        role=role,
        mfa_enabled=False,
        must_change_password=False,
    )


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = _make_user(
        email=f"admin-{uuid.uuid4().hex[:8]}@example.com", is_admin=True, role="admin"
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def member_user(db_session: AsyncSession) -> User:
    user = _make_user(email=f"member-{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()
    return user


def _new_email() -> str:
    return f"attorney-{uuid.uuid4().hex[:8]}@example.com"


# ---------------------------------------------------------------------------
# POST /admin/users
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_user_returns_plaintext_once_and_stores_only_the_hash(
    client: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    email = _new_email()
    resp = await client.post(
        "/api/v1/admin/users",
        json={"email": email, "display_name": "Ana Ruiz", "role": "member"},
        headers=_bearer(admin_user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    plaintext = body["initial_password"]
    assert len(plaintext) == 24
    assert body["email"] == email
    assert body["display_name"] == "Ana Ruiz"
    assert body["role"] == "member"
    assert body["is_admin"] is False
    assert body["must_change_password"] is True

    row = (
        await db_session.execute(select(User).where(User.id == uuid.UUID(body["user_id"])))
    ).scalar_one()
    # Only the hash is persisted, and it verifies against the returned plaintext.
    assert row.hashed_password != plaintext
    assert verify_password(plaintext, row.hashed_password)
    assert row.must_change_password is True
    assert row.mfa_enabled is False


@pytest.mark.asyncio
async def test_create_user_audit_row_never_carries_the_password(
    client: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    email = _new_email()
    resp = await client.post(
        "/api/v1/admin/users",
        json={"email": email, "role": "member"},
        headers=_bearer(admin_user),
    )
    assert resp.status_code == 201
    plaintext = resp.json()["initial_password"]

    entry = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "user.created",
                AuditLog.resource_id == resp.json()["user_id"],
            )
        )
    ).scalar_one()
    assert entry.user_id == admin_user.id
    assert entry.resource_type == "user"
    assert entry.details is not None
    assert entry.details["target_user_email"] == email
    assert entry.details["role"] == "member"
    assert plaintext not in str(entry.details)


@pytest.mark.asyncio
async def test_create_admin_role_sets_is_admin(
    client: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    resp = await client.post(
        "/api/v1/admin/users",
        json={"email": _new_email(), "role": "admin"},
        headers=_bearer(admin_user),
    )
    assert resp.status_code == 201
    assert resp.json()["is_admin"] is True

    row = (
        await db_session.execute(select(User).where(User.id == uuid.UUID(resp.json()["user_id"])))
    ).scalar_one()
    assert row.is_admin is True
    assert row.role == "admin"


@pytest.mark.asyncio
async def test_create_user_rejects_duplicate_email(
    client: AsyncClient, admin_user: User, member_user: User
) -> None:
    resp = await client.post(
        "/api/v1/admin/users",
        json={"email": member_user.email, "role": "member"},
        headers=_bearer(admin_user),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "conflict"


@pytest.mark.asyncio
async def test_create_user_duplicate_check_is_case_insensitive(
    client: AsyncClient, admin_user: User, member_user: User
) -> None:
    """``users.email`` is CITEXT, so an upper-cased duplicate must still 409."""
    resp = await client.post(
        "/api/v1/admin/users",
        json={"email": member_user.email.upper(), "role": "member"},
        headers=_bearer(admin_user),
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_create_user_rejects_unknown_role(client: AsyncClient, admin_user: User) -> None:
    resp = await client.post(
        "/api/v1/admin/users",
        json={"email": _new_email(), "role": "partner"},
        headers=_bearer(admin_user),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_create_user_requires_admin(client: AsyncClient, member_user: User) -> None:
    resp = await client.post(
        "/api/v1/admin/users",
        json={"email": _new_email(), "role": "member"},
        headers=_bearer(member_user),
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_two_created_users_get_different_passwords(
    client: AsyncClient, admin_user: User
) -> None:
    first = await client.post(
        "/api/v1/admin/users",
        json={"email": _new_email(), "role": "member"},
        headers=_bearer(admin_user),
    )
    second = await client.post(
        "/api/v1/admin/users",
        json={"email": _new_email(), "role": "member"},
        headers=_bearer(admin_user),
    )
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["initial_password"] != second.json()["initial_password"]


# ---------------------------------------------------------------------------
# POST /admin/users/{user_id}/reset-password
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_password_rotates_hash_and_rearms_forced_change(
    client: AsyncClient, db_session: AsyncSession, admin_user: User, member_user: User
) -> None:
    before_hash = member_user.hashed_password

    resp = await client.post(
        f"/api/v1/admin/users/{member_user.id}/reset-password",
        headers=_bearer(admin_user),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    row = (await db_session.execute(select(User).where(User.id == member_user.id))).scalar_one()
    assert row.hashed_password != before_hash
    assert verify_password(body["initial_password"], row.hashed_password)
    assert row.must_change_password is True


@pytest.mark.asyncio
async def test_reset_password_revokes_active_sessions(
    client: AsyncClient, db_session: AsyncSession, admin_user: User, member_user: User
) -> None:
    now = datetime.now(UTC)
    active = UserSession(
        user_id=member_user.id,
        refresh_token_hash=hash_password("refresh-token-value"),
        expires_at=now + timedelta(days=7),
        absolute_expires_at=now + timedelta(hours=8),
        last_active_at=now,
    )
    already_revoked = UserSession(
        user_id=member_user.id,
        refresh_token_hash=hash_password("older-refresh-token"),
        expires_at=now + timedelta(days=7),
        absolute_expires_at=now + timedelta(hours=8),
        last_active_at=now,
        revoked_at=now - timedelta(hours=1),
    )
    db_session.add_all([active, already_revoked])
    await db_session.flush()

    resp = await client.post(
        f"/api/v1/admin/users/{member_user.id}/reset-password",
        headers=_bearer(admin_user),
    )
    assert resp.status_code == 200, resp.text
    # Only the one live session is revoked; the already-revoked row is untouched.
    assert resp.json()["sessions_revoked"] == 1

    refreshed = (
        await db_session.execute(select(UserSession).where(UserSession.id == active.id))
    ).scalar_one()
    await db_session.refresh(refreshed)
    assert refreshed.revoked_at is not None


@pytest.mark.asyncio
async def test_reset_password_writes_audit_row(
    client: AsyncClient, db_session: AsyncSession, admin_user: User, member_user: User
) -> None:
    resp = await client.post(
        f"/api/v1/admin/users/{member_user.id}/reset-password",
        headers=_bearer(admin_user),
    )
    assert resp.status_code == 200

    entry = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "user.password_reset",
                AuditLog.resource_id == str(member_user.id),
            )
        )
    ).scalar_one()
    assert entry.user_id == admin_user.id
    assert entry.details is not None
    assert entry.details["target_user_email"] == member_user.email
    assert resp.json()["initial_password"] not in str(entry.details)


@pytest.mark.asyncio
async def test_reset_password_unknown_user_404(client: AsyncClient, admin_user: User) -> None:
    resp = await client.post(
        f"/api/v1/admin/users/{uuid.uuid4()}/reset-password",
        headers=_bearer(admin_user),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_reset_password_malformed_uuid_404(client: AsyncClient, admin_user: User) -> None:
    resp = await client.post(
        "/api/v1/admin/users/not-a-uuid/reset-password",
        headers=_bearer(admin_user),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_reset_password_requires_admin(client: AsyncClient, member_user: User) -> None:
    resp = await client.post(
        f"/api/v1/admin/users/{member_user.id}/reset-password",
        headers=_bearer(member_user),
    )
    assert resp.status_code == 403, resp.text
