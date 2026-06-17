"""Tool egress log — per docs/db-schema.md §`tool_egress_log`.

One row per outbound tool/data-source call through the gateway (ADR 0014
D3). Distinct from `inference_routing_log` (different egress, retention)
and from `audit_log` (hot path, counts-only). Gateway-written via raw SQL
(`gateway/app/tool_egress_log.py`, a later task); this ORM model backs
api-side reads.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ToolEgressLog(Base):
    __tablename__ = "tool_egress_log"
    __table_args__ = (
        CheckConstraint("tier BETWEEN 0 AND 5", name="chk_tool_egress_log_tier_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    tool: Mapped[str] = mapped_column(String, nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    bytes_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anonymization_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    refused: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    refusal_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ToolEgressLog id={self.id} provider={self.provider} "
            f"tool={self.tool} tier={self.tier} refused={self.refused}>"
        )
