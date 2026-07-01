"""Authority citation tables — schema round-trip tests (WS-E PR1b, migration 0064).

Verifies:
- MessageAuthorityCitation inserts + reads back correctly
- CHECK constraint rejects unknown verification_method values
- AuthorityTextCache enforces UNIQUE (source_type, external_ref)
- CitationLedgerEntry exactly-one-source CHECK now covers 4 FK slots
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.authority_text_cache import AuthorityTextCache
from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.message_authority_citation import MessageAuthorityCitation
from app.models.user import User

# ---------------------------------------------------------------------------
# Shared helper factories  (mirrors api/tests/citation/conftest.py pattern)
# ---------------------------------------------------------------------------


async def _a_message(db: AsyncSession) -> uuid.UUID:
    """Create minimal user→chat→message chain; return message_id.

    Pattern taken from api/tests/citation/conftest.py (the `seeded` fixture):
    User → Chat → Message.
    """
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db.add(user)
    await db.flush()
    chat = Chat(owner_id=user.id, title="t")
    db.add(chat)
    await db.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="x")
    db.add(msg)
    await db.flush()
    return msg.id


async def _chat_of(db: AsyncSession, message_id: uuid.UUID) -> uuid.UUID:
    """Return the chat_id for a given message_id (queries within the same session)."""
    result = await db.execute(select(Message).where(Message.id == message_id))
    return result.scalar_one().chat_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authority_citation_round_trips(db_session: AsyncSession) -> None:
    mid = await _a_message(db_session)
    row = MessageAuthorityCitation(
        message_id=mid,
        source_type="govinfo",
        external_ref="USCODE-2022-title15",
        content_kind="statute",
        source_offset_start=0,
        source_offset_end=10,
        source_text="Every cont",
        verified=True,
        verification_method="exact_match",
        verification_confidence=1.0,
        partial=False,
    )
    db_session.add(row)
    await db_session.flush()
    got = (await db_session.execute(select(MessageAuthorityCitation))).scalar_one()
    assert got.source_type == "govinfo" and got.content_kind == "statute"


@pytest.mark.asyncio
async def test_authority_method_check_rejects_bad_method(db_session: AsyncSession) -> None:
    mid = await _a_message(db_session)
    db_session.add(
        MessageAuthorityCitation(
            message_id=mid,
            source_type="govinfo",
            external_ref="x",
            content_kind="statute",
            source_offset_start=0,
            source_offset_end=1,
            source_text="a",
            verified=True,
            verification_method="made_up_method",
            partial=False,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_authority_text_cache_unique_source_external_ref(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        AuthorityTextCache(
            source_type="govinfo",
            external_ref="USCODE-2022-title15",
            storage_path="authority/govinfo/USCODE-2022-title15",
            char_length=5,
        )
    )
    await db_session.flush()
    db_session.add(
        AuthorityTextCache(
            source_type="govinfo",
            external_ref="USCODE-2022-title15",
            storage_path="authority/govinfo/dup",
            char_length=9,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_ledger_entry_exactly_one_of_four_sources(db_session: AsyncSession) -> None:
    mid = await _a_message(db_session)
    ac = MessageAuthorityCitation(
        message_id=mid,
        source_type="govinfo",
        external_ref="x",
        content_kind="statute",
        source_offset_start=0,
        source_offset_end=1,
        source_text="a",
        verified=True,
        verification_method="exact_match",
        partial=False,
    )
    db_session.add(ac)
    await db_session.flush()
    # exactly one (the authority slot) → OK
    ok = CitationLedgerEntry(
        chat_id=(await _chat_of(db_session, mid)),
        message_id=mid,
        source_kind="statute",
        message_authority_citation_id=ac.id,
        verification_status="exact_match",
    )
    db_session.add(ok)
    await db_session.flush()
    # zero non-null FKs → CHECK violation
    db_session.add(
        CitationLedgerEntry(
            chat_id=(await _chat_of(db_session, mid)),
            message_id=mid,
            source_kind="statute",
            verification_status="unverified",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
