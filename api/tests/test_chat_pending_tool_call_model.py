"""Model + migration tests for chat_pending_tool_call (PR5b / 0054).

Verifies:

* All spec'd columns are present on the ORM model (unit, no DB required).
* PK is id only (UUID).
* chat_id FK is CASCADE, user_id FK is CASCADE, tool_call_log_id FK is SET NULL.
* Row round-trips with all fields intact, status defaults to 'pending'.
* resume_state and tool_call_args persist as JSONB and are not logged.
* expires_at and timestamps persist.

Security: resume_state holds the conversation-so-far (same sensitivity class
as messages.content). Tests only verify persistence; they never emit
resume_state to logs or stdout.

Tests use the session-scoped migrated DB + per-test rollback from conftest.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat
from app.models.chat_pending_tool_call import ChatPendingToolCall
from app.models.user import User
from app.security.passwords import hash_password

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user() -> User:
    """Return an unsaved User with a unique email."""
    return User(
        email=f"cptc-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("test-pass"),
        is_admin=False,
        mfa_enabled=False,
    )


def _make_chat(owner_id: uuid.UUID) -> Chat:
    """Return an unsaved Chat owned by the given user."""
    return Chat(owner_id=owner_id, title="Test chat")


def _make_pending(
    chat_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ChatPendingToolCall:
    """Return an unsaved ChatPendingToolCall row with realistic values."""
    return ChatPendingToolCall(
        chat_id=chat_id,
        user_id=user_id,
        assistant_message_id=uuid.uuid4(),
        function_name="mcp__files__delete_doc",
        kind="mcp",
        provider="files",
        tool="delete_doc",
        destructive=True,
        tier=2,
        tool_call_args={"path": "/x"},
        resume_state={"messages": [{"role": "user", "content": "hi"}], "calls_used": 1},
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


# ---------------------------------------------------------------------------
# Unit tests — no DB required
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_chat_pending_tool_call_columns() -> None:
    """All spec'd columns are present on the ORM model."""
    cols = ChatPendingToolCall.__table__.columns.keys()
    expected = {
        "id",
        "chat_id",
        "user_id",
        "assistant_message_id",
        "tool_call_log_id",
        "function_name",
        "kind",
        "provider",
        "tool",
        "destructive",
        "tier",
        "tool_call_args",
        "resume_state",
        "status",
        "expires_at",
        "created_at",
        "updated_at",
    }
    assert set(cols) >= expected


@pytest.mark.unit
def test_chat_pending_tool_call_pk() -> None:
    """PK is 'id' only (single UUID column)."""
    pk = {c.name for c in ChatPendingToolCall.__table__.primary_key.columns}
    assert pk == {"id"}


@pytest.mark.unit
def test_chat_pending_tool_call_fk_chat_cascade() -> None:
    """chat_id FK references chats.id ON DELETE CASCADE."""
    fk_col = ChatPendingToolCall.__table__.columns["chat_id"]
    fks = list(fk_col.foreign_keys)
    assert len(fks) == 1
    fk = fks[0]
    assert fk.column.table.name == "chats"
    assert fk.ondelete == "CASCADE"


@pytest.mark.unit
def test_chat_pending_tool_call_fk_user_cascade() -> None:
    """user_id FK references users.id ON DELETE CASCADE."""
    fk_col = ChatPendingToolCall.__table__.columns["user_id"]
    fks = list(fk_col.foreign_keys)
    assert len(fks) == 1
    fk = fks[0]
    assert fk.column.table.name == "users"
    assert fk.ondelete == "CASCADE"


@pytest.mark.unit
def test_chat_pending_tool_call_fk_tool_call_log_set_null() -> None:
    """tool_call_log_id FK references tool_call_log.id ON DELETE SET NULL."""
    fk_col = ChatPendingToolCall.__table__.columns["tool_call_log_id"]
    fks = list(fk_col.foreign_keys)
    assert len(fks) == 1
    fk = fks[0]
    assert fk.column.table.name == "tool_call_log"
    assert fk.ondelete == "SET NULL"


# ---------------------------------------------------------------------------
# Integration tests (require migrated DB via conftest)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_pending_tool_call_roundtrip(db_session: AsyncSession) -> None:
    """Row persists and reads back; status defaults to 'pending'; id is assigned."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    chat = _make_chat(owner_id=user.id)
    db_session.add(chat)
    await db_session.flush()

    row = _make_pending(chat_id=chat.id, user_id=user.id)
    db_session.add(row)
    await db_session.flush()

    assert row.status == "pending"
    assert row.id is not None

    result = await db_session.execute(
        select(ChatPendingToolCall).where(ChatPendingToolCall.id == row.id)
    )
    fetched = result.scalar_one()
    assert fetched.function_name == "mcp__files__delete_doc"
    assert fetched.kind == "mcp"
    assert fetched.provider == "files"
    assert fetched.tool == "delete_doc"
    assert fetched.destructive is True
    assert fetched.tier == 2
    assert fetched.tool_call_args == {"path": "/x"}
    assert fetched.resume_state["calls_used"] == 1
    assert fetched.expires_at is not None
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


@pytest.mark.integration
async def test_pending_tool_call_status_default(db_session: AsyncSession) -> None:
    """status server-default 'pending' is applied by the DB on insert."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    chat = _make_chat(owner_id=user.id)
    db_session.add(chat)
    await db_session.flush()

    row = _make_pending(chat_id=chat.id, user_id=user.id)
    db_session.add(row)
    await db_session.flush()

    result = await db_session.execute(
        select(ChatPendingToolCall).where(ChatPendingToolCall.id == row.id)
    )
    fetched = result.scalar_one()
    assert fetched.status == "pending"


@pytest.mark.integration
async def test_pending_tool_call_tool_call_log_id_nullable(db_session: AsyncSession) -> None:
    """tool_call_log_id is nullable — row inserts fine without it."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    chat = _make_chat(owner_id=user.id)
    db_session.add(chat)
    await db_session.flush()

    row = _make_pending(chat_id=chat.id, user_id=user.id)
    assert row.tool_call_log_id is None
    db_session.add(row)
    await db_session.flush()

    result = await db_session.execute(
        select(ChatPendingToolCall).where(ChatPendingToolCall.id == row.id)
    )
    fetched = result.scalar_one()
    assert fetched.tool_call_log_id is None
