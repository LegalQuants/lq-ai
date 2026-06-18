"""ORM model for the MCP tool-discovery cache (WS2/PR4b).

One row per (mcp server, tool). Populated by discovering tools through the
gateway (PR4a's GET /v1/tools/{provider}); ``enabled`` is the operator toggle
that gates what PR5 exposes to the model. MCP servers themselves are NOT stored
here — they come from the gateway config (list_tool_providers, type==mcp)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MCPToolCache(Base):
    __tablename__ = "mcp_tools"

    provider_name: Mapped[str] = mapped_column(String, primary_key=True)
    tool_name: Mapped[str] = mapped_column(String, primary_key=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, server_default=text("'{}'")
    )
    read_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    destructive: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    requires_confirmation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
