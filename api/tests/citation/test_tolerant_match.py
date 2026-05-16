"""Citation Engine Stage 2 — tolerant-match verifier tests.

``verify_tolerant_match(candidate, document)`` normalizes both
``document.normalized_content[start:end]`` and ``candidate.source_text``
via :func:`app.citation.normalization.normalize` and compares them
with ``rapidfuzz.fuzz.ratio``. A ratio of 95 or above passes; the
verdict carries ``method='tolerant_match'`` and
``confidence=ratio/100``.

The threshold ``95`` is locked at this stage (per M2 plan §M2-B1):

* Below 95: paraphrases and meaningful edits start passing — that's
  Stage 3's (LLM judge) job, not Stage 2's.
* 95+: normalization-only diffs (smart quotes, whitespace, OCR
  fixups under ``was_ocrd=True``) pass cleanly.

M2-E2 (ensemble calibration) revisits this against the acceptance
corpus and may surface a different number once we have empirical
data; until then, 95 is the lock.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from app.citation.verification import VerificationResult, verify_tolerant_match


@dataclass(slots=True)
class _StubDocument:
    id: uuid.UUID
    normalized_content: str
    was_ocrd: bool = False


@dataclass(slots=True)
class _StubCandidate:
    source_file_id: uuid.UUID
    source_document_id: uuid.UUID
    source_offset_start: int
    source_offset_end: int
    source_page: int | None
    source_text: str


def _doc(text: str, *, was_ocrd: bool = False) -> _StubDocument:
    return _StubDocument(id=uuid.uuid4(), normalized_content=text, was_ocrd=was_ocrd)


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
def test_tolerant_match_smart_quotes_pass() -> None:
    """Smart-vs-straight quote differences pass Stage 2."""

    text = '"the agreement shall terminate after five years."'
    doc = _doc(text)
    smart_quoted = "“the agreement shall terminate after five years.”"
    cand = _candidate(doc, offset_start=0, offset_end=len(text), source_text=smart_quoted)

    result = verify_tolerant_match(cand, doc)

    assert isinstance(result, VerificationResult)
    assert result.verified is True
    assert result.method == "tolerant_match"
    assert result.confidence is not None
    assert result.confidence >= 0.95


@pytest.mark.unit
def test_tolerant_match_whitespace_diff_passes() -> None:
    """Whitespace differences (newlines, double spaces) pass Stage 2."""

    text = "the agreement shall terminate after five years."
    doc = _doc(text)
    # Quote substitutes whitespace runs and adds newlines.
    quote = "the agreement\nshall  terminate after five years."
    cand = _candidate(doc, offset_start=0, offset_end=len(text), source_text=quote)

    result = verify_tolerant_match(cand, doc)
    assert result.verified is True
    assert result.method == "tolerant_match"


@pytest.mark.unit
def test_tolerant_match_byte_for_byte_match_also_passes() -> None:
    """Byte-for-byte matches pass at confidence 1.0 — Stage 2 doesn't need
    Stage 1 to run first; it just happens to be slower."""

    text = "the agreement shall terminate."
    doc = _doc(text)
    cand = _candidate(doc, offset_start=0, offset_end=len(text), source_text=text)

    result = verify_tolerant_match(cand, doc)
    assert result.verified is True
    assert result.confidence == 1.0


@pytest.mark.unit
def test_tolerant_match_paraphrase_fails() -> None:
    """Real paraphrases fall below threshold — Stage 3 (LLM judge) catches those."""

    text = "the agreement shall terminate after five years."
    doc = _doc(text)
    # "may" instead of "shall", "ten" instead of "five" — paraphrase, not formatting.
    paraphrase = "the agreement may end after ten years."
    cand = _candidate(doc, offset_start=0, offset_end=len(text), source_text=paraphrase)

    result = verify_tolerant_match(cand, doc)
    assert result.verified is False
    assert result.method is None
    assert result.confidence is None


@pytest.mark.unit
def test_tolerant_match_ocr_substitution_passes_when_was_ocrd() -> None:
    """``modern`` ↔ ``modem`` normalizes equal under was_ocrd=True."""

    text = "in the modern provisions"
    doc = _doc(text, was_ocrd=True)
    quote = "in the modem provisions"
    cand = _candidate(doc, offset_start=0, offset_end=len(text), source_text=quote)

    result = verify_tolerant_match(cand, doc)
    assert result.verified is True
    assert result.method == "tolerant_match"


@pytest.mark.unit
def test_tolerant_match_ocr_rule_does_not_fire_without_was_ocrd() -> None:
    """``modern`` vs ``modem`` fails Stage 2 when document is clean-extracted."""

    text = "in the modern provisions"
    doc = _doc(text, was_ocrd=False)
    quote = "in the modem provisions"
    cand = _candidate(doc, offset_start=0, offset_end=len(text), source_text=quote)

    # Short enough that one differing character drops the ratio below 95.
    result = verify_tolerant_match(cand, doc)
    assert result.verified is False


@pytest.mark.unit
def test_tolerant_match_offset_out_of_range_returns_false() -> None:
    """Defensive: offsets past the document end never claim verified."""

    text = "Short text."
    doc = _doc(text)
    cand = _candidate(doc, offset_start=0, offset_end=1000, source_text="Short text.")

    result = verify_tolerant_match(cand, doc)
    assert result.verified is False


@pytest.mark.unit
def test_tolerant_match_empty_source_text_returns_false() -> None:
    """Zero-length quote can't be meaningfully matched; reject."""

    text = "Some text."
    doc = _doc(text)
    cand = _candidate(doc, offset_start=0, offset_end=0, source_text="")

    result = verify_tolerant_match(cand, doc)
    assert result.verified is False
