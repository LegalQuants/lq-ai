"""Integration tests for WS2/PR4b's /api/v1/admin/mcp admin surface.

Covers:

* ``GET /api/v1/admin/mcp`` — lists configured servers + cached tools.
* ``POST /api/v1/admin/mcp/{server}/refresh`` — re-discovers tools; writes
  a ``mcp.tools_refreshed`` audit row.
* ``POST /api/v1/admin/mcp/{oauth-server}/refresh`` — raises
  ``MCPAuthorizationRequired`` (409) for per-user OAuth servers.
* ``PATCH /api/v1/admin/mcp/{server}/tools/{tool}`` — toggles enabled;
  writes a ``mcp.tool_enabled`` audit row; missing tool → 404.
* Non-admin caller → 403 on all three endpoints.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.errors import MCPAuthorizationRequired
from app.main import app
from app.models.audit import AuditLog
from app.models.mcp import MCPToolCache
from app.models.user import User
from app.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


async def _make_user(
    db_session: AsyncSession,
    *,
    email: str,
    is_admin: bool,
) -> tuple[User, str]:
    """Insert a user and return the user + a bearer token."""
    user = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password("test-password-123"),
        is_admin=is_admin,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.commit()
    token = create_access_token(user_id=user.id, email=user.email, is_admin=user.is_admin)
    return user, token


@pytest_asyncio.fixture
async def admin_client(db_session: AsyncSession) -> AsyncIterator[tuple[AsyncClient, str]]:
    _user, token = await _make_user(
        db_session,
        email="admin-mcp@example.com",
        is_admin=True,
    )
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, token
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def member_client(db_session: AsyncSession) -> AsyncIterator[tuple[AsyncClient, str]]:
    _user, token = await _make_user(
        db_session,
        email="member-mcp@example.com",
        is_admin=False,
    )
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, token
    app.dependency_overrides.pop(get_db, None)


def _tool_row(
    *,
    provider: str,
    tool: str,
    enabled: bool = True,
    description: str | None = None,
) -> MCPToolCache:
    return MCPToolCache(
        provider_name=provider,
        tool_name=tool,
        description=description,
        parameters={},
        read_only=False,
        destructive=False,
        requires_confirmation=True,
        enabled=enabled,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/admin/mcp
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_mcp_returns_servers_with_tools(
    admin_client: tuple[AsyncClient, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET returns server list with their cached tools and enabled states."""
    # Seed two cached tools for acme-mcp.
    db_session.add(_tool_row(provider="acme-mcp", tool="read_doc", enabled=True))
    db_session.add(_tool_row(provider="acme-mcp", tool="write_doc", enabled=False))
    await db_session.commit()

    # Mock service.list_servers so no gateway call is needed.
    async def _fake_list_servers(**_: Any) -> list[dict[str, str]]:
        return [{"name": "acme-mcp", "type": "mcp"}]

    monkeypatch.setattr("app.api.admin_mcp.service.list_servers", _fake_list_servers)

    ac, token = admin_client
    res = await ac.get(
        "/api/v1/admin/mcp",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["servers"]) == 1
    srv = body["servers"][0]
    assert srv["name"] == "acme-mcp"
    assert srv["type"] == "mcp"
    tool_names = {t["name"] for t in srv["tools"]}
    assert tool_names == {"read_doc", "write_doc"}
    enabled_map = {t["name"]: t["enabled"] for t in srv["tools"]}
    assert enabled_map["read_doc"] is True
    assert enabled_map["write_doc"] is False


@pytest.mark.integration
async def test_list_mcp_empty_when_no_servers(
    admin_client: tuple[AsyncClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET returns empty servers list when gateway has no MCP providers."""

    async def _fake_list_servers(**_: Any) -> list[dict[str, str]]:
        return []

    monkeypatch.setattr("app.api.admin_mcp.service.list_servers", _fake_list_servers)

    ac, token = admin_client
    res = await ac.get(
        "/api/v1/admin/mcp",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["servers"] == []


# ---------------------------------------------------------------------------
# POST /api/v1/admin/mcp/{server}/refresh
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_refresh_returns_tools_and_writes_audit(
    admin_client: tuple[AsyncClient, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST refresh returns tools and writes a mcp.tools_refreshed audit row."""
    refreshed_tools = [
        {
            "name": "read_doc",
            "description": "reads a doc",
            "parameters": {},
            "read_only": True,
            "destructive": False,
            "requires_confirmation": False,
            "enabled": True,
        }
    ]

    async def _fake_refresh(db: Any, *, provider: str, **_: Any) -> list[dict[str, Any]]:
        return refreshed_tools

    monkeypatch.setattr("app.api.admin_mcp.service.refresh_server", _fake_refresh)

    ac, token = admin_client
    res = await ac.post(
        "/api/v1/admin/mcp/acme-mcp/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["server"] == "acme-mcp"
    assert len(body["tools"]) == 1
    assert body["tools"][0]["name"] == "read_doc"

    # Verify the audit row was written.
    await db_session.rollback()  # sync the session after the handler committed
    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "mcp.tools_refreshed",
                    AuditLog.resource_id == "acme-mcp",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].resource_type == "mcp_server"
    assert audit_rows[0].details["tool_count"] == 1


@pytest.mark.integration
async def test_refresh_oauth_server_returns_409(
    admin_client: tuple[AsyncClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST refresh of an oauth server → 409 MCPAuthorizationRequired (not 500).

    Admin refresh covers none/bearer only; oauth servers are user-scoped.
    The response must not contain any token value.
    """

    async def _raise_auth_required(db: Any, *, provider: str, **_: Any) -> list[dict[str, Any]]:
        raise MCPAuthorizationRequired(
            message=f"MCP server {provider!r} uses per-user OAuth; refresh it via the "
            "user-scoped connect flow, not admin refresh.",
            details={"server": provider},
        )

    monkeypatch.setattr("app.api.admin_mcp.service.refresh_server", _raise_auth_required)

    ac, token = admin_client
    res = await ac.post(
        "/api/v1/admin/mcp/oauth-mcp/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 409, res.text
    body = res.json()
    assert body["detail"]["code"] == "mcp_authorization_required"
    # The response body must not contain any raw token value.
    assert "secret" not in res.text
    # The server name appears in the message but no token bytes.
    assert "oauth-mcp" in body["detail"]["message"]


# ---------------------------------------------------------------------------
# PATCH /api/v1/admin/mcp/{server}/tools/{tool}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_patch_tool_enabled_flips_and_audits(
    admin_client: tuple[AsyncClient, str],
    db_session: AsyncSession,
) -> None:
    """PATCH disables a tool that was enabled, returns updated view, writes audit."""
    db_session.add(_tool_row(provider="acme-mcp", tool="read_doc", enabled=True))
    await db_session.commit()

    ac, token = admin_client
    res = await ac.patch(
        "/api/v1/admin/mcp/acme-mcp/tools/read_doc",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": False},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "read_doc"
    assert body["enabled"] is False

    # Verify DB row was flipped.
    await db_session.rollback()
    row = (
        await db_session.execute(
            select(MCPToolCache).where(
                MCPToolCache.provider_name == "acme-mcp",
                MCPToolCache.tool_name == "read_doc",
            )
        )
    ).scalar_one()
    assert row.enabled is False

    # Verify audit row uses mcp.tool_disabled when enabled=False.
    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "mcp.tool_disabled",
                    AuditLog.resource_id == "acme-mcp/read_doc",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].resource_type == "mcp_tool"
    assert audit_rows[0].details["enabled"] is False


@pytest.mark.integration
async def test_patch_tool_enable_writes_enabled_audit(
    admin_client: tuple[AsyncClient, str],
    db_session: AsyncSession,
) -> None:
    """PATCH enables a tool that was disabled; audit action is mcp.tool_enabled."""
    db_session.add(_tool_row(provider="acme-mcp", tool="write_doc", enabled=False))
    await db_session.commit()

    ac, token = admin_client
    res = await ac.patch(
        "/api/v1/admin/mcp/acme-mcp/tools/write_doc",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": True},
    )
    assert res.status_code == 200, res.text
    assert res.json()["enabled"] is True

    # Verify audit row uses mcp.tool_enabled when enabled=True.
    await db_session.rollback()
    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "mcp.tool_enabled",
                    AuditLog.resource_id == "acme-mcp/write_doc",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].resource_type == "mcp_tool"
    assert audit_rows[0].details["enabled"] is True


@pytest.mark.integration
async def test_patch_tool_missing_returns_404(
    admin_client: tuple[AsyncClient, str],
) -> None:
    """PATCH on a tool not in the discovery cache returns 404."""
    ac, token = admin_client
    res = await ac.patch(
        "/api/v1/admin/mcp/acme-mcp/tools/nonexistent-tool",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": True},
    )
    assert res.status_code == 404, res.text


# ---------------------------------------------------------------------------
# Non-admin → 403
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_non_admin_gets_403_on_list(
    member_client: tuple[AsyncClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_list_servers(**_: Any) -> list[dict[str, str]]:
        return []

    monkeypatch.setattr("app.api.admin_mcp.service.list_servers", _fake_list_servers)

    ac, token = member_client
    res = await ac.get(
        "/api/v1/admin/mcp",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403, res.text


@pytest.mark.integration
async def test_non_admin_gets_403_on_refresh(
    member_client: tuple[AsyncClient, str],
) -> None:
    ac, token = member_client
    res = await ac.post(
        "/api/v1/admin/mcp/acme-mcp/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403, res.text


@pytest.mark.integration
async def test_non_admin_gets_403_on_patch(
    member_client: tuple[AsyncClient, str],
) -> None:
    ac, token = member_client
    res = await ac.patch(
        "/api/v1/admin/mcp/acme-mcp/tools/read_doc",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": False},
    )
    assert res.status_code == 403, res.text
