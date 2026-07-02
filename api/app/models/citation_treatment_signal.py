"""citation_treatment_signal — one judged citing passage's treatment (WS-G PR2).

One row per citing opinion the treatment judge classified for a cited case.
Stores the DERIVED classification + confidence + the judge's short
justification (our reasoning) + the citing opinion ref — NEVER the raw
snippet or opinion text (ADR 0016 P3 / ADR 0019 D7). Joins the P3 tripwire.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base

_CLASS_LIST = (
    "'followed','distinguished','criticized','questioned','overruled','superseded','neutral'"
)


class CitationTreatmentSignal(Base):
    __tablename__ = "citation_treatment_signal"
    __table_args__ = (
        UniqueConstraint(
            "treatment_id",
            "citing_opinion_id",
            name="uq_treatment_signal_treatment_citing",
        ),
        CheckConstraint(
            f"classification IN ({_CLASS_LIST})",
            name="chk_treatment_signal_classification",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    treatment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("citation_treatment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    citing_opinion_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    classification: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
