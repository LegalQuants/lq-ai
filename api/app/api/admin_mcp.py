"""/api/v1/admin/mcp — MCP registry admin surface (WS2/PR4b).

Lists configured MCP servers (from gateway config) + their cached tools,
refreshes discovery through the gateway, and toggles per-tool enable. All
AdminUser-gated. The api never speaks MCP directly (ADR 0014)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AdminUser
from app.audit import audit_action
from app.db.session import get_db
from app.mcp import service
from app.schemas.mcp import (
    MCPRefreshResponse,
    MCPServersResponse,
    MCPServerView,
    MCPToolEnableRequest,
    MCPToolView,
)

router = APIRouter(prefix="/admin/mcp", tags=["admin"])


@router.get("", response_model=MCPServersResponse)
async def list_mcp(
    _admin: AdminUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> MCPServersResponse:
    """GET /api/v1/admin/mcp — list configured MCP servers + cached tools."""
    servers = await service.list_servers()
    views: list[MCPServerView] = []
    for s in servers:
        tools = await service.list_cached_tools(db, provider=s["name"])
        views.append(
            MCPServerView(
                name=s["name"],
                type=s["type"],
                tools=[MCPToolView(**t) for t in tools],
            )
        )
    return MCPServersResponse(servers=views)


@router.post("/{server}/refresh", response_model=MCPRefreshResponse)
async def refresh_mcp(
    server: str,
    admin: AdminUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MCPRefreshResponse:
    """POST /api/v1/admin/mcp/{server}/refresh — re-discover tools; audited.

    Covers ``none`` and ``bearer`` MCP servers only.  OAuth servers are
    per-user — discovery and refresh happen on the user-scoped OAuth-connect
    path (``/api/v1/mcp/oauth/{server}/authorize``).  Calling this endpoint
    for an ``auth: oauth`` server raises a typed
    :class:`~app.errors.MCPAuthorizationRequired` (409) so the caller knows
    to redirect to the user-scoped flow rather than receiving a silent failure.
    """
    tools = await service.refresh_server(db, provider=server)
    await audit_action(
        db,
        user_id=admin.id,
        action="mcp.tools_refreshed",
        resource_type="mcp_server",
        resource_id=server,
        request=request,
        details={"tool_count": len(tools)},
    )
    await db.commit()
    return MCPRefreshResponse(server=server, tools=[MCPToolView(**t) for t in tools])


@router.patch("/{server}/tools/{tool}", response_model=MCPToolView)
async def set_mcp_tool_enabled(
    server: str,
    tool: str,
    body: MCPToolEnableRequest,
    admin: AdminUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MCPToolView:
    """PATCH /api/v1/admin/mcp/{server}/tools/{tool} — toggle enabled; audited."""
    updated = await service.set_tool_enabled(db, provider=server, tool=tool, enabled=body.enabled)
    action = "mcp.tool_enabled" if body.enabled else "mcp.tool_disabled"
    await audit_action(
        db,
        user_id=admin.id,
        action=action,
        resource_type="mcp_tool",
        resource_id=f"{server}/{tool}",
        request=request,
        details={"enabled": body.enabled},
    )
    await db.commit()
    return MCPToolView(**updated)
