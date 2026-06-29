"""WS-D PR2 — bridge a matter session's structured citations into the chat-path
ledger + fiduciary gate.

Reuses the character-fidelity verifier cascade (exact/tolerant/paraphrase)
and assembles ``MessageCitation`` rows in the same shape the chat path uses,
with no duplication of verification logic.

Only the citation-candidate front-end is session-specific: instead of
extracting citations from assistant text + retrieved chunks (the chat path),
here the planner hands us explicit ``(quote, chunk_id)`` pairs resolved
during the autonomous analysis turn.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.extraction import CitationCandidate, locate_in_chunk
from app.citation.verification import verify
from app.models.chat import MessageCitation
from app.models.document import Document, DocumentChunk

log = logging.getLogger(__name__)


async def build_kb_citations(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    citations: list[tuple[str, str]],  # (quote, chunk_id)
    gateway: Any,
    judge_model: str = "fast",
) -> int:
    """Resolve, verify, and persist KB structured citations into the ledger.

    For each ``(quote, chunk_id)`` pair:

    1. Fetch the ``DocumentChunk`` by ``chunk_id``.
    2. Locate ``quote`` inside ``chunk.content`` via :func:`locate_in_chunk`
       (exact, then fuzzy).  Miss → drop without a row.
    3. Fetch the ``Document`` the chunk belongs to.
    4. Build a :class:`CitationCandidate` with byte-precise offsets into
       ``normalized_content`` (``chunk.char_offset_start + in_chunk_offset``).
    5. Run the verifier cascade via :func:`verify`.  MISS → drop without a
       row (honest-degradation invariant).
    6. ``db.add`` a ``MessageCitation`` row; accumulate the count.

    ``db.flush()`` is called once at the end so callers can roll back the
    entire block as a unit if needed.

    Returns the number of rows added (0 when every citation was unverifiable
    or the chunk / document was not found).  Never fabricates rows.

    Note on lazy-relationship avoidance: ``chunk.document`` is NOT accessed
    (it is a lazy SQLAlchemy relationship that raises ``MissingGreenlet``
    inside an async session).  ``doc.file_id`` is read from the separately
    fetched ``Document`` row instead.
    """
    added = 0

    for quote, chunk_id_str in citations:
        try:
            chunk_uuid = uuid.UUID(str(chunk_id_str))
        except ValueError:
            log.warning(
                "kb citation build: invalid chunk_id",
                extra={"event": "autonomous_kb_citation_skip", "chunk_id": chunk_id_str},
            )
            continue

        try:
            chunk = (
                await db.execute(select(DocumentChunk).where(DocumentChunk.id == chunk_uuid))
            ).scalar_one_or_none()
            if chunk is None:
                log.warning(
                    "kb citation build: chunk not found",
                    extra={"event": "autonomous_kb_citation_skip", "chunk_id": chunk_id_str},
                )
                continue

            span = locate_in_chunk(quote, chunk.content)
            if span is None:
                # Quote not found in chunk — honest drop; no row.
                log.debug(
                    "kb citation build: locate miss",
                    extra={"event": "autonomous_kb_citation_skip", "chunk_id": chunk_id_str},
                )
                continue
            in_start, in_end = span

            doc = (
                await db.execute(select(Document).where(Document.id == chunk.document_id))
            ).scalar_one_or_none()
            if doc is None:
                log.warning(
                    "kb citation build: document not found",
                    extra={
                        "event": "autonomous_kb_citation_skip",
                        "document_id": str(chunk.document_id),
                    },
                )
                continue

            # Use doc.file_id directly — never access chunk.document (lazy
            # relationship; raises MissingGreenlet in async sessions).
            candidate = CitationCandidate(
                source_file_id=doc.file_id,
                source_document_id=chunk.document_id,
                source_offset_start=chunk.char_offset_start + in_start,
                source_offset_end=chunk.char_offset_start + in_end,
                source_page=chunk.page_start,
                source_text=quote,
            )

            # Pass raw Document — it satisfies _DocumentProtocol directly
            # (has id, normalized_content, was_ocrd).  Mirrors what
            # _persist_message_citations in chats.py does.
            result = await verify(candidate, doc, gateway=gateway, judge_model=judge_model)
            if not result.verified:
                # Every stage rejected — honest drop; no row.
                continue

            db.add(
                MessageCitation(
                    message_id=message_id,
                    source_file_id=candidate.source_file_id,
                    source_offset_start=candidate.source_offset_start,
                    source_offset_end=candidate.source_offset_end,
                    source_page=candidate.source_page,
                    source_text=quote,
                    verified=True,
                    verification_method=result.method,
                    verification_confidence=result.confidence,
                    partial=result.partial,
                    tier_envelope=result.tier_envelope,
                )
            )
            added += 1

        except Exception:
            # One bad citation must not sink the rest (per honest-degradation
            # invariant).  Log and continue so the remaining citations still
            # get a chance.
            log.warning(
                "kb citation build: unexpected error, skipping citation",
                extra={"event": "autonomous_kb_citation_skip", "chunk_id": chunk_id_str},
                exc_info=True,
            )

    await db.flush()
    return added
