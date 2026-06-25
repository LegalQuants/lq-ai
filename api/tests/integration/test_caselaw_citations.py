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

from app.chat.tool_loop import ToolSourceRecord
from app.citation.caselaw import verify_and_persist_caselaw_citations
from app.models.chat import Chat, Message
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.research import ResearchOpinionMetadata
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


# ---------------------------------------------------------------------------
# Orchestrator tests (Task 4 additions)
# ---------------------------------------------------------------------------

_OPINION_TEXT = "Intro. The covenant of good faith is implied in every contract. End."


def _caselaw_source(cluster_id: int) -> ToolSourceRecord:
    return ToolSourceRecord(
        source_kind="caselaw",
        label=f"Cluster {cluster_id}",
        subtitle=None,
        url=None,
        external_ref=str(cluster_id),
        provider="courtlistener",
        tool="get_cluster",
    )


@pytest.mark.asyncio
async def test_verbatim_quote_persists_verified_row(db_session, seeded_chat_message):
    message_id = seeded_chat_message
    db_session.add(
        ResearchOpinionMetadata(
            opinion_id=501,
            cluster_id=42,
            text_field_used="plain_text",
            storage_path="courtlistener/opinions/by-cluster/42/501",
            char_length=len(_OPINION_TEXT),
        )
    )
    await db_session.flush()

    async def fake_loader(db, opinion_id):
        return _OPINION_TEXT

    answer = "**Relevant passage:**\n> The covenant of good faith is implied in every contract.\n"
    n = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=answer,
        tool_sources=[_caselaw_source(42)],
        load_opinion_text=fake_loader,
    )
    await db_session.flush()
    rows = (
        (
            await db_session.execute(
                select(MessageCaselawCitation).where(
                    MessageCaselawCitation.message_id == message_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert n == 1
    assert len(rows) == 1
    assert rows[0].verified is True
    assert rows[0].verification_method == "exact_match"
    assert rows[0].opinion_id == 501


@pytest.mark.asyncio
async def test_invented_quote_persists_nothing(db_session, seeded_chat_message):
    message_id = seeded_chat_message
    db_session.add(
        ResearchOpinionMetadata(
            opinion_id=502,
            cluster_id=43,
            text_field_used="plain_text",
            storage_path="p",
            char_length=len(_OPINION_TEXT),
        )
    )
    await db_session.flush()

    async def fake_loader(db, opinion_id):
        return _OPINION_TEXT

    answer = "> The court invented a rule that appears in no opinion whatsoever.\n"
    n = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=answer,
        tool_sources=[_caselaw_source(43)],
        load_opinion_text=fake_loader,
    )
    assert n == 0


@pytest.mark.asyncio
async def test_storage_miss_is_skipped_not_fatal(db_session, seeded_chat_message):
    message_id = seeded_chat_message
    db_session.add(
        ResearchOpinionMetadata(
            opinion_id=503, cluster_id=44, text_field_used=None, storage_path="gone", char_length=1
        )
    )
    await db_session.flush()

    async def boom_loader(db, opinion_id):
        raise RuntimeError("object storage unavailable")

    answer = "> The covenant of good faith is implied in every contract.\n"
    n = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=answer,
        tool_sources=[_caselaw_source(44)],
        load_opinion_text=boom_loader,
    )
    assert n == 0  # skipped, no exception
