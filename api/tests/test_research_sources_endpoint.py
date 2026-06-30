"""Integration tests for GET /api/v1/research/sources (WS-E PR1a).

Covers:
- 200 with govinfo source in response when gateway has a govinfo provider
- govinfo source has ``enabled=True`` and correct coverage string
- egress_tier resolved from governance admin-config cache (not list_tool_providers)
- Response NEVER contains api_key or cost fields (P3 / ADR 0016)
- Unauthenticated request returns 401
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import set_gateway_client
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.security import create_access_token, hash_password
from app.tools.governance import _reset_provider_tier_cache_for_tests

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"sources-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Sources Test User",
        hashed_password=hash_password("test-password-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _bearer(user: User) -> str:
    return create_access_token(user.id, user.email, is_admin=user.is_admin)


def _h(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {_bearer(user)}"}


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """In-process AsyncClient with the test DB session wired in."""

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def fake_gateway_with_govinfo() -> AsyncMock:
    """Return a mock gateway client whose list_tool_providers returns a govinfo provider.

    Returns {name, type} ONLY — matching the real GatewayClient projection.
    egress_tier is deliberately absent: the real client strips it, and the
    registry must resolve it from the governance admin-config cache instead.
    """
    mock_gw = AsyncMock()
    mock_gw.list_tool_providers.return_value = [
        {"name": "govinfo-prod", "type": "govinfo"},
    ]
    return mock_gw


# ---------------------------------------------------------------------------
# Cache isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_tier_cache() -> None:
    """Reset the process-level governance tier cache around every test.

    resolve_available_sources now calls resolve_provider_tier (from
    app.tools.governance) which reads a process-level cache.  We clear it
    before and after each test to prevent stale tier values leaking between
    tests.
    """
    _reset_provider_tier_cache_for_tests()
    yield  # type: ignore[misc]
    _reset_provider_tier_cache_for_tests()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_sources_unauthenticated_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/research/sources")
    assert resp.status_code == 401


@pytest.mark.integration
async def test_sources_returns_200_with_govinfo_present(
    client: AsyncClient,
    db_user: User,
    fake_gateway_with_govinfo: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _empty_admin_config(*, request_id: str | None = None) -> dict:
        return {"tool_providers": []}

    class _FakeAdminGW:
        get_admin_config = staticmethod(_empty_admin_config)

    monkeypatch.setattr("app.tools.governance.get_gateway_client", lambda: _FakeAdminGW())

    set_gateway_client(fake_gateway_with_govinfo)  # type: ignore[arg-type]
    try:
        resp = await client.get("/api/v1/research/sources", headers=_h(db_user))
    finally:
        set_gateway_client(None)

    assert resp.status_code == 200
    body = resp.json()
    assert "sources" in body

    by_type = {s["type"]: s for s in body["sources"]}
    assert "govinfo" in by_type, f"govinfo missing from sources: {body}"

    govinfo = by_type["govinfo"]
    assert govinfo["enabled"] is True
    assert govinfo["name"] == "govinfo-prod"
    assert "U.S. Code" in govinfo["coverage"] or "CFR" in govinfo["coverage"] or govinfo["coverage"]


@pytest.mark.integration
async def test_sources_response_never_contains_secrets(
    client: AsyncClient,
    db_user: User,
    fake_gateway_with_govinfo: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P3 / ADR 0016: api_key and cost must NEVER appear in the response body."""

    async def _empty_admin_config(*, request_id: str | None = None) -> dict:
        return {"tool_providers": []}

    class _FakeAdminGW:
        get_admin_config = staticmethod(_empty_admin_config)

    monkeypatch.setattr("app.tools.governance.get_gateway_client", lambda: _FakeAdminGW())

    set_gateway_client(fake_gateway_with_govinfo)  # type: ignore[arg-type]
    try:
        resp = await client.get("/api/v1/research/sources", headers=_h(db_user))
    finally:
        set_gateway_client(None)

    assert resp.status_code == 200
    raw_text = resp.text
    assert "api_key" not in raw_text, "api_key must not appear in the response"
    assert "cost" not in raw_text, "cost must not appear in the response"

    # Also check each source object explicitly
    for source in resp.json().get("sources", []):
        assert "api_key" not in source, f"api_key in source {source['type']}"
        assert "cost" not in source, f"cost in source {source['type']}"


@pytest.mark.integration
async def test_sources_egress_tier_resolved_from_admin_config(
    client: AsyncClient,
    db_user: User,
    fake_gateway_with_govinfo: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """egress_tier on /sources comes from the governance admin-config cache.

    The list_tool_providers payload carries only {name, type} in production
    (the real GatewayClient strips everything else).  resolve_available_sources
    must call resolve_provider_tier from the governance module to get the real
    tier, not read a key that is never there.
    """

    async def _admin_config_with_tier(*, request_id: str | None = None) -> dict:
        return {
            "tool_providers": [
                {"name": "govinfo-prod", "type": "govinfo", "egress_tier": 4},
            ]
        }

    class _FakeAdminGW:
        get_admin_config = staticmethod(_admin_config_with_tier)

    monkeypatch.setattr("app.tools.governance.get_gateway_client", lambda: _FakeAdminGW())

    set_gateway_client(fake_gateway_with_govinfo)  # type: ignore[arg-type]
    try:
        resp = await client.get("/api/v1/research/sources", headers=_h(db_user))
    finally:
        set_gateway_client(None)

    assert resp.status_code == 200
    by_type = {s["type"]: s for s in resp.json()["sources"]}
    assert "govinfo" in by_type, f"govinfo missing: {resp.json()}"
    assert by_type["govinfo"]["egress_tier"] == 4, (
        "egress_tier must be resolved from the admin-config governance cache, "
        f"got: {by_type['govinfo'].get('egress_tier')!r}"
    )
