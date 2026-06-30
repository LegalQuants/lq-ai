"""authority_text_cache — cached fetched-authority source text (WS-E PR1b).

Content store for fetched statute / regulation / other authority source bodies.
The actual text lives in object storage under ``storage_path``; this table
holds the cache key (source_type, external_ref), the storage path, and
retrieval metadata. Analogous to ``research_opinion_metadata`` for CourtListener
opinion bodies. Cache key is UNIQUE (source_type, external_ref). ADR 0021 D3.

NOT added to the _AUDIT_MODELS no-raw-payload tripwire — this is a content
cache, not an audit record.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AuthorityTextCache(Base):
    __tablename__ = "authority_text_cache"
    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "external_ref",
            name="uq_authority_text_cache_source_ref",
        ),
        Index("ix_authority_text_cache_source_ref", "source_type", "external_ref"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    external_ref: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    char_length: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
