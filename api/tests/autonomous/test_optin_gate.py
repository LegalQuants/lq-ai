"""Opt-out keeps read+halt; mutate paths 403 (M4-C2 opt-out split).

Verifies the `AutonomousEnabledUser` gate:
- MUTATE endpoints return 403 when `autonomous_enabled == False` (the default).
- READ and halt endpoints stay reachable regardless of opt-in state.
- MUTATE endpoints succeed when the user has opted in.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


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


async def _make_user(
    db: AsyncSession,
    *,
    suffix: str = "",
    autonomous_enabled: bool = False,
) -> User:
    user = User(
        email=f"optin-test-{suffix or uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Opt-in Test User {suffix}".strip(),
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
        autonomous_enabled=autonomous_enabled,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def opted_out_user(db_session: AsyncSession) -> User:
    """User with autonomous_enabled=False (default)."""
    return await _make_user(db_session, suffix="opted-out", autonomous_enabled=False)


@pytest_asyncio.fixture
async def opted_in_user(db_session: AsyncSession) -> User:
    """User with autonomous_enabled=True."""
    return await _make_user(db_session, suffix="opted-in", autonomous_enabled=True)


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Gate: mutate endpoints → 403 when opted out
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_mutate_403_when_opted_out(
    client: AsyncClient,
    opted_out_user: User,
) -> None:
    """default autonomous_enabled=False → POST /schedules returns 403."""
    r = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(opted_out_user),
        json={"cron_expr": "0 9 * * 1", "name": "scan"},
    )
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# No gate: read + halt endpoints stay reachable when opted out
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_read_sessions_reachable_when_opted_out(
    client: AsyncClient,
    opted_out_user: User,
) -> None:
    """GET /sessions returns 200 even when autonomous_enabled=False."""
    r = await client.get(
        "/api/v1/autonomous/sessions",
        headers=_bearer(opted_out_user),
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Gate lifted: mutate allowed when opted in
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_mutate_allowed_when_opted_in(
    client: AsyncClient,
    opted_in_user: User,
) -> None:
    """autonomous_enabled=True → POST /schedules returns 201."""
    r = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(opted_in_user),
        json={"cron_expr": "0 9 * * 1", "name": "scan"},
    )
    assert r.status_code == 201, r.text
