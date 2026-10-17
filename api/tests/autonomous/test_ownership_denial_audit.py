"""Retrieval ownership refusals are distinct from ordinary validation errors."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import ToolIntent
from app.autonomous.guard import guarded_tool_call
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.file import File
from app.models.knowledge import KnowledgeBase
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


@pytest.mark.parametrize("mode", ["query", "file", "since"])
async def test_unknown_target_has_same_ownership_outcome(
    db_session: AsyncSession, seeded_matter_session: AutonomousSession, mode: str
) -> None:
    session = seeded_matter_session
    session.current_phase = "analysis"
    await db_session.flush()
    unknown_id = str(uuid.uuid4())
    params_by_mode: dict[str, dict[str, Any]] = {
        "query": {"kb_id": unknown_id, "query": "private"},
        "file": {"file_id": unknown_id},
        "since": {"kb_id": unknown_id, "since": "2026-01-01T00:00:00Z"},
    }
    with pytest.raises(ValueError, match="not accessible"):
        await guarded_tool_call(
            session, ToolIntent.retrieve_chunks, params_by_mode[mode], db_session, None
        )
    assert await _retrieval_outcomes(db_session, session) == ["ownership_denied", "started"]


@pytest.mark.parametrize("mode", ["query", "file", "since"])
async def test_hidden_owned_target_is_audited_as_ownership_denied(
    db_session: AsyncSession,
    seeded_matter_session: AutonomousSession,
    kb_with_one_indexed_file: KbOneFile,
    mode: str,
) -> None:
    session, kb = seeded_matter_session, kb_with_one_indexed_file
    session.current_phase = "analysis"
    session.user_id = kb.owner_id
    if mode != "file":
        await db_session.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.id == kb.kb_id)
            .values(archived_at=datetime.now(UTC))
        )
        params = (
            {"kb_id": str(kb.kb_id), "query": "private"}
            if mode == "query"
            else {"kb_id": str(kb.kb_id), "since": "2026-01-01T00:00:00Z"}
        )
    else:
        await db_session.execute(
            update(File).where(File.id == kb.file_id).values(deleted_at=datetime.now(UTC))
        )
        params = {"file_id": str(kb.file_id)}
    await db_session.flush()
    with pytest.raises(ValueError, match="not accessible"):
        await guarded_tool_call(session, ToolIntent.retrieve_chunks, params, db_session, None)
    assert await _retrieval_outcomes(db_session, session) == ["ownership_denied", "started"]


@pytest.mark.parametrize("mode", ["query", "file", "since"])
async def test_owned_retrieval_still_succeeds_without_denial(
    db_session: AsyncSession,
    seeded_matter_session: AutonomousSession,
    kb_with_one_indexed_file: KbOneFile,
    mode: str,
) -> None:
    session, kb = seeded_matter_session, kb_with_one_indexed_file
    session.current_phase = "analysis"
    session.user_id = kb.owner_id
    await db_session.flush()
    params_by_mode: dict[str, dict[str, Any]] = {
        "query": {"kb_id": str(kb.kb_id), "query": "confidential", "alpha": 1.0},
        "file": {"file_id": str(kb.file_id)},
        "since": {"kb_id": str(kb.kb_id), "since": "2026-01-01T00:00:00Z"},
    }
    result = await guarded_tool_call(
        session, ToolIntent.retrieve_chunks, params_by_mode[mode], db_session, None
    )
    assert result.data["summary"]["chunk_count"] == 1
    assert await _retrieval_outcomes(db_session, session) == ["started", "success"]


@pytest.mark.parametrize("params", [{}, {"query": "private"}, {"file_id": "invalid-uuid"}])
async def test_validation_error_is_not_ownership_denial(
    db_session: AsyncSession, seeded_matter_session: AutonomousSession, params: dict[str, Any]
) -> None:
    session = seeded_matter_session
    session.current_phase = "analysis"
    await db_session.flush()
    with pytest.raises(ValueError):
        await guarded_tool_call(session, ToolIntent.retrieve_chunks, params, db_session, None)
    assert await _retrieval_outcomes(db_session, session) == ["started"]


async def test_post_ownership_validation_error_is_not_denial(
    db_session: AsyncSession,
    seeded_matter_session: AutonomousSession,
    kb_with_one_indexed_file: KbOneFile,
) -> None:
    session, kb = seeded_matter_session, kb_with_one_indexed_file
    session.current_phase = "analysis"
    session.user_id = kb.owner_id
    await db_session.flush()
    with pytest.raises(ValueError, match="timezone-aware"):
        await guarded_tool_call(
            session,
            ToolIntent.retrieve_chunks,
            {"kb_id": str(kb.kb_id), "since": "2026-01-01T00:00:00"},
            db_session,
            None,
        )
    assert await _retrieval_outcomes(db_session, session) == ["started"]


async def test_denial_audit_failure_does_not_reach_retrieval(
    db_session: AsyncSession,
    seeded_matter_session: AutonomousSession,
    kb_with_one_indexed_file: KbOneFile,
) -> None:
    session, kb = seeded_matter_session, kb_with_one_indexed_file
    session.current_phase = "analysis"
    await db_session.flush()
    # A failed audit must remain visible and must not bypass the refusal.
    with (
        patch(
            "app.autonomous.guard.audit_retrieval_ownership_denial",
            new=AsyncMock(side_effect=RuntimeError("audit unavailable")),
        ),
        patch(
            "app.autonomous.guard._handle_retrieve_chunks_query", new_callable=AsyncMock
        ) as retrieve,
    ):
        with pytest.raises(RuntimeError, match="audit unavailable"):
            await guarded_tool_call(
                session,
                ToolIntent.retrieve_chunks,
                {"kb_id": str(kb.kb_id), "query": "private"},
                db_session,
                None,
            )
        retrieve.assert_not_awaited()
    assert await _retrieval_outcomes(db_session, session) == ["started"]
