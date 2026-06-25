"""citation_ledger_entry — the Citation Ledger (ADR 0018 D1).

One row per (assistant turn, source brought into context). A thin REFERENCING
record: it points at exactly one of message_citations / message_caselaw_citations
/ message_tool_sources by id (a CHECK enforces exactly-one-non-null) and mirrors
that source's verification status as a queryable label. It holds NO content
(source_text lives on the referenced row), so it is a metadata index and joins
the P3 no-raw-payload tripwire. ``treatment_id`` is reserved for the WS-G derived
treatment layer (ADR 0018 D6) and is always NULL in Phase 1.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, CheckConstraint, Float, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class CitationLedgerEntry(Base):
    __tablename__ = "citation_ledger_entry"
    __table_args__ = (
        CheckConstraint(
            "(message_citation_id IS NOT NULL)::int "
            "+ (message_caselaw_citation_id IS NOT NULL)::int "
            "+ (message_tool_source_id IS NOT NULL)::int = 1",
            name="chk_citation_ledger_entry_exactly_one_source",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="chk_citation_ledger_entry_confidence_range",
        ),
        Index("ix_citation_ledger_entry_chat_id", "chat_id"),
        Index("ix_citation_ledger_entry_message_id", "message_id"),
        Index("ix_citation_ledger_entry_project_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_citation_ledger_entry_project"),
        nullable=True,
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE", name="fk_citation_ledger_entry_chat"),
        nullable=False,
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE", name="fk_citation_ledger_entry_message"),
        nullable=False,
    )
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    message_citation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "message_citations.id", ondelete="CASCADE", name="fk_citation_ledger_entry_msg_citation"
        ),
        nullable=True,
    )
    message_caselaw_citation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "message_caselaw_citations.id",
            ondelete="CASCADE",
            name="fk_citation_ledger_entry_caselaw_citation",
        ),
        nullable=True,
    )
    message_tool_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "message_tool_sources.id",
            ondelete="CASCADE",
            name="fk_citation_ledger_entry_tool_source",
        ),
        nullable=True,
    )
    verification_status: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    treatment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
