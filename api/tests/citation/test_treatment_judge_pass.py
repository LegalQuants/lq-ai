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
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.ledger import resolve_ledger_entries
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

    # Use distinct timestamps so the second pass is genuinely stale and re-runs the judge.
    now1 = _NOW
    now2 = _NOW + timedelta(days=1)  # forces stale on the second pass (ttl_days=0)
    for now in (now1, now2):
        await derive_treatment_for_message(
            db_session,
            message_id=message_id,
            now=now,
            fetch_citing=_fetch_with_snippets,
            gateway=_GW(),
            judge_model="fast",
            ttl_days=0,
        )

    sigs = (await db_session.execute(select(CitationTreatmentSignal))).scalars().all()
    assert len(sigs) == 2  # delete-and-rewrite, not 4


async def _fetch_with_dup_opinion_id(opinion_id: int) -> dict[str, Any]:
    """Two citing refs sharing the same opinion_id — dedup guard under test."""
    return {
        "cited_by_count": 2,
        "citing": [
            {
                "cluster_id": 90,
                "opinion_id": 900,
                "case_name": "A v. B",
                "court": "ca9",
                "date_filed": "2021-01-01",
                "snippet": "First occurrence with opinion 900.",
            },
            {
                "cluster_id": 90,
                "opinion_id": 900,  # duplicate
                "case_name": "A v. B",
                "court": "ca9",
                "date_filed": "2021-01-01",
                "snippet": "Second occurrence — same opinion_id.",
            },
        ],
    }


class _BadGW:
    """Stub gateway that always returns malformed JSON → parse_treatment_response returns None."""

    async def chat_completion(self, request: Any, *, request_id: Any = None) -> Any:
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))]
        )


@pytest.mark.asyncio
async def test_failed_refresh_leaves_consistent_graph_only(
    db_session: AsyncSession, seeded: Any
) -> None:
    """Regression: a refresh where the judge yields no judgments must leave a consistent
    graph-only row — derived_method='citation_graph', rollup columns all None, no signals."""
    message_id, *_ = seeded
    await _seed_cluster_metadata(db_session)

    # First pass: working judge — writes signals + full rollup.
    await derive_treatment_for_message(
        db_session,
        message_id=message_id,
        now=_NOW,
        fetch_citing=_fetch_with_snippets,
        gateway=_GW(),
        judge_model="fast",
        ttl_days=0,
    )
    t = (
        await db_session.execute(
            select(CitationTreatment).where(CitationTreatment.cluster_id == _CLUSTER_ID)
        )
    ).scalar_one()
    assert t.derived_method == "citation_graph+judge"  # sanity

    # Second pass (stale): bad gateway → parser returns None for every snippet.
    await derive_treatment_for_message(
        db_session,
        message_id=message_id,
        now=_NOW + timedelta(days=1),
        fetch_citing=_fetch_with_snippets,
        gateway=_BadGW(),
        judge_model="fast",
        ttl_days=0,
    )

    await db_session.refresh(t)
    # Row must be honest graph-only — no stale judge fields.
    assert t.derived_method == "citation_graph"
    assert t.strongest_negative_class is None
    assert t.judged_count is None
    assert t.judge_as_of is None
    # Graph signal must have survived (cited_by_count refreshed by fetch_citing).
    assert t.cited_by_count == 3
    # Prior signals must be gone (deleted at the start of _run_judge_pass).
    sigs = (await db_session.execute(select(CitationTreatmentSignal))).scalars().all()
    assert sigs == []


# ---------------------------------------------------------------------------
# FIX 1 regression: orphaned child signals on a no-judge-pass stale refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_without_judge_pass_clears_prior_signals(
    db_session: AsyncSession, seeded: Any
) -> None:
    """Stale refresh with gateway=None must delete prior signals (FIX 1).

    Previously, the stale-refresh else-branch null-ed rollup columns but left
    child CitationTreatmentSignal rows, producing a contradictory graph-only
    parent with 'overruled' child signals visible on the read path.
    """
    message_id, chat_id, *_ = seeded
    await _seed_cluster_metadata(db_session)

    # First pass: working judge — writes 2 signals + full rollup.
    await derive_treatment_for_message(
        db_session,
        message_id=message_id,
        now=_NOW,
        fetch_citing=_fetch_with_snippets,
        gateway=_GW(),
        judge_model="fast",
        ttl_days=0,
    )
    t = (
        await db_session.execute(
            select(CitationTreatment).where(CitationTreatment.cluster_id == _CLUSTER_ID)
        )
    ).scalar_one()
    assert t.derived_method == "citation_graph+judge"  # sanity: judge ran

    # Second pass (stale, now+1d, ttl_days=0) with NO gateway — judge pass skipped.
    await derive_treatment_for_message(
        db_session,
        message_id=message_id,
        now=_NOW + timedelta(days=1),
        fetch_citing=_fetch_with_snippets,
        gateway=None,
        ttl_days=0,
    )

    await db_session.refresh(t)
    # Parent row must be honest graph-only.
    assert t.derived_method == "citation_graph"
    assert t.strongest_negative_class is None
    assert t.judged_count is None
    assert t.judge_as_of is None
    assert t.cited_by_count == 3  # graph still set

    # Child signals cleared even though no judge pass ran (FIX 1).
    remaining_sigs = (
        (
            await db_session.execute(
                select(CitationTreatmentSignal).where(CitationTreatmentSignal.treatment_id == t.id)
            )
        )
        .scalars()
        .all()
    )
    assert remaining_sigs == []

    # Read path must be consistent: no stale signals visible via resolve_ledger_entries.
    ledger = await resolve_ledger_entries(db_session, chat_id=chat_id, message_id=message_id)
    caselaw_entries = [e for e in ledger if e.get("source_kind") == "caselaw"]
    assert len(caselaw_entries) == 1
    treatment_dict = caselaw_entries[0]["treatment"]
    assert treatment_dict["signals"] == []
    assert treatment_dict["per_class_counts"] == {}
    assert treatment_dict["case_confidence"] is None


@pytest.mark.asyncio
async def test_refresh_without_judge_pass_clears_prior_signals_missing_case_name(
    db_session: AsyncSession, seeded: Any
) -> None:
    """Stale refresh with gateway but no case_name must also delete prior signals (FIX 1).

    The judge pass is skipped when ResearchClusterMetadata is absent/case_name blank.
    Signals written in the first pass must still be deleted.
    """
    message_id, chat_id, *_ = seeded
    await _seed_cluster_metadata(db_session)

    # First pass: working judge — writes signals.
    await derive_treatment_for_message(
        db_session,
        message_id=message_id,
        now=_NOW,
        fetch_citing=_fetch_with_snippets,
        gateway=_GW(),
        judge_model="fast",
        ttl_days=0,
    )

    # Remove ResearchClusterMetadata so the second pass cannot resolve case_name.
    meta = (
        await db_session.execute(
            select(ResearchClusterMetadata).where(ResearchClusterMetadata.cluster_id == _CLUSTER_ID)
        )
    ).scalar_one()
    await db_session.delete(meta)
    await db_session.flush()

    # Second pass (stale): gateway supplied but case_name unresolvable.
    await derive_treatment_for_message(
        db_session,
        message_id=message_id,
        now=_NOW + timedelta(days=1),
        fetch_citing=_fetch_with_snippets,
        gateway=_GW(),
        ttl_days=0,
    )

    t = (
        await db_session.execute(
            select(CitationTreatment).where(CitationTreatment.cluster_id == _CLUSTER_ID)
        )
    ).scalar_one()
    # Parent row must be graph-only.
    assert t.derived_method == "citation_graph"
    assert t.strongest_negative_class is None
    assert t.judged_count is None
    assert t.judge_as_of is None

    # Child signals cleared despite gateway being present (FIX 1).
    remaining_sigs = (
        (
            await db_session.execute(
                select(CitationTreatmentSignal).where(CitationTreatmentSignal.treatment_id == t.id)
            )
        )
        .scalars()
        .all()
    )
    assert remaining_sigs == []

    # Read path consistent.
    ledger = await resolve_ledger_entries(db_session, chat_id=chat_id, message_id=message_id)
    caselaw_entries = [e for e in ledger if e.get("source_kind") == "caselaw"]
    assert len(caselaw_entries) == 1
    treatment_dict = caselaw_entries[0]["treatment"]
    assert treatment_dict["signals"] == []
    assert treatment_dict["per_class_counts"] == {}
    assert treatment_dict["case_confidence"] is None


# ---------------------------------------------------------------------------
# FIX 2 regression: dedup citing_opinion_id in judge loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_citing_opinion_id_writes_single_signal(
    db_session: AsyncSession, seeded: Any
) -> None:
    """Two citing refs sharing opinion_id=900 must produce only one signal row (FIX 2).

    Without the dedup guard, the second insert would violate the
    uq_treatment_signal_treatment_citing unique constraint, raising IntegrityError.
    """
    message_id, *_ = seeded
    await _seed_cluster_metadata(db_session)

    await derive_treatment_for_message(
        db_session,
        message_id=message_id,
        now=_NOW,
        fetch_citing=_fetch_with_dup_opinion_id,
        gateway=_GW(),
        judge_model="fast",
    )

    t = (
        await db_session.execute(
            select(CitationTreatment).where(CitationTreatment.cluster_id == _CLUSTER_ID)
        )
    ).scalar_one()

    sigs = (
        (
            await db_session.execute(
                select(CitationTreatmentSignal).where(CitationTreatmentSignal.treatment_id == t.id)
            )
        )
        .scalars()
        .all()
    )
    # Only one signal for opinion_id=900, not two (dedup guard in effect).
    assert len(sigs) == 1
    assert sigs[0].citing_opinion_id == 900
