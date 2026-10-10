"""The bounded document read: refused outside a governed run, and behind the audited ownership check.

ADR 0038 adds a second way to read a file by id: one bounded span of its
canonical text (``file_id`` with ``offset`` and ``max_chars``). The chokepoint
refuses it to a session that is not a governed run, before any ownership
predicate. Behind that, the read keeps the ownership predicate of the
whole-file read as a second check, so a refusal there closes with the same
``ownership_denied`` audit row (#494) and never reaches the text.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import ToolIntent
from app.autonomous.guard import _handle_retrieve_chunks, guarded_tool_call
from app.errors import ToolNotGranted
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.file import File
from tests.autonomous.conftest import KbOneFile


async def _retrieval_outcomes(db: AsyncSession, session: AutonomousSession) -> list[str]:
    rows = (await db.scalars(select(AuditLog).where(AuditLog.resource_id == str(session.id)))).all()
    return sorted(
        row.details["outcome"]
        for row in rows
        if row.action == "autonomous_session.tool_call"
        and row.details
        and row.details.get("tool") == "retrieve_chunks"
    )


@pytest.mark.parametrize("target", ["unknown", "deleted", "another owner's"])
async def test_a_refused_bounded_read_is_audited_and_reads_nothing(
    db_session: AsyncSession,
    seeded_matter_session: AutonomousSession,
    kb_with_one_indexed_file: KbOneFile,
    target: str,
) -> None:
    session, kb = seeded_matter_session, kb_with_one_indexed_file
    file_id = kb.file_id
    if target == "unknown":
        file_id = uuid.uuid4()
    elif target == "deleted":
        session.user_id = kb.owner_id
        await db_session.execute(
            update(File).where(File.id == kb.file_id).values(deleted_at=datetime.now(UTC))
        )
    # "another owner's": the session keeps its own owner, who does not own the file.
    await db_session.flush()
    # The handler as the chokepoint calls it for a step of a run, which is the
    # only caller the chokepoint lets through to the bounded read.
    with patch(
        "app.autonomous.guard._handle_read_document_text", new_callable=AsyncMock
    ) as read_text:
        with pytest.raises(ValueError, match="not accessible"):
            await _handle_retrieve_chunks(
                {"file_id": str(file_id), "offset": 0, "max_chars": 100},
                db=db_session,
                owner_id=session.user_id,
                retrieval_session=session,
            )
        read_text.assert_not_awaited()
    assert await _retrieval_outcomes(db_session, session) == ["ownership_denied"]


async def test_an_owned_bounded_read_passes_the_ownership_check_without_a_denial(
    db_session: AsyncSession,
    seeded_matter_session: AutonomousSession,
    kb_with_one_indexed_file: KbOneFile,
) -> None:
    session, kb = seeded_matter_session, kb_with_one_indexed_file
    session.user_id = kb.owner_id
    await db_session.flush()
    result = await _handle_retrieve_chunks(
        {"file_id": str(kb.file_id), "offset": 0, "max_chars": 100},
        db=db_session,
        owner_id=session.user_id,
        retrieval_session=session,
    )
    assert result.data["summary"]["file_id"] == str(kb.file_id)
    assert result.data["text"]
    assert await _retrieval_outcomes(db_session, session) == []


async def test_a_session_that_is_not_a_run_is_refused_the_bounded_read(
    db_session: AsyncSession,
    seeded_matter_session: AutonomousSession,
    kb_with_one_indexed_file: KbOneFile,
) -> None:
    session, kb = seeded_matter_session, kb_with_one_indexed_file
    session.current_phase = "analysis"
    # The file is the session owner's, so the ownership check would pass it.
    session.user_id = kb.owner_id
    await db_session.flush()
    with patch(
        "app.autonomous.guard._handle_read_document_text", new_callable=AsyncMock
    ) as read_text:
        with pytest.raises(ToolNotGranted, match="requires a governed run"):
            await guarded_tool_call(
                session,
                ToolIntent.retrieve_chunks,
                {"file_id": str(kb.file_id), "offset": 0, "max_chars": 100},
                db_session,
                None,
            )
        read_text.assert_not_awaited()
    assert await _retrieval_outcomes(db_session, session) == []
    # The whole-file read such a session had before ADR 0038 is still served.
    whole = await guarded_tool_call(
        session,
        ToolIntent.retrieve_chunks,
        {"file_id": str(kb.file_id)},
        db_session,
        None,
    )
    assert whole.data["chunks"]
    assert await _retrieval_outcomes(db_session, session) == ["started", "success"]
