"""Derive the citation-graph treatment signal for a turn's cited cases (WS-G PR1).

Graph-only: for each case a turn cited, reuse a fresh ``citation_treatment`` row
or fetch the citing graph via the gateway and upsert one, then link the turn's
caselaw ledger entries to it. No LLM-judge (that is PR2). Per-case non-fatal
(conservative posture). ADR 0019 D2.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.citation_treatment import CitationTreatment
from app.models.message_caselaw_citation import MessageCaselawCitation

log = logging.getLogger(__name__)

TREATMENT_TTL_DAYS = 30

_FetchCiting = Callable[[int], Awaitable[dict[str, Any]]]


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
) -> int:
    """Derive/refresh graph treatment for each case this turn cited; link entries.

    Returns the number of caselaw ledger entries linked to a treatment row.
    Never raises on a per-case failure (logged and skipped).
    """
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
                cluster_to_treatment[cluster_id] = existing.id
                continue
            payload = await fetch_citing(opinion_id)
            if existing is None:
                row = CitationTreatment(
                    cluster_id=cluster_id,
                    opinion_id=opinion_id,
                    cited_by_count=int(payload.get("cited_by_count") or 0),
                    citing_opinions=list(payload.get("citing") or []),
                    derived_method="citation_graph",
                    as_of=now,
                )
                db.add(row)
                await db.flush()
                cluster_to_treatment[cluster_id] = row.id
            else:
                existing.cited_by_count = int(payload.get("cited_by_count") or 0)
                existing.citing_opinions = list(payload.get("citing") or [])
                existing.derived_method = "citation_graph"
                existing.opinion_id = opinion_id
                existing.as_of = now
                await db.flush()
                cluster_to_treatment[cluster_id] = existing.id
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
        cluster_id = cc_id_to_cluster.get(e.message_caselaw_citation_id)
        treatment_id = cluster_to_treatment.get(cluster_id) if cluster_id is not None else None
        if treatment_id is not None:
            e.treatment_id = treatment_id
            linked += 1
    if linked:
        await db.flush()
    return linked
