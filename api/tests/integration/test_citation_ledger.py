import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.citation.ledger import assemble_ledger_entries, resolve_ledger_entries
from app.models.chat import Chat, Message, MessageCitation
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.file import File as FileModel
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
        message_id=seeded_message,
        source_kind="caselaw",
        label="Cluster 1",
        subtitle=None,
        url=None,
        external_ref="1",
        provider="courtlistener",
        tool="get_cluster",
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
            chat_id=chat_id,
            message_id=seeded_message,
            source_kind="kb_document",
            verification_status="exact_match",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
    # two FKs -> CHECK violation
    db_session.add(
        CitationLedgerEntry(
            chat_id=chat_id,
            message_id=seeded_message,
            source_kind="kb_document",
            verification_status="exact_match",
            message_citation_id=uuid.uuid4(),
            message_tool_source_id=uuid.uuid4(),
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
            message_id=mid,
            opinion_id=11,
            cluster_id=22,
            source_offset_start=0,
            source_offset_end=5,
            source_text="hello",
            verified=True,
            verification_method="exact_match",
            verification_confidence=1.0,
        )
    )
    db_session.add(
        MessageToolSource(
            message_id=mid,
            source_kind="caselaw",
            label="Cluster 22",
            subtitle=None,
            url=None,
            external_ref="22",
            provider="courtlistener",
            tool="get_cluster",
        )
    )
    await db_session.flush()

    n = await assemble_ledger_entries(db_session, message_id=mid)
    await db_session.flush()

    entries = (
        (
            await db_session.execute(
                select(CitationLedgerEntry).where(CitationLedgerEntry.message_id == mid)
            )
        )
        .scalars()
        .all()
    )
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


@pytest.mark.asyncio
async def test_resolve_shapes_all_three_source_kinds(db_session, seeded_message):
    """Each entry resolves to its source block; passages present for quote kinds."""
    mid = seeded_message
    chat_id = (
        await db_session.execute(select(Message.chat_id).where(Message.id == mid))
    ).scalar_one()
    # caselaw citation + its provenance row + a KB-document citation (needs a File FK)
    owner_id = (
        await db_session.execute(select(Chat.owner_id).where(Chat.id == chat_id))
    ).scalar_one()
    f = FileModel(
        owner_id=owner_id,
        filename="doc.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        hash_sha256="0" * 64,
        storage_path=f"k/{uuid.uuid4().hex}",
    )
    db_session.add(f)
    await db_session.flush()
    doc_cite = MessageCitation(
        message_id=mid,
        source_file_id=f.id,
        source_offset_start=0,
        source_offset_end=5,
        source_page=3,
        source_text="hello",
        verified=True,
        verification_method="exact_match",
        verification_confidence=1.0,
    )
    caselaw_cite = MessageCaselawCitation(
        message_id=mid,
        opinion_id=11,
        cluster_id=22,
        source_offset_start=0,
        source_offset_end=5,
        source_text="world",
        verified=True,
        verification_method="tolerant_match",
        verification_confidence=0.95,
    )
    tool_src = MessageToolSource(
        message_id=mid,
        source_kind="caselaw",
        label="Cluster 22",
        subtitle=None,
        url="https://courtlistener.test/22",
        external_ref="22",
        provider="courtlistener",
        tool="get_cluster",
    )
    db_session.add_all([doc_cite, caselaw_cite, tool_src])
    await db_session.flush()
    await assemble_ledger_entries(db_session, message_id=mid)
    await db_session.flush()

    out = await resolve_ledger_entries(db_session, chat_id=chat_id)
    assert {e["source_kind"] for e in out} == {"kb_document", "caselaw"}
    # there are three entries (two share source_kind "caselaw"); assert count
    assert len(out) == 3

    kb = next(e for e in out if e["source"]["kind"] == "kb_document")
    assert kb["verification_status"] == "exact_match"
    assert kb["source"]["source_file_id"] == str(f.id)
    assert kb["source"]["passages"] == [
        {"text": "hello", "offset_start": 0, "offset_end": 5, "page": 3}
    ]

    case = next(e for e in out if "opinion_id" in e["source"])
    assert case["source"]["opinion_id"] == 11
    assert case["source"]["passages"][0]["text"] == "world"
    assert case["confidence"] == 0.95

    prov = next(e for e in out if "passages" not in e["source"])
    assert prov["verification_status"] == "provenance"
    assert prov["source"]["url"] == "https://courtlistener.test/22"
    assert prov["source"]["external_ref"] == "22"


@pytest.mark.asyncio
async def test_resolve_message_id_filter_and_empty(db_session, seeded_message):
    chat_id = (
        await db_session.execute(select(Message.chat_id).where(Message.id == seeded_message))
    ).scalar_one()
    assert await resolve_ledger_entries(db_session, chat_id=chat_id) == []
    # entry under a different message id is excluded by the filter
    src = MessageToolSource(
        message_id=seeded_message, source_kind="mcp", label="x", provider="srv", tool="t"
    )
    db_session.add(src)
    await db_session.flush()
    db_session.add(
        CitationLedgerEntry(
            chat_id=chat_id,
            message_id=seeded_message,
            source_kind="mcp",
            message_tool_source_id=src.id,
            verification_status="provenance",
        )
    )
    await db_session.flush()
    assert (
        len(await resolve_ledger_entries(db_session, chat_id=chat_id, message_id=seeded_message))
        == 1
    )
    assert await resolve_ledger_entries(db_session, chat_id=chat_id, message_id=uuid.uuid4()) == []


@pytest.mark.asyncio
async def test_resolve_skips_dangling_reference(db_session, seeded_message):
    """An entry whose referenced row is absent is skipped, not fatal."""
    _chat_id = (
        await db_session.execute(select(Message.chat_id).where(Message.id == seeded_message))
    ).scalar_one()
    # FK constraints make a truly dangling row unpersistable, so the conservative
    # skip branch is exercised at the _resolve_source unit level: a present FK whose
    # referenced row is absent resolves to None.
    from app.citation.ledger import _resolve_source

    class _E:
        message_citation_id = uuid.uuid4()
        message_caselaw_citation_id = None
        message_tool_source_id = None
        id = uuid.uuid4()

    assert _resolve_source(_E(), {}, {}, {}) is None
