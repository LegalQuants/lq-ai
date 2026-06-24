"""Integration tests for the message_caselaw_citations table.

Tests round-trip persistence of quote-verified caselaw citation rows.
P1-A1 / ADR 0018 D2.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat, Message
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.user import User
from app.security import hash_password

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seeded_chat_message(db_session: AsyncSession) -> uuid.UUID:
    """Seed a user + chat + assistant message; yield the message id."""
    user = User(
        email=f"cite-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Citation Test User",
        hashed_password=hash_password("hunter2"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()

    chat = Chat(owner_id=user.id, project_id=None, title="cite-chat")
    db_session.add(chat)
    await db_session.flush()

    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="relevant passage")
    db_session.add(msg)
    await db_session.flush()

    return msg.id


@pytest.mark.asyncio
async def test_caselaw_citation_row_roundtrips(
    db_session: AsyncSession, seeded_chat_message: uuid.UUID
) -> None:
    """A verified caselaw-citation row persists and reads back."""
    message_id = seeded_chat_message  # fixture: an existing messages.id (assistant)
    row = MessageCaselawCitation(
        message_id=message_id,
        opinion_id=12345,
        cluster_id=999,
        source_offset_start=10,
        source_offset_end=42,
        source_text="the implied covenant of good faith",
        verified=True,
        verification_method="exact_match",
        verification_confidence=1.0,
        partial=False,
    )
    db_session.add(row)
    await db_session.flush()

    got = (
        await db_session.execute(
            select(MessageCaselawCitation).where(MessageCaselawCitation.message_id == message_id)
        )
    ).scalar_one()
    assert got.opinion_id == 12345
    assert got.verified is True
    assert got.verification_method == "exact_match"
    assert got.id is not None
