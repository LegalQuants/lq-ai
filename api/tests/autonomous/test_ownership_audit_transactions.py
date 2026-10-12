"""Ownership audit persistence uses real executor and PostgreSQL boundaries."""

from __future__ import annotations

import uuid
from typing import Any, cast
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.autonomous.enums import ToolIntent
from app.autonomous.executor import run_autonomous_session
from app.autonomous.guard import guarded_tool_call
from app.clients.gateway import GatewayClient
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.user import User
from tests.autonomous.conftest import _make_optedin_user, _make_running_session
from tests.autonomous.test_agentic_loop import _ScriptedGateway


async def _seed_run(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = await _make_optedin_user(db)
    session = await _make_running_session(
        db,
        user=user,
        trigger_kind="manual",
        params={"skill_ref": "alpha-test-skill", "query": "Research the test agreement"},
    )
    await db.commit()
    return user.id, session.id


async def _audit_details(db: AsyncSession, session_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (await db.scalars(select(AuditLog).where(AuditLog.resource_id == str(session_id)))).all()
    return [row.details for row in rows if row.details]


async def _cleanup_run(engine: AsyncEngine, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
    async with AsyncSession(engine) as cleanup:
        await cleanup.execute(delete(AuditLog).where(AuditLog.resource_id == str(session_id)))
        await cleanup.execute(delete(User).where(User.id == user_id))
        await cleanup.commit()


@pytest.mark.parametrize("commit", [True, False])
async def test_denial_audit_follows_caller_commit_or_rollback(
    test_engine: AsyncEngine, commit: bool
) -> None:
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        user_id, session_id = await _seed_run(db)
        try:
            session = await db.get(AutonomousSession, session_id)
            assert session is not None
            with pytest.raises(ValueError, match="not accessible"):
                await guarded_tool_call(
                    session,
                    ToolIntent.retrieve_chunks,
                    {"file_id": str(uuid.uuid4())},
                    db,
                    None,
                )
            # Another connection cannot see the flushed row before commit.
            async with AsyncSession(test_engine) as reader:
                assert await _audit_details(reader, session_id) == []
            if commit:
                await db.commit()
            else:
                await db.rollback()
            async with AsyncSession(test_engine) as reader:
                details = await _audit_details(reader, session_id)
                denied = [d for d in details if d.get("outcome") == "ownership_denied"]
                assert denied == (
                    [{"tool": "retrieve_chunks", "outcome": "ownership_denied"}] if commit else []
                )
        finally:
            await db.rollback()
            await _cleanup_run(test_engine, user_id, session_id)


@pytest.mark.parametrize("mode", ["query", "file", "since"])
async def test_executor_commits_denial_and_completes_after_nonfatal_loop_refusal(
    test_engine: AsyncEngine, _installed_skill_registry: None, mode: str
) -> None:
    unknown_id = str(uuid.uuid4())
    params_by_mode: dict[str, dict[str, Any]] = {
        "query": {"kb_id": unknown_id, "query": "private"},
        "file": {"file_id": unknown_id},
        "since": {"kb_id": unknown_id, "since": "2026-01-01T00:00:00Z"},
    }
    gateway = _ScriptedGateway(
        [
            {
                "next_intent": "retrieve_chunks",
                "args": params_by_mode[mode],
                "rationale": "test",
            },
            {"done": True, "rationale": "done"},
        ]
    )
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        user_id, session_id = await _seed_run(db)
        try:
            await run_autonomous_session(
                db, session_id=session_id, gateway=cast(GatewayClient, gateway)
            )
            async with AsyncSession(test_engine) as reader:
                saved = await reader.get(AutonomousSession, session_id)
                assert saved is not None and saved.status == "completed"
                details = await _audit_details(reader, session_id)
                denied = [d for d in details if d.get("outcome") == "ownership_denied"]
                assert denied == [{"tool": "retrieve_chunks", "outcome": "ownership_denied"}]
                outcomes = [d["outcome"] for d in details if d.get("tool") == "retrieve_chunks"]
                assert sorted(outcomes) == ["ownership_denied", "started"]
        finally:
            await db.rollback()
            await _cleanup_run(test_engine, user_id, session_id)


async def test_executor_recovers_from_denial_audit_database_failure(
    test_engine: AsyncEngine, _installed_skill_registry: None
) -> None:
    gateway = _ScriptedGateway(
        [
            {
                "next_intent": "retrieve_chunks",
                "args": {"file_id": str(uuid.uuid4())},
                "rationale": "test",
            },
        ]
    )

    async def break_audit(db: AsyncSession, session: AutonomousSession) -> None:
        # A real PostgreSQL error poisons the transaction; a mocked exception
        # alone cannot verify the executor's rollback/re-fetch recovery.
        await db.execute(text("SELECT 1 / 0"))

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        user_id, session_id = await _seed_run(db)
        try:
            with patch("app.autonomous.guard.audit_retrieval_ownership_denial", new=break_audit):
                await run_autonomous_session(
                    db, session_id=session_id, gateway=cast(GatewayClient, gateway)
                )
            async with AsyncSession(test_engine) as reader:
                saved = await reader.get(AutonomousSession, session_id)
                assert saved is not None and saved.status == "failed"
                assert saved.error
                assert await _audit_details(reader, session_id) == []
            # No synthesis or private retrieval proceeds after the DB failure.
            assert len(gateway.captured_requests) == 1
        finally:
            await db.rollback()
            await _cleanup_run(test_engine, user_id, session_id)
