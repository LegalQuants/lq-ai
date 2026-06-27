from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.treatment import derive_treatment_for_message
from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.citation_treatment import CitationTreatment
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.user import User

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 27, tzinfo=UTC)


async def _seed_two_cluster_turn(db: AsyncSession) -> uuid.UUID:
    """An assistant turn citing two uncached cases: clusters 7001 and 7002."""
    user = User(email=f"c-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db.add(user)
    await db.flush()
    chat = Chat(owner_id=user.id, title="c")
    db.add(chat)
    await db.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="x")
    db.add(msg)
    await db.flush()
    for cluster_id, opinion_id in ((7001, 8001), (7002, 8002)):
        cc = MessageCaselawCitation(
            message_id=msg.id,
            opinion_id=opinion_id,
            cluster_id=cluster_id,
            source_offset_start=0,
            source_offset_end=5,
            source_text="q",
            verified=True,
            verification_method="exact_match",
        )
        db.add(cc)
        await db.flush()
        db.add(
            CitationLedgerEntry(
                chat_id=chat.id,
                message_id=msg.id,
                source_kind="caselaw",
                message_caselaw_citation_id=cc.id,
                verification_status="exact_match",
            )
        )
        await db.flush()
    return msg.id


async def test_concurrent_insert_conflict_isolates_and_reuses(db_session: AsyncSession):
    """One cluster's parent INSERT conflicts with a concurrently-inserted row;
    the other cluster still derives + links, and the conflicting cluster reuses
    the winner's row instead of poisoning the session."""
    message_id = await _seed_two_cluster_turn(db_session)

    staged = {"done": False}

    async def fetch_staging_winner(opinion_id: int) -> dict:
        # Simulate a concurrent turn: when 7001 (opinion 8001) is being derived,
        # insert + flush the "winner" row for cluster 7001 AFTER our existing-check
        # (None) but BEFORE our own flush — so our INSERT hits the unique constraint.
        if opinion_id == 8001 and not staged["done"]:
            staged["done"] = True
            db_session.add(
                CitationTreatment(
                    cluster_id=7001,
                    opinion_id=8001,
                    cited_by_count=99,
                    citing_opinions=[],
                    derived_method="citation_graph",
                    as_of=_NOW,
                )
            )
            await db_session.flush()
        return {"cited_by_count": 5, "citing": []}

    # gateway=None → graph-only (no judge pass); isolates the DE-364 behavior.
    linked = await derive_treatment_for_message(
        db_session,
        message_id=message_id,
        now=_NOW,
        fetch_citing=fetch_staging_winner,
    )

    # Both caselaw entries are linked: 7002 to its freshly-derived row, 7001 to the winner.
    entries = (
        (
            await db_session.execute(
                select(CitationLedgerEntry).where(CitationLedgerEntry.message_id == message_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) == 2
    assert all(e.treatment_id is not None for e in entries)  # NO cluster lost
    assert linked == 2

    # 7001's entry links to the winner row (cited_by_count=99 marks the winner).
    rows = {r.id: r for r in (await db_session.execute(select(CitationTreatment))).scalars().all()}
    cc_map = {
        c.id: c.cluster_id
        for c in (
            await db_session.execute(
                select(MessageCaselawCitation).where(
                    MessageCaselawCitation.message_id == message_id
                )
            )
        )
        .scalars()
        .all()
    }
    by_cluster = {cc_map[e.message_caselaw_citation_id]: rows[e.treatment_id] for e in entries}
    assert by_cluster[7001].cited_by_count == 99  # reused the winner, did not overwrite
    assert by_cluster[7002].cited_by_count == 5  # derived normally
