"""Chunk-boundary fallback tests for the citation extractor — M3-0.2 / DE-277.

Until DE-277 landed, the extractor located each quote inside the cited
chunk's content only. A quote spanning the boundary between two
adjacent retrieved chunks — present in
``documents.normalized_content`` but in neither chunk individually —
dropped silently. The marker rendered as "unverified" in the M2-C2 UI
even though the underlying text matched.

DE-277 extends the extractor's locator with a full-document fallback:
when the chunk-local search misses, retry the same exact-then-fuzzy
locator against the chunk's parent document's
``normalized_content``. The resolved offsets are document-absolute
(no ``chunk.char_offset_start`` arithmetic) so the downstream verifier
consumes them with no change.

These are pure unit tests against the extractor function; the
end-to-end persistence path is exercised separately by
``test_edge_cases.py::test_chunk_boundary_spanning_citation_verifies_via_full_doc_scan``.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import pytest

from app.citation.extraction import extract_citations


@dataclass(slots=True)
class _StubChunk:
    """HybridSearchResult-shaped stub — no DB needed for extractor tests."""

    document_id: uuid.UUID
    file_id: uuid.UUID
    content: str
    page_start: int | None
    char_offset_start: int
    char_offset_end: int


def _make_doc_with_two_chunks(
    full_content: str, split_at: int
) -> tuple[uuid.UUID, uuid.UUID, list[_StubChunk]]:
    """Build a document split into two adjacent half-chunks.

    Returns ``(doc_id, file_id, [chunk_a, chunk_b])``. Both chunks
    share the same ``document_id`` and ``file_id``; their
    ``char_offset_*`` are document-absolute and the union of their
    content equals ``full_content``.
    """
    doc_id = uuid.uuid4()
    file_id = uuid.uuid4()
    chunk_a = _StubChunk(
        document_id=doc_id,
        file_id=file_id,
        content=full_content[:split_at],
        page_start=1,
        char_offset_start=0,
        char_offset_end=split_at,
    )
    chunk_b = _StubChunk(
        document_id=doc_id,
        file_id=file_id,
        content=full_content[split_at:],
        page_start=1,
        char_offset_start=split_at,
        char_offset_end=len(full_content),
    )
    return doc_id, file_id, [chunk_a, chunk_b]


@pytest.mark.unit
def test_two_chunk_span_verifies_via_doc_scan() -> None:
    """Quote spanning two adjacent chunks resolves with document-absolute offsets."""

    full = "Section 1: The non-compete clause provides for a two-year restriction."
    doc_id, file_id, chunks = _make_doc_with_two_chunks(full, split_at=35)

    # The quote sits in the middle of the document, straddling chunks.
    quote_start, quote_end = 20, 55
    quote = full[quote_start:quote_end]
    assert quote not in chunks[0].content
    assert quote not in chunks[1].content
    assert quote in full

    response = f'The agreement says "{quote}" (Source: [1]).'

    candidates = extract_citations(response, chunks, document_contents={doc_id: full})

    assert len(candidates) == 1
    cite = candidates[0]
    assert cite.source_document_id == doc_id
    assert cite.source_file_id == file_id
    # Document-absolute offsets, NOT chunk-relative + chunk_offset_start.
    assert cite.source_offset_start == quote_start
    assert cite.source_offset_end == quote_end
    assert cite.source_text == quote


@pytest.mark.unit
def test_three_chunk_span_verifies_via_doc_scan() -> None:
    """Quotes spanning three adjacent chunks (long quotes) also resolve."""

    full = (
        "Article 1. Confidential Information. "
        "Each Party shall hold in confidence all Confidential Information disclosed. "
        "Permitted Disclosures include legal counsel and regulators."
    )
    doc_id = uuid.uuid4()
    file_id = uuid.uuid4()

    boundaries = [(0, 40), (40, 110), (110, len(full))]
    chunks = [
        _StubChunk(
            document_id=doc_id,
            file_id=file_id,
            content=full[start:end],
            page_start=1,
            char_offset_start=start,
            char_offset_end=end,
        )
        for start, end in boundaries
    ]

    # Quote spans all three chunks.
    quote_start, quote_end = 20, 135
    quote = full[quote_start:quote_end]
    assert all(quote not in c.content for c in chunks)
    assert quote in full

    response = f'The agreement says "{quote}" (Source: [1]).'

    candidates = extract_citations(response, chunks, document_contents={doc_id: full})

    assert len(candidates) == 1
    cite = candidates[0]
    assert cite.source_offset_start == quote_start
    assert cite.source_offset_end == quote_end
    assert cite.source_text == quote


@pytest.mark.unit
def test_single_chunk_citation_uses_chunk_local_path_no_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Quote entirely inside the cited chunk → chunk-arithmetic path, no warning.

    Regression case: existing single-chunk citations must continue to
    flow through the chunk-local locator and apply
    ``chunk.char_offset_start`` arithmetic. The ``citation_chunk_mismatch``
    warning must NOT fire — that signal is reserved for cases where the
    full-document fallback actually fired.
    """

    full = "The contract term shall be five years from the effective date."
    doc_id, _file_id, chunks = _make_doc_with_two_chunks(full, split_at=27)

    # Quote fits entirely inside chunk_b — chunk-local search succeeds.
    quote = "five years from the effective date."
    assert quote in chunks[1].content

    response = f'The agreement says "{quote}" (Source: [2]).'

    with caplog.at_level(logging.WARNING, logger="app.citation.extraction"):
        candidates = extract_citations(response, chunks, document_contents={doc_id: full})

    assert len(candidates) == 1
    cite = candidates[0]
    # Document-absolute via chunk_b.char_offset_start + in_chunk_start.
    expected_start = chunks[1].char_offset_start + chunks[1].content.find(quote)
    assert cite.source_offset_start == expected_start
    assert cite.source_offset_end == expected_start + len(quote)

    # The chunk-mismatch warning is reserved for the fallback path. A
    # successful chunk-local hit must NOT emit it.
    mismatch_records = [
        r for r in caplog.records if r.__dict__.get("event") == "citation_chunk_mismatch"
    ]
    assert mismatch_records == []


@pytest.mark.unit
def test_spanning_fallback_emits_chunk_mismatch_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the doc-scan fallback fires, emit the operator-observability warning."""

    full = "Section 1: The non-compete clause provides for a two-year restriction."
    doc_id, _file_id, chunks = _make_doc_with_two_chunks(full, split_at=35)

    quote = full[20:55]
    assert quote not in chunks[0].content
    assert quote not in chunks[1].content
    assert quote in full

    response = f'The agreement says "{quote}" (Source: [1]).'

    with caplog.at_level(logging.WARNING, logger="app.citation.extraction"):
        candidates = extract_citations(response, chunks, document_contents={doc_id: full})

    assert len(candidates) == 1
    mismatch_records = [
        r for r in caplog.records if r.__dict__.get("event") == "citation_chunk_mismatch"
    ]
    assert len(mismatch_records) == 1
    record = mismatch_records[0]
    assert record.__dict__["document_id"] == str(doc_id)
    assert record.__dict__["cited_chunk_index"] == 1
    assert record.__dict__["quote_prefix"] == quote[:40]


@pytest.mark.unit
def test_quote_not_in_document_drops() -> None:
    """Quote absent from both the chunk AND the document → no candidate."""

    full = "Section 1: The non-compete clause provides for a two-year restriction."
    doc_id, _file_id, chunks = _make_doc_with_two_chunks(full, split_at=35)

    # Quote fabricated by the model — not in the document anywhere.
    fabricated = "five-year exclusive license to undisclosed third parties"
    assert fabricated not in full

    response = f'The agreement says "{fabricated}" (Source: [1]).'

    candidates = extract_citations(response, chunks, document_contents={doc_id: full})

    assert candidates == []


@pytest.mark.unit
def test_no_document_contents_preserves_pre_de277_behavior() -> None:
    """Without ``document_contents``, the extractor behaves exactly as it did pre-DE-277.

    Spanning quotes drop silently — same as the M2-B1 shipped behavior.
    Backward compatibility for any caller that hasn't yet adopted the
    new map parameter.
    """

    full = "Section 1: The non-compete clause provides for a two-year restriction."
    _doc_id, _file_id, chunks = _make_doc_with_two_chunks(full, split_at=35)

    quote = full[20:55]
    response = f'The agreement says "{quote}" (Source: [1]).'

    candidates = extract_citations(response, chunks)  # no document_contents arg

    assert candidates == []


@pytest.mark.unit
def test_document_contents_map_missing_doc_id_drops_safely() -> None:
    """If the caller's map omits a chunk's doc_id, that candidate falls back to drop.

    Defensive: rather than crashing or raising KeyError, the extractor
    treats a missing entry the same as the no-map case for that
    specific chunk.
    """

    full = "Section 1: The non-compete clause provides for a two-year restriction."
    doc_id, _file_id, chunks = _make_doc_with_two_chunks(full, split_at=35)

    quote = full[20:55]
    response = f'The agreement says "{quote}" (Source: [1]).'

    # Empty map (or map keyed by some unrelated id) — extractor must
    # not raise.
    candidates = extract_citations(response, chunks, document_contents={uuid.uuid4(): "unrelated"})
    assert candidates == []

    # Confirm the success path still works when the right id is present.
    candidates_ok = extract_citations(response, chunks, document_contents={doc_id: full})
    assert len(candidates_ok) == 1
