"""ORM model for the tool-call governance audit log (PR5a).

One row per governed tool call — chat or autonomous origin. Records
counts/types only: provider, tool, tier, outcome, estimated cost, a
short args digest.  NEVER stores raw arguments or tool results (mirrors
``tool_egress_log`` discipline).

``confirmation_state`` tracks the human-gate lifecycle for calls that
require confirmation before execution.  ``outcome`` progresses from
``pending`` → ``executed`` | ``refused_tier`` | ``error`` | ``denied``.

The ``user_id`` FK cascades so that deleting a user removes their audit
rows (GDPR erasure path).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ToolCallLog(Base):
    """Per-call governance audit log — counts/types only, never raw payloads."""

    __tablename__ = "tool_call_log"
    __table_args__ = (
        CheckConstraint(
            # 0 ("no egress") is a real applied ceiling: a scope-0 refusal is
            # audited with max_allowed_tier=0.  Configured ceilings (operator /
            # project / pending) are 1-5; 0 only ever comes from the scope.
            "max_allowed_tier IS NULL OR (max_allowed_tier BETWEEN 0 AND 5)",
            name="chk_tool_call_log_max_allowed_tier_range",
        ),
        CheckConstraint(
            "ceiling_source IS NULL OR (ceiling_source IN "
            "('operator', 'project', 'execution_scope', 'pending_original', 'unresolved'))",
            name="chk_tool_call_log_ceiling_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    """'chat' | 'autonomous' — which execution context fired the tool."""

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_tool_call_log_user"),
        nullable=True,
    )
    """FK to users.id; NULL when the call originates from a headless job."""

    chat_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    """Set for chat-origin calls; NULL for autonomous."""

    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    """Chat message that triggered this call; NULL for autonomous."""

    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    """Autonomous session id; NULL for chat-origin calls."""

    intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    """ToolIntent value for autonomous calls; NULL for chat-origin marker."""

    provider: Mapped[str] = mapped_column(Text, nullable=False)
    """Logical provider name from gateway config (e.g. 'courtlistener')."""

    tool: Mapped[str] = mapped_column(Text, nullable=False)
    """Tool / function name within the provider."""

    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    """Provider egress tier (0-5) at call time."""

    max_allowed_tier: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    """Egress ceiling actually applied to this call (issue #593).

    NULL when the call ran unconstrained (no operator, Project, or scope
    ceiling was set).
    """

    ceiling_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Which policy bound this call: 'operator' | 'project' |
    'execution_scope' | 'pending_original' | 'unresolved'.

    NULL when no ceiling applied. 'unresolved' marks a fail-closed refusal
    where the egress policy could not be read at call time.
    """

    confirmation_state: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'not_required'"),
    )
    """not_required | pending_confirmation | approved | denied."""

    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    """pending | executed | refused_tier | error | denied."""

    cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6),
        nullable=True,
    )
    """Estimated / actual cost in USD.  Serialised as a JSON string per the
    project-wide Decimal-as-string convention (CLAUDE.md)."""

    args_digest: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Short hash/summary of the call arguments — NEVER raw args."""

    request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Propagated request-id for cross-service trace correlation."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    """App-bumped on every state transition (pending → executed/error/denied)."""

    def __repr__(self) -> str:
        return (
            f"<ToolCallLog id={self.id} origin={self.origin!r}"
            f" provider={self.provider!r} tool={self.tool!r}"
            f" outcome={self.outcome!r}>"
        )
