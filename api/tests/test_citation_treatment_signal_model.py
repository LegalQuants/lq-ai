import pytest
from sqlalchemy import select

from app.models.citation_treatment import CitationTreatment
from app.models.citation_treatment_signal import CitationTreatmentSignal

pytestmark = pytest.mark.asyncio


async def _treatment(db) -> CitationTreatment:
    t = CitationTreatment(
        cluster_id=111,
        opinion_id=222,
        cited_by_count=5,
        citing_opinions=[],
        derived_method="citation_graph+judge",
        strongest_negative_class="questioned",
        judged_count=3,
    )
    db.add(t)
    await db.flush()
    return t


async def test_signal_round_trips_and_cascades(db_session) -> None:
    t = await _treatment(db_session)
    db_session.add(
        CitationTreatmentSignal(
            treatment_id=t.id,
            citing_opinion_id=5000,
            classification="questioned",
            confidence=0.7,
            justification="The citing court doubted the holding.",
        )
    )
    await db_session.flush()
    rows = (
        (
            await db_session.execute(
                select(CitationTreatmentSignal).where(CitationTreatmentSignal.treatment_id == t.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1 and rows[0].classification == "questioned"
    # CASCADE: deleting the parent removes its signals.
    await db_session.delete(t)
    await db_session.flush()
    remaining = (await db_session.execute(select(CitationTreatmentSignal))).scalars().all()
    assert remaining == []


async def test_bad_classification_rejected(db_session) -> None:
    from sqlalchemy.exc import IntegrityError

    t = await _treatment(db_session)
    db_session.add(
        CitationTreatmentSignal(
            treatment_id=t.id,
            citing_opinion_id=1,
            classification="bogus",
            confidence=0.5,
            justification="x",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_parent_allows_graph_plus_judge_method(db_session) -> None:
    db_session.add(
        CitationTreatment(
            cluster_id=9,
            opinion_id=9,
            cited_by_count=0,
            citing_opinions=[],
            derived_method="citation_graph+judge",
        )
    )
    await db_session.flush()  # must not raise
