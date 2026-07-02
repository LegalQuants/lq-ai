"""Pydantic v2 response schemas for the MCP OAuth REST surface (PR4c / PR4d)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class MCPOAuthCallbackResponse(BaseModel):
    """Response body for a successful OAuth callback."""

    connected: bool
    server: str
    scopes: list[str]
    expires_at: datetime | None = None


class MCPOAuthStatusResponse(BaseModel):
    """Response body for the connection status endpoint."""

    connected: bool
    scopes: list[str]
    expires_at: datetime | None = None


class MCPOAuthServerStatus(BaseModel):
    """Per-server connection status in the per-user list endpoint (PR4d Ask 1).

    Token bytes are NEVER included — only the non-secret status fields.
    """

    server: str
    connected: bool
    scopes: list[str]
    expires_at: datetime | None = None


class MCPOAuthServersResponse(BaseModel):
    """Response body for GET /api/v1/mcp/oauth — list of all connectable OAuth servers."""

    servers: list[MCPOAuthServerStatus]
