"""Audit log model — per docs/db-schema.md §`audit_log` and PRD §5.3.

Append-only at the application layer. The privilege fields (privilege_marked,
privilege_basis, routed_inference_tier) are first-class columns rather than
JSONB so audit queries can filter on them efficiently.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """One row per state-changing action; queryable by privilege flag and tier."""

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(
            "routed_inference_tier IS NULL OR (routed_inference_tier BETWEEN 1 AND 5)",
            name="chk_audit_log_tier_range",
        ),
        CheckConstraint(
            "NOT privilege_marked OR privilege_basis IS NOT NULL",
            name="chk_audit_log_privileged_with_basis",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # clock_timestamp(), not now(): now() is fixed at transaction start, so
    # rows flushed inside one transaction (an autonomous session commits
    # once) would all share a timestamp and have no defined order.
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_audit_log_user_id"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String, nullable=False)
    resource_type: Mapped[str] = mapped_column(String, nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Privilege fields (PRD §5.3, new in v0.2)
    privilege_marked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    privilege_basis: Mapped[str | None] = mapped_column(String, nullable=True)
    routed_inference_tier: Mapped[int | None] = mapped_column(Integer, nullable=True)
    routed_provider: Mapped[str | None] = mapped_column(String, nullable=True)

    # Request context
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Opaque payload — queryable but not indexed by default
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} action={self.action!r} "
            f"resource={self.resource_type}/{self.resource_id} "
            f"privileged={self.privilege_marked}>"
        )
