"""Tests for the M3-0.3 / DE-276 ingest-health endpoint and embed-status wiring.

Covers two surfaces landed in M3-0.3:

* :func:`app.knowledge.embed.embed_chunks_for_file` flips
  ``documents.ingest_status`` to ``'embed_failed'`` or ``'partial'``
  on batch failure, and clears it back to ``'ok'`` on a successful
  re-run.
* :func:`app.api.admin.get_ingest_health` aggregates the document-level
  and file-level ingest signals into a single admin-visible summary.

Tests run against the same SAVEPOINT-rolled-back per-test session as
the rest of the API tests (per ``tests/conftest.py``).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.knowledge.embed import embed_chunks_for_file
from app.main import app
from app.models.document import Document, DocumentChunk
from app.models.file import File as FileModel
from app.models.user import User
from app.security import create_access_token, hash_password


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


async def _make_admin(db_session: AsyncSession) -> User:
    admin = User(
        email=f"admin-{uuid.uuid4().hex[:8]}@lq.ai",
        hashed_password=hash_password("pw"),
        is_admin=True,
        role="admin",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(admin)
    await db_session.flush()
    return admin


async def _make_member(db_session: AsyncSession) -> User:
    member = User(
        email=f"member-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(member)
    await db_session.flush()
    return member


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


async def _make_file_doc_chunks(
    db_session: AsyncSession,
    *,
    owner: User,
    chunk_count: int,
    ingest_status: str = "ok",
    ingest_failure_reason: str | None = None,
) -> tuple[FileModel, Document, list[DocumentChunk]]:
    f = FileModel(
        owner_id=owner.id,
        filename=f"doc-{uuid.uuid4().hex[:8]}.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        hash_sha256="b" * 64,
        storage_path=f"ingest-health-fixture/{uuid.uuid4()}",
        ingestion_status="ready",
    )
    db_session.add(f)
    await db_session.flush()

    doc = Document(
        file_id=f.id,
        parser="pymupdf-only",
        parser_version="pymupdf=1.27",
        page_count=1,
        character_count=200,
        normalized_content="x" * 200,
        was_ocrd=False,
        ingest_status=ingest_status,
        ingest_failure_reason=ingest_failure_reason,
    )
    db_session.add(doc)
    await db_session.flush()

    chunks: list[DocumentChunk] = []
    for i in range(chunk_count):
        chunk = DocumentChunk(
            document_id=doc.id,
            chunk_index=i,
            content=f"chunk content {i} " * 5,
            page_start=1,
            page_end=1,
            char_offset_start=i * 40,
            char_offset_end=(i + 1) * 40,
        )
        db_session.add(chunk)
        chunks.append(chunk)
    await db_session.flush()
    return f, doc, chunks


# ---------------------------------------------------------------------------
# /api/v1/admin/ingest-health — endpoint behavior
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_ingest_health_requires_admin(client: AsyncClient, db_session: AsyncSession) -> None:
    """Non-admin caller gets 403; the endpoint is operator-only."""
    member = await _make_member(db_session)
    resp = await client.get("/api/v1/admin/ingest-health", headers=_bearer(member))
    assert resp.status_code == 403


@pytest.mark.integration
async def test_ingest_health_requires_bearer(client: AsyncClient) -> None:
    """No token → 401. Unlike bootstrap-status, this is admin-only."""
    resp = await client.get("/api/v1/admin/ingest-health")
    assert resp.status_code == 401


@pytest.mark.integration
async def test_ingest_health_empty_deployment(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Fresh-install state: zeroes across the board, totals consistent."""
    admin = await _make_admin(db_session)
    resp = await client.get("/api/v1/admin/ingest-health", headers=_bearer(admin))
    assert resp.status_code == 200
    body = resp.json()
    # The test DB starts empty for documents/files at fixture-flush time.
    assert body["embed_failed"] == 0
    assert body["partial"] == 0
    assert body["parse_failed"] == 0
    assert body["total_documents"] == body["ok"]


@pytest.mark.integration
async def test_ingest_health_aggregates_mixed_states(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Healthy + failed + partial + parse_failed states all surface."""
    admin = await _make_admin(db_session)

    # Healthy document.
    await _make_file_doc_chunks(db_session, owner=admin, chunk_count=3)
    # Embed-failed document.
    await _make_file_doc_chunks(
        db_session,
        owner=admin,
        chunk_count=2,
        ingest_status="embed_failed",
        ingest_failure_reason="gateway unreachable",
    )
    # Partial document.
    await _make_file_doc_chunks(
        db_session,
        owner=admin,
        chunk_count=4,
        ingest_status="partial",
        ingest_failure_reason="batch 2 of 3 failed",
    )
    # Parse-failed file (no documents row).
    parse_fail = FileModel(
        owner_id=admin.id,
        filename="corrupt.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        hash_sha256="c" * 64,
        storage_path=f"ingest-health-fixture/{uuid.uuid4()}",
        ingestion_status="failed",
        ingestion_error="parse_failed",
    )
    db_session.add(parse_fail)
    await db_session.flush()

    resp = await client.get("/api/v1/admin/ingest-health", headers=_bearer(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] >= 1
    assert body["embed_failed"] >= 1
    assert body["partial"] >= 1
    assert body["parse_failed"] >= 1
    # The total reflects only document-level rows.
    assert body["total_documents"] == body["ok"] + body["embed_failed"] + body["partial"]


@pytest.mark.integration
async def test_ingest_health_excludes_soft_deleted_files(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A soft-deleted file's document does not contribute to the counts."""
    from datetime import UTC, datetime

    admin = await _make_admin(db_session)
    f, _doc, _chunks = await _make_file_doc_chunks(
        db_session,
        owner=admin,
        chunk_count=2,
        ingest_status="embed_failed",
        ingest_failure_reason="legacy",
    )
    f.deleted_at = datetime.now(UTC)
    await db_session.flush()

    resp = await client.get("/api/v1/admin/ingest-health", headers=_bearer(admin))
    assert resp.status_code == 200
    body = resp.json()
    # Embed-failed row is soft-deleted → invisible.
    assert body["embed_failed"] == 0


# ---------------------------------------------------------------------------
# embed_chunks_for_file — ingest_status flips on failure / recovery
# ---------------------------------------------------------------------------


def _vectors(n: int, dim: int = 1536) -> list[list[float]]:
    """Deterministic dummy embedding vectors for tests."""
    return [[0.01 * (i + 1)] * dim for i in range(n)]


@pytest.mark.integration
async def test_embed_failure_with_zero_progress_marks_embed_failed(
    db_session: AsyncSession,
) -> None:
    """First-batch failure flips the document's ingest_status to ``embed_failed``."""
    admin = await _make_admin(db_session)
    f, doc, _chunks = await _make_file_doc_chunks(db_session, owner=admin, chunk_count=3)
    assert doc.ingest_status == "ok"

    async def _raise(*_args: Any, **_kwargs: Any) -> list[list[float]]:
        raise RuntimeError("gateway unreachable")

    with patch("app.knowledge.embed.request_embedding_vectors", new=AsyncMock(side_effect=_raise)):
        result = await embed_chunks_for_file(db_session, f.id)

    assert result.chunks_embedded == 0
    assert result.error is not None and "gateway unreachable" in result.error

    await db_session.refresh(doc)
    assert doc.ingest_status == "embed_failed"
    assert doc.ingest_failure_reason is not None
    assert "gateway unreachable" in doc.ingest_failure_reason


@pytest.mark.integration
async def test_embed_failure_after_partial_progress_marks_partial(
    db_session: AsyncSession,
) -> None:
    """Mid-batch failure with some chunks already embedded → ``partial``."""
    admin = await _make_admin(db_session)
    # Many chunks → multiple batches; first batch succeeds, second raises.
    f, doc, _chunks = await _make_file_doc_chunks(db_session, owner=admin, chunk_count=150)
    assert doc.ingest_status == "ok"

    call_count = {"n": 0}

    async def _flaky(texts: list[str], *_args: Any, **_kwargs: Any) -> list[list[float]]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _vectors(len(texts))
        raise RuntimeError("transient embedding error")

    with patch("app.knowledge.embed.request_embedding_vectors", new=AsyncMock(side_effect=_flaky)):
        result = await embed_chunks_for_file(db_session, f.id)

    assert 0 < result.chunks_embedded < 150
    assert result.error is not None

    await db_session.refresh(doc)
    assert doc.ingest_status == "partial"
    assert doc.ingest_failure_reason is not None


@pytest.mark.integration
async def test_embed_success_clears_prior_failure_back_to_ok(
    db_session: AsyncSession,
) -> None:
    """Re-running embed after a recovered outage flips the document back to ``ok``."""
    admin = await _make_admin(db_session)
    f, doc, _chunks = await _make_file_doc_chunks(
        db_session,
        owner=admin,
        chunk_count=3,
        ingest_status="embed_failed",
        ingest_failure_reason="prior outage",
    )
    assert doc.ingest_status == "embed_failed"

    async def _succeed(texts: list[str], *_args: Any, **_kwargs: Any) -> list[list[float]]:
        return _vectors(len(texts))

    with patch(
        "app.knowledge.embed.request_embedding_vectors", new=AsyncMock(side_effect=_succeed)
    ):
        result = await embed_chunks_for_file(db_session, f.id)

    assert result.chunks_embedded == 3
    assert result.error is None

    await db_session.refresh(doc)
    assert doc.ingest_status == "ok"
    assert doc.ingest_failure_reason is None


@pytest.mark.integration
async def test_embed_no_op_when_nothing_needs_embedding_preserves_status(
    db_session: AsyncSession,
) -> None:
    """A no-op embed run (all chunks already embedded) doesn't touch ingest_status.

    Defensive: an idempotent re-run on an already-healthy document
    must NOT spuriously clear ingest_status. The recovery path is
    gated on ``embedded_count == total_to_embed`` AND ``total_to_embed > 0``.
    """
    admin = await _make_admin(db_session)
    f, doc, chunks = await _make_file_doc_chunks(
        db_session, owner=admin, chunk_count=2, ingest_status="ok"
    )
    # Pre-fill embeddings so embed_chunks_for_file's WHERE NULL returns
    # nothing — same code path as a re-run on already-embedded doc.
    from sqlalchemy import text as sql_text

    for chunk in chunks:
        await db_session.execute(
            sql_text("UPDATE document_chunks SET embedding = CAST(:vec AS vector) WHERE id = :id"),
            {"vec": "[" + ",".join(["0.5"] * 1536) + "]", "id": str(chunk.id)},
        )
    await db_session.commit()

    result = await embed_chunks_for_file(db_session, f.id)
    assert result.chunks_embedded == 0

    await db_session.refresh(doc)
    assert doc.ingest_status == "ok"


# ---------------------------------------------------------------------------
# Schema invariants — CHECK constraint pins the enum at the storage layer
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_ingest_status_check_constraint_rejects_unknown_value(
    db_session: AsyncSession,
) -> None:
    """The CHECK constraint pins the enum — any value outside the four allowed is rejected."""
    admin = await _make_admin(db_session)
    _f, doc, _chunks = await _make_file_doc_chunks(db_session, owner=admin, chunk_count=1)

    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await db_session.execute(select(Document.id).where(Document.id == doc.id))
        doc.ingest_status = "not_a_real_status"
        await db_session.flush()
