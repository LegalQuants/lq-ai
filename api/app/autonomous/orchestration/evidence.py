"""Citation checks on a delivered run answer (ADR 0038 D5).

Each selected document is numbered evidence: ``[N]`` is document ``N`` of the
approved selection. A file that a task's knowledge-base search found is
numbered too, above the selection, when it is found
(:mod:`app.autonomous.orchestration.sourcing`). A child copies quotations from
what it read and marks them ``"quoted words" (Source: [N])``; the root keeps
them. At delivery the answer goes through the Citation Engine's local stages,
its ledger and its gate, on the run's own chat message, so the result is shown
where a chat answer's is.

A quotation is checked against the whole text of the file its number names,
whether a task read that file as a selected document or was shown one passage
of it by a search.

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
from app.autonomous.orchestration.planning import PlanningSnapshot
from app.autonomous.orchestration.sourcing import run_sources
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


async def source_numbers(
    db: AsyncSession, root_id: Any, plan: PreparedPlan | PlanningSnapshot
) -> dict[int, tuple[Any, Any]]:
    """Every source number of a run, as the file and the document it names.

    The selected documents, and above them the files its tasks' searches found.
    A selected document keeps its number if a search also finds it under another.
    """
    numbers: dict[int, tuple[Any, Any]] = {
        ref.number: (ref.file_id, ref.document_id) for ref in plan.documents
    }
    for source in await run_sources(db, root_id):
        numbers.setdefault(source.number, (source.file_id, source.document_id))
    return numbers


async def verify_delivered_answer(
    db: AsyncSession,
    root: OrchestrationRoot,
    plan: PreparedPlan | PlanningSnapshot,
    message: Message,
) -> dict[str, Any]:
    """Check the answer's quotations against the files their numbers name.

    ``plan`` is the approved plan, or the intake when the orchestrator
    answered by itself. Returns counts and labels for the delivery audit row.
    Never text.
    """
    by_number = await source_numbers(db, root.session_id, plan)
    documents = {
        doc.id: doc
        for doc in (
            await db.scalars(
                select(Document).where(
                    Document.id.in_([document_id for _, document_id in by_number.values()])
                )
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
        named = by_number.get(int(number)) if quote and number else None
        document = documents.get(named[1]) if named is not None else None
        if not quote or named is None or document is None:
            # No source of this run to hold a row against. Counted, and shown
            # by the message's citation list as a marker without a match.
            unresolved += 1
            continue
        file_id = named[0]
        span = locate_in_chunk(quote, document.normalized_content or "")
        if span is None:
            rows.append(_unverified(message, file_id, quote))
            failed += 1
            continue
        candidate = CitationCandidate(
            source_file_id=file_id,
            source_document_id=document.id,
            source_offset_start=span[0],
            source_offset_end=span[1],
            source_page=None,
            source_text=quote,
        )
        result = await verify(candidate, document, gateway=None)
        if not result.verified:
            rows.append(_unverified(message, file_id, quote))
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
