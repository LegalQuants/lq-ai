"""Citation Engine — verifies every model-emitted citation before persistence.

Per PRD §3.3 the engine is staged so high-confidence verdicts land
cheaply and only difficult citations escalate to expensive checks:

* **Stage 1 (M2-A2; this module)** — exact-match against the
  retrieved chunk + the source document's
  ``normalized_content``.
* **Stage 2 (M2-B1)** — tolerant-match (whitespace + OCR
  artefacts + smart-quote normalization).
* **Stage 3 (M2-C1)** — LLM paraphrase judge.
* **Stage 4 (M2-D1)** — ensemble verification for high-stakes
  operations.

A citation that fails Stage 1 falls through to Stage 2; one that
fails every stage is persisted with ``verified=False`` and rendered
as "unverified" by the UI (M2-C2). The persistence shape is the
``message_citations`` table; see ``app.models.chat.MessageCitation``.
"""

from app.citation.extraction import CitationCandidate, extract_citations
from app.citation.verification import (
    VerificationResult,
    verify,
    verify_exact_match,
    verify_tolerant_match,
)

__all__ = [
    "CitationCandidate",
    "VerificationResult",
    "extract_citations",
    "verify",
    "verify_exact_match",
    "verify_tolerant_match",
]
