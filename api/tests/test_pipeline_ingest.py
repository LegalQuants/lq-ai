"""Integration tests for the C5 ingest orchestration.

The orchestration sits between three things:

1. The DB (real per-test session via the conftest fixture).
2. MinIO (mocked via the FakeS3Client from test_storage_streaming).
3. The parsers (real PyMuPDF on real fixture PDFs; Docling disabled
   in tests to avoid the heavy install footprint).

What the tests check:

* Happy path: pending → ready, with chunks persisted and offsets
  byte-precise against the canonical text.
* Idempotent re-run: enqueueing the same file twice does NOT
  duplicate chunks (the replace-on-rerun strategy).
* Unsupported MIME: row goes to ``failed`` with
  ``ingestion_error='unsupported_type'``.
* Corrupt PDF: row goes to ``failed`` with
  ``ingestion_error='parse_failed'``.
* Soft-deleted row: pipeline skips it (no chunks written).
* Page-span / chunk-span: chunks across page boundaries record
  ``page_start`` / ``page_end`` correctly.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk
from app.models.file import File as FileModel
from app.models.user import User
from app.pipeline.ingest import ingest_file
from app.security import hash_password
from tests.test_storage_streaming import FakeS3Client

fitz = pytest.importorskip("fitz", reason="PyMuPDF not installed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_simple_pdf() -> bytes:
    text = (
        "Hello, world. " * 50
        + "The quick brown fox jumps over the lazy dog. " * 50
        + "Pack my box with five dozen liquor jugs. " * 50
    )
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), text, fontsize=11)
    out = doc.tobytes()
    doc.close()
    return out


def _make_multipage_pdf() -> bytes:
    doc = fitz.open()
    # ``insert_text`` writes a single non-wrapping line, so a long
    # string just runs off the page and PyMuPDF only extracts the
    # leading portion. Use ``insert_textbox`` with a bounding rect so
    # the content actually wraps onto multiple lines and PyMuPDF
    # captures the full per-page text. Each page carries ~1.2K chars
    # so the 3-page total (~3.6K) exceeds ``DEFAULT_TARGET_CHARS``
    # (2_000) and the chunker emits multiple chunks spanning pages
    # 1 and 2 — the cross-page assertion this test is meant to
    # exercise.
    for chapter in ("Alpha", "Beta", "Gamma"):
        page = doc.new_page()
        body = f"Chapter {chapter}. " + "Content content content. " * 50
        # A4 at 72 DPI is ~612x792; leave a half-inch margin.
        page.insert_textbox(
            fitz.Rect(50, 50, 562, 742),
            body,
            fontsize=11,
        )
    out = doc.tobytes()
    doc.close()
    return out


@pytest_asyncio.fixture
async def fake_s3() -> FakeS3Client:
    return FakeS3Client()


@pytest_asyncio.fixture
async def patched_storage(fake_s3: FakeS3Client) -> AsyncIterator[FakeS3Client]:
    """Patch the s3_client to yield the fake; the same pattern test_files_endpoints uses."""

    @asynccontextmanager
    async def _ctx() -> AsyncIterator[FakeS3Client]:
        yield fake_s3

    with patch("app.storage.s3_client", _ctx):
        yield fake_s3


@pytest_asyncio.fixture
async def db_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"ingest-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Ingest Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _create_file_row(
    db: AsyncSession,
    user: User,
    *,
    storage_path: str,
    pdf_bytes: bytes,
    mime: str = "application/pdf",
    filename: str = "test.pdf",
    sha: str | None = None,
) -> FileModel:
    row = FileModel(
        owner_id=user.id,
        filename=filename,
        mime_type=mime,
        size_bytes=len(pdf_bytes),
        hash_sha256=sha or ("0" * 64),
        storage_path=storage_path,
        ingestion_status="pending",
    )
    db.add(row)
    await db.flush()
    return row


def _put_in_fake_s3(fake_s3: FakeS3Client, key: str, body: bytes) -> None:
    fake_s3.objects[key] = body
    fake_s3.content_types[key] = "application/pdf"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_ingest_happy_path_marks_ready_with_chunks(
    db_session: AsyncSession,
    db_user: User,
    fake_s3: FakeS3Client,
    patched_storage: FakeS3Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: pending → ready, chunks persisted, offsets byte-precise."""

    # Ensure docling is disabled in tests to keep them fast and offline.
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "lq_ai_docling_enabled", False)

    pdf_bytes = _make_simple_pdf()
    storage_key = f"{uuid.uuid4()}"
    _put_in_fake_s3(fake_s3, storage_key, pdf_bytes)

    file_row = await _create_file_row(
        db_session, db_user, storage_path=storage_key, pdf_bytes=pdf_bytes
    )
    file_id = file_row.id

    result = await ingest_file(db_session, file_id)

    assert result.status == "ready"
    assert result.error is None
    assert result.document_id is not None
    assert result.chunk_count > 0

    await db_session.refresh(file_row)
    assert file_row.ingestion_status == "ready"
    assert file_row.ingestion_error is None

    # Document row exists.
    doc = (
        await db_session.execute(select(Document).where(Document.file_id == file_id))
    ).scalar_one()
    assert doc.parser == "pymupdf-only"
    assert doc.character_count is not None and doc.character_count > 0
    assert doc.page_count == 1

    # Chunks exist and slice back byte-for-byte against the canonical text.
    chunks = (
        (
            await db_session.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == doc.id)
                .order_by(DocumentChunk.chunk_index)
            )
        )
        .scalars()
        .all()
    )
    assert len(chunks) > 0

    # Re-derive canonical text from PyMuPDF for the slice check.
    from app.pipeline.parsers import parse_pdf

    parsed = parse_pdf(pdf_bytes, run_docling=False)

    for chunk in chunks:
        slice_ = parsed.canonical_text[chunk.char_offset_start : chunk.char_offset_end]
        assert slice_ == chunk.content, (
            f"chunk {chunk.chunk_index} fidelity broken: "
            f"len(slice)={len(slice_)}, len(content)={len(chunk.content)}"
        )


@pytest.mark.integration
async def test_ingest_multipage_records_per_chunk_pages(
    db_session: AsyncSession,
    db_user: User,
    fake_s3: FakeS3Client,
    patched_storage: FakeS3Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multi-page PDF: chunks record their page numbers."""

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "lq_ai_docling_enabled", False)

    pdf_bytes = _make_multipage_pdf()
    storage_key = f"{uuid.uuid4()}"
    _put_in_fake_s3(fake_s3, storage_key, pdf_bytes)

    file_row = await _create_file_row(
        db_session, db_user, storage_path=storage_key, pdf_bytes=pdf_bytes
    )

    result = await ingest_file(db_session, file_row.id)
    assert result.status == "ready"

    chunks = (
        (
            await db_session.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == result.document_id)
                .order_by(DocumentChunk.chunk_index)
            )
        )
        .scalars()
        .all()
    )

    pages_seen = {c.page_start for c in chunks if c.page_start is not None}
    # Three-page document should produce chunks with page_start
    # spanning at least pages 1 + 2 (last page may be tiny).
    assert pages_seen >= {1, 2}


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_ingest_re_run_does_not_duplicate_chunks(
    db_session: AsyncSession,
    db_user: User,
    fake_s3: FakeS3Client,
    patched_storage: FakeS3Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running ingest twice produces the same chunk count, not double."""

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "lq_ai_docling_enabled", False)

    pdf_bytes = _make_simple_pdf()
    storage_key = f"{uuid.uuid4()}"
    _put_in_fake_s3(fake_s3, storage_key, pdf_bytes)

    file_row = await _create_file_row(
        db_session, db_user, storage_path=storage_key, pdf_bytes=pdf_bytes
    )
    file_id = file_row.id

    first = await ingest_file(db_session, file_id)
    assert first.status == "ready"
    initial_chunk_count = first.chunk_count

    # Reset the row to pending and re-ingest (simulating an operator
    # forced re-ingest).
    await db_session.refresh(file_row)
    file_row.ingestion_status = "pending"
    await db_session.commit()

    second = await ingest_file(db_session, file_id)
    assert second.status == "ready"
    assert second.chunk_count == initial_chunk_count

    # Same Document row id — we re-used it.
    assert second.document_id == first.document_id

    chunks = (
        (
            await db_session.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == first.document_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(chunks) == initial_chunk_count


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_ingest_unsupported_mime_marks_failed(
    db_session: AsyncSession,
    db_user: User,
    fake_s3: FakeS3Client,
    patched_storage: FakeS3Client,
) -> None:
    """A non-PDF MIME flips the row to failed with unsupported_type."""

    storage_key = f"{uuid.uuid4()}"
    _put_in_fake_s3(fake_s3, storage_key, b"hello world")

    file_row = await _create_file_row(
        db_session,
        db_user,
        storage_path=storage_key,
        pdf_bytes=b"hello world",
        mime="text/plain",
        filename="x.txt",
    )

    result = await ingest_file(db_session, file_row.id)
    assert result.status == "failed"
    assert result.error == "unsupported_type"

    await db_session.refresh(file_row)
    assert file_row.ingestion_status == "failed"
    assert file_row.ingestion_error == "unsupported_type"


@pytest.mark.integration
async def test_ingest_corrupt_pdf_marks_failed(
    db_session: AsyncSession,
    db_user: User,
    fake_s3: FakeS3Client,
    patched_storage: FakeS3Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A corrupt PDF flips the row to failed with parse_failed."""

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "lq_ai_docling_enabled", False)

    storage_key = f"{uuid.uuid4()}"
    _put_in_fake_s3(fake_s3, storage_key, b"NOT A PDF")

    file_row = await _create_file_row(
        db_session,
        db_user,
        storage_path=storage_key,
        pdf_bytes=b"NOT A PDF",
    )

    result = await ingest_file(db_session, file_row.id)
    assert result.status == "failed"
    assert result.error == "parse_failed"

    await db_session.refresh(file_row)
    assert file_row.ingestion_status == "failed"


@pytest.mark.integration
async def test_ingest_soft_deleted_row_skipped(
    db_session: AsyncSession,
    db_user: User,
    fake_s3: FakeS3Client,
    patched_storage: FakeS3Client,
) -> None:
    """A soft-deleted file is skipped — no chunks are written."""

    from datetime import UTC, datetime

    storage_key = f"{uuid.uuid4()}"
    _put_in_fake_s3(fake_s3, storage_key, _make_simple_pdf())

    file_row = await _create_file_row(
        db_session,
        db_user,
        storage_path=storage_key,
        pdf_bytes=_make_simple_pdf(),
    )
    file_row.deleted_at = datetime.now(tz=UTC)
    await db_session.commit()

    result = await ingest_file(db_session, file_row.id)
    assert result.status != "ready"
    assert result.error == "soft_deleted"

    chunks = (await db_session.execute(select(DocumentChunk))).scalars().all()
    assert chunks == []


@pytest.mark.integration
async def test_ingest_missing_row(
    db_session: AsyncSession,
) -> None:
    """A missing file_id returns missing without raising."""

    result = await ingest_file(db_session, uuid.uuid4())
    assert result.status == "missing"
    assert result.error == "row_not_found"


# ---------------------------------------------------------------------------
# M2-A1: normalized_content + was_ocrd
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_ingest_populates_normalized_content_and_was_ocrd(
    db_session: AsyncSession,
    db_user: User,
    fake_s3: FakeS3Client,
    patched_storage: FakeS3Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M2-A1: ingest writes the canonical text to ``normalized_content``
    and sets ``was_ocrd=False`` (M1 has no OCR path).

    The Citation Engine (M2-A2) re-reads from ``normalized_content`` at
    chunk offsets — this test guards the load-bearing fidelity invariant
    that ``normalized_content[start:end] == chunk.content`` for every
    chunk in the document.
    """

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "lq_ai_docling_enabled", False)

    pdf_bytes = _make_simple_pdf()
    storage_key = f"{uuid.uuid4()}"
    _put_in_fake_s3(fake_s3, storage_key, pdf_bytes)

    file_row = await _create_file_row(
        db_session, db_user, storage_path=storage_key, pdf_bytes=pdf_bytes
    )

    result = await ingest_file(db_session, file_row.id)
    assert result.status == "ready"

    doc = (
        await db_session.execute(select(Document).where(Document.file_id == file_row.id))
    ).scalar_one()

    # New columns are populated and have the expected M1 values.
    from app.pipeline.parsers import parse_pdf

    parsed = parse_pdf(pdf_bytes, run_docling=False)
    assert doc.normalized_content == parsed.canonical_text
    assert doc.was_ocrd is False

    # Fidelity: every chunk slices back byte-for-byte against the
    # persisted normalized_content (not the re-parsed canonical text).
    chunks = (
        (
            await db_session.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == doc.id)
                .order_by(DocumentChunk.chunk_index)
            )
        )
        .scalars()
        .all()
    )
    assert len(chunks) > 0
    for chunk in chunks:
        slice_ = doc.normalized_content[chunk.char_offset_start : chunk.char_offset_end]
        assert slice_ == chunk.content, (
            f"chunk {chunk.chunk_index} fidelity against normalized_content broken: "
            f"len(slice)={len(slice_)}, len(content)={len(chunk.content)}"
        )


@pytest.mark.integration
async def test_ingest_re_run_refreshes_normalized_content(
    db_session: AsyncSession,
    db_user: User,
    fake_s3: FakeS3Client,
    patched_storage: FakeS3Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M2-A1: idempotent re-ingest keeps normalized_content in sync with chunks."""

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "lq_ai_docling_enabled", False)

    pdf_bytes = _make_simple_pdf()
    storage_key = f"{uuid.uuid4()}"
    _put_in_fake_s3(fake_s3, storage_key, pdf_bytes)

    file_row = await _create_file_row(
        db_session, db_user, storage_path=storage_key, pdf_bytes=pdf_bytes
    )

    first = await ingest_file(db_session, file_row.id)
    assert first.status == "ready"
    second = await ingest_file(db_session, file_row.id)
    assert second.status == "ready"
    assert second.document_id == first.document_id  # same row, replaced chunks.

    doc = (
        await db_session.execute(select(Document).where(Document.file_id == file_row.id))
    ).scalar_one()

    from app.pipeline.parsers import parse_pdf

    parsed = parse_pdf(pdf_bytes, run_docling=False)
    assert doc.normalized_content == parsed.canonical_text
    assert doc.was_ocrd is False
