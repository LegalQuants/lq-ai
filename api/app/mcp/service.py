"""MCP registry + discovery-cache orchestration (WS2/PR4b).

Servers come from gateway config (type==mcp); tools are discovered through the
gateway (PR4a) and cached in ``mcp_tools`` with an operator ``enabled`` toggle.
The api never speaks MCP directly (ADR 0014)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import get_gateway_client
from app.errors import MCPAuthorizationRequired, NotFound
from app.mcp import oauth
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
    user_id: UUID | None = None,
    request_id: str | None = None,
) -> list[dict[str, Any]]:
    """Re-discover ``provider``'s tools through the gateway and reconcile the
    cache: upsert returned tools (preserving each surviving tool's ``enabled``),
    delete cached tools the server no longer returns.

    For ``auth: oauth`` servers the calling user's valid token is resolved via
    :func:`app.mcp.oauth.get_valid_token` and forwarded to the gateway.  If no
    ``user_id`` is provided for an oauth server (e.g., an admin-context call),
    :class:`~app.errors.MCPAuthorizationRequired` is raised — admin refresh
    covers ``none``/``bearer`` servers only; oauth discovery is user-scoped.
    """
    # Determine whether this is a per-user OAuth server.
    oauth_servers = {
        p["name"] for p in await get_gateway_client().list_mcp_oauth_config(request_id=request_id)
    }
    user_token: str | None = None
    if provider in oauth_servers:
        if user_id is None:
            raise MCPAuthorizationRequired(
                message=(
                    f"MCP server {provider!r} uses per-user OAuth; refresh it via the "
                    "user-scoped connect flow, not admin refresh."
                ),
                details={"server": provider},
            )
        token = await oauth.get_valid_token(db, user_id=user_id, server=provider)
        if token is None:
            raise MCPAuthorizationRequired(
                message=(
                    f"MCP server {provider!r} requires authorization; "
                    f"connect via /api/v1/mcp/oauth/{provider}/authorize"
                ),
                details={"server": provider},
            )
        user_token = token

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
