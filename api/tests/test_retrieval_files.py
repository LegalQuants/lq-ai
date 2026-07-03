"""DB-backed tests for the file-scoped hybrid retrieval primitive.

:func:`hybrid_search_files` (referenced-files Task 2) is the file-scoped sibling
of :func:`hybrid_search` — same score model, but the candidate set is
``document_chunks`` whose owning file is in an explicit ``file_ids``
list rather than a KB join. These tests exercise the FTS-only path
(``alpha=1.0``, ``query_embedding=None``) deterministically against a
real Postgres so the SQL (not a mock) is what's under test.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.retrieval import hybrid_search_files
from app.models.document import Document, DocumentChunk
from app.models.file import File as FileModel
from app.models.user import User
from app.security import hash_password

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def owner_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"retrieval-files-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("correct-horse-battery-staple"),
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_ready_file(
    db_session: AsyncSession,
    owner: User,
    *,
    chunk_bodies: list[str],
    ingestion_status: str = "ready",
    deleted: bool = False,
) -> FileModel:
    f = FileModel(
        owner_id=owner.id,
        filename=f"retrieval-files-{uuid.uuid4().hex[:8]}.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        hash_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        storage_path=f"retrieval-files-fixture/{uuid.uuid4()}",
        ingestion_status=ingestion_status,
    )
    if deleted:
        f.deleted_at = datetime.now(UTC)
    db_session.add(f)
    await db_session.flush()

    full_text = "\n\n".join(chunk_bodies)
    doc = Document(
        file_id=f.id,
        parser="pymupdf-only",
        parser_version="pymupdf=1.27",
        page_count=1,
        character_count=len(full_text),
        normalized_content=full_text,
        was_ocrd=False,
    )
    db_session.add(doc)
    await db_session.flush()

    offset = 0
    for idx, body in enumerate(chunk_bodies):
        chunk = DocumentChunk(
            document_id=doc.id,
            chunk_index=idx,
            content=body,
            page_start=1,
            page_end=1,
            char_offset_start=offset,
            char_offset_end=offset + len(body),
        )
        db_session.add(chunk)
        offset += len(body) + 2

    await db_session.flush()
    return f


async def test_hybrid_search_files_scopes_to_requested_files(
    db_session: AsyncSession, owner_user: User
) -> None:
    """Searching with file_ids=[file_a] returns only file_a's chunks."""

    file_a = await _make_ready_file(
        db_session,
        owner_user,
        chunk_bodies=[
            "The termination clause governs early exit from the agreement.",
            "Termination for cause requires thirty days written notice.",
        ],
    )
    file_b = await _make_ready_file(
        db_session,
        owner_user,
        chunk_bodies=[
            "The confidentiality clause survives termination of the agreement.",
        ],
    )

    results = await hybrid_search_files(
        db_session,
        file_ids=[file_a.id],
        query="termination",
        query_embedding=None,
        top_k=10,
        alpha=1.0,
    )

    assert results
    assert {r.file_id for r in results} == {file_a.id}
    assert file_b.id not in {r.file_id for r in results}


async def test_hybrid_search_files_empty_file_ids_returns_empty_without_query(
    db_session: AsyncSession,
) -> None:
    """file_ids=[] short-circuits to [] without touching the DB."""

    results = await hybrid_search_files(
        db_session,
        file_ids=[],
        query="termination",
        query_embedding=None,
        top_k=10,
        alpha=1.0,
    )

    assert results == []


async def test_hybrid_search_files_excludes_non_ready_file(
    db_session: AsyncSession, owner_user: User
) -> None:
    """A file with ingestion_status='processing' contributes nothing even if requested."""

    processing_file = await _make_ready_file(
        db_session,
        owner_user,
        chunk_bodies=["The termination clause governs early exit from the agreement."],
        ingestion_status="processing",
    )

    results = await hybrid_search_files(
        db_session,
        file_ids=[processing_file.id],
        query="termination",
        query_embedding=None,
        top_k=10,
        alpha=1.0,
    )

    assert results == []


async def test_hybrid_search_files_excludes_soft_deleted_file(
    db_session: AsyncSession, owner_user: User
) -> None:
    """A soft-deleted file contributes nothing even if its id is requested."""

    deleted_file = await _make_ready_file(
        db_session,
        owner_user,
        chunk_bodies=["The termination clause governs early exit from the agreement."],
        deleted=True,
    )

    results = await hybrid_search_files(
        db_session,
        file_ids=[deleted_file.id],
        query="termination",
        query_embedding=None,
        top_k=10,
        alpha=1.0,
    )

    assert results == []
