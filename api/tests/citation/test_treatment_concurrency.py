from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import delete as _real_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.treatment import derive_treatment_for_message
from app.citation.treatment_judge import TreatmentJudgment
from app.citation.treatment_rollup import roll_up
from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.citation_treatment import CitationTreatment
from app.models.citation_treatment_signal import CitationTreatmentSignal
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.research import ResearchClusterMetadata
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


async def test_concurrent_judge_write_last_writer_wins(db_session: AsyncSession):
    """With the in-savepoint DELETE restored, a concurrently-staged winner signal is
    overwritten by last-writer-wins. The committed state must be CONSISTENT: parent
    derived_method='citation_graph+judge', judged_count == len(signals), and
    strongest_negative_class matching roll_up over the surviving signals (DE-364b)."""
    message_id = await _seed_two_cluster_turn(db_session)
    old = datetime(2026, 1, 1, tzinfo=UTC)
    rows: dict[int, uuid.UUID] = {}
    for cluster_id, opinion_id in ((7001, 8001), (7002, 8002)):
        db_session.add(ResearchClusterMetadata(cluster_id=cluster_id, case_name="A v. B"))
        t = CitationTreatment(
            cluster_id=cluster_id,
            opinion_id=opinion_id,
            cited_by_count=1,
            citing_opinions=[],
            derived_method="citation_graph",
            as_of=old,
        )
        db_session.add(t)
        await db_session.flush()
        rows[cluster_id] = t.id

    async def fetch(opinion_id: int) -> dict:
        return {
            "cited_by_count": 5,
            "citing": [
                {
                    "cluster_id": 1,
                    "opinion_id": 9001,
                    "case_name": "C",
                    "court": "ca9",
                    "date_filed": "2021-01-01",
                    "snippet": "criticized in part",
                },
            ],
        }

    class _GW:
        """Judge returns 'criticized'.  While judging cluster 7001, stage a concurrent
        winner signal — but the in-savepoint DELETE removes it, so last-writer-wins."""

        def __init__(self) -> None:
            self.staged = False

        async def chat_completion(self, request: object, *, request_id: object = None) -> object:
            body = request.messages[1].content  # type: ignore[attr-defined]
            if "A v. B" in body and not self.staged:
                self.staged = True
                db_session.add(
                    CitationTreatmentSignal(
                        treatment_id=rows[7001],
                        citing_opinion_id=9001,
                        classification="criticized",
                        confidence=0.7,
                        justification="winner",
                    )
                )
                await db_session.flush()
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "treatment": "criticized",
                                    "confidence": "high",
                                    "justification": "x",
                                }
                            )
                        )
                    )
                ]
            )

    linked = await derive_treatment_for_message(
        db_session,
        message_id=message_id,
        now=_NOW,
        fetch_citing=fetch,
        gateway=_GW(),
        judge_model="fast",
    )

    # Turn not poisoned.
    assert linked == 2

    # --- Consistency check for cluster 7001 ---
    t_7001 = (
        await db_session.execute(
            select(CitationTreatment).where(CitationTreatment.id == rows[7001])
        )
    ).scalar_one()
    # Refresh from DB to ensure parent-column assertions read persisted state, not in-memory.
    await db_session.refresh(t_7001)
    sigs_7001 = (
        (
            await db_session.execute(
                select(CitationTreatmentSignal).where(
                    CitationTreatmentSignal.treatment_id == rows[7001]
                )
            )
        )
        .scalars()
        .all()
    )
    expected = roll_up(
        [
            TreatmentJudgment(
                classification=s.classification,
                confidence=s.confidence,
                justification=s.justification,
            )
            for s in sigs_7001
        ]
    )
    # The parent must mirror its own signal rows — never graph-only beside judge signals.
    assert t_7001.derived_method == "citation_graph+judge"
    assert t_7001.judged_count == len(sigs_7001)
    assert t_7001.strongest_negative_class == expected.strongest_negative_class


async def test_judge_write_conflict_skip_restores_parent(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rare conflict→skip→restore backstop: when the persist-phase flush raises
    IntegrityError (a row committed by another txn between our DELETE and flush),
    the except block re-reads the winner's signals and restores the parent rollup
    to match them.  The parent must never be left in graph-only state beside judge
    signals (DE-364b).

    Mechanism: patch app.citation.treatment.delete to a no-op so neither the
    caller's refresh branch nor the persist-phase DELETE removes the staged winner
    signal; our subsequent INSERT conflicts → IntegrityError → backstop fires.
    """
    message_id = await _seed_two_cluster_turn(db_session)
    old = datetime(2026, 1, 1, tzinfo=UTC)
    rows: dict[int, uuid.UUID] = {}
    for cluster_id, opinion_id in ((7001, 8001), (7002, 8002)):
        db_session.add(ResearchClusterMetadata(cluster_id=cluster_id, case_name="A v. B"))
        t = CitationTreatment(
            cluster_id=cluster_id,
            opinion_id=opinion_id,
            cited_by_count=1,
            citing_opinions=[],
            derived_method="citation_graph",
            as_of=old,
        )
        db_session.add(t)
        await db_session.flush()
        rows[cluster_id] = t.id

    # Stage the winner's signal for cluster 7001 BEFORE calling derive_treatment.
    db_session.add(
        CitationTreatmentSignal(
            treatment_id=rows[7001],
            citing_opinion_id=9001,
            classification="criticized",
            confidence=0.7,
            justification="winner",
        )
    )
    await db_session.flush()

    # Patch delete to a no-op so the staged winner survives both the refresh-branch
    # clear and the persist-phase DELETE, forcing our INSERT to conflict.
    # Use `treatment_id IS NULL` (always false for the required FK) rather than
    # `false()` so SQLAlchemy's ORM `evaluate` mode can handle it in Python without
    # falling back to `fetch` mode, which issues a sync SELECT during savepoint
    # teardown and raises MissingGreenlet in the async context.
    def _noop_delete(model: type) -> object:  # type: ignore[type-arg]
        return _real_delete(model).where(model.treatment_id.is_(None))

    monkeypatch.setattr("app.citation.treatment.delete", _noop_delete)

    async def fetch(opinion_id: int) -> dict:
        return {
            "cited_by_count": 5,
            "citing": [
                {
                    "cluster_id": 1,
                    "opinion_id": 9001,
                    "case_name": "C",
                    "court": "ca9",
                    "date_filed": "2021-01-01",
                    "snippet": "criticized in part",
                },
            ],
        }

    class _GW:
        async def chat_completion(self, request: object, *, request_id: object = None) -> object:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "treatment": "criticized",
                                    "confidence": "high",
                                    "justification": "x",
                                }
                            )
                        )
                    )
                ]
            )

    linked = await derive_treatment_for_message(
        db_session,
        message_id=message_id,
        now=_NOW,
        fetch_citing=fetch,
        gateway=_GW(),
        judge_model="fast",
    )

    # Turn not poisoned — the other cluster still links.
    assert linked == 2

    # --- Backstop ran: parent restored to match the winner's signals ---
    t_7001 = (
        await db_session.execute(
            select(CitationTreatment).where(CitationTreatment.id == rows[7001])
        )
    ).scalar_one()
    # Refresh from DB to ensure parent-column assertions read persisted state, not in-memory.
    await db_session.refresh(t_7001)
    sigs_7001 = (
        (
            await db_session.execute(
                select(CitationTreatmentSignal).where(
                    CitationTreatmentSignal.treatment_id == rows[7001]
                )
            )
        )
        .scalars()
        .all()
    )
    # The winner's signal must survive (our INSERT was rolled back).
    assert len(sigs_7001) == 1
    assert sigs_7001[0].justification == "winner"

    expected = roll_up(
        [
            TreatmentJudgment(
                classification=s.classification,
                confidence=s.confidence,
                justification=s.justification,
            )
            for s in sigs_7001
        ]
    )
    # The parent must mirror the winner's signals — never graph-only beside judge signals.
    assert t_7001.derived_method == "citation_graph+judge"
    assert t_7001.judged_count == len(sigs_7001)
    assert t_7001.strongest_negative_class == expected.strongest_negative_class
