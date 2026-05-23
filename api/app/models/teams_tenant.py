"""TeamsTenant ORM — M3-D3.

Persists Microsoft 365 tenant records produced by the ``teams-bridge``
OAuth install flow. See migration ``0038_teams_tenants.py`` for the
table DDL.

Teams uses app-level bot credentials (one ``MICROSOFT_APP_ID`` per
deployment), so there's no per-tenant bot token to encrypt here —
contrast :class:`app.models.slack_workspace.SlackWorkspace` which
holds a Fernet-wrapped ``bot_token_encrypted``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TeamsTenant(Base):
    """One Microsoft 365 tenant connected via the teams-bridge install flow."""

    __tablename__ = "teams_tenants"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_teams_tenants_tenant_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    tenant_name: Mapped[str] = mapped_column(Text, nullable=False)
    installer_oid: Mapped[str] = mapped_column(Text, nullable=False)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
