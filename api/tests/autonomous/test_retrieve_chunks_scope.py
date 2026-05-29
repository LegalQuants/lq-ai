"""Tests for ``_handle_retrieve_chunks`` scope extensions — M4 Task 6.

Covers the three modes of
:func:`app.autonomous.guard._handle_retrieve_chunks`:

1. ``query`` (existing path) — hybrid semantic+FTS search, unchanged.
2. ``file_id`` — file-scoped fetch in ``char_offset_start`` order.
3. ``since`` + ``kb_id`` — KB-scoped fetch of files whose
   ``KnowledgeBaseFile.attached_at`` > ``since``.

All three modes return the SAME ``{"summary": ..., "chunks": ...}``
shape, so downstream consumers (intake_node) are mode-agnostic.  The
test asserts both the shape and the scope semantics; the privacy
contract (no raw chunk text in ``data["summary"]``) is tested by
:mod:`test_autonomous_observability`.

Also asserts the "no mode applies" error message lists all three
options, so an invocation bug surfaces with an actionable failure.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.guard import _handle_retrieve_chunks
from tests.autonomous.conftest import KbOneFile, KbTwoFiles


async def test_retrieve_chunks_query_path_unchanged(
    db_session: AsyncSession, kb_with_one_indexed_file: KbOneFile
) -> None:
    """Mode 1 (existing query-path) keeps producing the documented shape.

    Uses ``alpha=1.0`` (FTS-only) so no embedding is required — matches
    the fixture's KB default and avoids a gateway call.
    """
    result = await _handle_retrieve_chunks(
        {
            "kb_id": str(kb_with_one_indexed_file.kb_id),
            "query": "confidential",
            "query_embedding": None,
            "alpha": 1.0,
            "top_k": 4,
        },
        db=db_session,
    )
    assert "summary" in result.data
    assert "chunks" in result.data
    assert isinstance(result.data["summary"]["chunk_count"], int)
    # FTS over the seeded chunk text matches "confidential".
    assert result.data["summary"]["chunk_count"] >= 1
    # Shape contract: every chunk has the keys downstream consumers
    # rely on, identical across all three modes.
    for chunk in result.data["chunks"]:
        assert set(chunk.keys()) >= {
            "chunk_id",
            "document_id",
            "file_id",
            "file_name",
            "content",
            "hybrid_score",
            "char_offset_start",
            "char_offset_end",
        }


async def test_retrieve_chunks_by_file_id(
    db_session: AsyncSession, kb_with_one_indexed_file: KbOneFile
) -> None:
    """Mode 2 (``file_id``): file-scoped fetch; no query needed.

    Asserts the returned chunks all belong to the requested file
    (``chunk["file_id"]`` matches the input) AND that the chunk's
    ``document_id`` equals the file's owning document — confirming
    the chunks → documents → files join resolves correctly.
    """
    result = await _handle_retrieve_chunks(
        {
            "kb_id": str(kb_with_one_indexed_file.kb_id),
            "file_id": str(kb_with_one_indexed_file.file_id),
        },
        db=db_session,
    )
    assert result.data["summary"]["chunk_count"] > 0
    for chunk in result.data["chunks"]:
        # The file_id we passed in flows back as-is on every chunk.
        assert chunk["file_id"] == str(kb_with_one_indexed_file.file_id)
        # And the chunk's document_id is the matching documents.id.
        assert chunk["document_id"] == str(kb_with_one_indexed_file.document_id)
    # Mode 2 is unranked — hybrid_score is None across the board.
    assert all(c["hybrid_score"] is None for c in result.data["chunks"])


async def test_retrieve_chunks_since_scope(
    db_session: AsyncSession, kb_with_old_and_new_files: KbTwoFiles
) -> None:
    """Mode 3 (``since`` + ``kb_id``): only files attached after cutoff.

    Cutoff is 5 min ago.  The fixture backdated ``old_file``'s
    attachment by 1 hour and left ``new_file``'s attachment at "now".
    So the returned chunk set must include ``new_file`` and exclude
    ``old_file``.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=5)
    result = await _handle_retrieve_chunks(
        {
            "kb_id": str(kb_with_old_and_new_files.kb_id),
            "since": cutoff.isoformat(),
        },
        db=db_session,
    )
    returned_file_ids = {c["file_id"] for c in result.data["chunks"]}
    assert str(kb_with_old_and_new_files.new_file_id) in returned_file_ids
    assert str(kb_with_old_and_new_files.old_file_id) not in returned_file_ids
    # Same unranked semantics as mode 2.
    assert all(c["hybrid_score"] is None for c in result.data["chunks"])


async def test_retrieve_chunks_since_accepts_aware_datetime(
    db_session: AsyncSession, kb_with_old_and_new_files: KbTwoFiles
) -> None:
    """Mode 3 also accepts an aware ``datetime`` directly (not just ISO str).

    The intake_node may pass a Python ``datetime`` straight through from
    ``schedule.last_run_at``; the handler must not require ISO
    serialisation at the call site.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=5)
    result = await _handle_retrieve_chunks(
        {
            "kb_id": str(kb_with_old_and_new_files.kb_id),
            "since": cutoff,
        },
        db=db_session,
    )
    returned_file_ids = {c["file_id"] for c in result.data["chunks"]}
    assert str(kb_with_old_and_new_files.new_file_id) in returned_file_ids
    assert str(kb_with_old_and_new_files.old_file_id) not in returned_file_ids


async def test_retrieve_chunks_no_mode_raises_actionable_error(
    db_session: AsyncSession,
) -> None:
    """No-mode input raises ``ValueError`` naming all three options.

    A programming-error at the call site (forgot to pass any of
    ``query`` / ``file_id`` / ``since`` + ``kb_id``) must surface with
    a message that points the caller at the right fix — not a silent
    empty result, not a generic KeyError.
    """
    with pytest.raises(ValueError) as excinfo:
        await _handle_retrieve_chunks({}, db=db_session)
    message = str(excinfo.value)
    assert "query" in message
    assert "file_id" in message
    assert "since" in message


@pytest.mark.asyncio
async def test_retrieve_chunks_since_rejects_naive_datetime(
    db_session: AsyncSession, kb_with_old_and_new_files: KbTwoFiles
) -> None:
    """Naive datetime (object) and naive ISO string (no offset) both raise
    ValueError — Postgres timestamps are tz-aware; comparing against a naive
    datetime would surface as a cryptic execution-time error otherwise."""
    naive_dt = datetime(2026, 5, 27, 12, 0, 0)  # no tzinfo
    with pytest.raises(ValueError, match="timezone-aware"):
        await _handle_retrieve_chunks(
            {
                "kb_id": str(kb_with_old_and_new_files.kb_id),
                "since": naive_dt,
            },
            db=db_session,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        await _handle_retrieve_chunks(
            {
                "kb_id": str(kb_with_old_and_new_files.kb_id),
                "since": "2026-05-27T12:00:00",  # naive ISO string (no offset)
            },
            db=db_session,
        )
