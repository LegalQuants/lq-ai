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

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from rapidfuzz import fuzz

from app.citation.judge_prompts import build_judge_prompt
from app.citation.normalization import normalize
from app.schemas.gateway import ChatCompletionRequest

logger = logging.getLogger(__name__)


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

    M2-C1 added ``partial``: Stage 3 (paraphrase judge) can return
    ``verified=True, partial=True`` when the source supports *some*
    but not all of the claim. Stages 1 and 2 always emit
    ``partial=False`` because they are exact-content stages — a
    partial match is, by their definition, no match.
    """

    verified: bool
    method: str | None
    confidence: float | None
    partial: bool = False


# A sentinel result for misses, reused so callers don't allocate.
_MISS = VerificationResult(verified=False, method=None, confidence=None, partial=False)

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


# --- Stage 3 — paraphrase judge (M2-C1) --------------------------------------


# Map the judge's high/medium/low to a numeric confidence the
# ``message_citations.verification_confidence`` column accepts. Stages 1
# and 2 emit 1.0 / 0.95+; Stage 3 sits below — a paraphrase verdict
# is genuinely less certain than a byte-or-normalization match.
_CONFIDENCE_MAP: dict[str, float] = {
    "high": 0.90,
    "medium": 0.70,
    "low": 0.50,
}

# Window of context characters to include around the cited span. A pure
# slice can be too narrow ("the source span says X but the claim adds Y"
# when Y appears in the same sentence). A small window picks up that
# context without flooding the judge with the full document.
_CONTEXT_WINDOW_CHARS = 200


class _JudgeGatewayProtocol(Protocol):
    """Subset of :class:`app.clients.gateway.GatewayClient` the judge needs.

    Tests pass a stub that records the request and returns canned
    responses; production passes the real client.
    """

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        *,
        request_id: str | None = ...,
    ) -> Any: ...


async def verify_paraphrase(
    candidate: _CandidateProtocol,
    document: _DocumentProtocol,
    *,
    gateway: _JudgeGatewayProtocol,
    judge_model: str,
) -> VerificationResult:
    """Stage 3: ask an LLM judge whether the claim is supported by the source.

    Dispatches a structured-JSON judge prompt to the gateway, parses
    the verdict, and maps the high/medium/low confidence to numeric
    confidence (0.90 / 0.70 / 0.50). A ``partial`` verdict persists as
    ``verified=True, partial=True`` so the M2-C2 UI can render it
    distinctly from a fully verified citation.

    Failure modes are silent: gateway transport errors, malformed
    JSON, unknown verdict / confidence values, and empty responses
    all return :data:`_MISS`. Stage 3 is best-effort verification on
    top of Stages 1 and 2; a failure here just means the citation
    falls through to "unverified" without crashing the persistence
    pipeline.
    """

    claim = candidate.source_text
    if not claim:
        return _MISS

    chunk = _source_chunk_with_context(candidate, document)
    if chunk is None:
        return _MISS

    messages = build_judge_prompt(claim_text=claim, chunks=[chunk])
    request = ChatCompletionRequest(
        model=judge_model,
        messages=messages,
        # The judge prompt asks for a short structured JSON; cap the
        # token budget so a chatty model can't run away with the
        # output. ~400 tokens is plenty for ``{"verdict": ..., ...}``
        # plus a one-sentence justification.
        max_tokens=400,
        # We don't want creative paraphrases of the verdict; 0.0 keeps
        # the judge deterministic.
        temperature=0.0,
        # Per-request opt-out from anonymization — the judge needs to
        # see actual content to verify it. Anonymized text would
        # destroy the semantics the judge is checking against.
        anonymize=False,
    )

    try:
        response = await gateway.chat_completion(request)
    except Exception as exc:
        logger.warning(
            "paraphrase judge gateway call failed: %s",
            exc,
            extra={"event": "citation_judge_error", "error_type": type(exc).__name__},
        )
        return _MISS

    return _parse_judge_response(response)


def _source_chunk_with_context(
    candidate: _CandidateProtocol,
    document: _DocumentProtocol,
) -> str | None:
    """Return the cited span plus ``_CONTEXT_WINDOW_CHARS`` on each side."""

    content = document.normalized_content
    doc_len = len(content)
    if not _slice_in_range(candidate.source_offset_start, candidate.source_offset_end, doc_len):
        return None
    start = max(0, candidate.source_offset_start - _CONTEXT_WINDOW_CHARS)
    end = min(doc_len, candidate.source_offset_end + _CONTEXT_WINDOW_CHARS)
    return content[start:end]


def _parse_judge_response(response: Any) -> VerificationResult:
    """Extract verdict + confidence + partial from the judge's chat completion."""

    try:
        choices = response.choices
        if not choices:
            return _MISS
        content = choices[0].message.content
    except AttributeError:
        return _MISS

    if not content:
        return _MISS

    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        logger.info(
            "paraphrase judge produced non-JSON output",
            extra={"event": "citation_judge_malformed"},
        )
        return _MISS

    if not isinstance(payload, dict):
        return _MISS

    verdict = payload.get("verdict")
    confidence_label = payload.get("confidence")

    if verdict == "no":
        # The judge rejected the claim — fall through to unverified.
        return _MISS

    if verdict not in ("yes", "partial"):
        logger.info(
            "paraphrase judge returned unknown verdict %r",
            verdict,
            extra={"event": "citation_judge_unknown_verdict"},
        )
        return _MISS

    if confidence_label not in _CONFIDENCE_MAP:
        logger.info(
            "paraphrase judge returned unknown confidence %r",
            confidence_label,
            extra={"event": "citation_judge_unknown_confidence"},
        )
        return _MISS

    return VerificationResult(
        verified=True,
        method="paraphrase_judge",
        confidence=_CONFIDENCE_MAP[confidence_label],
        partial=(verdict == "partial"),
    )


async def verify(
    candidate: _CandidateProtocol,
    document: _DocumentProtocol,
    *,
    gateway: _JudgeGatewayProtocol | None = None,
    judge_model: str = "fast",
) -> VerificationResult:
    """Run the verification cascade and return the first hit.

    Order: Stage 1 (exact-match) → Stage 2 (tolerant-match) → Stage 3
    (paraphrase judge). Returns :data:`_MISS` only when every stage
    has rejected the candidate.

    Stage 3 only runs when ``gateway`` is supplied. Callers without
    an LLM (smoke tests, eval scripts that exercise only the
    deterministic stages) pass ``gateway=None``; the cascade then
    runs Stages 1+2 only and short-circuits to MISS if both miss.

    ``judge_model`` is the alias the gateway resolves for the Stage 3
    judge call. Default ``"fast"`` matches ``gateway.yaml.example``'s
    ``citation_engine.judge_model``; the chat-send caller passes the
    value it pulled from ``GatewayClient.get_citation_engine_judge_model``.

    Made async in M2-C1: Stages 1 and 2 are still pure Python and run
    synchronously inside the function; the ``async def`` is for
    Stage 3's gateway call.
    """

    result = verify_exact_match(candidate, document)
    if result.verified:
        return result

    result = verify_tolerant_match(candidate, document)
    if result.verified:
        return result

    if gateway is None:
        return _MISS

    return await verify_paraphrase(candidate, document, gateway=gateway, judge_model=judge_model)
