"""SlackWorkspace ORM — M3-D1.

Persists Slack workspace records produced by the ``slack-bridge`` OAuth
install flow. The bot token is stored encrypted at rest under
:envvar:`LQ_AI_BRIDGE_MASTER_KEY` via
:class:`app.security.encryption.BridgeTokenEncryptor`. See migration
``0037_slack_workspaces.py`` for the table DDL.

One workspace per Slack team (``team_id`` is unique). The persistence
endpoint upserts on ``team_id`` so a re-install (Slack rotates the bot
token) replaces the prior row's ciphertext + installer + scope and
revives ``deleted_at`` if the workspace had been soft-deleted.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, LargeBinary, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SlackWorkspace(Base):
    """One Slack workspace connected via the bridge OAuth install flow."""

    __tablename__ = "slack_workspaces"
    __table_args__ = (UniqueConstraint("team_id", name="uq_slack_workspaces_team_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    team_id: Mapped[str] = mapped_column(Text, nullable=False)
    team_name: Mapped[str] = mapped_column(Text, nullable=False)
    bot_token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    bot_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    installer_slack_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
