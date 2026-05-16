"""Document-ingest orchestration — Task C5.

This module is the entry point invoked by the ``arq`` worker. Given a
``files.id``, it:

1. Loads the file row (refusing to ingest soft-deleted rows).
2. Pulls the bytes from MinIO via :func:`app.storage.stream_download`.
3. Runs :func:`app.pipeline.parsers.parse_pdf` (PyMuPDF mandatory,
   Docling best-effort) on the byte stream — wrapped in
   :func:`asyncio.to_thread` because the parsers are sync.
4. Runs :func:`app.pipeline.chunker.chunk_document` to produce
   character-precise chunks.
5. Persists a :class:`Document` row and the :class:`DocumentChunk`
   rows in a single transaction.
6. Flips ``files.ingestion_status`` to ``'ready'``.

Failure paths:

* **Unsupported file type** (non-PDF MIME): row goes to
  ``ingestion_status='failed'`` with
  ``ingestion_error='unsupported_type'``. C4 leaves project_id and
  other metadata intact.
* **Parser failure** (corrupt PDF, encrypted, image-only PDF that
  PyMuPDF can't handle): same — ``failed`` + descriptive
  ``ingestion_error``.
* **Storage failure** (MinIO unreachable): the worker raises and
  ``arq`` retries per its visibility-timeout policy. The row stays
  at ``processing`` until a successful run flips it.

Idempotency: the worker deletes any existing :class:`Document` /
:class:`DocumentChunk` rows for the file before re-inserting. The
delete + insert run in the same transaction so a mid-run failure
leaves prior state intact (per ADR 0006 §4).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.document import Document, DocumentChunk
from app.models.file import File as FileModel
from app.pipeline.chunker import (
    chunk_document,
)
from app.pipeline.parsers import (
    ParsedDocument,
    ParserError,
    ParserUnsupported,
    is_pdf_mime,
    parse_pdf,
)
from app.storage import stream_download

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class IngestResult:
    """Outcome of an ingest run for visibility / testing.

    ``status`` is the final ``files.ingestion_status`` value.
    ``error`` is the populated ``ingestion_error`` on failure, or
    ``None`` on success.
    """

    file_id: uuid.UUID
    status: str
    document_id: uuid.UUID | None
    chunk_count: int
    parser: str | None
    error: str | None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def ingest_file(
    db: AsyncSession,
    file_id: uuid.UUID,
    *,
    target_chars: int | None = None,
    overlap_chars: int | None = None,
) -> IngestResult:
    """Run the document pipeline against ``file_id``.

    The function is the orchestration entry point — both the worker
    and tests invoke it via this signature. Caller is responsible for
    providing an ``AsyncSession``.

    Args:
        db: An active :class:`AsyncSession`. The function commits its
            own transaction(s); the caller is expected to manage the
            session lifecycle.
        file_id: ``files.id`` of the file to ingest.
        target_chars: Override for the chunker's target chunk size.
            Defaults to :data:`LQ_AI_CHUNK_TARGET_CHARS` from settings.
        overlap_chars: Override for the chunker's overlap. Defaults to
            :data:`LQ_AI_CHUNK_OVERLAP_CHARS` from settings.

    Returns:
        :class:`IngestResult` describing the run's outcome.
    """

    settings = get_settings()
    target = target_chars if target_chars is not None else settings.lq_ai_chunk_target_chars
    overlap = overlap_chars if overlap_chars is not None else settings.lq_ai_chunk_overlap_chars

    # ---- Load the file row.
    stmt = select(FileModel).where(FileModel.id == file_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        log.warning(
            "ingest_file: row not found",
            extra={"event": "ingest_row_missing", "file_id": str(file_id)},
        )
        return IngestResult(
            file_id=file_id,
            status="missing",
            document_id=None,
            chunk_count=0,
            parser=None,
            error="row_not_found",
        )

    if row.deleted_at is not None:
        log.info(
            "ingest_file: row soft-deleted; skipping",
            extra={"event": "ingest_skip_soft_deleted", "file_id": str(file_id)},
        )
        return IngestResult(
            file_id=file_id,
            status=row.ingestion_status,
            document_id=None,
            chunk_count=0,
            parser=None,
            error="soft_deleted",
        )

    # ---- Reject unsupported types early.
    if not is_pdf_mime(row.mime_type):
        await _mark_failed(db, row, error="unsupported_type", reason=f"mime={row.mime_type!r}")
        return IngestResult(
            file_id=file_id,
            status="failed",
            document_id=None,
            chunk_count=0,
            parser=None,
            error="unsupported_type",
        )

    # ---- Mark processing (if not already).
    if row.ingestion_status != "processing":
        row.ingestion_status = "processing"
        row.ingestion_error = None
        await db.commit()
        await db.refresh(row)

    # ---- Pull bytes from MinIO.
    try:
        pdf_bytes = await _read_all_bytes(row.storage_path)
    except Exception as exc:
        # Storage failures: log and re-raise so arq retries. Don't flip
        # status to failed — operator-side fixes (MinIO restart) should
        # let the next attempt succeed.
        log.warning(
            "ingest_file: storage read failed",
            extra={
                "event": "ingest_storage_failed",
                "file_id": str(file_id),
                "error": str(exc),
            },
        )
        raise

    # ---- Run parsers in a thread (sync libraries).
    try:
        parsed = await asyncio.to_thread(
            parse_pdf,
            pdf_bytes,
            run_docling=settings.lq_ai_docling_enabled,
        )
    except ParserUnsupported as exc:
        await _mark_failed(db, row, error="unsupported_content", reason=str(exc))
        return IngestResult(
            file_id=file_id,
            status="failed",
            document_id=None,
            chunk_count=0,
            parser=None,
            error="unsupported_content",
        )
    except ParserError as exc:
        await _mark_failed(db, row, error="parse_failed", reason=str(exc))
        return IngestResult(
            file_id=file_id,
            status="failed",
            document_id=None,
            chunk_count=0,
            parser=None,
            error="parse_failed",
        )

    # ---- Chunk the parsed text.
    chunks = chunk_document(
        parsed,
        target_chars=target,
        overlap_chars=overlap,
    )

    # ---- Persist (idempotent replace).
    document_id = await _persist_document_and_chunks(db, row, parsed, chunks)

    # ---- Flip status to ready.
    row.ingestion_status = "ready"
    row.ingestion_error = None
    await db.commit()

    log.info(
        "ingest_file: done",
        extra={
            "event": "ingest_done",
            "file_id": str(file_id),
            "document_id": str(document_id),
            "chunks": len(chunks),
            "parser": parsed.parser,
        },
    )

    return IngestResult(
        file_id=file_id,
        status="ready",
        document_id=document_id,
        chunk_count=len(chunks),
        parser=parsed.parser,
        error=None,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _read_all_bytes(storage_path: str) -> bytes:
    """Pull every byte from the MinIO object at ``storage_path``.

    For M1 we read the full body into memory — PDF size is bounded by
    ``LQ_AI_MAX_UPLOAD_SIZE_MB`` (default 100 MB) which is acceptable
    for a single worker process. If the cap is raised significantly
    we'll need a streaming-parse path; PyMuPDF's ``open(stream=...)``
    accepts a bytes-like object so the substitution is local.
    """

    parts: list[bytes] = []
    async with stream_download(storage_path=storage_path) as chunks:
        async for chunk in chunks:
            parts.append(chunk)
    return b"".join(parts)


async def _mark_failed(
    db: AsyncSession,
    row: FileModel,
    *,
    error: str,
    reason: str | None = None,
) -> None:
    """Flip a file row to failed with a populated ingestion_error."""

    row.ingestion_status = "failed"
    row.ingestion_error = error
    await db.commit()
    log.info(
        "ingest_file: marked failed",
        extra={
            "event": "ingest_marked_failed",
            "file_id": str(row.id),
            "error": error,
            "reason": reason,
        },
    )


async def _persist_document_and_chunks(
    db: AsyncSession,
    file_row: FileModel,
    parsed: ParsedDocument,
    chunks: list,  # list[Chunk] but avoid circular import
) -> uuid.UUID:
    """Write the Document + DocumentChunk rows; idempotent replace.

    If a Document already exists for this file (re-ingest), we delete
    its chunks (CASCADE-via-FK on document_id) and re-use the
    Document row id with updated metadata. The (document_id,
    chunk_index) UNIQUE constraint is what makes the replace safe at
    the storage layer.
    """

    # ---- Find or create the Document row.
    existing_doc_stmt = select(Document).where(Document.file_id == file_row.id)
    existing_doc = (await db.execute(existing_doc_stmt)).scalar_one_or_none()

    # M2-A1: ``normalized_content`` is exactly the PyMuPDF canonical text
    # the chunker sliced — keeping them coupled at write time means the
    # Citation Engine's re-read invariant
    # ``chunk.content == normalized_content[char_offset_start:char_offset_end]``
    # holds for every freshly ingested document. ``was_ocrd`` is False
    # because M1's parsers never OCR.
    if existing_doc is None:
        doc = Document(
            file_id=file_row.id,
            parser=parsed.parser,
            parser_version=parsed.parser_version,
            page_count=parsed.page_count,
            character_count=len(parsed.canonical_text),
            structured_content=parsed.structured_content,
            normalized_content=parsed.canonical_text,
            was_ocrd=False,
        )
        db.add(doc)
        await db.flush()  # populate doc.id
    else:
        # Re-use the document row but refresh the metadata.
        doc = existing_doc
        doc.parser = parsed.parser
        doc.parser_version = parsed.parser_version
        doc.page_count = parsed.page_count
        doc.character_count = len(parsed.canonical_text)
        doc.structured_content = parsed.structured_content
        doc.normalized_content = parsed.canonical_text
        doc.was_ocrd = False
        # Delete prior chunks so the re-insert doesn't violate the
        # (document_id, chunk_index) UNIQUE constraint.
        await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        await db.flush()

    # ---- Insert chunks.
    for chunk in chunks:
        db.add(
            DocumentChunk(
                document_id=doc.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                char_offset_start=chunk.char_offset_start,
                char_offset_end=chunk.char_offset_end,
                tokens=None,  # computed in C6 alongside embeddings
                metadata_json=chunk.metadata,
            )
        )
    await db.flush()
    return doc.id


# ---------------------------------------------------------------------------
# Convenience: sweep `pending` and `processing` rows on worker startup
# ---------------------------------------------------------------------------


async def find_orphaned_files(db: AsyncSession) -> list[uuid.UUID]:
    """Return file_ids stuck in pending/processing — worker startup sweep.

    Used by the worker's startup hook to re-enqueue any rows that were
    dropped by a previous worker crash. The result is intentionally
    bounded: the worker enqueues each one and the queue worker handles
    the rest.
    """

    stmt = select(FileModel.id).where(
        FileModel.ingestion_status.in_(["pending", "processing"]),
        FileModel.deleted_at.is_(None),
    )
    rows = await db.execute(stmt)
    return [row[0] for row in rows.all()]


async def aiter_pending_files(db: AsyncSession) -> AsyncIterator[uuid.UUID]:
    """Async-iterate over file_ids in pending/processing.

    Convenience generator wrapping :func:`find_orphaned_files` for
    callers that prefer streaming. M1 doesn't have many files at any
    time so the difference is mostly stylistic.
    """

    for file_id in await find_orphaned_files(db):
        yield file_id
