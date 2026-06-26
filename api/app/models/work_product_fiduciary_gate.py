"""work_product_fiduciary_gate — the per-turn fiduciary-grade verdict (ADR 0018 D3).

One row per assistant turn (UNIQUE on message_id): the computed gate verdict
(``fiduciary_grade`` | ``supported_only`` | ``flagged``) plus per-tier counts and
an aggregate confidence, derived deterministically from the turn's
``citation_ledger_entry`` rows. Metadata-only — a status label, integer counts,
and a numeric confidence; it holds NO content, so it joins the P3 no-raw-payload
tripwire. The history-preserving record is the ledger; this verdict is upserted
(current-verdict) on re-finalize.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class WorkProductFiduciaryGate(Base):
    __tablename__ = "work_product_fiduciary_gate"
    __table_args__ = (
        CheckConstraint(
            "gate_status IN ('fiduciary_grade', 'supported_only', 'flagged')",
            name="chk_work_product_fiduciary_gate_status_values",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="chk_work_product_fiduciary_gate_confidence_range",
        ),
        CheckConstraint(
            "pass_count >= 0 AND supported_count >= 0 AND fail_count >= 0 "
            "AND total_assertions >= 0",
            name="chk_work_product_fiduciary_gate_counts_nonneg",
        ),
        Index("ix_work_product_fiduciary_gate_chat_id", "chat_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "messages.id", ondelete="CASCADE", name="fk_work_product_fiduciary_gate_message"
        ),
        nullable=False,
        unique=True,
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE", name="fk_work_product_fiduciary_gate_chat"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "projects.id", ondelete="SET NULL", name="fk_work_product_fiduciary_gate_project"
        ),
        nullable=True,
    )
    gate_status: Mapped[str] = mapped_column(Text, nullable=False)
    pass_count: Mapped[int] = mapped_column(Integer, nullable=False)
    supported_count: Mapped[int] = mapped_column(Integer, nullable=False)
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_assertions: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
