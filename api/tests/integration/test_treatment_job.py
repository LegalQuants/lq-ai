from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.citation_treatment import CitationTreatment
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.user import User

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_run_treatment_derivation_writes_row_and_links(db_session: AsyncSession, monkeypatch):
    # Seed a turn with a caselaw citation + ledger entry (as in Task 3's fixture).
    user = User(email=f"j-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="j")
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
        source_text="q",
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

    # The job's _run helper takes an injected session + fetch so we can test it without Redis/arq.
    from app.workers.treatment_worker import run_treatment_derivation

    async def fake_fetch(opinion_id: int) -> dict:
        return {
            "cited_by_count": 7,
            "citing": [
                {
                    "cluster_id": 1,
                    "opinion_id": 2,
                    "case_name": "A",
                    "court": "ca9",
                    "date_filed": "2022-01-01",
                }
            ],
        }

    linked = await run_treatment_derivation(db_session, message_id=msg.id, fetch_citing=fake_fetch)
    assert linked == 1
    row = (
        await db_session.execute(
            select(CitationTreatment).where(CitationTreatment.cluster_id == 2812209)
        )
    ).scalar_one()
    assert row.cited_by_count == 7
    await db_session.refresh(entry)
    assert entry.treatment_id == row.id
