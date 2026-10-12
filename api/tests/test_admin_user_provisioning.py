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

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException, Request, Response
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.user import User, UserSession
from app.security import create_access_token, create_refresh_token, hash_password, verify_password

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(
        user.id, user.email, is_admin=user.is_admin, credential_version=user.credential_version
    )
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
    assert resp.headers["Cache-Control"] == "no-store"
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
    assert resp.headers["Cache-Control"] == "no-store"
    body = resp.json()

    row = (await db_session.execute(select(User).where(User.id == member_user.id))).scalar_one()
    assert row.hashed_password != before_hash
    assert verify_password(body["initial_password"], row.hashed_password)
    assert row.must_change_password is True
    assert row.credential_version == 1


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


@pytest.mark.asyncio
async def test_reset_invalidates_tokens_permanently_after_password_change(
    client: AsyncClient, admin_user: User, member_user: User
) -> None:
    """Old access/refresh tokens never regain access when forced change clears."""
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": member_user.email, "password": "s3cr3t-battery-staple"},
    )
    assert login.status_code == 200, login.text
    old = login.json()
    old_bearer = {"Authorization": f"Bearer {old['access_token']}"}

    reset = await client.post(
        f"/api/v1/admin/users/{member_user.id}/reset-password", headers=_bearer(admin_user)
    )
    assert reset.status_code == 200, reset.text
    # /users/me uses CurrentUser, bypassing the forced-change gate: this
    # verifies actual token invalidation, rather than temporary 403 gating.
    assert (await client.get("/api/v1/users/me", headers=old_bearer)).status_code == 401
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": old["refresh_token"]})
    ).status_code == 401

    temporary = await client.post(
        "/api/v1/auth/login",
        json={"email": member_user.email, "password": reset.json()["initial_password"]},
    )
    assert temporary.status_code == 200, temporary.text
    temporary_bearer = {"Authorization": f"Bearer {temporary.json()['access_token']}"}
    change = await client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": reset.json()["initial_password"],
            "new_password": "user-owned-new-password",
        },
        headers=temporary_bearer,
    )
    assert change.status_code == 204, change.text
    for headers in (old_bearer, temporary_bearer):
        assert (await client.get("/api/v1/users/me", headers=headers)).status_code == 401
    permanent = await client.post(
        "/api/v1/auth/login",
        json={"email": member_user.email, "password": "user-owned-new-password"},
    )
    assert permanent.status_code == 200, permanent.text
    assert (
        await client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {permanent.json()['access_token']}"},
        )
    ).status_code == 200
    assert (
        await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": permanent.json()["refresh_token"]}
        )
    ).status_code == 200


@pytest.mark.asyncio
async def test_reset_preserves_mfa_but_invalidates_old_challenge(
    client: AsyncClient, db_session: AsyncSession, admin_user: User, member_user: User
) -> None:
    """A challenge proving the old password cannot mint a post-reset session."""
    import pyotp

    secret = pyotp.random_base32()
    member_user.mfa_enabled = True
    member_user.totp_secret = secret
    await db_session.flush()
    challenge = await client.post(
        "/api/v1/auth/login",
        json={"email": member_user.email, "password": "s3cr3t-battery-staple"},
    )
    assert challenge.status_code == 423, challenge.text
    reset = await client.post(
        f"/api/v1/admin/users/{member_user.id}/reset-password", headers=_bearer(admin_user)
    )
    assert reset.status_code == 200
    assert member_user.mfa_enabled is True
    assert member_user.totp_secret == secret
    assert (
        await client.post(
            "/api/v1/auth/mfa/verify",
            json={"mfa_token": challenge.json()["mfa_token"], "code": pyotp.TOTP(secret).now()},
        )
    ).status_code == 401
    fresh = await client.post(
        "/api/v1/auth/login",
        json={"email": member_user.email, "password": reset.json()["initial_password"]},
    )
    assert fresh.status_code == 423
    assert (
        await client.post(
            "/api/v1/auth/mfa/verify",
            json={"mfa_token": fresh.json()["mfa_token"], "code": pyotp.TOTP(secret).now()},
        )
    ).status_code == 200


@pytest.mark.asyncio
async def test_admin_can_reset_another_admin_and_itself(
    client: AsyncClient, db_session: AsyncSession, admin_user: User, member_user: User
) -> None:
    """Trusted admins retain deployment-wide reset authority."""
    member_user.is_admin = True
    member_user.role = "admin"
    await db_session.flush()
    for target in (member_user, admin_user):
        headers = _bearer(admin_user)
        response = await client.post(
            f"/api/v1/admin/users/{target.id}/reset-password", headers=headers
        )
        assert response.status_code == 200, response.text
        assert (await client.get("/api/v1/users/me", headers=_bearer(target))).status_code == 200
        # The current admin's old token is invalid after resetting itself.
        if target is admin_user:
            assert (await client.get("/api/v1/users/me", headers=headers)).status_code == 401


@pytest.mark.asyncio
async def test_concurrent_refresh_cannot_escape_reset(
    test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refresh that matched before reset must recheck revocation after its lock."""
    from app.api.admin import reset_user_password
    from app.api.auth import RefreshRequest, refresh

    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    plaintext, hashed = create_refresh_token()
    now = datetime.now(UTC)
    async with factory() as seed:
        admin = _make_user(email=_new_email(), is_admin=True, role="admin")
        target = _make_user(email=_new_email())
        seed.add_all([admin, target])
        await seed.flush()
        seed.add(
            UserSession(
                user_id=target.id,
                refresh_token_hash=hashed,
                expires_at=now + timedelta(days=7),
                absolute_expires_at=now + timedelta(hours=8),
                last_active_at=now,
            )
        )
        await seed.commit()

    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    task = None
    try:
        async with factory() as reset_db, factory() as refresh_db:
            # Hold the reset's user lock, but leave the old session visible
            # until the refresh has scanned and matched it.
            await reset_db.execute(select(User).where(User.id == target.id).with_for_update())
            waiting = asyncio.Event()
            original_execute = refresh_db.execute

            async def observe_lock(statement, *args, **kwargs):
                if statement._for_update_arg is not None:
                    waiting.set()
                return await original_execute(statement, *args, **kwargs)

            monkeypatch.setattr(refresh_db, "execute", observe_lock)
            task = asyncio.create_task(
                refresh(
                    payload=RefreshRequest(refresh_token=plaintext), request=request, db=refresh_db
                )
            )
            await asyncio.wait_for(waiting.wait(), timeout=5)
            response = await reset_user_password(
                user_id=str(target.id),
                request=request,
                response=Response(),
                admin=admin,
                db=reset_db,
            )
            assert response.sessions_revoked == 1
            with pytest.raises(HTTPException) as caught:
                await asyncio.wait_for(task, timeout=5)
            assert caught.value.status_code == 401
        async with factory() as check:
            live = (
                (
                    await check.execute(
                        select(UserSession).where(
                            UserSession.user_id == target.id, UserSession.revoked_at.is_(None)
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert live == []
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with factory() as cleanup:
            await cleanup.execute(
                delete(AuditLog).where(AuditLog.user_id.in_([admin.id, target.id]))
            )
            await cleanup.execute(delete(User).where(User.id.in_([admin.id, target.id])))
            await cleanup.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["member", "viewer", "auditor"])
async def test_non_admin_roles_cannot_provision_or_reset(
    client: AsyncClient, db_session: AsyncSession, member_user: User, role: str
) -> None:
    member_user.role = role
    await db_session.flush()
    headers = _bearer(member_user)
    assert (
        await client.post("/api/v1/admin/users", json={"email": _new_email()}, headers=headers)
    ).status_code == 403
    assert (
        await client.post(f"/api/v1/admin/users/{member_user.id}/reset-password", headers=headers)
    ).status_code == 403


@pytest.mark.asyncio
async def test_provisioning_and_reset_require_authentication(client: AsyncClient) -> None:
    assert (
        await client.post("/api/v1/admin/users", json={"email": _new_email()})
    ).status_code == 401
    assert (
        await client.post(f"/api/v1/admin/users/{uuid.uuid4()}/reset-password")
    ).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "reset"])
async def test_account_mutation_rolls_back_if_audit_fails(
    test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Credentials and refresh revocation cannot commit without their audit row."""
    from app.api.admin import AdminUserCreateRequest, create_user, reset_user_password

    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    new_email = _new_email()
    now = datetime.now(UTC)
    async with factory() as seed:
        admin = _make_user(email=_new_email(), is_admin=True, role="admin")
        target = _make_user(email=_new_email())
        seed.add_all([admin, target])
        await seed.flush()
        old_hash = target.hashed_password
        session = UserSession(
            user_id=target.id,
            refresh_token_hash=hash_password("old-refresh"),
            expires_at=now + timedelta(days=7),
            absolute_expires_at=now + timedelta(hours=8),
            last_active_at=now,
        )
        seed.add(session)
        await seed.commit()

    async def fail_audit(*args, **kwargs):
        raise RuntimeError("test audit failure")

    monkeypatch.setattr("app.audit.audit_action", fail_audit)
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    try:
        with pytest.raises(RuntimeError, match="test audit failure"):
            async with factory() as db:
                if operation == "create":
                    await create_user(
                        body=AdminUserCreateRequest(email=new_email),
                        request=request,
                        response=Response(),
                        admin=admin,
                        db=db,
                    )
                else:
                    await reset_user_password(
                        user_id=str(target.id),
                        request=request,
                        response=Response(),
                        admin=admin,
                        db=db,
                    )
        async with factory() as check:
            current = await check.get(User, target.id)
            assert current is not None
            assert current.hashed_password == old_hash
            assert current.credential_version == 0
            assert current.must_change_password is False
            current_session = await check.get(UserSession, session.id)
            assert current_session is not None and current_session.revoked_at is None
            assert (
                await check.execute(select(User).where(User.email == new_email))
            ).scalar_one_or_none() is None
    finally:
        async with factory() as cleanup:
            await cleanup.execute(delete(User).where(User.id.in_([admin.id, target.id])))
            await cleanup.commit()
