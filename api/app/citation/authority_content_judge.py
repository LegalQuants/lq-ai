"""Whole-body authority content judge (WS-E PR1c, SUPPORTED tier).

For an authority blockquote (statute / regulation) that did not match a
fetched authority body verbatim, ask an LLM judge whether the passage is
faithfully supported by the *whole* fetched body — the SUPPORTED tier.
Reuses the cascade's judge surface (``_JudgeGatewayProtocol``) and response
parser; conservative bias (a false-positive verification is worse than a
false-negative). Cost-bounded by a per-message budget enforced in the
authority orchestrator (``verify_and_persist_authority_citations``).

Mirrors :mod:`app.citation.case_content_judge` (the caselaw B1b judge); the
only differences are the ``lq_ai_purpose`` tag (segregated cost calibration)
and authority-appropriate naming. The judge prompt itself is the shared
generic ``build_judge_prompt`` (claim vs. source chunk), which applies
equally to statutory/regulatory text.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.cost import DEFAULT_PER_JUDGE_USD, estimate_judge_call_cost_usd
from app.citation.judge_prompts import build_judge_prompt
from app.citation.verification import (
    _MISS,
    VerificationResult,
    _JudgeGatewayProtocol,
    _parse_judge_response,
)
from app.schemas.gateway import ChatCompletionRequest

log = logging.getLogger(__name__)

CHARS_PER_TOKEN: int = 4
"""Approximate characters per token for body-length cost scaling. Conservative
so the estimate errs toward over-budgeting."""

TYPICAL_PARAPHRASE_TOKENS: int = 1500
"""Stage-3 baseline (matches case_content_judge): the per-call judge cost in
cost.py was calibrated against ~1500-input-token calls. Denominator when
scaling a per-call average up to a whole-body cost estimate."""

AUTHORITY_CONTENT_JUDGE_BUDGET_USD: Decimal = Decimal("0.25")
"""Per-assistant-turn hard cap. The orchestrator refuses to run further
whole-body judge calls once the accumulated pre-flight estimate exceeds this.
Matches the caselaw budget."""

_PURPOSE = "judge_authority_content"


def _build_prompt(passage: str, authority_text: str, *, judge_model: str) -> ChatCompletionRequest:
    """Build the ChatCompletionRequest for the whole-body authority judge.

    Reuses ``build_judge_prompt`` (same system prompt / conservative-bias
    calibration) with the full authority body as the single source chunk.
    The ``lq_ai_purpose`` tag segregates these rows from caselaw judge calls
    in the cost-calibration routing log.
    """
    messages = build_judge_prompt(claim_text=passage, chunks=[authority_text])
    return ChatCompletionRequest(
        model=judge_model,
        messages=messages,
        max_tokens=400,
        temperature=0.0,
        anonymize=False,
        lq_ai_purpose=_PURPOSE,
    )


async def judge_authority_content(
    *,
    passage: str,
    authority_text: str,
    gateway: _JudgeGatewayProtocol,
    judge_model: str,
) -> VerificationResult:
    """Ask the LLM judge whether ``passage`` is faithfully supported by ``authority_text``.

    Returns ``VerificationResult(verified=True, method='paraphrase_judge', ...)``
    on a ``yes``/``partial`` verdict; :data:`_MISS` (``verified=False``) on
    ``no``, malformed JSON, or a gateway error. Never raises — all failures
    are swallowed and surfaced as MISS (the orchestrator drops on MISS).
    """
    try:
        request = _build_prompt(passage, authority_text, judge_model=judge_model)
        response = await gateway.chat_completion(request)
    except Exception as exc:
        log.warning(
            "authority-content judge call failed: %r",
            exc,
            extra={"event": "authority_content_judge_error", "error_type": type(exc).__name__},
        )
        return _MISS
    return _parse_judge_response(response)


async def estimate_authority_content_cost_usd(
    db: AsyncSession | None,
    *,
    judge_model: str,
    authority_text: str,
) -> Decimal:
    """Estimate the USD cost of one whole-body authority judge call.

    Scales the per-call rolling average (routing log filtered to
    ``purpose='judge_authority_content'``) by the ratio of the body's token
    count to the Stage-3 baseline, floored at 1. ``db=None`` → conservative
    :data:`DEFAULT_PER_JUDGE_USD` scaled by length (tests / cold-start).
    """
    per_call = await estimate_judge_call_cost_usd(db, judge_model=judge_model, purpose=_PURPOSE)
    body_tokens = max(1, len(authority_text) // CHARS_PER_TOKEN)
    scale = Decimal(body_tokens) / Decimal(TYPICAL_PARAPHRASE_TOKENS)
    if scale < Decimal(1):
        scale = Decimal(1)
    return max(per_call * scale, DEFAULT_PER_JUDGE_USD)
