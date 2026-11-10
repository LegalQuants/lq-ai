"""Model + migration tests for tool_call_log (PR5a / 0053).

Verifies:

* Table exists with the expected columns and PK after the 0053 migration runs.
* No raw-payload columns: the schema contains only counts/types/digest fields —
  no 'args', 'result', 'response', or 'payload' columns (counts/types only).
* FK cascade: deleting the user removes owned ``tool_call_log`` rows.
* Nullable columns (user_id, chat_id, message_id, session_id, intent,
  cost_usd, args_digest, request_id) are genuinely nullable.
* confirmation_state defaults to 'not_required'.

Tests use the session-scoped migrated DB + per-test rollback from conftest.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tool_call_log import ToolCallLog
from app.models.user import User
from app.security.passwords import hash_password

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user() -> User:
    """Return an unsaved User with a unique email."""
    return User(
        email=f"tcl-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("test-pass"),
        is_admin=False,
        mfa_enabled=False,
    )


def _make_log(user_id: uuid.UUID | None = None) -> ToolCallLog:
    """Return an unsaved ToolCallLog row (chat-origin, no raw payloads)."""
    return ToolCallLog(
        origin="chat",
        user_id=user_id,
        provider="courtlistener",
        tool="search_case_law",
        tier=2,
        outcome="pending",
        args_digest="sha256:abcd1234",  # digest only — never raw args
    )


# ---------------------------------------------------------------------------
# Column / schema tests (unit — no DB required)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_tool_call_log_columns() -> None:
    """All spec'd columns are present on the ORM model."""
    cols = ToolCallLog.__table__.columns.keys()
    expected = {
        "id",
        "origin",
        "user_id",
        "chat_id",
        "message_id",
        "session_id",
        "intent",
        "provider",
        "tool",
        "tier",
        "confirmation_state",
        "outcome",
        "cost_usd",
        "args_digest",
        "request_id",
        "created_at",
        "updated_at",
    }
    assert set(cols) >= expected


@pytest.mark.unit
def test_tool_call_log_primary_key() -> None:
    """PK is 'id' only (single UUID column)."""
    pk = {c.name for c in ToolCallLog.__table__.primary_key}
    assert pk == {"id"}


@pytest.mark.unit
def test_tool_call_log_no_raw_payload_columns() -> None:
    """Ensure no raw-payload column names exist (counts/types only discipline)."""
    cols = set(ToolCallLog.__table__.columns.keys())
    forbidden = {"args", "result", "response", "payload", "raw_args", "raw_result"}
    assert cols.isdisjoint(forbidden), (
        f"Raw-payload columns found in tool_call_log: {cols & forbidden}"
    )


@pytest.mark.unit
def test_tool_call_log_user_fk_cascade() -> None:
    """The user_id FK is defined with ON DELETE CASCADE and the expected name."""
    fk_col = ToolCallLog.__table__.columns["user_id"]
    fks = list(fk_col.foreign_keys)
    assert len(fks) == 1
    fk = fks[0]
    assert fk.column.table.name == "users"
    assert fk.ondelete == "CASCADE"
    assert fk.name == "fk_tool_call_log_user"


# ---------------------------------------------------------------------------
# Integration tests (require migrated DB via conftest)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_tool_call_log_row_roundtrips(db_session: AsyncSession) -> None:
    """A log row persists and reads back with all fields intact."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    log = ToolCallLog(
        origin="autonomous",
        user_id=user.id,
        session_id=uuid.uuid4(),
        intent="retrieve_caselaw",
        provider="courtlistener",
        tool="search_case_law",
        tier=2,
        confirmation_state="not_required",
        outcome="executed",
        cost_usd=Decimal("0.001234"),
        args_digest="sha256:deadbeef",
        request_id="req-abc123",
    )
    db_session.add(log)
    await db_session.flush()

    result = await db_session.execute(select(ToolCallLog).where(ToolCallLog.id == log.id))
    row = result.scalar_one()
    assert row.origin == "autonomous"
    assert row.user_id == user.id
    assert row.intent == "retrieve_caselaw"
    assert row.provider == "courtlistener"
    assert row.tool == "search_case_law"
    assert row.tier == 2
    assert row.outcome == "executed"
    assert row.cost_usd == Decimal("0.001234")
    assert row.args_digest == "sha256:deadbeef"
    assert row.request_id == "req-abc123"
    assert row.created_at is not None
    assert row.updated_at is not None


@pytest.mark.integration
async def test_tool_call_log_confirmation_state_default(db_session: AsyncSession) -> None:
    """confirmation_state defaults to 'not_required' when not supplied."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    log = _make_log(user_id=user.id)
    db_session.add(log)
    await db_session.flush()

    result = await db_session.execute(select(ToolCallLog).where(ToolCallLog.id == log.id))
    row = result.scalar_one()
    assert row.confirmation_state == "not_required"


@pytest.mark.integration
async def test_tool_call_log_nullable_columns(db_session: AsyncSession) -> None:
    """Nullable columns (user_id, chat_id, ...) accept None."""
    log = ToolCallLog(
        origin="chat",
        user_id=None,
        chat_id=None,
        message_id=None,
        session_id=None,
        intent=None,
        provider="internal",
        tool="noop",
        tier=0,
        outcome="pending",
        cost_usd=None,
        args_digest=None,
        request_id=None,
    )
    db_session.add(log)
    await db_session.flush()

    result = await db_session.execute(select(ToolCallLog).where(ToolCallLog.id == log.id))
    row = result.scalar_one()
    assert row.user_id is None
    assert row.chat_id is None
    assert row.cost_usd is None
    assert row.args_digest is None


@pytest.mark.integration
async def test_tool_call_log_user_cascade_delete(db_session: AsyncSession) -> None:
    """Deleting a user CASCADE-deletes their tool_call_log rows."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    user_id = user.id

    log = _make_log(user_id=user_id)
    db_session.add(log)
    await db_session.flush()
    log_id = log.id

    # Delete via raw SQL to bypass ORM; FK ON DELETE CASCADE fires at DB level.
    await db_session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    await db_session.flush()

    result = await db_session.execute(select(ToolCallLog).where(ToolCallLog.id == log_id))
    assert result.scalars().all() == []
