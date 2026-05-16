"""Citation Engine — extraction tests.

The extractor parses the assistant response for quote-then-locate
citations: a double-quoted passage immediately followed by a
``(Source: [N])`` marker referring to a retrieved-chunk index.

Each successfully located citation is materialized as a
``CitationCandidate`` carrying the source_file_id / document_id /
byte-precise offsets / source_text / page — everything the verifier
and the persistence layer need.

Quotes that can't be located inside their cited chunk are dropped
silently for M2-A2. The schema requires file_id + offsets to be
non-null, and we don't speculate where an unfindable quote came from.
"Model claimed to cite but we can't find it" is a future failure-mode
audit task (DE candidate).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from app.citation.extraction import CitationCandidate, extract_citations


@dataclass(slots=True)
class _StubChunk:
    """HybridSearchResult-shaped stub for extractor tests — no DB needed."""

    document_id: uuid.UUID
    file_id: uuid.UUID
    content: str
    page_start: int | None
    char_offset_start: int
    char_offset_end: int


def _chunk(
    *,
    content: str,
    char_offset_start: int = 0,
    page_start: int | None = 1,
) -> _StubChunk:
    return _StubChunk(
        document_id=uuid.uuid4(),
        file_id=uuid.uuid4(),
        content=content,
        page_start=page_start,
        char_offset_start=char_offset_start,
        char_offset_end=char_offset_start + len(content),
    )


@pytest.mark.unit
def test_extract_single_citation_byte_precise_offsets() -> None:
    """A verbatim quote with (Source: [1]) becomes a candidate with derived offsets."""

    chunk = _chunk(
        content="The contract term shall be five years.",
        char_offset_start=200,
    )
    response = 'The agreement says "The contract term shall be five years." (Source: [1]).'

    candidates = extract_citations(response, [chunk])

    assert len(candidates) == 1
    cite = candidates[0]
    assert isinstance(cite, CitationCandidate)
    assert cite.source_file_id == chunk.file_id
    assert cite.source_document_id == chunk.document_id
    # Quote starts at the beginning of the chunk → offsets relative to the
    # document begin at chunk.char_offset_start.
    assert cite.source_offset_start == 200
    assert cite.source_offset_end == 200 + len("The contract term shall be five years.")
    assert cite.source_text == "The contract term shall be five years."
    assert cite.source_page == 1


@pytest.mark.unit
def test_extract_handles_offset_within_chunk() -> None:
    """Quote in the middle of a chunk → offsets account for the position inside."""

    # The chunk text places the quote at character 4 within the chunk.
    chunk = _chunk(content="==> The cited bit. ==>", char_offset_start=1000)
    response = 'It says "The cited bit." (Source: [1]).'

    candidates = extract_citations(response, [chunk])

    assert len(candidates) == 1
    cite = candidates[0]
    assert cite.source_offset_start == 1000 + chunk.content.find("The cited bit.")
    assert cite.source_offset_end == cite.source_offset_start + len("The cited bit.")
    assert cite.source_text == "The cited bit."


@pytest.mark.unit
def test_extract_multiple_citations_resolve_independent_chunks() -> None:
    """Two quotes citing two chunks produce two candidates."""

    chunk1 = _chunk(content="First fact statement.", char_offset_start=0)
    chunk2 = _chunk(content="Second fact assertion.", char_offset_start=500, page_start=3)
    response = (
        'He said "First fact statement." (Source: [1]) and '
        'also "Second fact assertion." (Source: [2]).'
    )

    candidates = extract_citations(response, [chunk1, chunk2])

    assert len(candidates) == 2
    assert candidates[0].source_file_id == chunk1.file_id
    assert candidates[1].source_file_id == chunk2.file_id
    assert candidates[1].source_page == 3


@pytest.mark.unit
def test_extract_drops_quote_without_source_marker() -> None:
    """A bare quote without `(Source: [N])` is not a citation; ignored."""

    chunk = _chunk(content="Some text.")
    response = 'He said "Some text." but cited nothing.'

    assert extract_citations(response, [chunk]) == []


@pytest.mark.unit
def test_extract_drops_source_marker_without_quote() -> None:
    """A standalone `(Source: [N])` with no preceding quote is ignored."""

    chunk = _chunk(content="Some text.")
    response = "Without quoting, the source is (Source: [1])."

    assert extract_citations(response, [chunk]) == []


@pytest.mark.unit
def test_extract_drops_unfindable_quote() -> None:
    """A quote not present in the cited chunk's content is dropped (M2-A2 policy)."""

    chunk = _chunk(content="The actual chunk text.")
    response = 'The model wrote "a fabricated quote." (Source: [1]).'

    assert extract_citations(response, [chunk]) == []


@pytest.mark.unit
def test_extract_drops_out_of_range_source_index() -> None:
    """`(Source: [99])` when only 2 chunks were retrieved is dropped."""

    chunk = _chunk(content="Real content.")
    response = 'He said "Real content." (Source: [99]).'

    assert extract_citations(response, [chunk]) == []


@pytest.mark.unit
def test_extract_tolerates_whitespace_around_source_marker() -> None:
    """Permissive: optional whitespace between quote and (Source: ...)."""

    chunk = _chunk(content="Cited text.")
    response = 'It says "Cited text."   (Source: [1]) here.'

    candidates = extract_citations(response, [chunk])
    assert len(candidates) == 1
    assert candidates[0].source_text == "Cited text."


@pytest.mark.unit
def test_extract_handles_smart_quotes() -> None:
    """M2-B1: extractor accepts curly-quote pairs; Stage 2 verifier will pass them."""

    chunk = _chunk(content="Cited text.")
    response = "It says “Cited text.” (Source: [1]) here."

    candidates = extract_citations(response, [chunk])
    assert len(candidates) == 1
    # source_text preserves the model's quote shape (smart quotes); the
    # verifier normalizes both sides before comparing.
    assert candidates[0].source_text == "Cited text."


@pytest.mark.unit
def test_extract_handles_multiline_quote() -> None:
    """Quotes spanning newlines are extracted (regex must cross line breaks)."""

    chunk_content = "First line.\nSecond line of the same quote."
    chunk = _chunk(content=chunk_content)
    response = f'It says "{chunk_content}" (Source: [1]).'

    candidates = extract_citations(response, [chunk])
    assert len(candidates) == 1
    assert candidates[0].source_text == chunk_content


# ---------------------------------------------------------------------------
# M2-B1: rapidfuzz alignment fallback for quotes that aren't byte-for-byte
# substrings of the cited chunk (smart quotes, whitespace drift).
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extract_alignment_fallback_finds_whitespace_drift_quote() -> None:
    """When byte-for-byte fails, partial_ratio_alignment locates the quote.

    The candidate's offsets point at the best-aligned span in the chunk;
    the verifier (Stage 2) re-checks at threshold 95 after normalizing.
    """

    chunk = _chunk(
        content="The   agreement\nshall terminate.",
        char_offset_start=100,
    )
    # Model emits the same text with normalized whitespace — byte-for-byte
    # find will miss; alignment fallback locates it.
    response = 'The model says "The agreement shall terminate." (Source: [1]).'

    candidates = extract_citations(response, [chunk])
    assert len(candidates) == 1
    cite = candidates[0]
    # The aligned span covers the whitespace-divergent region.
    assert cite.source_offset_start >= 100
    assert cite.source_offset_end <= 100 + len(chunk.content)
    # source_text is the model's quote verbatim; verifier normalizes both sides.
    assert cite.source_text == "The agreement shall terminate."


@pytest.mark.unit
def test_extract_alignment_fallback_rejects_unrelated_quote() -> None:
    """A quote with no real overlap with the chunk falls below threshold."""

    chunk = _chunk(content="The contract term is five years.")
    response = 'The model wrote "completely unrelated subject matter." (Source: [1]).'

    assert extract_citations(response, [chunk]) == []


@pytest.mark.unit
def test_extract_smart_quote_alignment_pairs() -> None:
    """Mixed shapes: a smart-quoted citation whose text differs in whitespace."""

    chunk = _chunk(content="The   agreement\nshall  terminate.")
    response = "The model says “The agreement shall terminate.” (Source: [1])."

    candidates = extract_citations(response, [chunk])
    assert len(candidates) == 1
    assert candidates[0].source_text == "The agreement shall terminate."
