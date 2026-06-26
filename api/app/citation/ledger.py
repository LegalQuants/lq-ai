"""Citation Ledger assembly (ADR 0018 D1).

Reads the three per-turn citation/source artifacts for an assistant message and
writes one ``CitationLedgerEntry`` per row — a thin referencing index. Source-kind
agnostic over ``message_tool_sources`` (so generic-MCP rows flow in once DE-350
lands). Holds no content; references by id.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat, Message, MessageCitation
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.message_tool_source import MessageToolSource

log = logging.getLogger(__name__)


async def assemble_ledger_entries(db: AsyncSession, *, message_id: uuid.UUID) -> int:
    """Write one ledger entry per citation/source row for ``message_id``.

    Self-derives ``chat_id`` (from the message) and ``project_id`` (from the chat).
    Returns the number of entries written. Pure DB; no egress.
    """
    chat_id = (
        await db.execute(select(Message.chat_id).where(Message.id == message_id))
    ).scalar_one_or_none()
    if chat_id is None:
        return 0
    project_id = (
        await db.execute(select(Chat.project_id).where(Chat.id == chat_id))
    ).scalar_one_or_none()

    entries: list[CitationLedgerEntry] = []

    doc_citations = (
        (await db.execute(select(MessageCitation).where(MessageCitation.message_id == message_id)))
        .scalars()
        .all()
    )
    for c in doc_citations:
        entries.append(
            CitationLedgerEntry(
                project_id=project_id,
                chat_id=chat_id,
                message_id=message_id,
                source_kind="kb_document",
                message_citation_id=c.id,
                verification_status=c.verification_method if c.verified else "unverified",
                confidence=(
                    float(c.verification_confidence)
                    if (c.verified and c.verification_confidence is not None)
                    else None
                ),
                provider=None,
                retrieved_at=None,
            )
        )

    caselaw_citations = (
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
    for cc in caselaw_citations:
        entries.append(
            CitationLedgerEntry(
                project_id=project_id,
                chat_id=chat_id,
                message_id=message_id,
                source_kind="caselaw",
                message_caselaw_citation_id=cc.id,
                verification_status=cc.verification_method if cc.verified else "unverified",
                confidence=cc.verification_confidence if cc.verified else None,
                provider="courtlistener",
                retrieved_at=cc.created_at,
            )
        )

    tool_sources = (
        (
            await db.execute(
                select(MessageToolSource).where(MessageToolSource.message_id == message_id)
            )
        )
        .scalars()
        .all()
    )
    for ts in tool_sources:
        entries.append(
            CitationLedgerEntry(
                project_id=project_id,
                chat_id=chat_id,
                message_id=message_id,
                source_kind=ts.source_kind,
                message_tool_source_id=ts.id,
                verification_status="provenance",
                confidence=None,
                provider=ts.provider,
                retrieved_at=ts.created_at,
            )
        )

    if entries:
        db.add_all(entries)
        await db.flush()
    return len(entries)


def _resolve_source(
    entry: CitationLedgerEntry,
    docs: dict[uuid.UUID, MessageCitation],
    caselaw: dict[uuid.UUID, MessageCaselawCitation],
    tools: dict[uuid.UUID, MessageToolSource],
) -> dict[str, Any] | None:
    """Resolve an entry's single referenced row to a source block, or None if absent."""
    if entry.message_citation_id is not None:
        c = docs.get(entry.message_citation_id)
        if c is None:
            return None
        return {
            "kind": "kb_document",
            "source_file_id": str(c.source_file_id),
            "passages": [
                {
                    "text": c.source_text,
                    "offset_start": c.source_offset_start,
                    "offset_end": c.source_offset_end,
                    "page": c.source_page,
                }
            ],
        }
    if entry.message_caselaw_citation_id is not None:
        cc = caselaw.get(entry.message_caselaw_citation_id)
        if cc is None:
            return None
        return {
            "kind": "caselaw",
            "opinion_id": cc.opinion_id,
            "cluster_id": cc.cluster_id,
            "passages": [
                {
                    "text": cc.source_text,
                    "offset_start": cc.source_offset_start,
                    "offset_end": cc.source_offset_end,
                }
            ],
        }
    if entry.message_tool_source_id is not None:
        ts = tools.get(entry.message_tool_source_id)
        if ts is None:
            return None
        return {
            "kind": ts.source_kind,
            "label": ts.label,
            "subtitle": ts.subtitle,
            "url": ts.url,
            "external_ref": ts.external_ref,
            "tool": ts.tool,
        }
    return None


async def resolve_ledger_entries(
    db: AsyncSession, *, chat_id: uuid.UUID, message_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    """Return ledger entries for a chat (optionally one turn), each resolved to its
    source identity + passage(s) read + status + provenance. Pure DB; no egress.

    Passage text is resolved from the content layer at read time; the ledger row
    itself holds no content (ADR 0018 D4/D5).
    """
    stmt = select(CitationLedgerEntry).where(CitationLedgerEntry.chat_id == chat_id)
    if message_id is not None:
        stmt = stmt.where(CitationLedgerEntry.message_id == message_id)
    stmt = stmt.order_by(CitationLedgerEntry.created_at, CitationLedgerEntry.id)
    entries = (await db.execute(stmt)).scalars().all()
    if not entries:
        return []

    doc_ids = {e.message_citation_id for e in entries if e.message_citation_id is not None}
    case_ids = {
        e.message_caselaw_citation_id for e in entries if e.message_caselaw_citation_id is not None
    }
    tool_ids = {e.message_tool_source_id for e in entries if e.message_tool_source_id is not None}

    docs: dict[uuid.UUID, MessageCitation] = {}
    if doc_ids:
        docs = {
            r.id: r
            for r in (
                await db.execute(select(MessageCitation).where(MessageCitation.id.in_(doc_ids)))
            )
            .scalars()
            .all()
        }
    caselaw: dict[uuid.UUID, MessageCaselawCitation] = {}
    if case_ids:
        caselaw = {
            r.id: r
            for r in (
                await db.execute(
                    select(MessageCaselawCitation).where(MessageCaselawCitation.id.in_(case_ids))
                )
            )
            .scalars()
            .all()
        }
    tools: dict[uuid.UUID, MessageToolSource] = {}
    if tool_ids:
        tools = {
            r.id: r
            for r in (
                await db.execute(
                    select(MessageToolSource).where(MessageToolSource.id.in_(tool_ids))
                )
            )
            .scalars()
            .all()
        }

    out: list[dict[str, Any]] = []
    for e in entries:
        source = _resolve_source(e, docs, caselaw, tools)
        if source is None:
            log.warning("ledger entry %s references a missing source row; skipping", e.id)
            continue
        out.append(
            {
                "id": str(e.id),
                "message_id": str(e.message_id),
                "source_kind": e.source_kind,
                "verification_status": e.verification_status,
                "confidence": e.confidence,
                "provider": e.provider,
                "retrieved_at": e.retrieved_at.isoformat() if e.retrieved_at else None,
                "treatment_id": str(e.treatment_id) if e.treatment_id else None,
                "created_at": e.created_at.isoformat(),
                "source": source,
            }
        )
    return out
