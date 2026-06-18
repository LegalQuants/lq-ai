"""Pydantic schemas for /api/v1/admin/mcp (WS2/PR4b)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MCPToolView(BaseModel):
    name: str
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    read_only: bool
    destructive: bool
    requires_confirmation: bool
    enabled: bool


class MCPServerView(BaseModel):
    name: str
    type: str
    tools: list[MCPToolView] = Field(default_factory=list)


class MCPServersResponse(BaseModel):
    servers: list[MCPServerView] = Field(default_factory=list)


class MCPRefreshResponse(BaseModel):
    server: str
    tools: list[MCPToolView] = Field(default_factory=list)


class MCPToolEnableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
