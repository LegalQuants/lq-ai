from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.ledger import resolve_ledger_entries
from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.citation_treatment import CitationTreatment
from app.models.citation_treatment_signal import CitationTreatmentSignal
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


@pytest.mark.asyncio
async def test_ledger_exposes_treatment_rollup_and_signals(db_session: AsyncSession):
    """WS-G PR2: treatment dict gains rollup + per-passage signals from judge run."""
    user = User(email=f"trs-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="trs")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="x")
    db_session.add(msg)
    await db_session.flush()
    cc = MessageCaselawCitation(
        message_id=msg.id,
        opinion_id=9999001,
        cluster_id=9999001,
        source_offset_start=0,
        source_offset_end=5,
        source_text="q",
        verified=True,
        verification_method="exact_match",
    )
    db_session.add(cc)
    await db_session.flush()

    # Treatment with judge-populated rollup columns.
    judge_ts = datetime(2026, 6, 27, 12, 0, 0, tzinfo=UTC)
    treatment = CitationTreatment(
        cluster_id=9999001,
        opinion_id=9999001,
        cited_by_count=5,
        citing_opinions=[],
        derived_method="citation_graph+judge",
        strongest_negative_class="overruled",
        judged_count=2,
        judge_as_of=judge_ts,
    )
    db_session.add(treatment)
    await db_session.flush()

    sig1 = CitationTreatmentSignal(
        treatment_id=treatment.id,
        citing_opinion_id=111,
        classification="overruled",
        confidence=0.9,
        justification="The later court explicitly overruled this decision.",
    )
    sig2 = CitationTreatmentSignal(
        treatment_id=treatment.id,
        citing_opinion_id=222,
        classification="neutral",
        confidence=0.5,
        justification="Bare citation only.",
    )
    db_session.add_all([sig1, sig2])
    await db_session.flush()

    linked = CitationLedgerEntry(
        chat_id=chat.id,
        message_id=msg.id,
        source_kind="caselaw",
        message_caselaw_citation_id=cc.id,
        verification_status="exact_match",
        treatment_id=treatment.id,
    )
    db_session.add(linked)
    await db_session.flush()

    entries = await resolve_ledger_entries(db_session, chat_id=chat.id, message_id=msg.id)
    assert len(entries) == 1
    t = entries[0]["treatment"]
    assert t is not None

    # Rollup columns from CitationTreatment.
    assert t["strongest_negative_class"] == "overruled"
    assert t["judged_count"] == 2
    assert t["judge_as_of"] == judge_ts.isoformat()

    # Computed from signals via roll_up.
    assert t["per_class_counts"]["overruled"] == 1
    assert t["per_class_counts"]["neutral"] == 1
    assert isinstance(t["case_confidence"], float)
    assert t["case_confidence"] > 0.0

    # Per-passage signals list.
    sigs = t["signals"]
    assert len(sigs) == 2
    assert any(s["classification"] == "overruled" for s in sigs)
    # P3: no snippet field in signals.
    assert all("snippet" not in s for s in sigs)
    # Required signal fields.
    for s in sigs:
        assert "citing_opinion_id" in s
        assert "classification" in s
        assert "confidence" in s
        assert "justification" in s


@pytest.mark.asyncio
async def test_ledger_graph_only_treatment_yields_null_rollup(db_session: AsyncSession):
    """WS-G PR2: graph-only treatment (no signals) yields new keys as null/empty."""
    user = User(email=f"go-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="go")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="x")
    db_session.add(msg)
    await db_session.flush()
    cc = MessageCaselawCitation(
        message_id=msg.id,
        opinion_id=9999002,
        cluster_id=9999002,
        source_offset_start=0,
        source_offset_end=5,
        source_text="q",
        verified=True,
        verification_method="exact_match",
    )
    db_session.add(cc)
    await db_session.flush()

    # PR1-style row: no judge columns, no signals.
    treatment = CitationTreatment(
        cluster_id=9999002,
        opinion_id=9999002,
        cited_by_count=10,
        citing_opinions=[],
        derived_method="citation_graph",
        strongest_negative_class=None,
        judged_count=None,
        judge_as_of=None,
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
    db_session.add(linked)
    await db_session.flush()

    entries = await resolve_ledger_entries(db_session, chat_id=chat.id, message_id=msg.id)
    assert len(entries) == 1
    t = entries[0]["treatment"]
    assert t is not None

    # Original PR1 keys still present.
    assert t["cited_by_count"] == 10
    assert t["derived_method"] == "citation_graph"

    # New PR2 keys: null/empty for graph-only row.
    assert t["strongest_negative_class"] is None
    assert t["judged_count"] is None
    assert t["judge_as_of"] is None
    assert t["per_class_counts"] == {}
    assert t["case_confidence"] is None
    assert t["signals"] == []
