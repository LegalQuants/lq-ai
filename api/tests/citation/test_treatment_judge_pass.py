"""Integration tests for the treatment judge pass (WS-G PR2).

Verifies that derive_treatment_for_message correctly:
- Runs the judge when gateway is supplied + case_name is resolvable.
- Writes CitationTreatmentSignal child rows and rolls up to the parent.
- Strips snippets from persisted citing_opinions (P3).
- Falls back to graph-only when gateway=None, budget=0, or case_name missing.
- Replaces signals on re-derivation (idempotent refresh).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.treatment import derive_treatment_for_message
from app.models.citation_treatment import CitationTreatment
from app.models.citation_treatment_signal import CitationTreatmentSignal
from app.models.research import ResearchClusterMetadata

# `seeded` fixture is provided by tests/citation/conftest.py (auto-discovered by pytest).

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

_NOW = datetime(2026, 6, 26, tzinfo=UTC)
_CLUSTER_ID = 2812209


async def _fetch_with_snippets(opinion_id: int) -> dict[str, Any]:
    return {
        "cited_by_count": 3,
        "citing": [
            {
                "cluster_id": 90,
                "opinion_id": 900,
                "case_name": "A v. B",
                "court": "ca9",
                "date_filed": "2021-01-01",
                "snippet": "We overrule the cited case.",
            },
            {
                "cluster_id": 91,
                "opinion_id": 901,
                "case_name": "C v. D",
                "court": "ca2",
                "date_filed": "2020-01-01",
                "snippet": "Citing for background.",
            },
        ],
    }


class _GW:
    """Stub gateway: returns 'overruled' if snippet contains 'overrule', else 'neutral'."""

    async def chat_completion(self, request: Any, *, request_id: Any = None) -> Any:
        body = request.messages[1].content
        cls = "overruled" if "overrule" in body else "neutral"
        conf = "high" if cls == "overruled" else "low"
        payload = json.dumps({"treatment": cls, "confidence": conf, "justification": "x"})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=payload))])


async def _seed_cluster_metadata(db_session: AsyncSession) -> None:
    db_session.add(ResearchClusterMetadata(cluster_id=_CLUSTER_ID, case_name="Smith v. Jones"))
    await db_session.flush()


@pytest.mark.asyncio
async def test_judge_pass_writes_signals_and_rollup(db_session: AsyncSession, seeded: Any) -> None:
    message_id, *_ = seeded
    await _seed_cluster_metadata(db_session)

    await derive_treatment_for_message(
        db_session,
        message_id=message_id,
        now=_NOW,
        fetch_citing=_fetch_with_snippets,
        gateway=_GW(),
        judge_model="fast",
    )

    t = (
        await db_session.execute(
            select(CitationTreatment).where(CitationTreatment.cluster_id == _CLUSTER_ID)
        )
    ).scalar_one()
    assert t.derived_method == "citation_graph+judge"
    assert t.strongest_negative_class == "overruled"
    assert t.judged_count == 2

    # P3: persisted refs carry NO snippet.
    assert all("snippet" not in ref for ref in t.citing_opinions)

    sigs = (
        (
            await db_session.execute(
                select(CitationTreatmentSignal).where(CitationTreatmentSignal.treatment_id == t.id)
            )
        )
        .scalars()
        .all()
    )
    assert {s.classification for s in sigs} == {"overruled", "neutral"}


@pytest.mark.asyncio
async def test_graph_only_when_no_gateway(db_session: AsyncSession, seeded: Any) -> None:
    message_id, *_ = seeded
    await _seed_cluster_metadata(db_session)

    # gateway omitted → graph-only
    await derive_treatment_for_message(
        db_session,
        message_id=message_id,
        now=_NOW,
        fetch_citing=_fetch_with_snippets,
    )

    t = (
        await db_session.execute(
            select(CitationTreatment).where(CitationTreatment.cluster_id == _CLUSTER_ID)
        )
    ).scalar_one()
    assert t.derived_method == "citation_graph"
    assert t.strongest_negative_class is None

    sigs = (await db_session.execute(select(CitationTreatmentSignal))).scalars().all()
    assert sigs == []


@pytest.mark.asyncio
async def test_budget_stops_pass_but_keeps_graph(db_session: AsyncSession, seeded: Any) -> None:
    message_id, *_ = seeded
    await _seed_cluster_metadata(db_session)

    await derive_treatment_for_message(
        db_session,
        message_id=message_id,
        now=_NOW,
        fetch_citing=_fetch_with_snippets,
        gateway=_GW(),
        judge_model="fast",
        judge_budget_usd=Decimal("0"),  # zero budget → no passages judged
    )

    t = (
        await db_session.execute(
            select(CitationTreatment).where(CitationTreatment.cluster_id == _CLUSTER_ID)
        )
    ).scalar_one()
    assert t.cited_by_count == 3  # graph survived
    assert t.derived_method == "citation_graph"  # no passages judged

    sigs = (await db_session.execute(select(CitationTreatmentSignal))).scalars().all()
    assert sigs == []


@pytest.mark.asyncio
async def test_graph_only_when_no_case_name(db_session: AsyncSession, seeded: Any) -> None:
    """When ResearchClusterMetadata is absent, judge pass is skipped (graph-only)."""
    message_id, *_ = seeded
    # deliberately do NOT seed ResearchClusterMetadata

    await derive_treatment_for_message(
        db_session,
        message_id=message_id,
        now=_NOW,
        fetch_citing=_fetch_with_snippets,
        gateway=_GW(),
        judge_model="fast",
    )

    t = (
        await db_session.execute(
            select(CitationTreatment).where(CitationTreatment.cluster_id == _CLUSTER_ID)
        )
    ).scalar_one()
    assert t.derived_method == "citation_graph"
    assert t.strongest_negative_class is None

    sigs = (await db_session.execute(select(CitationTreatmentSignal))).scalars().all()
    assert sigs == []


@pytest.mark.asyncio
async def test_re_derive_replaces_signals(db_session: AsyncSession, seeded: Any) -> None:
    """Re-derivation deletes prior signals — no duplicates, idempotent refresh."""
    message_id, *_ = seeded
    await _seed_cluster_metadata(db_session)

    # Derive twice with TTL=0 to force a refetch both times.
    for _ in range(2):
        await derive_treatment_for_message(
            db_session,
            message_id=message_id,
            now=_NOW,
            fetch_citing=_fetch_with_snippets,
            gateway=_GW(),
            judge_model="fast",
            ttl_days=0,
        )

    sigs = (await db_session.execute(select(CitationTreatmentSignal))).scalars().all()
    assert len(sigs) == 2  # not 4 — prior signals replaced
