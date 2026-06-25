"""Citation Ledger assembly (ADR 0018 D1).

Reads the three per-turn citation/source artifacts for an assistant message and
writes one ``CitationLedgerEntry`` per row — a thin referencing index. Source-kind
agnostic over ``message_tool_sources`` (so generic-MCP rows flow in once DE-350
lands). Holds no content; references by id.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat, Message, MessageCitation
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.message_tool_source import MessageToolSource


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
                verification_status=c.verification_method or "verified",
                confidence=float(c.verification_confidence)
                if c.verification_confidence is not None
                else None,
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
                verification_status=cc.verification_method or "verified",
                confidence=cc.verification_confidence,
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
