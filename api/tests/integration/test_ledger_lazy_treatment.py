"""Integration tests: DE-363 lazy-on-trace-open treatment re-enqueue.

GET /ledger (get_chat_ledger) best-effort enqueues treatment derivation
for any caselaw ledger entry whose treatment is missing or stale.
This exercises Task 4 of WS-G PR3.

Pattern: direct handler invocation with db_session — matches the
convention in test_citation_ledger.py / test_ledger_treatment_exposure.py.
No HTTP client; no auth fixtures needed.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.chats as chats_mod
from app.api.chats import get_chat_ledger
from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.citation_treatment import CitationTreatment
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.user import User

pytestmark = pytest.mark.integration


def _fake_request() -> Request:
    """Minimal ASGI-scope Request for direct handler invocation (no HTTP client)."""
    return Request(
        scope={"type": "http", "headers": [], "client": None, "method": "GET", "path": "/"}
    )


@pytest_asyncio.fixture
async def seeded_caselaw_null_treatment(
    db_session: AsyncSession,
) -> tuple[User, uuid.UUID, uuid.UUID]:
    """Seed: user + chat + assistant message + caselaw citation + ledger entry
    with null treatment_id. Yields (user, chat_id, message_id)."""
    user = User(
        email=f"lazy-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role="member",
    )
    db_session.add(user)
    await db_session.flush()

    chat = Chat(owner_id=user.id, title="lazy-enqueue test")
    db_session.add(chat)
    await db_session.flush()

    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="answer")
    db_session.add(msg)
    await db_session.flush()

    cc = MessageCaselawCitation(
        message_id=msg.id,
        opinion_id=99001,
        cluster_id=99001,
        source_offset_start=0,
        source_offset_end=5,
        source_text="q",
        verified=True,
        verification_method="exact_match",
        verification_confidence=1.0,
    )
    db_session.add(cc)
    await db_session.flush()

    entry = CitationLedgerEntry(
        chat_id=chat.id,
        message_id=msg.id,
        source_kind="caselaw",
        message_caselaw_citation_id=cc.id,
        verification_status="exact_match",
        treatment_id=None,
    )
    db_session.add(entry)
    await db_session.flush()

    return user, chat.id, msg.id


@pytest.mark.asyncio
async def test_ledger_read_enqueues_for_null_treatment(
    db_session: AsyncSession,
    seeded_caselaw_null_treatment: tuple[User, uuid.UUID, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /ledger best-effort enqueues derivation for a caselaw turn whose
    treatment is not yet derived; the response shape is unchanged."""
    user, chat_id, message_id = seeded_caselaw_null_treatment

    enqueued: list[uuid.UUID] = []

    async def _spy(mid: uuid.UUID) -> bool:
        enqueued.append(mid)
        return True

    monkeypatch.setattr(chats_mod, "enqueue_treatment_derivation_job", _spy)

    result = await get_chat_ledger(
        chat_id=str(chat_id),
        user=user,
        db=db_session,
        request=_fake_request(),
        message_id=None,
    )

    assert message_id in enqueued, f"Expected enqueue for message {message_id}; got {enqueued}"
    assert "entries" in result and "gates" in result  # response shape unchanged


@pytest.mark.asyncio
async def test_ledger_read_skips_enqueue_for_fresh_treatment(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /ledger does NOT enqueue for a caselaw turn with a fresh treatment
    (as_of within the TTL window)."""
    user = User(
        email=f"fresh-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role="member",
    )
    db_session.add(user)
    await db_session.flush()

    chat = Chat(owner_id=user.id, title="fresh-treatment test")
    db_session.add(chat)
    await db_session.flush()

    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="answer")
    db_session.add(msg)
    await db_session.flush()

    cc = MessageCaselawCitation(
        message_id=msg.id,
        opinion_id=99002,
        cluster_id=99002,
        source_offset_start=0,
        source_offset_end=5,
        source_text="q",
        verified=True,
        verification_method="exact_match",
        verification_confidence=1.0,
    )
    db_session.add(cc)
    await db_session.flush()

    # Fresh treatment: as_of defaults to NOW() via server_default — within the TTL.
    treatment = CitationTreatment(
        cluster_id=99002,
        opinion_id=99002,
        cited_by_count=5,
        citing_opinions=[],
        derived_method="citation_graph",
    )
    db_session.add(treatment)
    await db_session.flush()

    entry = CitationLedgerEntry(
        chat_id=chat.id,
        message_id=msg.id,
        source_kind="caselaw",
        message_caselaw_citation_id=cc.id,
        verification_status="exact_match",
        treatment_id=treatment.id,
    )
    db_session.add(entry)
    await db_session.flush()

    enqueued: list[uuid.UUID] = []

    async def _spy(mid: uuid.UUID) -> bool:
        enqueued.append(mid)
        return True

    monkeypatch.setattr(chats_mod, "enqueue_treatment_derivation_job", _spy)

    result = await get_chat_ledger(
        chat_id=str(chat.id),
        user=user,
        db=db_session,
        request=_fake_request(),
        message_id=None,
    )

    assert msg.id not in enqueued, (
        f"Expected NO enqueue for message {msg.id} (fresh treatment); got {enqueued}"
    )
    assert "entries" in result and "gates" in result  # response shape unchanged
