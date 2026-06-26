"""Whole-opinion caselaw content judge (DE-280, P1-B1b).

For a caselaw blockquote that did not match any consulted opinion verbatim,
ask an LLM judge whether the passage is faithfully supported by the *whole*
opinion text (10-50pp) — the SUPPORTED tier. Reuses the cascade's judge
surface (``_JudgeGatewayProtocol``) and response parser; conservative bias
(a false-positive verification is worse than a false-negative). Cost-bounded
by a per-message budget enforced in the caselaw orchestrator.

Unlike Stage 3 (``verify_paraphrase``), which feeds a ±200-char window
around the cited span, this judge feeds the *entire* opinion text so the
LLM can locate support anywhere in the document. That is appropriate for
caselaw paraphrase checks: a holding may be stated once, elaborated
elsewhere, and the blockquote may conflate both — a narrow window would miss
the elaboration. The cost estimate accounts for the longer context.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.cost import estimate_judge_call_cost_usd
from app.citation.judge_prompts import build_judge_prompt
from app.citation.verification import (
    _MISS,
    VerificationResult,
    _JudgeGatewayProtocol,
    _parse_judge_response,
)
from app.schemas.gateway import ChatCompletionRequest

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants.
# ---------------------------------------------------------------------------

CHARS_PER_TOKEN: int = 4
"""Approximate characters per token used for opinion-length cost scaling.
Conservative (real-world is ~3.8 for English legal prose) so the estimate
errs toward over-budgeting rather than under-budgeting."""

TYPICAL_PARAPHRASE_TOKENS: int = 1500
"""Stage-3 baseline: the rolling-average judge-call cost in ``cost.py``
was calibrated against calls that include a ±200-char context window and
a short claim, totalling roughly 1 500 input tokens. We use this as the
denominator when scaling from a per-call average up to a whole-opinion
cost estimate."""

CASE_CONTENT_JUDGE_BUDGET_USD: Decimal = Decimal("0.25")
"""Per-assistant-turn hard cap. The orchestrator (Task 3) refuses to run
the whole-opinion judge if the pre-flight estimate exceeds this value.
Intentionally conservative — a 50-page opinion with a high-cost model
can approach $0.05; $0.25 gives 5x headroom while still blocking runaway
spend."""

_PURPOSE = "judge_case_content"


# ---------------------------------------------------------------------------
# Prompt builder.
# ---------------------------------------------------------------------------


def _build_prompt(passage: str, opinion_text: str, *, judge_model: str) -> ChatCompletionRequest:
    """Build the ChatCompletionRequest for the whole-opinion content judge.

    Reuses ``build_judge_prompt`` from ``judge_prompts`` (same system
    prompt, same conservative-bias calibration) but passes the *full*
    opinion text as the single source chunk rather than a ±200-char window.

    The ``lq_ai_purpose`` tag is set to ``'judge_case_content'`` so the
    routing log segregates these calls from Stage-3 paraphrase calls in
    the cost-calibration query.
    """
    messages = build_judge_prompt(claim_text=passage, chunks=[opinion_text])
    return ChatCompletionRequest(
        model=judge_model,
        messages=messages,
        # Cap output — the judge returns a short JSON object; ~400 tokens
        # is ample for {"verdict": ..., "confidence": ..., "justification": "..."}.
        max_tokens=400,
        # Deterministic — no creative paraphrasing of the verdict.
        temperature=0.0,
        # The judge must see real content to verify it; anonymization would
        # destroy the semantics it is checking against.
        anonymize=False,
        # Tag the routing-log row for segregated cost calibration.
        lq_ai_purpose=_PURPOSE,
    )


# ---------------------------------------------------------------------------
# Public interface.
# ---------------------------------------------------------------------------


async def judge_case_content(
    *,
    passage: str,
    opinion_text: str,
    gateway: _JudgeGatewayProtocol,
    judge_model: str,
) -> VerificationResult:
    """Ask the LLM judge whether ``passage`` is faithfully supported by ``opinion_text``.

    Dispatches one structured-JSON judge call through the gateway (reusing
    the cascade's prompt and parser) and returns:

    * ``VerificationResult(verified=True, method='paraphrase_judge', ...)``
      when the judge returns ``yes`` or ``partial``.
    * :data:`app.citation.verification._MISS` (``verified=False``) when
      the judge returns ``no``, produces malformed JSON, or the gateway
      call fails.

    No exception is ever raised — all failure modes are swallowed and
    surfaced as MISS. The caselaw orchestrator (Task 3) treats MISS as
    "could not confirm support" and routes the citation accordingly.
    """
    try:
        request = _build_prompt(passage, opinion_text, judge_model=judge_model)
        response = await gateway.chat_completion(request)
    except Exception as exc:
        log.warning(
            "case-content judge call failed: %r",
            exc,
            extra={
                "event": "caselaw_content_judge_error",
                "error_type": type(exc).__name__,
            },
        )
        return _MISS

    return _parse_judge_response(response)


async def estimate_case_content_cost_usd(
    db: AsyncSession | None,
    *,
    judge_model: str,
    opinion_text: str,
) -> Decimal:
    """Estimate the USD cost of one whole-opinion judge call.

    Scales the per-call rolling average from the routing log (filtered to
    ``purpose='judge_case_content'`` rows) by the ratio of the opinion's
    token count to the Stage-3 baseline (:data:`TYPICAL_PARAPHRASE_TOKENS`).
    The scale factor is floored at 1 so short opinions (under the baseline
    length) use the per-call average as-is.

    ``db=None`` → no DB query; returns the conservative
    :data:`app.citation.cost.DEFAULT_PER_JUDGE_USD` scaled by the opinion
    length. This path is used in tests and cold-start pre-flights.
    """
    per_call = await estimate_judge_call_cost_usd(db, judge_model=judge_model, purpose=_PURPOSE)
    opinion_tokens = max(1, len(opinion_text) // CHARS_PER_TOKEN)
    scale = Decimal(opinion_tokens) / Decimal(TYPICAL_PARAPHRASE_TOKENS)
    if scale < Decimal(1):
        scale = Decimal(1)
    return per_call * scale
