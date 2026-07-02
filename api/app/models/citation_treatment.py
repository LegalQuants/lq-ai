"""citation_treatment — derived validity/treatment signal per cited case (WS-G).

One row per cited case (``cluster_id``), holding the citation-graph signal:
the total cited-by count + a capped list of recent citing-opinion *references*
(ids + case_name + court + date — never opinion text, P3). ADR 0019 D2/D7.
PR1 (this) is graph-only (``derived_method='citation_graph'``); PR2 extends the
row with judge-classified treatment. Reference-only → joins the P3 tripwire.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class CitationTreatment(Base):
    __tablename__ = "citation_treatment"
    __table_args__ = (
        UniqueConstraint("cluster_id", name="uq_citation_treatment_cluster_id"),
        CheckConstraint("cited_by_count >= 0", name="chk_citation_treatment_count_nonneg"),
        CheckConstraint(
            "derived_method IN ('citation_graph', 'citation_graph+judge')",
            name="chk_citation_treatment_method_values",
        ),
        CheckConstraint(
            "strongest_negative_class IS NULL OR strongest_negative_class IN "
            "('overruled','superseded','criticized','questioned','distinguished')",
            name="chk_citation_treatment_strongest_negative",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    cluster_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    opinion_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cited_by_count: Mapped[int] = mapped_column(Integer, nullable=False)
    citing_opinions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    derived_method: Mapped[str] = mapped_column(Text, nullable=False)
    strongest_negative_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    judged_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    judge_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    as_of: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
