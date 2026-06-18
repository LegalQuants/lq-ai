import httpx
import pytest
import respx
from sqlalchemy import select

from app.errors import NotFound
from app.mcp import service
from app.models.mcp import MCPToolCache

GW = "http://localhost:8001"  # settings.lq_ai_gateway_url default


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
