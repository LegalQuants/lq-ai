import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.citation.ledger import assemble_ledger_entries
from app.models.chat import Chat, Message, MessageCitation
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.message_caselaw_citation import MessageCaselawCitation
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


@pytest.mark.asyncio
async def test_assembles_one_entry_per_source_row(db_session, seeded_message):
    mid = seeded_message
    # A KB-document citation (verified) — needs a real source_file_id (files row).
    # Reuse the message_tool_sources + caselaw rows that DON'T need a file FK,
    # plus a caselaw citation, to exercise all three source kinds without a file.
    db_session.add(
        MessageCaselawCitation(
            message_id=mid, opinion_id=11, cluster_id=22,
            source_offset_start=0, source_offset_end=5, source_text="hello",
            verified=True, verification_method="exact_match", verification_confidence=1.0,
        )
    )
    db_session.add(
        MessageToolSource(
            message_id=mid, source_kind="caselaw", label="Cluster 22",
            subtitle=None, url=None, external_ref="22", provider="courtlistener", tool="get_cluster",
        )
    )
    await db_session.flush()

    n = await assemble_ledger_entries(db_session, message_id=mid)
    await db_session.flush()

    entries = (
        await db_session.execute(
            select(CitationLedgerEntry).where(CitationLedgerEntry.message_id == mid)
        )
    ).scalars().all()
    assert n == 2
    kinds = {e.source_kind for e in entries}
    assert kinds == {"caselaw"}  # one from the caselaw citation, one from the tool source
    by_fk = {
        "caselaw_citation": [e for e in entries if e.message_caselaw_citation_id is not None],
        "tool_source": [e for e in entries if e.message_tool_source_id is not None],
    }
    assert len(by_fk["caselaw_citation"]) == 1
    assert by_fk["caselaw_citation"][0].verification_status == "exact_match"
    assert by_fk["caselaw_citation"][0].confidence == 1.0
    assert by_fk["caselaw_citation"][0].provider == "courtlistener"
    assert len(by_fk["tool_source"]) == 1
    assert by_fk["tool_source"][0].verification_status == "provenance"
    assert by_fk["tool_source"][0].confidence is None
    assert by_fk["tool_source"][0].provider == "courtlistener"
    assert by_fk["tool_source"][0].retrieved_at is not None


@pytest.mark.asyncio
async def test_no_sources_yields_no_entries(db_session, seeded_message):
    n = await assemble_ledger_entries(db_session, message_id=seeded_message)
    assert n == 0
