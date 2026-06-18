"""MCP registry + discovery-cache orchestration (WS2/PR4b).

Servers come from gateway config (type==mcp); tools are discovered through the
gateway (PR4a) and cached in ``mcp_tools`` with an operator ``enabled`` toggle.
The api never speaks MCP directly (ADR 0014)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import get_gateway_client
from app.errors import NotFound
from app.models.mcp import MCPToolCache

_MCP_TYPE = "mcp"


async def list_servers(*, request_id: str | None = None) -> list[dict[str, str]]:
    """Configured MCP servers, from gateway config (name + type)."""
    providers = await get_gateway_client().list_tool_providers(request_id=request_id)
    return [p for p in providers if p.get("type") == _MCP_TYPE]


def _tool_dict(row: MCPToolCache) -> dict[str, Any]:
    return {
        "name": row.tool_name,
        "description": row.description,
        "parameters": row.parameters,
        "read_only": row.read_only,
        "destructive": row.destructive,
        "requires_confirmation": row.requires_confirmation,
        "enabled": row.enabled,
    }


async def list_cached_tools(db: AsyncSession, *, provider: str) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(MCPToolCache)
            .where(MCPToolCache.provider_name == provider)
            .order_by(MCPToolCache.tool_name)
        )
    ).scalars()
    return [_tool_dict(r) for r in rows]


async def refresh_server(
    db: AsyncSession,
    *,
    provider: str,
    user_token: str | None = None,
    request_id: str | None = None,
) -> list[dict[str, Any]]:
    """Re-discover ``provider``'s tools through the gateway and reconcile the
    cache: upsert returned tools (preserving each surviving tool's ``enabled``),
    delete cached tools the server no longer returns."""
    result = await get_gateway_client().discover_tools(
        provider, user_token=user_token, request_id=request_id
    )
    discovered = result.get("tools", [])
    existing = {
        r.tool_name: r
        for r in (
            await db.execute(select(MCPToolCache).where(MCPToolCache.provider_name == provider))
        ).scalars()
    }
    seen: set[str] = set()
    for tool in discovered:
        name = tool["name"]
        seen.add(name)
        row = existing.get(name)
        if row is None:
            db.add(
                MCPToolCache(
                    provider_name=provider,
                    tool_name=name,
                    description=tool.get("description"),
                    parameters=tool.get("parameters") or {},
                    read_only=bool(tool.get("read_only", False)),
                    destructive=bool(tool.get("destructive", False)),
                    requires_confirmation=bool(tool.get("requires_confirmation", True)),
                    enabled=True,
                )
            )
        else:
            row.description = tool.get("description")
            row.parameters = tool.get("parameters") or {}
            row.read_only = bool(tool.get("read_only", False))
            row.destructive = bool(tool.get("destructive", False))
            row.requires_confirmation = bool(tool.get("requires_confirmation", True))
            # enabled preserved
    stale = set(existing) - seen
    if stale:
        await db.execute(
            delete(MCPToolCache).where(
                MCPToolCache.provider_name == provider, MCPToolCache.tool_name.in_(stale)
            )
        )
    await db.flush()
    return await list_cached_tools(db, provider=provider)


async def set_tool_enabled(
    db: AsyncSession, *, provider: str, tool: str, enabled: bool
) -> dict[str, Any]:
    row = (
        await db.execute(
            select(MCPToolCache).where(
                MCPToolCache.provider_name == provider, MCPToolCache.tool_name == tool
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound(f"MCP tool {provider}/{tool} is not in the discovery cache")
    row.enabled = enabled
    await db.flush()
    return _tool_dict(row)
