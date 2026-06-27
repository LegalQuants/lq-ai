"""Derive the citation-graph treatment signal for a turn's cited cases (WS-G PR1/PR2).

Graph-only (PR1): for each case a turn cited, reuse a fresh ``citation_treatment`` row
or fetch the citing graph via the gateway and upsert one, then link the turn's
caselaw ledger entries to it.

Judge pass (PR2): when a gateway is supplied, after the graph upsert, judge the
top-N citing snippets per cluster, write CitationTreatmentSignal child rows, and
set the rollup on the parent row (``derived_method='citation_graph+judge'``).
Snippets are transient judge input — NEVER stored (P3). Per-case non-fatal
(conservative posture). ADR 0019 D2/D5.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.treatment_judge import (
    _TREATMENT_PURPOSE,  # noqa: F401 — imported for callers / tests
    estimate_treatment_cost_usd,
    judge_treatment,
)
from app.citation.treatment_rollup import roll_up
from app.citation.verification import _JudgeGatewayProtocol
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.citation_treatment import CitationTreatment
from app.models.citation_treatment_signal import CitationTreatmentSignal
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.research import ResearchClusterMetadata

log = logging.getLogger(__name__)

TREATMENT_TTL_DAYS = 30
N_JUDGED_CAP = 10
TREATMENT_JUDGE_BUDGET_USD = Decimal("0.25")

_FetchCiting = Callable[[int], Awaitable[dict[str, Any]]]


def _strip_snippet(citing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist refs only — the snippet is transient judge input (P3)."""
    return [{k: v for k, v in ref.items() if k != "snippet"} for ref in citing]


async def _default_fetch_citing(opinion_id: int) -> dict[str, Any]:
    from app.research import service as research_service

    return await research_service.get_citing_opinions(opinion_id)


async def derive_treatment_for_message(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    now: datetime,
    ttl_days: int = TREATMENT_TTL_DAYS,
    fetch_citing: _FetchCiting = _default_fetch_citing,
    gateway: _JudgeGatewayProtocol | None = None,
    judge_model: str = "fast",
    judge_budget_usd: Decimal = TREATMENT_JUDGE_BUDGET_USD,
    n_judged_cap: int = N_JUDGED_CAP,
) -> int:
    """Derive/refresh graph treatment for each case this turn cited; link entries.

    When ``gateway`` is supplied and the cited case name can be resolved from
    ``ResearchClusterMetadata``, also runs the treatment judge over the top-N
    citing snippets and writes ``CitationTreatmentSignal`` child rows + rollup.
    Snippets are transient — never stored (P3).

    Returns the number of caselaw ledger entries linked to a treatment row.
    Never raises on a per-case failure (logged and skipped).
    """
    if now.tzinfo is None:
        raise ValueError("derive_treatment_for_message requires a timezone-aware 'now'")
    citations = (
        (
            await db.execute(
                select(MessageCaselawCitation).where(
                    MessageCaselawCitation.message_id == message_id
                )
            )
        )
        .scalars()
        .all()
    )
    if not citations:
        return 0

    # One derivation per distinct cited cluster; remember a representative opinion_id.
    by_cluster: dict[int, int] = {}
    for c in citations:
        by_cluster.setdefault(c.cluster_id, c.opinion_id)

    cluster_to_treatment: dict[int, uuid.UUID] = {}
    stale_before = now - timedelta(days=ttl_days)
    for cluster_id, opinion_id in by_cluster.items():
        try:
            existing = (
                await db.execute(
                    select(CitationTreatment).where(CitationTreatment.cluster_id == cluster_id)
                )
            ).scalar_one_or_none()
            if existing is not None and existing.as_of >= stale_before:
                # Fresh cache — reuse without fetch or re-judging.
                cluster_to_treatment[cluster_id] = existing.id
                continue
            payload = await fetch_citing(opinion_id)
            raw_citing = list(payload.get("citing") or [])
            persisted_citing = _strip_snippet(raw_citing)
            treatment_row: CitationTreatment
            if existing is None:
                row = CitationTreatment(
                    cluster_id=cluster_id,
                    opinion_id=opinion_id,
                    cited_by_count=int(payload.get("cited_by_count") or 0),
                    citing_opinions=persisted_citing,
                    derived_method="citation_graph",
                    as_of=now,
                )
                db.add(row)
                await db.flush()
                cluster_to_treatment[cluster_id] = row.id
                treatment_row = row
            else:
                existing.cited_by_count = int(payload.get("cited_by_count") or 0)
                existing.citing_opinions = persisted_citing
                existing.derived_method = "citation_graph"
                existing.opinion_id = opinion_id
                existing.as_of = now
                await db.flush()
                cluster_to_treatment[cluster_id] = existing.id
                treatment_row = existing

            # Judge pass (PR2): only when a gateway is supplied.
            if gateway is not None:
                meta = (
                    await db.execute(
                        select(ResearchClusterMetadata).where(
                            ResearchClusterMetadata.cluster_id == cluster_id
                        )
                    )
                ).scalar_one_or_none()
                case_name = meta.case_name if meta is not None else None
                if case_name:
                    await _run_judge_pass(
                        db,
                        treatment_row=treatment_row,
                        cited_case_name=case_name,
                        raw_citing=raw_citing,
                        now=now,
                        gateway=gateway,
                        judge_model=judge_model,
                        judge_budget_usd=judge_budget_usd,
                        n_judged_cap=n_judged_cap,
                    )
                else:
                    log.debug(
                        "treatment judge skipped for cluster %s: case_name unavailable",
                        cluster_id,
                    )
        except Exception as exc:  # per-case non-fatal (conservative posture)
            log.warning("treatment derivation failed for cluster %s: %r", cluster_id, exc)

    if not cluster_to_treatment:
        return 0

    # Link this turn's caselaw ledger entries to their cluster's treatment row.
    cc_id_to_cluster = {c.id: c.cluster_id for c in citations}
    entries = (
        (
            await db.execute(
                select(CitationLedgerEntry).where(
                    CitationLedgerEntry.message_id == message_id,
                    CitationLedgerEntry.source_kind == "caselaw",
                )
            )
        )
        .scalars()
        .all()
    )
    linked = 0
    for e in entries:
        cc_id = e.message_caselaw_citation_id
        if cc_id is None:
            continue
        entry_cluster_id = cc_id_to_cluster.get(cc_id)
        if entry_cluster_id is None:
            continue
        treatment_id = cluster_to_treatment.get(entry_cluster_id)
        if treatment_id is not None:
            e.treatment_id = treatment_id
            linked += 1
    if linked:
        await db.flush()
    return linked


async def _run_judge_pass(
    db: AsyncSession,
    *,
    treatment_row: CitationTreatment,
    cited_case_name: str,
    raw_citing: list[dict[str, Any]],
    now: datetime,
    gateway: _JudgeGatewayProtocol,
    judge_model: str,
    judge_budget_usd: Decimal,
    n_judged_cap: int,
) -> None:
    """Judge top-N citing snippets, write child signals + rollup. Non-fatal per passage."""
    # Idempotent refresh: clear this row's prior signals before writing new ones.
    await db.execute(
        delete(CitationTreatmentSignal).where(
            CitationTreatmentSignal.treatment_id == treatment_row.id
        )
    )
    per_call = await estimate_treatment_cost_usd(db, judge_model=judge_model)
    spent = Decimal("0")
    judgments = []
    # raw_citing is already recency-sorted by the upstream service; take the cap.
    for ref in raw_citing[:n_judged_cap]:
        snippet = ref.get("snippet")
        citing_opinion_id = ref.get("opinion_id")
        if not snippet or citing_opinion_id is None:
            continue
        if spent + per_call > judge_budget_usd:
            break  # budget exhausted — keep what was judged so far
        spent += per_call
        try:
            judgment = await judge_treatment(
                cited_case_name=cited_case_name,
                snippet=snippet,
                gateway=gateway,
                judge_model=judge_model,
            )
        except Exception as exc:  # defense in depth; judge_treatment already swallows
            log.warning("treatment judge raised for opinion %s: %r", citing_opinion_id, exc)
            continue
        if judgment is None:
            continue
        db.add(
            CitationTreatmentSignal(
                treatment_id=treatment_row.id,
                citing_opinion_id=int(citing_opinion_id),
                classification=judgment.classification,
                confidence=judgment.confidence,
                justification=judgment.justification,
            )
        )
        judgments.append(judgment)
    if not judgments:
        # Nothing classified — leave graph-only; signals already cleared above.
        return
    rollup = roll_up(judgments)
    treatment_row.strongest_negative_class = rollup.strongest_negative_class
    treatment_row.judged_count = rollup.judged_count
    treatment_row.judge_as_of = now
    treatment_row.derived_method = "citation_graph+judge"
    await db.flush()
