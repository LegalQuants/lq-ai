from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.treatment import TREATMENT_TTL_DAYS, derive_treatment_for_message
from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.citation_treatment import CitationTreatment
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.user import User

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 26, tzinfo=UTC)


def _citing(n: int) -> dict:
    return {
        "cited_by_count": 412,
        "citing": [
            {
                "cluster_id": 1000 + i,
                "opinion_id": 9000 + i,
                "case_name": f"C{i}",
                "court": "ca9",
                "date_filed": "2021-01-01",
            }
            for i in range(n)
        ],
    }


@pytest.mark.asyncio
async def test_derives_fetches_and_links(
    db_session: AsyncSession,
    seeded: tuple[uuid.UUID, uuid.UUID, MessageCaselawCitation, CitationLedgerEntry],
) -> None:
    message_id, _chat, _cc, entry = seeded
    calls: list[int] = []

    async def fake_fetch(opinion_id: int) -> dict:
        calls.append(opinion_id)
        return _citing(32)

    n = await derive_treatment_for_message(
        db_session, message_id=message_id, now=_NOW, fetch_citing=fake_fetch
    )
    assert n == 1
    assert calls == [2812209]
    row = (
        await db_session.execute(
            select(CitationTreatment).where(CitationTreatment.cluster_id == 2812209)
        )
    ).scalar_one()
    assert row.cited_by_count == 412
    assert (
        len(row.citing_opinions) == 32
    )  # service stores what the op returns (op already capped at 30; service does not re-cap)
    assert row.derived_method == "citation_graph"
    await db_session.refresh(entry)
    assert entry.treatment_id == row.id


@pytest.mark.asyncio
async def test_reuses_fresh_cache_without_fetch(
    db_session: AsyncSession,
    seeded: tuple[uuid.UUID, uuid.UUID, MessageCaselawCitation, CitationLedgerEntry],
) -> None:
    message_id, _chat, _cc, entry = seeded
    db_session.add(
        CitationTreatment(
            cluster_id=2812209,
            opinion_id=2812209,
            cited_by_count=10,
            citing_opinions=[],
            derived_method="citation_graph",
            as_of=_NOW - timedelta(days=5),
        )
    )
    await db_session.flush()
    calls: list[int] = []

    async def fake_fetch(opinion_id: int) -> dict:
        calls.append(opinion_id)
        return _citing(1)

    n = await derive_treatment_for_message(
        db_session, message_id=message_id, now=_NOW, fetch_citing=fake_fetch
    )
    assert n == 1
    assert calls == []  # fresh cache reused, no fetch
    await db_session.refresh(entry)
    assert entry.treatment_id is not None


@pytest.mark.asyncio
async def test_refetches_when_stale(
    db_session: AsyncSession,
    seeded: tuple[uuid.UUID, uuid.UUID, MessageCaselawCitation, CitationLedgerEntry],
) -> None:
    message_id, *_ = seeded
    db_session.add(
        CitationTreatment(
            cluster_id=2812209,
            opinion_id=2812209,
            cited_by_count=10,
            citing_opinions=[],
            derived_method="citation_graph",
            as_of=_NOW - timedelta(days=TREATMENT_TTL_DAYS + 1),
        )
    )
    await db_session.flush()
    calls: list[int] = []

    async def fake_fetch(opinion_id: int) -> dict:
        calls.append(opinion_id)
        return _citing(3)

    await derive_treatment_for_message(
        db_session, message_id=message_id, now=_NOW, fetch_citing=fake_fetch
    )
    assert calls == [2812209]  # stale → refetch
    row = (
        await db_session.execute(
            select(CitationTreatment).where(CitationTreatment.cluster_id == 2812209)
        )
    ).scalar_one()
    assert row.cited_by_count == 412  # upserted


@pytest.mark.asyncio
async def test_per_case_fetch_error_is_non_fatal(
    db_session: AsyncSession,
    seeded: tuple[uuid.UUID, uuid.UUID, MessageCaselawCitation, CitationLedgerEntry],
) -> None:
    message_id, *_ = seeded

    async def boom(opinion_id: int) -> dict:
        raise RuntimeError("upstream down")

    n = await derive_treatment_for_message(
        db_session, message_id=message_id, now=_NOW, fetch_citing=boom
    )
    assert n == 0  # nothing linked, but no raise
    rows = (await db_session.execute(select(CitationTreatment))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_no_caselaw_citations_is_noop(db_session: AsyncSession) -> None:
    # a message with no caselaw citations
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="t")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="x")
    db_session.add(msg)
    await db_session.flush()
    called: list[int] = []

    async def fake_fetch(opinion_id: int) -> dict:
        called.append(opinion_id)
        return _citing(1)

    n = await derive_treatment_for_message(
        db_session, message_id=msg.id, now=_NOW, fetch_citing=fake_fetch
    )
    assert n == 0
    assert called == []
