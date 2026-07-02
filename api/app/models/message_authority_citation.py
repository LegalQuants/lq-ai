"""message_authority_citations — quote-verified citations against fetched authority text.

One row per verbatim passage in an assistant turn that was character-verified
against a fetched statute, regulation, or other authoritative source. Parallels
``message_caselaw_citations`` (CourtListener opinion verification) but uses
``source_type``/``external_ref``/``content_kind`` text columns instead of
``opinion_id``/``cluster_id`` BigInteger keys, since fetched-authority sources
(e.g. GovInfo) have string identifiers. WS-E PR1b / ADR 0021 D3.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class MessageAuthorityCitation(Base):
    __tablename__ = "message_authority_citations"
    __table_args__ = (
        CheckConstraint(
            "source_offset_start >= 0",
            name="chk_message_authority_citations_offset_start_nonneg",
        ),
        CheckConstraint(
            "source_offset_end > source_offset_start",
            name="chk_message_authority_citations_offset_end_gt_start",
        ),
        CheckConstraint(
            "verification_method IS NULL OR verification_method IN "
            "('exact_match', 'tolerant_match', 'paraphrase_judge')",
            name="chk_message_authority_citations_method_values",
        ),
        CheckConstraint(
            "verification_confidence IS NULL OR "
            "(verification_confidence >= 0 AND verification_confidence <= 1)",
            name="chk_message_authority_citations_confidence_range",
        ),
        CheckConstraint(
            "(verified = false) OR (verification_method IS NOT NULL)",
            name="chk_message_authority_citations_verified_has_method",
        ),
        Index("ix_message_authority_citations_message_id", "message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "messages.id",
            ondelete="CASCADE",
            name="fk_message_authority_citations_message",
        ),
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    external_ref: Mapped[str] = mapped_column(Text, nullable=False)
    content_kind: Mapped[str] = mapped_column(Text, nullable=False)
    source_offset_start: Mapped[int] = mapped_column(Integer, nullable=False)
    source_offset_end: Mapped[int] = mapped_column(Integer, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    verification_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    partial: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
