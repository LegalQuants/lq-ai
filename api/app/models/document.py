"""Document and DocumentChunk ORM models — per docs/db-schema.md and ADR 0006.

The C5 document pipeline produces these rows from uploaded PDFs:

* :class:`Document` is the parsed-document metadata — one row per
  successfully ingested file. ``parser`` records which adapter
  produced the result; ``structured_content`` carries Docling's
  representation for future M2 consumption.
* :class:`DocumentChunk` is the load-bearing artifact for the M2
  Citation Engine. ``char_offset_start`` and ``char_offset_end`` are
  byte-precise against the canonical PyMuPDF character stream — the
  fidelity contract the M2 Citation Engine's deterministic substring
  verification depends on (PRD §3.6).

Lifecycle (M1):

* C5 worker creates a :class:`Document` row when ingestion succeeds and
  inserts every :class:`DocumentChunk` in a single transaction. Replays
  delete prior chunks for the document and re-insert (idempotent
  replace per ADR 0006).
* On hard-delete of a :class:`File` (D6 export+delete or future GC), the
  cascade chain ``files → documents → document_chunks`` removes
  everything. C4's soft-delete leaves all of this intact.

Embeddings are NULL for M1 — C6 owns the embedding-generation work
(see ADR 0006 §3 and ``docs/M1-PROGRESS.md`` for the deferral).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Document(Base):
    """Parsed-document metadata for an ingested file.

    ``parser`` is a free-text string (``'docling+pymupdf'``,
    ``'pymupdf'``, etc.) rather than an enum so future parser additions
    don't require a migration. ``parser_version`` carries the library
    version used at ingestion time so re-ingest decisions can be made
    against version drift.

    ``structured_content`` is Docling's structured representation
    (titles, paragraphs, tables) stashed for M2 consumption. M1's
    chunker drives off the PyMuPDF character stream and ignores this
    column.
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="CASCADE", name="fk_documents_file_id"),
        nullable=False,
        unique=True,
    )
    parser: Mapped[str] = mapped_column(Text, nullable=False)
    parser_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    character_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    structured_content: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    # M2-A1: full canonical text from PyMuPDF, the source of truth the
    # Citation Engine slices at chunk offsets when verifying citations.
    # ``chunk.content == normalized_content[char_offset_start:char_offset_end]``
    # is the load-bearing invariant.
    normalized_content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="",
    )
    # M2-A1: True if the source document went through OCR — toggles
    # OCR-artifact normalization in tolerant-match (M2-B1). False for
    # every M1 ingest because M1's parsers do not OCR.
    was_ocrd: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return (
            f"<Document id={self.id} file_id={self.file_id} "
            f"parser={self.parser!r} pages={self.page_count} "
            f"chars={self.character_count}>"
        )


class DocumentChunk(Base):
    """A single chunk of parsed-document text with byte-precise offsets.

    ``char_offset_start`` / ``char_offset_end`` are 0-based, half-open
    interval (``[start, end)``) — they match Python slicing semantics
    and ``content == original_text[start:end]`` is the load-bearing
    fidelity invariant the M2 Citation Engine consumes.

    ``page_start`` and ``page_end`` are nullable because for some
    chunkers (or if PyMuPDF can't determine page boundaries cleanly)
    page assignment is best-effort. M2's UI uses page numbers for
    "scroll to source" affordances; missing page assignment degrades
    to "jump to top of document."

    ``embedding`` is nullable for M1 — C6 backfills via the gateway's
    ``/v1/embeddings`` once it lands. The pgvector column is declared
    via raw DDL in the migration; SQLAlchemy core sees it as a generic
    column type and we treat it as opaque on the read side until C6.

    ``metadata_json`` is a per-chunk free-form JSONB store. Currently
    used to record chunk-level metadata (e.g., parser source, sentence
    boundaries respected) for debugging.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_doc_idx"),
        CheckConstraint(
            "char_offset_start >= 0",
            name="chk_document_chunks_offset_start_nonneg",
        ),
        CheckConstraint(
            "char_offset_end >= char_offset_start",
            name="chk_document_chunks_offset_end_gte_start",
        ),
        CheckConstraint(
            "chunk_index >= 0",
            name="chk_document_chunks_index_nonneg",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "documents.id",
            ondelete="CASCADE",
            name="fk_document_chunks_document_id",
        ),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_offset_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_offset_end: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    # `embedding` exists in the DB (pgvector vector(1536)) but is NULL
    # for M1 and is not exposed on this ORM model. C6 will land
    # embedding-aware reads via a vector-aware ORM extension or raw
    # SQL queries. M1 readers do not touch the embedding column.

    def __repr__(self) -> str:
        return (
            f"<DocumentChunk id={self.id} document_id={self.document_id} "
            f"index={self.chunk_index} len={len(self.content)} "
            f"offsets=[{self.char_offset_start},{self.char_offset_end})>"
        )

    def slice_original(self, original_text: str) -> str:
        """Slice the canonical original-text representation by this chunk's offsets.

        Used by tests to verify the fidelity invariant
        ``content == original_text[char_offset_start:char_offset_end]``.
        Surface here (rather than inline in tests) so the slicing
        convention is centralised.
        """

        return original_text[self.char_offset_start : self.char_offset_end]
