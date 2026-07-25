from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.ledger import message_ids_needing_treatment
from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.citation_treatment import CitationTreatment
from app.models.file import File
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.user import User

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 27, tzinfo=UTC)


async def _entry(
    db: AsyncSession,
    chat_id: uuid.UUID,
    *,
    source_kind: str,
    treatment_id: uuid.UUID | None = None,
    cc_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> uuid.UUID:
    from app.models.chat import MessageCitation

    msg = Message(chat_id=chat_id, role="assistant", kind="ai", content="x")
    db.add(msg)
    await db.flush()

    # Create the required source object based on source_kind
    citation_id = None
    caselaw_id = None
    if source_kind == "caselaw" and cc_id is None:
        cc = MessageCaselawCitation(
            message_id=msg.id,
            cluster_id=1,
            opinion_id=1,
            source_text="test",
            source_offset_start=0,
            source_offset_end=4,
            verified=True,
            verification_method="exact_match",
        )
        db.add(cc)
        await db.flush()
        caselaw_id = cc.id
    elif source_kind == "document":
        # Create a File first (FK requirement), then a MessageCitation
        file = File(
            owner_id=user_id,
            filename="test.pdf",
            mime_type="application/pdf",
            size_bytes=100,
            hash_sha256="abcd1234",
            storage_path="test-path",
        )
        db.add(file)
        await db.flush()

        citation = MessageCitation(
            message_id=msg.id,
            source_file_id=file.id,
            source_text="test",
            source_offset_start=0,
            source_offset_end=4,
            verified=True,
            verification_method="exact_match",
        )
        db.add(citation)
        await db.flush()
        citation_id = citation.id

    db.add(
        CitationLedgerEntry(
            chat_id=chat_id,
            message_id=msg.id,
            source_kind=source_kind,
            message_citation_id=citation_id,
            message_caselaw_citation_id=caselaw_id or cc_id,
            treatment_id=treatment_id,
            verification_status="exact_match",
        )
    )
    await db.flush()
    return msg.id


@pytest.fixture
async def user(db_session: AsyncSession) -> User:
    u = User(email=f"n-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db_session.add(u)
    await db_session.flush()
    return u


@pytest.fixture
async def chat(db_session: AsyncSession, user: User) -> uuid.UUID:
    c = Chat(owner_id=user.id, title="n")
    db_session.add(c)
    await db_session.flush()
    return c.id


async def _treatment(db: AsyncSession, *, cluster_id: int, as_of: datetime) -> CitationTreatment:
    t = CitationTreatment(
        cluster_id=cluster_id,
        opinion_id=cluster_id,
        cited_by_count=0,
        citing_opinions=[],
        derived_method="citation_graph",
        as_of=as_of,
    )
    db.add(t)
    await db.flush()
    return t


async def test_null_treatment_caselaw_is_needed(db_session: AsyncSession, chat: uuid.UUID) -> None:
    mid = await _entry(db_session, chat, source_kind="caselaw", treatment_id=None)
    out = await message_ids_needing_treatment(db_session, chat_id=chat, message_id=None, now=_NOW)
    assert mid in out


async def test_fresh_treatment_not_needed(db_session: AsyncSession, chat: uuid.UUID) -> None:
    t = await _treatment(db_session, cluster_id=1, as_of=_NOW)
    mid = await _entry(db_session, chat, source_kind="caselaw", treatment_id=t.id)
    out = await message_ids_needing_treatment(db_session, chat_id=chat, message_id=None, now=_NOW)
    assert mid not in out


async def test_stale_treatment_is_needed(db_session: AsyncSession, chat: uuid.UUID) -> None:
    t = await _treatment(db_session, cluster_id=2, as_of=_NOW - timedelta(days=31))
    mid = await _entry(db_session, chat, source_kind="caselaw", treatment_id=t.id)
    out = await message_ids_needing_treatment(db_session, chat_id=chat, message_id=None, now=_NOW)
    assert mid in out


async def test_non_caselaw_excluded(db_session: AsyncSession, chat: uuid.UUID, user: User) -> None:
    mid = await _entry(db_session, chat, source_kind="document", treatment_id=None, user_id=user.id)
    out = await message_ids_needing_treatment(db_session, chat_id=chat, message_id=None, now=_NOW)
    assert mid not in out


async def test_message_id_scopes(db_session: AsyncSession, chat: uuid.UUID) -> None:
    mid1 = await _entry(db_session, chat, source_kind="caselaw", treatment_id=None)
    mid2 = await _entry(db_session, chat, source_kind="caselaw", treatment_id=None)
    out = await message_ids_needing_treatment(db_session, chat_id=chat, message_id=mid1, now=_NOW)
    assert out == {mid1} and mid2 not in out
