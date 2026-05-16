"""Citation Engine — Stage 1 (exact-match) verifier tests.

The Stage 1 verifier confirms that a citation candidate's
``source_text`` appears byte-for-byte at the cited offsets in the
document's ``normalized_content`` (the M2-A1 column).

In production the extractor (``app.citation.extraction``) derives
offsets from a substring search inside the retrieved chunk's content,
so the verifier passes by construction unless the fidelity invariant
``chunk.content == normalized_content[chunk_start:chunk_end]`` has
broken. The verifier is still load-bearing for:

* Defense against future drift (catches it loudly instead of
  rendering wrong text as "verified").
* The shared shape that later stages (tolerant-match, LLM judge,
  ensemble) write into.
* The handful of edge cases the M2 plan calls out: off-by-one
  offsets, whitespace-modified quotes, casing-modified quotes —
  these MUST return ``verified=False`` so they fall through to
  Stage 2 later.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from app.citation.verification import VerificationResult, verify_exact_match


@dataclass(slots=True)
class _StubDocument:
    """Minimal Document-shaped stub for verifier tests — no DB needed."""

    id: uuid.UUID
    normalized_content: str
    was_ocrd: bool = False


@dataclass(slots=True)
class _StubCandidate:
    """Minimal CitationCandidate-shaped stub for verifier tests."""

    source_file_id: uuid.UUID
    source_document_id: uuid.UUID
    source_offset_start: int
    source_offset_end: int
    source_page: int | None
    source_text: str


def _doc(text: str) -> _StubDocument:
    return _StubDocument(id=uuid.uuid4(), normalized_content=text)


def _candidate(
    doc: _StubDocument,
    *,
    offset_start: int,
    offset_end: int,
    source_text: str,
) -> _StubCandidate:
    return _StubCandidate(
        source_file_id=uuid.uuid4(),
        source_document_id=doc.id,
        source_offset_start=offset_start,
        source_offset_end=offset_end,
        source_page=None,
        source_text=source_text,
    )


@pytest.mark.unit
def test_exact_match_byte_for_byte_verified() -> None:
    """Stage 1: quote matches normalized_content[start:end] byte-for-byte."""

    text = "The agreement shall terminate after five years."
    doc = _doc(text)
    cand = _candidate(doc, offset_start=4, offset_end=13, source_text="agreement")

    result = verify_exact_match(cand, doc)

    assert isinstance(result, VerificationResult)
    assert result.verified is True
    assert result.method == "exact_match"
    assert result.confidence == 1.0


@pytest.mark.unit
def test_exact_match_off_by_one_returns_false() -> None:
    """Off-by-one offsets produce a different slice → unverified."""

    text = "The agreement shall terminate after five years."
    doc = _doc(text)
    cand = _candidate(doc, offset_start=3, offset_end=13, source_text="agreement")

    result = verify_exact_match(cand, doc)

    assert result.verified is False
    # method is left None — verifier doesn't claim a specific failure mode;
    # Stage 2 will try tolerant-match next.
    assert result.method is None
    assert result.confidence is None


@pytest.mark.unit
def test_exact_match_whitespace_difference_returns_false() -> None:
    """Modified whitespace fails Stage 1 (will be caught by Stage 2 M2-B1)."""

    text = "The agreement\nshall  terminate."
    doc = _doc(text)
    # The quoted source_text collapses whitespace to single spaces — Stage 1
    # rejects; Stage 2's normalize() will normalize whitespace and pass.
    cand = _candidate(
        doc,
        offset_start=0,
        offset_end=len(text),
        source_text="The agreement shall terminate.",
    )

    result = verify_exact_match(cand, doc)
    assert result.verified is False


@pytest.mark.unit
def test_exact_match_casing_difference_returns_false() -> None:
    """Casing differences fail Stage 1 (paraphrase judge may catch later)."""

    text = "The Agreement shall terminate."
    doc = _doc(text)
    cand = _candidate(
        doc,
        offset_start=0,
        offset_end=len(text),
        source_text="the agreement shall terminate.",
    )

    result = verify_exact_match(cand, doc)
    assert result.verified is False


@pytest.mark.unit
def test_exact_match_offset_out_of_range_returns_false() -> None:
    """Defensive: offsets past the document end never claim verified."""

    text = "Short text."
    doc = _doc(text)
    cand = _candidate(
        doc,
        offset_start=0,
        offset_end=1000,
        source_text="Short text.",
    )

    result = verify_exact_match(cand, doc)
    assert result.verified is False


@pytest.mark.unit
def test_exact_match_empty_source_text_returns_false() -> None:
    """Zero-length source_text is meaningless; verifier rejects."""

    text = "Some text."
    doc = _doc(text)
    cand = _candidate(doc, offset_start=0, offset_end=0, source_text="")

    result = verify_exact_match(cand, doc)
    assert result.verified is False
