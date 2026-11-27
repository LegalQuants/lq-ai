"""Payload-free chronological signals; authoritative DDL is migration 0079.

No producer is enabled by this model. References are opaque UUIDs rather than
copied finding titles/bodies. The source adapter owns source authorization and
calls the source-removal service when its source is removed (next slice).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkspaceEvent(Base):
    """Immutable signal metadata, scoped to its owner and optionally a project."""

    __tablename__ = "workspace_events"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "source_kind", "source_ref", "event_type", name="uq_workspace_events_source"
        ),
        CheckConstraint("source_kind = 'internal'", name="chk_workspace_events_source_kind"),
        CheckConstraint("event_type = 'finding.created'", name="chk_workspace_events_event_type"),
        CheckConstraint("status = 'recorded'", name="chk_workspace_events_status"),
        CheckConstraint(
            "sensitivity IN ('confidential', 'privileged')", name="chk_workspace_events_sensitivity"
        ),
        CheckConstraint(
            "dedupe_digest ~ '^[0-9a-f]{64}$'", name="chk_workspace_events_dedupe_digest"
        ),
        CheckConstraint(
            'provenance = \'{"producer": "autonomous"}\'::jsonb',
            name="chk_workspace_events_provenance",
        ),
        Index("ix_workspace_events_owner_time", "user_id", "occurred_at", "id"),
        Index("ix_workspace_events_project", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", name="fk_workspace_events_user_id"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_workspace_events_project_id")
    )
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    source_ref: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'recorded'"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    sensitivity: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_digest: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    def __repr__(self) -> str:
        return f"<WorkspaceEvent id={self.id} user_id={self.user_id}>"
