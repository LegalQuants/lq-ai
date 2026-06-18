"""Pydantic v2 response schemas for the MCP OAuth REST surface (PR4c)."""

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
