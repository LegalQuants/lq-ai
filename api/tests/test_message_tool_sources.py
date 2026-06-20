from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MessageToolSource
from app.models.chat import Chat, Message
from app.models.user import User
from app.security import hash_password

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def owner_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"src-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Sources Test Owner",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _assistant_message(db_session: AsyncSession, owner: User) -> tuple[Chat, Message]:
    chat = Chat(owner_id=owner.id, project_id=None, title="src-chat")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="answer")
    db_session.add(msg)
    await db_session.flush()
    return chat, msg


@pytest.mark.asyncio
async def test_message_tool_source_roundtrips(db_session: AsyncSession, owner_user: User):
    _chat, msg = await _assistant_message(db_session, owner_user)
    row = MessageToolSource(
        message_id=msg.id,
        source_kind="caselaw",
        label="Roe v. Wade",
        subtitle="scotus · 1973-01-22",
        url="https://www.courtlistener.com/opinion/42/",
        external_ref="42",
        provider="courtlistener",
        tool="search_case_law",
    )
    db_session.add(row)
    await db_session.flush()
    got = (
        await db_session.execute(
            select(MessageToolSource).where(MessageToolSource.message_id == msg.id)
        )
    ).scalar_one()
    assert got.label == "Roe v. Wade"
    assert got.source_kind == "caselaw"
    assert got.external_ref == "42"
    assert got.created_at is not None
