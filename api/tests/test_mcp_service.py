import uuid

import httpx
import pytest
import respx
from sqlalchemy import select

from app.errors import MCPAuthorizationRequired, NotFound
from app.mcp import service
from app.models.mcp import MCPToolCache

GW = "http://localhost:8001"  # settings.lq_ai_gateway_url default

# ---------------------------------------------------------------------------
# Gateway-client fake helpers
# ---------------------------------------------------------------------------

_OAUTH_CONFIG_PATH = "/admin/v1/config"

# A minimal gateway admin config response that includes one oauth MCP provider.
_GW_CONFIG_WITH_OAUTH = {
    "tool_providers": [
        {
            "name": "oauth-mcp",
            "type": "mcp",
            "auth": "oauth",
            "base_url": "https://mcp.example.com",
            "oauth_client_id": "client-xyz",
        }
    ]
}

# A config with no OAuth providers (none/bearer only).
_GW_CONFIG_NO_OAUTH = {
    "tool_providers": [
        {
            "name": "acme-mcp",
            "type": "mcp",
            "auth": "none",
            "base_url": "https://acme.example.com",
        }
    ]
}


def _tools_payload(provider, names):
    return {
        "provider": provider,
        "tools": [
            {
                "name": n,
                "description": f"{n} desc",
                "parameters": {"type": "object"},
                "read_only": False,
                "destructive": False,
                "requires_confirmation": True,
            }
            for n in names
        ],
    }


# ---------------------------------------------------------------------------
# OAuth-aware refresh_server tests (Task 6)
# ---------------------------------------------------------------------------


def _make_fake_gateway(*, oauth_names: list[str], tools_payload: dict | None = None):
    """Build a minimal fake gateway client for service-layer tests.

    ``oauth_names`` — list of provider names that appear in the oauth config.
    ``tools_payload`` — response to ``discover_tools``; defaults to empty tools.
    """
    oauth_cfg = [
        {"name": n, "server_url": "https://example.com", "oauth_client_id": "cid"}
        for n in oauth_names
    ]
    payload = tools_payload or {"provider": "p", "tools": []}

    async def fake_list_mcp_oauth_config(*, request_id=None):
        return oauth_cfg

    async def fake_discover_tools(provider, *, user_token=None, request_id=None):
        # Stash the token for assertion.
        fake_discover_tools.last_user_token = user_token  # type: ignore[attr-defined]
        return payload

    fake_discover_tools.last_user_token = None  # type: ignore[attr-defined]

    class FakeGW:
        list_mcp_oauth_config = staticmethod(fake_list_mcp_oauth_config)
        discover_tools = staticmethod(fake_discover_tools)

    return FakeGW(), fake_discover_tools


@pytest.mark.asyncio
async def test_refresh_oauth_server_with_valid_token_passes_token(db_session, monkeypatch) -> None:
    """oauth server + get_valid_token returns a token → discover_tools called with it."""
    fake_gw, fake_discover = _make_fake_gateway(
        oauth_names=["oauth-mcp"],
        tools_payload={"provider": "oauth-mcp", "tools": []},
    )
    monkeypatch.setattr("app.mcp.service.get_gateway_client", lambda: fake_gw)

    uid = uuid.uuid4()

    async def _fake_get_valid_token(db, *, user_id, server):
        return "secret-token"

    monkeypatch.setattr("app.mcp.service.oauth.get_valid_token", _fake_get_valid_token)

    await service.refresh_server(db_session, provider="oauth-mcp", user_id=uid)
    assert fake_discover.last_user_token == "secret-token"


@pytest.mark.asyncio
async def test_refresh_oauth_server_get_valid_token_none_raises(db_session, monkeypatch) -> None:
    """oauth server + get_valid_token returns None → MCPAuthorizationRequired."""
    fake_gw, _fake_discover = _make_fake_gateway(oauth_names=["oauth-mcp"])
    monkeypatch.setattr("app.mcp.service.get_gateway_client", lambda: fake_gw)

    uid = uuid.uuid4()

    async def _fake_get_valid_token_none(db, *, user_id, server):
        return None

    monkeypatch.setattr("app.mcp.service.oauth.get_valid_token", _fake_get_valid_token_none)

    with pytest.raises(MCPAuthorizationRequired) as exc_info:
        await service.refresh_server(db_session, provider="oauth-mcp", user_id=uid)

    err = exc_info.value
    assert "oauth-mcp" in err.message
    # Must not contain any token value.
    assert "secret" not in err.message
    assert err.details.get("server") == "oauth-mcp"
    assert err.effective_http_status == 409


@pytest.mark.asyncio
async def test_refresh_oauth_server_no_user_id_raises(db_session, monkeypatch) -> None:
    """oauth server + user_id=None (admin path) → MCPAuthorizationRequired."""
    fake_gw, _fake_discover = _make_fake_gateway(oauth_names=["oauth-mcp"])
    monkeypatch.setattr("app.mcp.service.get_gateway_client", lambda: fake_gw)

    with pytest.raises(MCPAuthorizationRequired) as exc_info:
        await service.refresh_server(db_session, provider="oauth-mcp", user_id=None)

    err = exc_info.value
    assert "oauth-mcp" in err.message
    assert err.details.get("server") == "oauth-mcp"
    assert err.effective_http_status == 409


@pytest.mark.asyncio
async def test_refresh_none_bearer_server_passes_no_token(db_session, monkeypatch) -> None:
    """none/bearer server → discover_tools called with user_token=None (unchanged path)."""
    fake_gw, fake_discover = _make_fake_gateway(
        oauth_names=[],  # acme-mcp is NOT in oauth list
        tools_payload={"provider": "acme-mcp", "tools": []},
    )
    monkeypatch.setattr("app.mcp.service.get_gateway_client", lambda: fake_gw)

    await service.refresh_server(db_session, provider="acme-mcp")
    assert fake_discover.last_user_token is None


# ---------------------------------------------------------------------------
# Original tests (unchanged, except that we patch list_mcp_oauth_config in the
# respx-based tests so they still pass without a gateway /admin/v1/config route)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_servers_filters_mcp(monkeypatch) -> None:
    async def fake_list(*, request_id=None):
        return [{"name": "acme-mcp", "type": "mcp"}, {"name": "cl", "type": "courtlistener"}]

    monkeypatch.setattr(
        "app.mcp.service.get_gateway_client",
        lambda: type("C", (), {"list_tool_providers": staticmethod(fake_list)})(),
    )
    servers = await service.list_servers()
    assert [s["name"] for s in servers] == ["acme-mcp"]


@pytest.mark.asyncio
async def test_refresh_upserts_and_preserves_enabled(db_session) -> None:
    # seed a disabled tool that will survive refresh + a stale tool that won't
    db_session.add(
        MCPToolCache(
            provider_name="acme-mcp",
            tool_name="read_doc",
            parameters={},
            enabled=False,
            requires_confirmation=True,
        )
    )
    db_session.add(
        MCPToolCache(
            provider_name="acme-mcp",
            tool_name="gone",
            parameters={},
            enabled=True,
            requires_confirmation=True,
        )
    )
    await db_session.commit()
    with respx.mock(base_url=GW) as mock:
        # list_mcp_oauth_config calls GET /admin/v1/config — no oauth providers here.
        mock.get("/admin/v1/config").mock(
            return_value=httpx.Response(200, json=_GW_CONFIG_NO_OAUTH)
        )
        mock.get("/v1/tools/acme-mcp").mock(
            return_value=httpx.Response(
                200, json=_tools_payload("acme-mcp", ["read_doc", "new_tool"])
            )
        )
        tools = await service.refresh_server(db_session, provider="acme-mcp")
    await db_session.commit()
    rows = {
        r.tool_name: r
        for r in (
            await db_session.execute(
                select(MCPToolCache).where(MCPToolCache.provider_name == "acme-mcp")
            )
        ).scalars()
    }
    assert set(rows) == {"read_doc", "new_tool"}  # stale "gone" deleted
    assert rows["read_doc"].enabled is False  # preserved
    assert rows["new_tool"].enabled is True  # new defaults enabled
    assert {t["name"] for t in tools} == {"read_doc", "new_tool"}


@pytest.mark.asyncio
async def test_set_tool_enabled_toggles(db_session) -> None:
    db_session.add(
        MCPToolCache(
            provider_name="acme-mcp",
            tool_name="read_doc",
            parameters={},
            enabled=True,
            requires_confirmation=True,
        )
    )
    await db_session.commit()
    await service.set_tool_enabled(db_session, provider="acme-mcp", tool="read_doc", enabled=False)
    await db_session.commit()
    row = (
        await db_session.execute(select(MCPToolCache).where(MCPToolCache.tool_name == "read_doc"))
    ).scalar_one()
    assert row.enabled is False


@pytest.mark.asyncio
async def test_set_tool_enabled_missing_raises(db_session) -> None:
    with pytest.raises(NotFound):
        await service.set_tool_enabled(db_session, provider="x", tool="y", enabled=True)


@pytest.mark.asyncio
async def test_set_tool_enabled_is_provider_scoped(db_session) -> None:
    """provider_name filter in set_tool_enabled is load-bearing: toggling a tool
    on one provider must not affect a same-named tool on a different provider."""
    db_session.add(
        MCPToolCache(
            provider_name="acme-mcp",
            tool_name="read_doc",
            parameters={},
            enabled=True,
            requires_confirmation=True,
        )
    )
    db_session.add(
        MCPToolCache(
            provider_name="other-mcp",
            tool_name="read_doc",
            parameters={},
            enabled=True,
            requires_confirmation=True,
        )
    )
    await db_session.commit()

    await service.set_tool_enabled(db_session, provider="acme-mcp", tool="read_doc", enabled=False)
    await db_session.commit()

    acme_row = (
        await db_session.execute(
            select(MCPToolCache).where(
                MCPToolCache.provider_name == "acme-mcp",
                MCPToolCache.tool_name == "read_doc",
            )
        )
    ).scalar_one()
    other_row = (
        await db_session.execute(
            select(MCPToolCache).where(
                MCPToolCache.provider_name == "other-mcp",
                MCPToolCache.tool_name == "read_doc",
            )
        )
    ).scalar_one()

    assert acme_row.enabled is False, "acme-mcp/read_doc should be disabled"
    assert other_row.enabled is True, "other-mcp/read_doc must not be affected"


@pytest.mark.asyncio
async def test_refresh_is_provider_scoped(db_session) -> None:
    """refresh_server(provider="acme-mcp") with a narrower tool list must not
    delete cached rows belonging to a different provider."""
    db_session.add(
        MCPToolCache(
            provider_name="acme-mcp",
            tool_name="read_doc",
            parameters={},
            enabled=True,
            requires_confirmation=True,
        )
    )
    db_session.add(
        MCPToolCache(
            provider_name="other-mcp",
            tool_name="read_doc",
            parameters={},
            enabled=True,
            requires_confirmation=True,
        )
    )
    await db_session.commit()

    # acme-mcp now returns zero tools — all its cached rows should be deleted
    with respx.mock(base_url=GW) as mock:
        # list_mcp_oauth_config calls GET /admin/v1/config — no oauth providers here.
        mock.get("/admin/v1/config").mock(
            return_value=httpx.Response(200, json=_GW_CONFIG_NO_OAUTH)
        )
        mock.get("/v1/tools/acme-mcp").mock(
            return_value=httpx.Response(200, json=_tools_payload("acme-mcp", []))
        )
        await service.refresh_server(db_session, provider="acme-mcp")
    await db_session.commit()

    acme_rows = (
        (
            await db_session.execute(
                select(MCPToolCache).where(MCPToolCache.provider_name == "acme-mcp")
            )
        )
        .scalars()
        .all()
    )
    other_row = (
        await db_session.execute(
            select(MCPToolCache).where(
                MCPToolCache.provider_name == "other-mcp",
                MCPToolCache.tool_name == "read_doc",
            )
        )
    ).scalar_one()

    assert acme_rows == [], "acme-mcp's stale rows should have been deleted"
    assert other_row.enabled is True, "other-mcp/read_doc must survive acme-mcp refresh"
