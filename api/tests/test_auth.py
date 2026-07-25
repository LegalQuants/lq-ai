"""Integration tests for the B1 auth endpoints.

Covers the verification step from M1-IMPLEMENTATION-ORDER.md Task B1:

    Integration test creates a user, logs in, fetches /api/v1/users/me with
    the bearer token, refreshes, logs out.

Plus the surrounding 401/423 and rotation/revocation paths.

Test database lifecycle is the SAVEPOINT-based fixture from conftest.py
(A2). Each test runs against the fresh per-run DB inside a SAVEPOINT that
is rolled back on teardown — so the integration tests share one Alembic
upgrade and stay isolated from each other.

The FastAPI app is exercised via httpx.AsyncClient + ASGITransport per
CONTRIBUTING.md. We override `get_db` and the `oauth2_scheme` dependency
to wire the test session into the in-process app without spinning up
uvicorn or routing through the real connection pool.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.user import User, UserSession
from app.security import hash_password


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    """Build a FastAPI dependency override that yields the test session.

    The session has a SAVEPOINT-based join to an outer connection-level
    transaction (per conftest.py). We must NOT close it here, and we
    must NOT call commit-that-closes — the per-test fixture owns the
    lifecycle. The handler is wrapped to swallow `session.commit()` so
    the SAVEPOINT pattern keeps working without us patching every
    handler.
    """

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Async HTTP client wired to the in-process app, sharing the test session.

    Override `get_db` so handlers see the same session the test is
    asserting against. We do not override the dependency module's
    `oauth2_scheme` — the real one runs and parses the Authorization
    header, exactly as in production.
    """
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def seed_user(db_session: AsyncSession) -> User:
    """Insert a baseline user with a known password and return the row."""
    user = User(
        email=f"user-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def seed_mfa_user(db_session: AsyncSession) -> User:
    """A user with mfa_enabled=true, used to exercise the 423 branch."""
    user = User(
        email=f"mfa-{uuid.uuid4().hex[:8]}@example.com",
        display_name="MFA User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


# ---------------------------------------------------------------------------
# /auth/login
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_login_success_returns_tokens_and_user(client: AsyncClient, seed_user: User) -> None:
    """Successful login returns access + refresh tokens and the User payload."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": seed_user.email, "password": "correct-horse-battery-staple"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == get_settings().jwt_access_token_ttl_seconds
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["email"] == seed_user.email
    assert body["user"]["id"] == str(seed_user.id)
    assert body["user"]["is_admin"] is False
    assert body["user"]["mfa_enabled"] is False


@pytest.mark.integration
async def test_login_wrong_password_returns_401(client: AsyncClient, seed_user: User) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": seed_user.email, "password": "totally-wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.integration
async def test_login_unknown_email_returns_401(client: AsyncClient) -> None:
    """Unknown email also returns 401 — no user-existence disclosure."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "anything"},
    )
    assert resp.status_code == 401


@pytest.mark.integration
async def test_login_email_is_case_insensitive(client: AsyncClient, seed_user: User) -> None:
    """`users.email` is CITEXT — login works regardless of case."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": seed_user.email.upper(),
            "password": "correct-horse-battery-staple",
        },
    )
    assert resp.status_code == 200


@pytest.mark.integration
async def test_login_with_mfa_enabled_returns_423_with_mfa_token(
    client: AsyncClient, seed_mfa_user: User
) -> None:
    """User with mfa_enabled=true: 423 + MFA challenge, no tokens issued yet."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": seed_mfa_user.email, "password": "correct-horse-battery-staple"},
    )
    assert resp.status_code == 423
    body = resp.json()
    assert body["mfa_token"]
    assert "totp" in body["methods"]
    # No access_token/refresh_token should be in the body — the user has not
    # completed authentication.
    assert "access_token" not in body
    assert "refresh_token" not in body


@pytest.mark.integration
async def test_login_creates_session_row(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    """A successful login inserts exactly one active session row."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": seed_user.email, "password": "correct-horse-battery-staple"},
    )
    assert resp.status_code == 200

    sessions = (
        (await db_session.execute(select(UserSession).where(UserSession.user_id == seed_user.id)))
        .scalars()
        .all()
    )
    assert len(sessions) == 1
    s = sessions[0]
    assert s.revoked_at is None
    assert s.expires_at > datetime.now(tz=UTC)
    # The plaintext refresh token from the response is NOT what's stored.
    assert s.refresh_token_hash != resp.json()["refresh_token"]


@pytest.mark.integration
async def test_login_updates_last_login_at(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    """`last_login_at` is set to (approximately) now after a successful login."""
    assert seed_user.last_login_at is None
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": seed_user.email, "password": "correct-horse-battery-staple"},
    )
    assert resp.status_code == 200
    await db_session.refresh(seed_user)
    assert seed_user.last_login_at is not None


# ---------------------------------------------------------------------------
# /users/me
# ---------------------------------------------------------------------------


async def _login(client: AsyncClient, user: User) -> dict:
    """Convenience helper — log in `user` and return the token bundle."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "correct-horse-battery-staple"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.integration
async def test_users_me_with_valid_token_returns_profile(
    client: AsyncClient, seed_user: User
) -> None:
    tokens = await _login(client, seed_user)
    resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(seed_user.id)
    assert body["email"] == seed_user.email
    assert body["mfa_enabled"] is False


@pytest.mark.integration
async def test_users_me_without_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401


@pytest.mark.integration
async def test_users_me_with_garbage_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer this-is-not-a-jwt"},
    )
    assert resp.status_code == 401


@pytest.mark.integration
async def test_users_me_with_expired_token_returns_401(
    client: AsyncClient, seed_user: User
) -> None:
    """Hand-craft an expired JWT for `seed_user` and verify it's rejected."""
    settings = get_settings()
    now = datetime.now(tz=UTC)
    payload = {
        "sub": str(seed_user.id),
        "email": seed_user.email,
        "is_admin": False,
        "iat": int((now - timedelta(hours=2)).timestamp()),
        "exp": int((now - timedelta(hours=1)).timestamp()),  # expired 1h ago
        "typ": "access",
    }
    token = pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


@pytest.mark.integration
async def test_users_me_with_wrong_signature_returns_401(
    client: AsyncClient, seed_user: User
) -> None:
    """A JWT signed with the wrong secret is rejected."""
    now = datetime.now(tz=UTC)
    payload = {
        "sub": str(seed_user.id),
        "email": seed_user.email,
        "is_admin": False,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
        "typ": "access",
    }
    token = pyjwt.encode(payload, "not-the-real-secret", algorithm="HS256")
    resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


@pytest.mark.integration
async def test_users_me_for_soft_deleted_user_returns_401(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    """A user with `deleted_at` set is treated as nonexistent for auth."""
    tokens = await _login(client, seed_user)
    seed_user.deleted_at = datetime.now(tz=UTC)
    await db_session.flush()

    resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /auth/refresh
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_refresh_with_valid_token_rotates_session(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    """Refresh issues new tokens AND revokes the old session row."""
    tokens = await _login(client, seed_user)
    old_refresh = tokens["refresh_token"]

    # Brief pause so revoked_at is observably after created_at.
    time.sleep(0.01)

    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["refresh_token"] != old_refresh
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == get_settings().jwt_access_token_ttl_seconds

    # Two session rows should now exist for this user — the old one revoked,
    # the new one active.
    sessions = (
        (await db_session.execute(select(UserSession).where(UserSession.user_id == seed_user.id)))
        .scalars()
        .all()
    )
    assert len(sessions) == 2
    revoked = [s for s in sessions if s.revoked_at is not None]
    active = [s for s in sessions if s.revoked_at is None]
    assert len(revoked) == 1
    assert len(active) == 1


@pytest.mark.integration
async def test_refresh_with_garbage_token_returns_401(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "this-token-was-never-issued"},
    )
    assert resp.status_code == 401


@pytest.mark.integration
async def test_refresh_with_revoked_session_returns_401(
    client: AsyncClient, seed_user: User
) -> None:
    """After rotating, the OLD refresh token must not be usable again."""
    tokens = await _login(client, seed_user)
    old_refresh = tokens["refresh_token"]

    # First refresh succeeds and revokes the original session.
    first = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
    )
    assert first.status_code == 200

    # Second use of the original (now-revoked) token must fail.
    second = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
    )
    assert second.status_code == 401


@pytest.mark.integration
async def test_refresh_with_expired_session_returns_401(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    """A session past `expires_at` is rejected even if not revoked."""
    tokens = await _login(client, seed_user)
    old_refresh = tokens["refresh_token"]

    # Backdate the session's expiry.
    sessions = (
        (await db_session.execute(select(UserSession).where(UserSession.user_id == seed_user.id)))
        .scalars()
        .all()
    )
    assert len(sessions) == 1
    sessions[0].expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
    await db_session.flush()

    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /auth/logout
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_logout_revokes_all_active_sessions(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    """Logout revokes every active session for the calling user."""
    # Two logins → two active sessions.
    t1 = await _login(client, seed_user)
    t2 = await _login(client, seed_user)
    assert t1["refresh_token"] != t2["refresh_token"]

    sessions = (
        (await db_session.execute(select(UserSession).where(UserSession.user_id == seed_user.id)))
        .scalars()
        .all()
    )
    assert len(sessions) == 2
    assert all(s.revoked_at is None for s in sessions)

    # Logout with the second access token.
    resp = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {t2['access_token']}"},
    )
    assert resp.status_code == 204

    # Both sessions are now revoked.
    for s in sessions:
        await db_session.refresh(s)
    assert all(s.revoked_at is not None for s in sessions)


@pytest.mark.integration
async def test_logout_without_token_returns_401(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Full round-trip — the verification described in M1-IMPLEMENTATION-ORDER.md
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_full_round_trip(client: AsyncClient, seed_user: User) -> None:
    """Login → /users/me → refresh → /users/me with new token → logout → expired refresh."""
    # 1) Login
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": seed_user.email, "password": "correct-horse-battery-staple"},
    )
    assert login_resp.status_code == 200
    tokens = login_resp.json()

    # 2) /users/me with the access token
    me_resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == seed_user.email

    # 3) Refresh. Sleep briefly so the rotated JWT's `iat` falls in a
    # different POSIX second than the original — otherwise the two tokens
    # are byte-identical (same sub/email/is_admin/iat/exp) and equality
    # checks below are meaningless. The refresh token, however, is
    # always fresh randomness regardless of timing.
    time.sleep(1.05)
    refresh_resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh_resp.status_code == 200
    rotated = refresh_resp.json()
    assert rotated["access_token"] != tokens["access_token"]
    assert rotated["refresh_token"] != tokens["refresh_token"]

    # 4) /users/me with the rotated access token
    me2_resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {rotated['access_token']}"},
    )
    assert me2_resp.status_code == 200

    # 5) Logout (revokes all active sessions)
    logout_resp = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {rotated['access_token']}"},
    )
    assert logout_resp.status_code == 204

    # 6) The original (already-rotated, already-revoked) refresh fails.
    fail_resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert fail_resp.status_code == 401

    # 7) The rotated refresh token also fails — logout revoked everything.
    fail2_resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": rotated["refresh_token"]},
    )
    assert fail2_resp.status_code == 401
