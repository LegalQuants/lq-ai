"""Shared fixtures for autonomous-package tests.

Currently scoped to the M4 real-executor-work additions (Task 6):

- :func:`kb_with_one_indexed_file` — KB + file + document + one chunk
  that is queryable via hybrid search (FTS) AND fetchable directly by
  ``file_id``.  Used by mode-1 (query) and mode-2 (file_id) tests of
  :func:`app.autonomous.guard._handle_retrieve_chunks`.
- :func:`kb_with_old_and_new_files` — KB with TWO attached files;
  ``old_file`` has ``KnowledgeBaseFile.attached_at`` set far in the
  past, ``new_file`` has it at "now".  Used by mode-3 (``since``)
  tests to verify the since-cutoff filters correctly.

Both fixtures populate the ``content_tsv`` generated column by issuing
a no-op UPDATE — mirrors the pattern in
:mod:`tests.autonomous.test_autonomous_observability` so FTS works
under the per-test SAVEPOINT-rollback session.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk
from app.models.file import File as FileModel
from app.models.knowledge import KnowledgeBase, KnowledgeBaseFile
from app.models.user import User
from app.security import hash_password


@dataclass
class KbOneFile:
    """Bundle exposing the IDs a Task-6 test needs.

    ``file_id`` is the :attr:`File.id` of the attached file — what a
    real caller would pass into ``_handle_retrieve_chunks(file_id=...)``.
    ``document_id`` is the matching :attr:`Document.id` — the value
    that appears in ``chunk["document_id"]`` per the existing
    query-path payload shape.
    """

    kb_id: uuid.UUID
    file_id: uuid.UUID
    document_id: uuid.UUID
    chunk_id: uuid.UUID


@dataclass
class KbTwoFiles:
    """Bundle exposing IDs for the ``since`` cutoff test (Mode 3).

    ``old_file_id`` was attached far in the past (backdated 1 hour);
    ``new_file_id`` was attached at "now".  A test passing a
    5-minute-ago ``since`` should see only ``new_file_id``'s chunks.
    """

    kb_id: uuid.UUID
    old_file_id: uuid.UUID
    new_file_id: uuid.UUID


_CHUNK_TEXT_DEFAULT = (
    "This Non-Disclosure Agreement is entered into between the parties "
    "and the receiving party shall keep all test information confidential."
)


async def _make_owner(db: AsyncSession) -> User:
    user = User(
        email=f"u-retr-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_kb(db: AsyncSession, *, owner: User) -> KnowledgeBase:
    kb = KnowledgeBase(
        owner_id=owner.id,
        name=f"retr-kb-{uuid.uuid4().hex[:6]}",
        hybrid_alpha=1.0,  # FTS-only — no embedding needed for these tests
    )
    db.add(kb)
    await db.flush()
    return kb


async def _attach_file_with_chunk(
    db: AsyncSession,
    *,
    owner: User,
    kb: KnowledgeBase,
    chunk_text: str = _CHUNK_TEXT_DEFAULT,
    attached_at: datetime | None = None,
) -> tuple[FileModel, Document, DocumentChunk]:
    """Create a file + document + one chunk attached to ``kb``.

    If ``attached_at`` is provided, the ``KnowledgeBaseFile`` row is
    written with that timestamp (used by
    :func:`kb_with_old_and_new_files` to backdate the "old" file).
    Otherwise the DB default (``now()``) wins.
    """
    f = FileModel(
        owner_id=owner.id,
        filename=f"retr-{uuid.uuid4().hex[:6]}.txt",
        mime_type="text/plain",
        size_bytes=len(chunk_text),
        hash_sha256="f" * 64,
        storage_path=f"retr-fixture/{uuid.uuid4()}",
        ingestion_status="ready",
    )
    db.add(f)
    await db.flush()

    kbf_kwargs: dict[str, object] = {"kb_id": kb.id, "file_id": f.id}
    if attached_at is not None:
        kbf_kwargs["attached_at"] = attached_at
    kbf = KnowledgeBaseFile(**kbf_kwargs)
    db.add(kbf)
    await db.flush()

    doc = Document(
        file_id=f.id,
        parser="pymupdf-only",
        parser_version="pymupdf=1.27",
        page_count=1,
        character_count=len(chunk_text),
        normalized_content=chunk_text,
        was_ocrd=False,
    )
    db.add(doc)
    await db.flush()

    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content=chunk_text,
        page_start=1,
        page_end=1,
        char_offset_start=0,
        char_offset_end=len(chunk_text),
    )
    db.add(chunk)
    await db.flush()
    return f, doc, chunk


@pytest_asyncio.fixture
async def kb_with_one_indexed_file(db_session: AsyncSession) -> KbOneFile:
    """KB + one attached file with a single chunk; FTS-queryable.

    Returns ``kb_id``, ``file_id`` (files.id — the real semantic file
    identifier callers pass into ``_handle_retrieve_chunks``),
    ``document_id`` (documents.id — appears in ``chunk["document_id"]``
    per the existing payload shape), and ``chunk_id``.
    """
    owner = await _make_owner(db_session)
    kb = await _make_kb(db_session, owner=owner)
    f, doc, chunk = await _attach_file_with_chunk(db_session, owner=owner, kb=kb)
    # Force Postgres to compute the generated content_tsv column so FTS works.
    await db_session.execute(text("UPDATE document_chunks SET chunk_index = chunk_index"))
    await db_session.flush()
    return KbOneFile(kb_id=kb.id, file_id=f.id, document_id=doc.id, chunk_id=chunk.id)


@pytest_asyncio.fixture
async def kb_with_old_and_new_files(db_session: AsyncSession) -> KbTwoFiles:
    """KB with TWO attached files: one backdated, one at "now".

    ``old_file`` has ``KnowledgeBaseFile.attached_at = now - 1 hour``;
    ``new_file`` has the DB default (``now()``).  A test passing
    ``since = now - 5 minutes`` should see only ``new_file``'s chunks.
    """
    owner = await _make_owner(db_session)
    kb = await _make_kb(db_session, owner=owner)

    old_attached_at = datetime.now(UTC) - timedelta(hours=1)
    old_f, _, _ = await _attach_file_with_chunk(
        db_session,
        owner=owner,
        kb=kb,
        chunk_text="Old indexed contract text from last quarter.",
        attached_at=old_attached_at,
    )
    new_f, _, _ = await _attach_file_with_chunk(
        db_session,
        owner=owner,
        kb=kb,
        chunk_text="Fresh contract uploaded today for the autonomous run.",
    )

    await db_session.execute(text("UPDATE document_chunks SET chunk_index = chunk_index"))
    await db_session.flush()

    return KbTwoFiles(kb_id=kb.id, old_file_id=old_f.id, new_file_id=new_f.id)
