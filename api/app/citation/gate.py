"""Fiduciary-grade gate computation (ADR 0018 D3).

Deterministically buckets a turn's ``citation_ledger_entry`` rows into PASS /
SUPPORTED / FAIL by their mirrored ``verification_status`` and records one
``work_product_fiduciary_gate`` verdict per assistant message. Pure DB; no egress.
Provenance-only entries (tool sources, no quote) are not assertions and are
excluded from the counts.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.work_product_fiduciary_gate import WorkProductFiduciaryGate

log = logging.getLogger(__name__)

PASS_STATUSES: frozenset[str] = frozenset({"exact_match", "tolerant_match"})
SUPPORTED_STATUSES: frozenset[str] = frozenset(
    {"paraphrase_judge", "ensemble_strict", "ensemble_majority"}
)
FAIL_STATUSES: frozenset[str] = frozenset({"unverified", "failed"})
_PROVENANCE = "provenance"


async def compute_and_record_gate(
    db: AsyncSession, *, message_id: uuid.UUID
) -> WorkProductFiduciaryGate | None:
    """Compute the fiduciary-grade verdict for ``message_id`` and upsert it.

    Returns the recorded row, or ``None`` if the message has no chat (should not
    happen at finalize). Flushes, never commits (rides the caller's transaction).
    """
    chat_id = (
        await db.execute(select(Message.chat_id).where(Message.id == message_id))
    ).scalar_one_or_none()
    if chat_id is None:
        return None
    project_id = (
        await db.execute(select(Chat.project_id).where(Chat.id == chat_id))
    ).scalar_one_or_none()

    entries = (
        (
            await db.execute(
                select(CitationLedgerEntry).where(CitationLedgerEntry.message_id == message_id)
            )
        )
        .scalars()
        .all()
    )

    pass_count = supported_count = fail_count = 0
    confidences: list[float] = []
    for e in entries:
        status = e.verification_status
        if status == _PROVENANCE:
            continue
        if status in PASS_STATUSES:
            pass_count += 1
        elif status in SUPPORTED_STATUSES:
            supported_count += 1
        elif status in FAIL_STATUSES:
            fail_count += 1
        else:
            log.warning(
                "fiduciary gate: unrecognized verification_status %r on entry %s; excluded",
                status,
                e.id,
            )
            continue
        if e.confidence is not None:
            confidences.append(e.confidence)

    total = pass_count + supported_count + fail_count
    if fail_count > 0:
        gate_status = "flagged"
    elif supported_count > 0:
        gate_status = "supported_only"
    else:
        gate_status = "fiduciary_grade"
    confidence = sum(confidences) / len(confidences) if confidences else None

    # Upsert: a re-finalize replaces the current verdict (the ledger is the history).
    await db.execute(
        delete(WorkProductFiduciaryGate).where(WorkProductFiduciaryGate.message_id == message_id)
    )
    row = WorkProductFiduciaryGate(
        message_id=message_id,
        chat_id=chat_id,
        project_id=project_id,
        gate_status=gate_status,
        pass_count=pass_count,
        supported_count=supported_count,
        fail_count=fail_count,
        total_assertions=total,
        confidence=confidence,
    )
    db.add(row)
    await db.flush()
    return row


async def resolve_gates(
    db: AsyncSession, *, chat_id: uuid.UUID, message_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    """Return the fiduciary-grade verdict(s) for a chat (optionally one turn)."""
    stmt = select(WorkProductFiduciaryGate).where(WorkProductFiduciaryGate.chat_id == chat_id)
    if message_id is not None:
        stmt = stmt.where(WorkProductFiduciaryGate.message_id == message_id)
    stmt = stmt.order_by(WorkProductFiduciaryGate.created_at, WorkProductFiduciaryGate.id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "message_id": str(g.message_id),
            "gate_status": g.gate_status,
            "pass_count": g.pass_count,
            "supported_count": g.supported_count,
            "fail_count": g.fail_count,
            "total_assertions": g.total_assertions,
            "confidence": g.confidence,
            "created_at": g.created_at.isoformat(),
        }
        for g in rows
    ]
