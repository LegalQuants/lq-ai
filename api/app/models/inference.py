"""Inference routing log — per docs/db-schema.md §`inference_routing_log`.

Distinct from `audit_log` because:
- Different access pattern (every inference request, hot path)
- Different retention policy (operator-configurable, often shorter)
- The Tier Derivation choke point per PRD §3.13 / §1.5.2 writes here
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InferenceRoutingLog(Base):
    """One row per inference request through the gateway.

    `chat_id` and `message_id` are nullable UUIDs without FK constraints in
    the Phase A1 schema — the `chats` and `messages` tables don't exist yet
    (they land in Task C3). A future migration will add the FK constraints
    via ALTER TABLE once those tables exist. App code can write to these
    columns from day one; the data shape is forward-compatible.
    """

    __tablename__ = "inference_routing_log"
    __table_args__ = (
        CheckConstraint(
            "routed_inference_tier BETWEEN 1 AND 5",
            name="chk_inference_log_tier_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_inference_log_user_id"),
        nullable=True,
    )
    # FK constraints to chats / messages added in a later migration when those
    # tables exist (Task C3). For now these are plain UUID columns.
    chat_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # What was asked vs. what was routed
    requested_model: Mapped[str | None] = mapped_column(String, nullable=True)
    routed_provider: Mapped[str] = mapped_column(String, nullable=False)
    routed_model: Mapped[str] = mapped_column(String, nullable=False)
    routed_inference_tier: Mapped[int] = mapped_column(Integer, nullable=False)

    # Cost and performance
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_estimate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Pipeline flags
    anonymization_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    refused: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    refusal_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    request_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # M2-E2: distinguishes Citation Engine Stage 3/4 judge calls from
    # regular chat completions and embeddings. Values written by the
    # gateway from the request's ``lq_ai_purpose`` extension field:
    # ``'chat'`` (default), ``'judge_paraphrase'``, ``'embedding'``.
    # Nullable for backwards compatibility with pre-0029 rows; cost
    # calibration treats NULL the same as ``'chat'``.
    purpose: Mapped[str | None] = mapped_column(String(32), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<InferenceRoutingLog id={self.id} "
            f"provider={self.routed_provider} model={self.routed_model} "
            f"tier={self.routed_inference_tier} refused={self.refused}>"
        )
