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
* :func:`verify_tolerant_match` — Stage 2 (M2-B1). Normalizes both
  source-at-offsets and ``source_text`` via
  :func:`app.citation.normalization.normalize` and compares with
  ``rapidfuzz.fuzz.ratio`` at threshold 95. Catches smart-quote,
  whitespace, and (when ``document.was_ocrd``) OCR-confusion
  differences that Stage 1 rejects.
* :func:`verify_paraphrase` — Stage 3 (M2-C1). LLM paraphrase judge.
  Dispatches one structured-JSON judge call through the gateway and
  parses the verdict into ``yes`` / ``partial`` / ``no``.
* :func:`verify_ensemble` — Stage 4 (M2-D1). Runs the paraphrase judge
  in parallel across multiple models and aggregates verdicts under
  the operator-chosen rule (strict = all agree; majority = simple
  majority wins). Replaces Stage 3 when activated; cost-budget
  fallback drops back to Stage 3 if the ensemble would exceed the
  per-message cap.

All stages share the :class:`VerificationResult` shape so the
persistence layer can copy fields onto ``message_citations`` without
remapping.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from rapidfuzz import fuzz

from app.citation.judge_prompts import build_judge_prompt
from app.citation.normalization import normalize
from app.observability_helpers import get_tracer, record_attributes
from app.schemas.gateway import ChatCompletionRequest

logger = logging.getLogger(__name__)


# Cold-start fallback for the per-judge-call cost pre-flight (M2-D1).
# Production pre-flight uses :func:`app.citation.cost.estimate_judge_call_cost_usd`
# which computes a per-model rolling average from the ``inference_routing_log``
# rows tagged ``purpose='judge_paraphrase'`` (M2-E2). When a judge
# model has fewer than 5 recent calls, the estimator falls back to
# this constant — the same conservative value M2-D1 shipped, retained
# so the cold-start posture is identical to the pre-M2-E2 behavior.
# Re-exported here (rather than only from cost.py) so call sites that
# only need the fallback can import without pulling in the SQLAlchemy
# dependency.
FLAT_PER_JUDGE_USD = 0.005


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

    M2-D1 added ``tier_envelope``: Stage 4 (ensemble) records the
    maximum (weakest) inference tier across the judge models that
    ran. Stages 1-3 are single-tier and emit ``tier_envelope=None``.
    The persistence layer copies it onto
    ``message_citations.tier_envelope``.
    """

    verified: bool
    method: str | None
    confidence: float | None
    partial: bool = False
    tier_envelope: int | None = None


# A sentinel result for misses, reused so callers don't allocate.
_MISS = VerificationResult(
    verified=False, method=None, confidence=None, partial=False, tier_envelope=None
)

# Stage 2 acceptance threshold on the rapidfuzz ratio scale (0-100).
# 95 catches normalization-only differences (smart quotes, whitespace
# collapse, OCR-confusion substitutions on ``was_ocrd`` docs) while
# rejecting genuine paraphrases — they live in the 70-90 range where
# Stage 3's LLM judge belongs.
#
# Per M2-B1 the value is locked here. M2-E2 calibrated the per-judge
# cost pre-flight against the routing log but did not adjust this
# threshold — empirical calibration requires production telemetry
# the project hasn't collected yet. DE-281 (operational-telemetry
# calibration) is the future home for both this and the ensemble
# aggregation rule. Until then the conservative default holds.
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
        # M2-E2: tag the routing-log row so per-model cost calibration
        # can filter judge calls from regular chat traffic.
        lq_ai_purpose="judge_paraphrase",
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


# --- Stage 4 — ensemble verification (M2-D1) ---------------------------------


class _EnsembleConfigProtocol(Protocol):
    """Shape :func:`verify_ensemble` reads from the ensemble config.

    Production passes :class:`app.clients.gateway.EnsembleConfig` (a
    frozen dataclass); tests pass an equivalent stub. Declared via
    ``@property`` so frozen-dataclass read-only attributes match the
    Protocol structurally (a plain attribute declaration would mark
    the field as settable, which a frozen dataclass cannot satisfy).

    ``judge_models`` is the list of aliases the gateway can resolve,
    ``aggregation_rule`` selects strict vs majority, and
    ``envelope_tier`` is the server-computed max tier across the
    configured judge models (persisted on the citation row).
    """

    @property
    def judge_models(self) -> tuple[str, ...]: ...

    @property
    def aggregation_rule(self) -> Literal["strict", "majority"]: ...

    @property
    def envelope_tier(self) -> int | None: ...


async def verify_ensemble(
    candidate: _CandidateProtocol,
    document: _DocumentProtocol,
    *,
    gateway: _JudgeGatewayProtocol,
    ensemble_config: _EnsembleConfigProtocol,
) -> VerificationResult:
    """Stage 4: run the paraphrase judge in parallel across N models.

    Dispatches one :func:`verify_paraphrase` call per model in
    ``ensemble_config.judge_models``, awaits all in parallel, and
    aggregates verdicts under the configured rule:

    * ``strict``: every judge must verdict verified (``yes`` or
      ``partial``). Any miss → MISS. Persist as
      ``'ensemble_strict'``; ``partial=true`` iff *any* judge said
      partial (caller still sees a verified row, the partial flag
      surfaces "some disagreement under the strict rule").
    * ``majority``: simple majority of verified verdicts wins.
      Ties (n=2 with one yes, one no) miss conservatively. Persist
      as ``'ensemble_majority'``; ``partial=true`` iff *any*
      verified judge said partial OR if any judge disagreed at all
      (the "Models disagreed: K of N verified" tooltip case from
      the M2-D1 spec).

    The persisted confidence is the mean of the verified judges'
    confidences (0.0 when no judges verified). ``tier_envelope`` is
    set from ``ensemble_config.envelope_tier`` regardless of outcome
    — the privacy exposure is the same whether the ensemble agreed.

    Judge call failures (gateway error, malformed JSON) count as a
    miss for that judge. An ensemble where most judges errored may
    still produce a verified result under the majority rule with the
    surviving verdicts — but with low confidence the UI's yellow
    tooltip flags the disagreement.
    """

    if not ensemble_config.judge_models:
        return _MISS

    claim = candidate.source_text
    if not claim:
        return _MISS
    if _source_chunk_with_context(candidate, document) is None:
        return _MISS

    verdicts = await asyncio.gather(
        *[
            verify_paraphrase(candidate, document, gateway=gateway, judge_model=model)
            for model in ensemble_config.judge_models
        ],
        return_exceptions=False,
    )

    n_total = len(verdicts)
    verified_verdicts = [v for v in verdicts if v.verified]
    n_verified = len(verified_verdicts)

    rule = ensemble_config.aggregation_rule
    method = "ensemble_strict" if rule == "strict" else "ensemble_majority"

    if rule == "strict":
        if n_verified < n_total:
            return _MISS
        # All judges verified. Partial = any judge said partial.
        partial = any(v.partial for v in verified_verdicts)
    else:
        # Majority: strict majority (> n/2). Even-N ties miss; we
        # surface those rather than picking a side.
        if n_verified * 2 <= n_total:
            return _MISS
        # Verified under majority. Partial flag = any judge said
        # partial OR any judge dissented (per the M2-D1 spec's
        # "disagreement is the yellow case" rendering).
        any_dissent = n_verified < n_total
        any_partial = any(v.partial for v in verified_verdicts)
        partial = any_dissent or any_partial

    mean_confidence = (
        sum(v.confidence or 0.0 for v in verified_verdicts) / n_verified if n_verified else 0.0
    )

    return VerificationResult(
        verified=True,
        method=method,
        confidence=mean_confidence,
        partial=partial,
        tier_envelope=ensemble_config.envelope_tier,
    )


# --- Cascade router ----------------------------------------------------------


def _set_result_attrs(span: object, result: VerificationResult) -> None:
    """Copy verification outcome fields onto a span as OTel attributes.

    Called on every return path from :func:`verify` so the top-level
    ``citation.verify`` span always carries the final outcome regardless
    of which stage short-circuited. ``record_attributes`` drops None
    values (method/confidence are None on MISS) and no-ops when the
    span is not recording (OTel disabled).
    """

    record_attributes(
        span,  # type: ignore[arg-type]
        **{
            "citation.method": result.method,
            "citation.confidence": result.confidence,
            "citation.partial": result.partial,
            "citation.tier_envelope": result.tier_envelope,
        },
    )


async def verify(
    candidate: _CandidateProtocol,
    document: _DocumentProtocol,
    *,
    gateway: _JudgeGatewayProtocol | None = None,
    judge_model: str = "fast",
    ensemble_config: _EnsembleConfigProtocol | None = None,
) -> VerificationResult:
    """Run the verification cascade and return the first hit.

    Order:

    * Stage 1 (exact-match) — pure Python; always runs.
    * Stage 2 (tolerant-match) — pure Python; always runs on Stage 1
      miss.
    * When ``ensemble_config`` is supplied — **Stage 4 (ensemble)**
      replaces Stage 3 (per M2-D1 decision B: ensemble replaces the
      single-judge stage when activated).
    * Otherwise — Stage 3 (single paraphrase judge).

    Returns :data:`_MISS` only when every routed stage has rejected
    the candidate.

    Stages 3 and 4 only run when ``gateway`` is supplied. Callers
    without an LLM (smoke tests, eval scripts that exercise only the
    deterministic stages) pass ``gateway=None`` and the cascade
    short-circuits to MISS after Stages 1+2.

    ``judge_model`` is the alias the gateway resolves for the Stage 3
    judge call. Default ``"fast"`` matches ``gateway.yaml.example``'s
    ``citation_engine.judge_model``; the chat-send caller passes the
    value it pulled from
    ``GatewayClient.get_citation_engine_judge_model``. Ignored when
    ``ensemble_config`` is supplied (Stage 4 dispatches its own
    per-judge aliases).

    ``ensemble_config`` is the resolved Stage 4 config (from
    ``GatewayClient.get_citation_engine_ensemble_config``). The
    chat-send caller passes it for messages where ensemble has been
    activated by skill / project / gateway default AND the per-message
    cost-budget check passed. When the budget check fails the caller
    drops the kwarg, falling the cascade back to Stage 3.
    """

    tracer = get_tracer()
    with tracer.start_as_current_span("citation.verify") as top:
        record_attributes(top, **{"document.id": str(document.id)})

        with tracer.start_as_current_span("citation.stage.exact_match") as s:
            result = verify_exact_match(candidate, document)
            record_attributes(
                s,
                **{
                    "citation.stage.verified": result.verified,
                    "citation.stage.confidence": result.confidence,
                },
            )
        if result.verified:
            top.add_event("exact_match.hit")
            _set_result_attrs(top, result)
            return result

        with tracer.start_as_current_span("citation.stage.tolerant_match") as s:
            result = verify_tolerant_match(candidate, document)
            record_attributes(
                s,
                **{
                    "citation.stage.verified": result.verified,
                    "citation.stage.confidence": result.confidence,
                },
            )
        if result.verified:
            top.add_event("tolerant_match.hit")
            _set_result_attrs(top, result)
            return result

        if gateway is None:
            _set_result_attrs(top, _MISS)
            return _MISS

        if ensemble_config is not None:
            with tracer.start_as_current_span("citation.stage.ensemble") as s:
                result = await verify_ensemble(
                    candidate,
                    document,
                    gateway=gateway,
                    ensemble_config=ensemble_config,
                )
                record_attributes(
                    s,
                    **{
                        "citation.stage.verified": result.verified,
                        "citation.stage.confidence": result.confidence,
                        "citation.ensemble.n_judges": len(ensemble_config.judge_models),
                        "citation.ensemble.rule": ensemble_config.aggregation_rule,
                    },
                )
        else:
            with tracer.start_as_current_span("citation.stage.paraphrase_judge") as s:
                result = await verify_paraphrase(
                    candidate,
                    document,
                    gateway=gateway,
                    judge_model=judge_model,
                )
                record_attributes(
                    s,
                    **{
                        "citation.stage.verified": result.verified,
                        "citation.stage.confidence": result.confidence,
                    },
                )
        _set_result_attrs(top, result)
        return result
