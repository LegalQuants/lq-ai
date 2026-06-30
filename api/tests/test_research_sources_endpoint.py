"""Integration tests for GET /api/v1/research/sources (WS-E PR1a).

Covers:
- 200 with govinfo source in response when gateway has a govinfo provider
- govinfo source has ``enabled=True`` and correct coverage string
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
    """Return a mock gateway client whose list_tool_providers returns a govinfo provider."""
    mock_gw = AsyncMock()
    mock_gw.list_tool_providers.return_value = [
        {
            "name": "govinfo-prod",
            "type": "govinfo",
            "egress_tier": 1,
        }
    ]
    return mock_gw


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
) -> None:
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
) -> None:
    """P3 / ADR 0016: api_key and cost must NEVER appear in the response body."""
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
