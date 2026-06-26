from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.ledger import resolve_ledger_entries
from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.citation_treatment import CitationTreatment
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.user import User

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_ledger_entry_carries_resolved_treatment(db_session: AsyncSession):
    user = User(email=f"l-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="l")
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
    treatment = CitationTreatment(
        cluster_id=2812209,
        opinion_id=2812209,
        cited_by_count=412,
        citing_opinions=[
            {
                "cluster_id": 1,
                "opinion_id": 2,
                "case_name": "A",
                "court": "ca9",
                "date_filed": "2021-01-01",
            }
        ],
        derived_method="citation_graph",
    )
    db_session.add(treatment)
    await db_session.flush()
    linked = CitationLedgerEntry(
        chat_id=chat.id,
        message_id=msg.id,
        source_kind="caselaw",
        message_caselaw_citation_id=cc.id,
        verification_status="exact_match",
        treatment_id=treatment.id,
    )
    unlinked = CitationLedgerEntry(
        chat_id=chat.id,
        message_id=msg.id,
        source_kind="caselaw",
        message_caselaw_citation_id=cc.id,
        verification_status="exact_match",
    )
    db_session.add_all([linked, unlinked])
    await db_session.flush()

    entries = await resolve_ledger_entries(db_session, chat_id=chat.id, message_id=msg.id)
    by_treatment = {bool(e.get("treatment")): e for e in entries}
    assert by_treatment[True]["treatment"]["cited_by_count"] == 412
    assert by_treatment[True]["treatment"]["derived_method"] == "citation_graph"
    assert by_treatment[True]["treatment"]["citing"][0]["case_name"] == "A"
    assert by_treatment[False]["treatment"] is None
