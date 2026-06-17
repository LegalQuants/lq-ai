"""Cached CourtListener research metadata (WS3b).

Cluster + opinion metadata for fetched case law. Opinion BODIES (extracted
plaintext) live in object storage under ``storage_path``; only metadata is
here. Backs the read-through cache for GET /research/clusters/{id} and the
find_in_case/read_case reads. Schema authority: migration 0049."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ResearchClusterMetadata(Base):
    __tablename__ = "research_cluster_metadata"

    cluster_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    case_name: Mapped[str | None] = mapped_column(String, nullable=True)
    court: Mapped[str | None] = mapped_column(String, nullable=True)
    date_filed: Mapped[str | None] = mapped_column(String, nullable=True)
    absolute_url: Mapped[str | None] = mapped_column(String, nullable=True)
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ResearchOpinionMetadata(Base):
    __tablename__ = "research_opinion_metadata"

    opinion_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cluster_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    text_field_used: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    char_length: Mapped[int] = mapped_column(Integer, nullable=False)
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
