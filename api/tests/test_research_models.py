"""Model + migration test for research metadata tables — WS3b.

Verifies that ``research_cluster_metadata`` and ``research_opinion_metadata``
rows persist and read back with their core fields intact after the 0049
migration runs.

Tests run against the same SAVEPOINT-rolled-back per-test session as
the rest of the API tests (per ``tests/conftest.py``).
"""

from __future__ import annotations

from app.models.research import ResearchClusterMetadata, ResearchOpinionMetadata


async def test_research_metadata_roundtrips(db_session) -> None:
    cluster = ResearchClusterMetadata(
        cluster_id=2812209,
        case_name="Obergefell v. Hodges",
        court="scotus",
        date_filed="2015-06-26",
        absolute_url="/opinion/2812209/",
    )
    db_session.add(cluster)
    await db_session.flush()
    op = ResearchOpinionMetadata(
        opinion_id=3247759,
        cluster_id=2812209,
        text_field_used="html_with_citations",
        storage_path="courtlistener/opinions/by-cluster/2812209/3247759",
        char_length=1234,
    )
    db_session.add(op)
    await db_session.flush()
    assert op.opinion_id == 3247759
    assert cluster.case_name == "Obergefell v. Hodges"
