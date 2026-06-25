import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.message_tool_source import MessageToolSource
from app.models.user import User

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seeded_message(db_session):
    """Seed a user + chat + assistant message; yield the message id."""
    user = User(
        email=f"ledger-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role="member",
    )
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="ledger test")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="answer")
    db_session.add(msg)
    await db_session.flush()
    return msg.id


@pytest.mark.asyncio
async def test_ledger_entry_roundtrips(db_session, seeded_message):
    """A single-FK entry referencing a real tool-source row persists and reads back."""
    chat_id = (
        await db_session.execute(select(Message.chat_id).where(Message.id == seeded_message))
    ).scalar_one()
    source = MessageToolSource(
        message_id=seeded_message, source_kind="caselaw", label="Cluster 1",
        subtitle=None, url=None, external_ref="1", provider="courtlistener", tool="get_cluster",
    )
    db_session.add(source)
    await db_session.flush()
    entry = CitationLedgerEntry(
        chat_id=chat_id,
        message_id=seeded_message,
        source_kind="caselaw",
        message_tool_source_id=source.id,
        verification_status="provenance",
        provider="courtlistener",
    )
    db_session.add(entry)
    await db_session.flush()
    got = (
        await db_session.execute(
            select(CitationLedgerEntry).where(CitationLedgerEntry.message_id == seeded_message)
        )
    ).scalar_one()
    assert got.message_tool_source_id == source.id
    assert got.message_citation_id is None
    assert got.verification_status == "provenance"
    assert got.treatment_id is None


@pytest.mark.asyncio
async def test_exactly_one_fk_check_rejects_zero_and_two(db_session, seeded_message):
    chat_id = (
        await db_session.execute(select(Message.chat_id).where(Message.id == seeded_message))
    ).scalar_one()
    # zero FKs -> CHECK violation
    db_session.add(
        CitationLedgerEntry(
            chat_id=chat_id, message_id=seeded_message,
            source_kind="kb_document", verification_status="exact_match",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
    # two FKs -> CHECK violation
    db_session.add(
        CitationLedgerEntry(
            chat_id=chat_id, message_id=seeded_message,
            source_kind="kb_document", verification_status="exact_match",
            message_citation_id=uuid.uuid4(), message_tool_source_id=uuid.uuid4(),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
