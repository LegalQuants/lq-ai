"""Shared pytest fixtures for api/tests/citation/."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.user import User


@pytest.fixture
async def seeded(db_session: AsyncSession):
    """Seed: User → Chat → assistant Message → MessageCaselawCitation(cluster_id=2812209)
    → CitationLedgerEntry.  Returns (msg_id, chat_id, cc, entry)."""
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="t")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="x")
    db_session.add(msg)
    await db_session.flush()
    cc = MessageCaselawCitation(
        message_id=msg.id,
        opinion_id=2812209,
        cluster_id=2812209,
        source_offset_start=0,
        source_offset_end=5,
        source_text="quote",
        verified=True,
        verification_method="exact_match",
    )
    db_session.add(cc)
    await db_session.flush()
    entry = CitationLedgerEntry(
        chat_id=chat.id,
        message_id=msg.id,
        source_kind="caselaw",
        message_caselaw_citation_id=cc.id,
        verification_status="exact_match",
    )
    db_session.add(entry)
    await db_session.flush()
    return msg.id, chat.id, cc, entry
