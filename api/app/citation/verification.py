"""Citation Engine — Stage 1: exact-match verification.

Given a :class:`CitationCandidate` produced by the extractor and the
:class:`Document` it points at, this stage confirms that
``document.normalized_content[source_offset_start:source_offset_end]``
equals ``source_text`` byte-for-byte. If the extractor did its job
the check passes trivially — the value here is twofold:

* **Defense against drift.** If the chunker-vs-canonical-text
  fidelity invariant breaks in a future change (e.g., a parser swap
  that produces a different ``canonical_text``), Stage 1 will start
  failing instead of silently rendering wrong text as "verified."
* **Symmetry with later stages.** Stages 2-4 (tolerant-match, LLM
  judge, ensemble) consume the same input shape and write the same
  :class:`VerificationResult` shape. The persistence layer doesn't
  need to know which stage produced the verdict.

This module is intentionally minimal — the Stage-2 normalization
pipeline (M2-B1) lives in ``app.citation.normalization``; the LLM
judge (M2-C1) lives in ``app.citation.llm_judge``; ensemble (M2-D1)
in ``app.citation.ensemble``. Mirror the file naming.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


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

    start = candidate.source_offset_start
    end = candidate.source_offset_end
    quote = candidate.source_text

    if not quote:
        return _MISS
    if start < 0 or end > len(document.normalized_content):
        return _MISS
    if end <= start:
        return _MISS

    if document.normalized_content[start:end] != quote:
        return _MISS

    return VerificationResult(verified=True, method="exact_match", confidence=1.0)
