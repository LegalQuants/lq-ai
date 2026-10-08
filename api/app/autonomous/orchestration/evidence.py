"""Citation checks on a delivered run answer (ADR 0038 D5).

Each selected document is numbered evidence: ``[N]`` is document ``N`` of the
approved selection. A child copies quotations from what it read and marks them
``"quoted words" (Source: [N])``; the root keeps them. At delivery the answer
goes through the Citation Engine's local stages, its ledger and its gate, on the
run's own chat message, so the result is shown where a chat answer's is.

Only the deterministic stages run: exact match, then tolerant match. No judge
model is called. A run's model calls are priced, reserved effects, and a judge
call made here would be neither. A quotation these stages cannot match is
recorded as unverified, which flags the gate; it is never dropped.

Runs inside the delivery transaction. No remote I/O and no commit.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.orchestration.contracts import PreparedPlan
from app.citation.extraction import _CITATION_RE, CitationCandidate, locate_in_chunk
from app.citation.gate import compute_and_record_gate
from app.citation.ledger import assemble_ledger_entries
from app.citation.verification import verify
from app.models.chat import Message, MessageCitation
from app.models.document import Document
from app.models.orchestration import OrchestrationRoot

MAX_CHECKED_QUOTATIONS = 64

# Quoted text this long is treated as a quotation rather than a defined term.
MIN_QUOTATION_CHARS = 20

_CURLY_QUOTED = re.compile(r"\u201c([^\u201d]*)\u201d")


def _quoted_spans(content: str) -> list[tuple[int, int]]:
    """Each quoted passage, pairing quotation marks in the order they appear."""
    spans = [match.span() for match in _CURLY_QUOTED.finditer(content)]
    opened: int | None = None
    for index, char in enumerate(content):
        if char != '"':
            continue
        if opened is None:
            opened = index
        else:
            spans.append((opened, index + 1))
            opened = None
    return spans


def quotation_counts(content: str, numbers: Collection[int]) -> dict[str, int]:
    """How much of an answer's quoted text the checks could see. Counts only.

    ``marked`` quotations carry ``(Source: [N])``. An ``unresolved`` one names a
    number outside the selection, or falls past the checking cap, so nothing
    was checked for it. An ``unmarked`` passage is quoted text of
    ``MIN_QUOTATION_CHARS`` or more with no marker: the checks never see it.
    Reported so that "every checked quotation matched" is not read as "every
    quotation matched".
    """
    marked_spans: list[tuple[int, int]] = []
    unresolved = 0
    for index, match in enumerate(_CITATION_RE.finditer(content)):
        marked_spans.append(match.span())
        number = match.group("sq_index") or match.group("cq_index")
        if index >= MAX_CHECKED_QUOTATIONS or int(number) not in numbers:
            unresolved += 1
    unmarked = 0
    for start, end in _quoted_spans(content):
        if end - start - 2 < MIN_QUOTATION_CHARS:
            continue
        if any(
            start < marked_end and marked_start < end for marked_start, marked_end in marked_spans
        ):
            continue
        unmarked += 1
    return {"marked": len(marked_spans), "unresolved": unresolved, "unmarked": unmarked}


def _unverified(message: Message, file_id: Any, quote: str) -> MessageCitation:
    """A quotation that named a selected document and could not be matched.

    Offsets are a documented placeholder, as for an unverified case-law row: an
    unmatched quotation has no span, but the table requires one. The ledger
    reads the status, not the offsets.
    """
    return MessageCitation(
        message_id=message.id,
        source_file_id=file_id,
        source_offset_start=0,
        source_offset_end=max(1, len(quote)),
        source_page=None,
        source_text=quote,
        verified=False,
        verification_method=None,
        verification_confidence=None,
        partial=False,
    )


async def verify_delivered_answer(
    db: AsyncSession, root: OrchestrationRoot, plan: PreparedPlan, message: Message
) -> dict[str, Any]:
    """Check the answer's quotations against the selected documents.

    Returns counts and labels for the delivery audit row. Never text.
    """
    by_number = {ref.number: ref for ref in plan.documents}
    documents = {
        doc.id: doc
        for doc in (
            await db.scalars(
                select(Document).where(Document.id.in_([ref.document_id for ref in plan.documents]))
            )
        ).all()
    }
    verified = failed = unresolved = 0
    rows: list[MessageCitation] = []
    for index, match in enumerate(_CITATION_RE.finditer(message.content)):
        if index >= MAX_CHECKED_QUOTATIONS:
            unresolved += 1
            continue
        quote = match.group("sq") or match.group("cq")
        number = match.group("sq_index") or match.group("cq_index")
        ref = by_number.get(int(number)) if quote and number else None
        document = documents.get(ref.document_id) if ref is not None else None
        if not quote or ref is None or document is None:
            # No selected document to hold a row against. Counted, and shown
            # by the message's citation list as a marker without a match.
            unresolved += 1
            continue
        span = locate_in_chunk(quote, document.normalized_content or "")
        if span is None:
            rows.append(_unverified(message, ref.file_id, quote))
            failed += 1
            continue
        candidate = CitationCandidate(
            source_file_id=ref.file_id,
            source_document_id=document.id,
            source_offset_start=span[0],
            source_offset_end=span[1],
            source_page=None,
            source_text=quote,
        )
        result = await verify(candidate, document, gateway=None)
        if not result.verified:
            rows.append(_unverified(message, ref.file_id, quote))
            failed += 1
            continue
        rows.append(
            MessageCitation(
                message_id=message.id,
                source_file_id=candidate.source_file_id,
                source_offset_start=candidate.source_offset_start,
                source_offset_end=candidate.source_offset_end,
                source_page=None,
                source_text=quote,
                verified=True,
                verification_method=result.method,
                verification_confidence=result.confidence,
                partial=result.partial,
                tier_envelope=result.tier_envelope,
            )
        )
        verified += 1
    gate_status = "not_computed"
    if rows:
        db.add_all(rows)
        await db.flush()
        await assemble_ledger_entries(db, message_id=message.id)
        gate = await compute_and_record_gate(db, message_id=message.id)
        if gate is not None:
            gate_status = gate.gate_status
    counts = quotation_counts(message.content, by_number.keys())
    return {
        # No quotation matched a selected document: nothing was established.
        "verification": "citations_checked" if rows else "unverified",
        "citations_verified": verified,
        "citations_unverified": failed,
        "citations_unresolved": unresolved,
        # Quoted text with no source marker: the checks never saw it.
        "citations_unmarked": counts["unmarked"],
        "gate": gate_status,
    }
