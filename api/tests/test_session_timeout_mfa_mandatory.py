"""Integration tests for M-Sec.1 — session timeouts + MFA-mandatory flag.

Covers:

* `_create_session` stamps ``absolute_expires_at`` from
  ``settings.session_absolute_timeout_seconds`` on fresh login.
* `/auth/refresh` 401s when ``now > absolute_expires_at``.
* `/auth/refresh` 401s when the idle window has elapsed since
  ``last_active_at``.
* `/auth/refresh` rotates ``last_active_at`` forward AND preserves
  ``absolute_expires_at`` across rotation (the original-login clock).
* When ``LQ_AI_MFA_MANDATORY=true`` and the user has not enrolled,
  ``get_active_user`` raises 403 with ``code='mfa_enrollment_required'``,
  while ``CurrentUser``-gated endpoints (``/users/me``, MFA setup) still
  work so the user can complete enrollment.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta

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
        email=f"sec-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Sec Test",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


# --- session-timeout columns are stamped on fresh login ---------------------


@pytest.mark.integration
async def test_login_stamps_absolute_and_idle_columns(
    client: AsyncClient, seed_user: User, db_session: AsyncSession
) -> None:
    """Fresh login creates a session row with both timeout clocks set."""

    settings = get_settings()
    before = datetime.now(tz=UTC)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": seed_user.email, "password": "correct-horse-battery-staple"},
    )
    assert resp.status_code == 200
    after = datetime.now(tz=UTC)

    result = await db_session.execute(
        select(UserSession).where(UserSession.user_id == seed_user.id)
    )
    sessions = result.scalars().all()
    assert len(sessions) == 1
    session = sessions[0]

    # absolute_expires_at = now + 8h (default). Allow a few seconds of slack.
    expected_absolute = before + timedelta(seconds=settings.session_absolute_timeout_seconds)
    expected_absolute_after = after + timedelta(seconds=settings.session_absolute_timeout_seconds)
    assert expected_absolute - timedelta(seconds=2) <= session.absolute_expires_at
    assert session.absolute_expires_at <= expected_absolute_after + timedelta(seconds=2)

    # last_active_at is "now" at insert.
    assert before - timedelta(seconds=2) <= session.last_active_at <= after + timedelta(seconds=2)


# --- absolute-timeout enforcement at /auth/refresh --------------------------


@pytest.mark.integration
async def test_refresh_rejects_when_absolute_timeout_exceeded(
    client: AsyncClient, seed_user: User, db_session: AsyncSession
) -> None:
    """A session past its ``absolute_expires_at`` cannot be refreshed."""

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": seed_user.email, "password": "correct-horse-battery-staple"},
    )
    refresh_token = login.json()["refresh_token"]

    # Backdate the session's absolute clock so the refresh sees it expired.
    result = await db_session.execute(
        select(UserSession).where(UserSession.user_id == seed_user.id)
    )
    session = result.scalars().first()
    assert session is not None
    session.absolute_expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
    await db_session.flush()

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 401
    assert "absolute timeout" in resp.json()["detail"].lower()


# --- idle-timeout enforcement at /auth/refresh ------------------------------


@pytest.mark.integration
async def test_refresh_rejects_when_idle_timeout_exceeded(
    client: AsyncClient, seed_user: User, db_session: AsyncSession
) -> None:
    """A session idle beyond ``session_idle_timeout_seconds`` cannot be refreshed."""

    settings = get_settings()
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": seed_user.email, "password": "correct-horse-battery-staple"},
    )
    refresh_token = login.json()["refresh_token"]

    # Backdate last_active_at past the idle window.
    result = await db_session.execute(
        select(UserSession).where(UserSession.user_id == seed_user.id)
    )
    session = result.scalars().first()
    assert session is not None
    session.last_active_at = datetime.now(tz=UTC) - timedelta(
        seconds=settings.session_idle_timeout_seconds + 60
    )
    await db_session.flush()

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 401
    assert "idle" in resp.json()["detail"].lower()


# --- refresh preserves absolute_expires_at, rotates last_active_at ----------


@pytest.mark.integration
async def test_refresh_preserves_absolute_expires_at_across_rotation(
    client: AsyncClient, seed_user: User, db_session: AsyncSession
) -> None:
    """The original-login absolute clock is copied forward, not reset."""

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": seed_user.email, "password": "correct-horse-battery-staple"},
    )
    refresh_token = login.json()["refresh_token"]

    # Capture the original absolute clock.
    result = await db_session.execute(
        select(UserSession).where(UserSession.user_id == seed_user.id)
    )
    original = result.scalars().first()
    assert original is not None
    original_absolute = original.absolute_expires_at

    # Rotate. The new session should have the SAME absolute_expires_at.
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200

    result = await db_session.execute(
        select(UserSession)
        .where(UserSession.user_id == seed_user.id, UserSession.revoked_at.is_(None))
        .order_by(UserSession.created_at.desc())
    )
    new = result.scalars().first()
    assert new is not None
    assert new.absolute_expires_at == original_absolute, (
        "absolute_expires_at must be preserved across rotation"
    )
    # last_active_at on the new session is fresh (>= when we called refresh).
    assert new.last_active_at >= original.last_active_at


# --- MFA-mandatory deployment flag ------------------------------------------


@pytest.mark.integration
async def test_mfa_mandatory_blocks_active_user_endpoints(
    client: AsyncClient, seed_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ``mfa_mandatory=true`` and the user lacks MFA, the gate fires."""

    # Flip the deployment flag on the cached settings instance. The
    # dependency reads ``settings.mfa_mandatory`` at request time so a
    # monkeypatch on the cached object propagates without restart.
    settings = get_settings()
    monkeypatch.setattr(settings, "mfa_mandatory", True)

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": seed_user.email, "password": "correct-horse-battery-staple"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    # An ``ActiveUser``-gated endpoint is blocked.
    resp = await client.get(
        "/api/v1/users/me/preferences",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    body = resp.json()
    # The error envelope uses {"detail": {"code": ..., "message": ...}}
    # because LQAIError renders through the canonical exception handler.
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else body.get("error", {})
    if isinstance(detail, dict):
        assert detail.get("code") == "mfa_enrollment_required"
    else:
        # Some endpoints surface as {"error": {...}} envelope.
        assert body.get("error", {}).get("code") == "mfa_enrollment_required"


@pytest.mark.integration
async def test_mfa_mandatory_allows_users_me(
    client: AsyncClient, seed_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``GET /users/me`` is on the enrollment-whitelist (uses ``CurrentUser``)."""

    settings = get_settings()
    monkeypatch.setattr(settings, "mfa_mandatory", True)

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": seed_user.email, "password": "correct-horse-battery-staple"},
    )
    token = login.json()["access_token"]

    resp = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == seed_user.email


@pytest.mark.integration
async def test_mfa_mandatory_off_does_not_block(
    client: AsyncClient, seed_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``mfa_mandatory=false`` (default), the gate is dormant."""

    settings = get_settings()
    monkeypatch.setattr(settings, "mfa_mandatory", False)

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": seed_user.email, "password": "correct-horse-battery-staple"},
    )
    token = login.json()["access_token"]

    resp = await client.get(
        "/api/v1/users/me/preferences",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Default ActiveUser-gated endpoint is reachable.
    assert resp.status_code == 200
