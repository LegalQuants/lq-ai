"""message_tool_sources — retrieval-provenance for external sources a chat turn consulted.

One row per external source (a case-law cluster) that a research tool *returned*
during an assistant turn. This is retrieval-provenance — "sources consulted" —
NOT quote-verification: it deliberately lives apart from ``message_citations``
(which is byte-offset quote-matching against uploaded documents). Case-law (``source_kind='caselaw'``, PR6c) and generic MCP connector results
(``source_kind='mcp'``, DE-350).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class MessageToolSource(Base):
    __tablename__ = "message_tool_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE", name="fk_message_tool_sources_message"),
        nullable=False,
    )
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_message_tool_sources_message_id", "message_id"),)
