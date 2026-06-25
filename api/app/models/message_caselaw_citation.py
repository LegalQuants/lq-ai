"""message_caselaw_citations — quote-verified citations against external opinions.

One row per verbatim passage in an assistant turn that was character-verified
against a CourtListener opinion the turn consulted. Parallels ``message_citations``
(KB-document quote verification) but keys to ``opinion_id``/``cluster_id`` and
offsets into the opinion plaintext stored by the research service, with no
``file_id`` (external sources are not uploaded ``files``). P1-A1 / ADR 0018 D2.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class MessageCaselawCitation(Base):
    __tablename__ = "message_caselaw_citations"
    __table_args__ = (
        CheckConstraint(
            "source_offset_start >= 0",
            name="chk_message_caselaw_citations_offset_start_nonneg",
        ),
        CheckConstraint(
            "source_offset_end > source_offset_start",
            name="chk_message_caselaw_citations_offset_end_gt_start",
        ),
        CheckConstraint(
            "verification_method IS NULL OR verification_method IN "
            "('exact_match', 'tolerant_match')",
            name="chk_message_caselaw_citations_method_values",
        ),
        CheckConstraint(
            "verification_confidence IS NULL OR "
            "(verification_confidence >= 0 AND verification_confidence <= 1)",
            name="chk_message_caselaw_citations_confidence_range",
        ),
        CheckConstraint(
            "(verified = false) OR (verification_method IS NOT NULL)",
            name="chk_message_caselaw_citations_verified_has_method",
        ),
        Index("ix_message_caselaw_citations_message_id", "message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE", name="fk_message_caselaw_citations_message"),
        nullable=False,
    )
    opinion_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cluster_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_offset_start: Mapped[int] = mapped_column(Integer, nullable=False)
    source_offset_end: Mapped[int] = mapped_column(Integer, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    verification_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    partial: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
