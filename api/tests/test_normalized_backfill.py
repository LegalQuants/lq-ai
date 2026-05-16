"""Tests for the M2-A1 backfill that reconstructs ``documents.normalized_content``
from existing ``document_chunks`` rows.

Reconstruction has to handle the chunker's overlap (default 200 chars);
the algorithm walks chunks by ``char_offset_start`` and appends only the
suffix that extends beyond ``cur_end``. The async backfill walks rows
where ``normalized_content = ''`` (the schema default that landed in
migration 0024) and writes the reconstructed text.

Verification matches the M2 plan's stated criteria:

* Re-extraction at chunk offsets reproduces ``chunk.content``
  byte-for-byte (the load-bearing fidelity invariant).
* The script is idempotent — a second run is a no-op on rows already
  populated (and ``force=True`` re-runs everything).
* ``was_ocrd`` is left at the schema default (False) — M1 has no OCR.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk
from app.models.file import File as FileModel
from app.models.user import User
from app.pipeline.ingest import ingest_file
from app.pipeline.normalized_backfill import (
    BackfillReport,
    backfill_documents,
    reconstruct_from_chunks,
)
from app.security import hash_password
from tests.test_storage_streaming import FakeS3Client

fitz = pytest.importorskip("fitz", reason="PyMuPDF not installed")


# ---------------------------------------------------------------------------
# Reconstruction algorithm — pure-function tests (no DB needed)
# ---------------------------------------------------------------------------


def _chunk(start: int, end: int, content: str) -> DocumentChunk:
    """Build a transient DocumentChunk for algorithm tests; no DB write."""

    return DocumentChunk(
        document_id=uuid.uuid4(),
        chunk_index=start,  # arbitrary; ordering driven by offset
        content=content,
        char_offset_start=start,
        char_offset_end=end,
    )


@pytest.mark.unit
def test_reconstruct_handles_disjoint_chunks() -> None:
    """Two non-overlapping, adjacent chunks reconstruct trivially."""

    chunks = [
        _chunk(0, 5, "hello"),
        _chunk(5, 11, " world"),
    ]
    text, gap = reconstruct_from_chunks(chunks)
    assert text == "hello world"
    assert gap is False


@pytest.mark.unit
def test_reconstruct_handles_overlap() -> None:
    """Overlapping chunks (typical chunker output) reconstruct correctly."""

    # canonical = "abcdefghij"
    # chunk 0 covers [0,6) = "abcdef"
    # chunk 1 covers [3,10) = "defghij" (overlaps chunk 0 by "def")
    chunks = [
        _chunk(0, 6, "abcdef"),
        _chunk(3, 10, "defghij"),
    ]
    text, gap = reconstruct_from_chunks(chunks)
    assert text == "abcdefghij"
    assert gap is False


@pytest.mark.unit
def test_reconstruct_handles_unordered_input() -> None:
    """Algorithm sorts by ``char_offset_start`` — order-agnostic."""

    chunks = [
        _chunk(3, 10, "defghij"),
        _chunk(0, 6, "abcdef"),
    ]
    text, gap = reconstruct_from_chunks(chunks)
    assert text == "abcdefghij"
    assert gap is False


@pytest.mark.unit
def test_reconstruct_flags_gap() -> None:
    """A missing range between chunks is flagged — never silently filled."""

    chunks = [
        _chunk(0, 5, "hello"),
        _chunk(7, 12, "world"),  # gap at [5,7)
    ]
    _text, gap = reconstruct_from_chunks(chunks)
    assert gap is True
    # text may be best-effort or empty — the caller decides what to do
    # with a gap (skip the document, log, etc.). The contract is just
    # "tell me if there's a gap."


@pytest.mark.unit
def test_reconstruct_empty_chunks_returns_empty() -> None:
    """No chunks → empty string, no gap (vacuously true)."""

    text, gap = reconstruct_from_chunks([])
    assert text == ""
    assert gap is False


# ---------------------------------------------------------------------------
# Async backfill — integration against a real DB + ingest pipeline
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


@pytest_asyncio.fixture
async def fake_s3() -> FakeS3Client:
    return FakeS3Client()


@pytest_asyncio.fixture
async def patched_storage(fake_s3: FakeS3Client) -> AsyncIterator[FakeS3Client]:
    @asynccontextmanager
    async def _ctx() -> AsyncIterator[FakeS3Client]:
        yield fake_s3

    with patch("app.storage.s3_client", _ctx):
        yield fake_s3


@pytest_asyncio.fixture
async def db_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"backfill-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Backfill Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _ingest_then_clear_normalized(
    db: AsyncSession,
    user: User,
    fake_s3: FakeS3Client,
    pdf: bytes,
) -> uuid.UUID:
    """Run the live ingest and then clear the normalized_content column so the
    document looks like a pre-M2 row that needs backfilling."""

    storage_key = f"{uuid.uuid4()}"
    fake_s3.objects[storage_key] = pdf
    fake_s3.content_types[storage_key] = "application/pdf"

    file_row = FileModel(
        owner_id=user.id,
        filename="test.pdf",
        mime_type="application/pdf",
        size_bytes=len(pdf),
        hash_sha256="0" * 64,
        storage_path=storage_key,
        ingestion_status="pending",
    )
    db.add(file_row)
    await db.flush()

    result = await ingest_file(db, file_row.id)
    assert result.status == "ready"
    assert result.document_id is not None

    # Simulate pre-M2 state: the column existed (schema default '')
    # but no canonical text was written.
    await db.execute(
        update(Document).where(Document.id == result.document_id).values(normalized_content="")
    )
    await db.commit()
    return result.document_id


@pytest.mark.integration
async def test_backfill_populates_pre_m2_rows(
    db_session: AsyncSession,
    db_user: User,
    fake_s3: FakeS3Client,
    patched_storage: FakeS3Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A document with empty normalized_content gets reconstructed from chunks."""

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "lq_ai_docling_enabled", False)

    doc_id = await _ingest_then_clear_normalized(db_session, db_user, fake_s3, _make_simple_pdf())

    report = await backfill_documents(db_session)

    assert report.processed == 1
    assert report.skipped == 0
    assert report.gaps == 0

    # Reload and check fidelity: slicing at chunk offsets reproduces
    # chunk content byte-for-byte.
    doc = (await db_session.execute(select(Document).where(Document.id == doc_id))).scalar_one()
    assert doc.normalized_content != ""
    assert doc.was_ocrd is False  # backfill must not touch this column

    chunks = (
        (
            await db_session.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == doc_id)
                .order_by(DocumentChunk.chunk_index)
            )
        )
        .scalars()
        .all()
    )
    assert len(chunks) > 0
    for chunk in chunks:
        slice_ = doc.normalized_content[chunk.char_offset_start : chunk.char_offset_end]
        assert slice_ == chunk.content


@pytest.mark.integration
async def test_backfill_is_idempotent(
    db_session: AsyncSession,
    db_user: User,
    fake_s3: FakeS3Client,
    patched_storage: FakeS3Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-running on already-populated rows is a no-op (skip semantics)."""

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "lq_ai_docling_enabled", False)

    await _ingest_then_clear_normalized(db_session, db_user, fake_s3, _make_simple_pdf())

    first = await backfill_documents(db_session)
    assert first.processed == 1

    second = await backfill_documents(db_session)
    assert second.processed == 0
    assert second.skipped == 1


@pytest.mark.integration
async def test_backfill_force_rewrites_populated_rows(
    db_session: AsyncSession,
    db_user: User,
    fake_s3: FakeS3Client,
    patched_storage: FakeS3Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``force=True`` re-processes rows whose normalized_content is non-empty."""

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "lq_ai_docling_enabled", False)

    doc_id = await _ingest_then_clear_normalized(db_session, db_user, fake_s3, _make_simple_pdf())

    await backfill_documents(db_session)

    # Sabotage the row to prove force actually recomputes.
    await db_session.execute(
        update(Document).where(Document.id == doc_id).values(normalized_content="bogus")
    )
    await db_session.commit()

    report = await backfill_documents(db_session, force=True)
    assert report.processed == 1

    doc = (await db_session.execute(select(Document).where(Document.id == doc_id))).scalar_one()
    assert doc.normalized_content != "bogus"
    # Fidelity check after force re-run.
    chunks = (
        (await db_session.execute(select(DocumentChunk).where(DocumentChunk.document_id == doc_id)))
        .scalars()
        .all()
    )
    for chunk in chunks:
        assert (
            doc.normalized_content[chunk.char_offset_start : chunk.char_offset_end] == chunk.content
        )


@pytest.mark.integration
async def test_backfill_report_shape(
    db_session: AsyncSession,
) -> None:
    """Empty DB → report shows zero rows everywhere; type is BackfillReport."""

    report = await backfill_documents(db_session)
    assert isinstance(report, BackfillReport)
    assert report.processed == 0
    assert report.skipped == 0
    assert report.gaps == 0
