"""Explicit Slack identity links and single-use, hashed linking challenges."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SlackAccountLink(Base):
    __tablename__ = "slack_account_links"
    __table_args__ = (UniqueConstraint("workspace_id", "slack_user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("slack_workspaces.id", ondelete="CASCADE"), nullable=False
    )
    slack_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class SlackLinkRequest(Base):
    __tablename__ = "slack_link_requests"
    __table_args__ = (UniqueConstraint("workspace_id", "slack_user_id"),)

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("slack_workspaces.id", ondelete="CASCADE"), nullable=False
    )
    slack_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
