from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.citation_treatment import CitationTreatment

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_citation_treatment_roundtrip(db_session: AsyncSession) -> None:
    row = CitationTreatment(
        cluster_id=2812209,
        opinion_id=2812209,
        cited_by_count=412,
        citing_opinions=[
            {
                "cluster_id": 1001,
                "opinion_id": 9001,
                "case_name": "X v. Y",
                "court": "ca9",
                "date_filed": "2021-01-01",
            }
        ],
        derived_method="citation_graph",
    )
    db_session.add(row)
    await db_session.flush()
    got = (
        await db_session.execute(
            select(CitationTreatment).where(CitationTreatment.cluster_id == 2812209)
        )
    ).scalar_one()
    assert got.cited_by_count == 412
    assert got.citing_opinions[0]["case_name"] == "X v. Y"
    assert got.derived_method == "citation_graph"
    assert got.as_of is not None  # server_default now()
