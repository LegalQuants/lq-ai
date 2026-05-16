"""Citation Engine — staged verification cascade.

Each stage takes a :class:`CitationCandidate` produced by the extractor
and the :class:`Document` it points at and returns a
:class:`VerificationResult`. :func:`verify` is the orchestrator the
persistence layer calls; it tries stages in order and returns the
first hit, falling through to a MISS only when every stage has
rejected the candidate.

Stages live in canonical method-string order:

* :func:`verify_exact_match` — Stage 1 (M2-A2). Byte-for-byte equality
  at the offsets the extractor produced. Trivially fast.
* :func:`verify_tolerant_match` — Stage 2 (M2-B1; this task).
  Normalizes both source-at-offsets and ``source_text`` via
  :func:`app.citation.normalization.normalize` and compares with
  ``rapidfuzz.fuzz.ratio`` at threshold 95. Catches smart-quote,
  whitespace, and (when ``document.was_ocrd``) OCR-confusion
  differences that Stage 1 rejects.
* Stage 3 LLM judge (M2-C1) and Stage 4 ensemble (M2-D1) land in
  later milestone tasks; :func:`verify` will route into them once
  they ship.

All stages share the :class:`VerificationResult` shape so the
persistence layer can copy fields onto ``message_citations`` without
remapping.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from rapidfuzz import fuzz

from app.citation.normalization import normalize


class _CandidateProtocol(Protocol):
    """Shape the verifier reads from a citation candidate.

    Production passes :class:`app.citation.extraction.CitationCandidate`;
    tests pass an equivalent stub.
    """

    source_offset_start: int
    source_offset_end: int
    source_text: str
    source_document_id: uuid.UUID


class _DocumentProtocol(Protocol):
    """Shape the verifier reads from a Document.

    Production passes :class:`app.models.document.Document`; tests
    pass a minimal stub.
    """

    id: uuid.UUID
    normalized_content: str
    was_ocrd: bool


@dataclass(slots=True)
class VerificationResult:
    """Outcome of running one verification stage against one citation.

    Either:

    * ``verified=True``, ``method`` set to the canonical stage name
      (e.g., ``'exact_match'``), and ``confidence`` populated; or
    * ``verified=False``, ``method=None``, ``confidence=None``. The
      caller routes the candidate to the next stage when False.

    The shape is symmetric with the ``message_citations`` columns so
    the persistence layer can copy fields without re-mapping.
    """

    verified: bool
    method: str | None
    confidence: float | None


# A sentinel result for misses, reused so callers don't allocate.
_MISS = VerificationResult(verified=False, method=None, confidence=None)

# Stage 2 acceptance threshold on the rapidfuzz ratio scale (0-100).
# 95 catches normalization-only differences (smart quotes, whitespace
# collapse, OCR-confusion substitutions on ``was_ocrd`` docs) while
# rejecting genuine paraphrases — they live in the 70-90 range where
# Stage 3's LLM judge belongs.
#
# Per M2-B1 the value is locked here; M2-E2 (ensemble calibration
# against the M2-F1 acceptance corpus) revisits it with empirical
# data and may move it. Keep the constant rather than inlining so
# the calibration task changes one number.
TOLERANT_MATCH_THRESHOLD = 95.0


def _slice_in_range(start: int, end: int, document_len: int) -> bool:
    """Whether the candidate's offsets describe a valid range inside the doc."""

    return start >= 0 and end > start and end <= document_len


def verify_exact_match(
    candidate: _CandidateProtocol,
    document: _DocumentProtocol,
) -> VerificationResult:
    """Return ``VerificationResult(verified=True)`` iff Stage 1 passes.

    The contract is byte-for-byte equality between the candidate's
    ``source_text`` and the document's ``normalized_content`` slice at
    the candidate's offsets. No normalization is performed; whitespace
    or case differences fall through to Stage 2.
    """

    quote = candidate.source_text
    if not quote:
        return _MISS
    if not _slice_in_range(
        candidate.source_offset_start,
        candidate.source_offset_end,
        len(document.normalized_content),
    ):
        return _MISS

    if (
        document.normalized_content[candidate.source_offset_start : candidate.source_offset_end]
        != quote
    ):
        return _MISS

    return VerificationResult(verified=True, method="exact_match", confidence=1.0)


def verify_tolerant_match(
    candidate: _CandidateProtocol,
    document: _DocumentProtocol,
) -> VerificationResult:
    """Stage 2: fuzzy-match after normalization (M2-B1).

    Normalizes both ``document.normalized_content[start:end]`` and
    ``candidate.source_text`` via
    :func:`app.citation.normalization.normalize` (passing the
    document's ``was_ocrd`` flag so OCR-confusion rules fire only on
    actually-OCR'd sources) and compares with
    ``rapidfuzz.fuzz.ratio``. Returns verified=True when the ratio
    is at or above :data:`TOLERANT_MATCH_THRESHOLD` (95.0).

    The confidence on a pass is ``ratio / 100`` so the
    ``verification_confidence`` column stays in the documented
    ``[0, 1]`` range. A perfect match yields ``1.0`` (same as Stage 1).
    """

    quote = candidate.source_text
    if not quote:
        return _MISS
    if not _slice_in_range(
        candidate.source_offset_start,
        candidate.source_offset_end,
        len(document.normalized_content),
    ):
        return _MISS

    source_slice = document.normalized_content[
        candidate.source_offset_start : candidate.source_offset_end
    ]
    was_ocrd = bool(getattr(document, "was_ocrd", False))
    normalized_source = normalize(source_slice, was_ocrd=was_ocrd)
    normalized_quote = normalize(quote, was_ocrd=was_ocrd)

    score = fuzz.ratio(normalized_source, normalized_quote)
    if score < TOLERANT_MATCH_THRESHOLD:
        return _MISS

    return VerificationResult(
        verified=True,
        method="tolerant_match",
        confidence=score / 100.0,
    )


def verify(
    candidate: _CandidateProtocol,
    document: _DocumentProtocol,
) -> VerificationResult:
    """Run the verification cascade and return the first hit.

    Order: Stage 1 (exact-match) → Stage 2 (tolerant-match). Returns
    :data:`_MISS` only when every stage has rejected the candidate.
    Stages 3 and 4 (LLM judge, ensemble) land in M2-C1 / M2-D1 and
    will plug in here.

    The persistence layer in ``app.api.chats`` calls this rather than
    a specific stage so the cascade is opaque to callers.
    """

    result = verify_exact_match(candidate, document)
    if result.verified:
        return result

    result = verify_tolerant_match(candidate, document)
    if result.verified:
        return result

    return _MISS
