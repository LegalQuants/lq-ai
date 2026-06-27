"""Treatment-classifying judge over a citing snippet (WS-G PR2).

A NEW judge prompt + verdict schema (the cascade judge speaks yes/partial/no;
this speaks the 7-class treatment taxonomy). Reuses the judge RAILS only:
the gateway protocol, the cost estimator, the _CONFIDENCE_MAP scale, and the
parse-or-skip discipline. The snippet is transient input — never persisted (P3).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.cost import estimate_judge_call_cost_usd
from app.citation.verification import _CONFIDENCE_MAP, _JudgeGatewayProtocol
from app.schemas.gateway import ChatCompletionMessage, ChatCompletionRequest

log = logging.getLogger(__name__)

TREATMENT_CLASSES = (
    "followed",
    "distinguished",
    "criticized",
    "questioned",
    "overruled",
    "superseded",
    "neutral",
)
_TREATMENT_PURPOSE = "judge_treatment"

_SYSTEM_PROMPT = """\
You are a Legal Treatment Classifier for a legal AI assistant.

You are given the NAME of a CITED case and a SNIPPET from a LATER opinion
that cites it. Classify how the later opinion TREATS the cited case, using
EXACTLY ONE of these labels:

* "overruled"    — the later court overrules/abrogates the cited case.
* "superseded"   — the cited case is superseded (e.g., by statute/rule).
* "criticized"   — the later court criticizes the cited case's reasoning.
* "questioned"   — the later court doubts/questions the cited case.
* "distinguished"— the later court distinguishes the cited case on its facts.
* "followed"     — the later court follows/applies the cited case favorably.
* "neutral"      — a bare citation with no discernible treatment signal.

Respond with STRICTLY VALID JSON in this exact shape:

  {"treatment": "<one label above>",
   "confidence": "high" | "medium" | "low",
   "justification": "<one or two sentences; DESCRIBE the treatment in your
                      own words — do NOT quote the opinion text>"}

CALIBRATION — IMPORTANT. When uncertain between a negative label
(overruled/superseded/criticized/questioned/distinguished) and "neutral",
choose "neutral". A false negative-treatment flag is worse than a missed
one. Only assert a negative label when the snippet clearly supports it.

Output ONLY the JSON object. No preamble, no markdown fencing."""


@dataclass(slots=True)
class TreatmentJudgment:
    classification: str
    confidence: float
    justification: str


def build_treatment_judge_prompt(
    *, cited_case_name: str, snippet: str
) -> list[ChatCompletionMessage]:
    user = (
        f'CITED CASE:\n"""\n{cited_case_name}\n"""\n\n'
        f'SNIPPET FROM THE LATER (CITING) OPINION:\n"""\n{snippet}\n"""\n\n'
        "How does the later opinion treat the CITED CASE? Respond with the JSON object only."
    )
    return [
        ChatCompletionMessage(role="system", content=_SYSTEM_PROMPT),
        ChatCompletionMessage(role="user", content=user),
    ]


def parse_treatment_response(response: Any) -> TreatmentJudgment | None:
    try:
        choices = response.choices
        if not choices:
            return None
        content = choices[0].message.content
    except AttributeError:
        return None
    if not content:
        return None
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        log.info("treatment judge produced non-JSON", extra={"event": "treatment_judge_malformed"})
        return None
    if not isinstance(payload, dict):
        return None
    treatment = payload.get("treatment")
    confidence_label = payload.get("confidence")
    justification = payload.get("justification")
    if treatment not in TREATMENT_CLASSES:
        log.info(
            "treatment judge unknown class %r",
            treatment,
            extra={"event": "treatment_judge_unknown_class"},
        )
        return None
    if confidence_label not in _CONFIDENCE_MAP:
        return None
    if not isinstance(justification, str) or not justification.strip():
        return None
    return TreatmentJudgment(
        classification=treatment,
        confidence=_CONFIDENCE_MAP[confidence_label],
        justification=justification.strip(),
    )


async def judge_treatment(
    *,
    cited_case_name: str,
    snippet: str,
    gateway: _JudgeGatewayProtocol,
    judge_model: str,
) -> TreatmentJudgment | None:
    request = ChatCompletionRequest(
        model=judge_model,
        messages=build_treatment_judge_prompt(cited_case_name=cited_case_name, snippet=snippet),
        max_tokens=400,
        temperature=0.0,
        anonymize=False,
        lq_ai_purpose=_TREATMENT_PURPOSE,
    )
    try:
        response = await gateway.chat_completion(request)
    except Exception as exc:
        log.warning(
            "treatment judge gateway call failed: %r",
            exc,
            extra={"event": "treatment_judge_error", "error_type": type(exc).__name__},
        )
        return None
    return parse_treatment_response(response)


async def estimate_treatment_cost_usd(db: AsyncSession | None, *, judge_model: str) -> Decimal:
    """Per-call estimate. The snippet is short + bounded, so (unlike the
    whole-opinion judge) no opinion-length scaling is applied."""
    return await estimate_judge_call_cost_usd(
        db, judge_model=judge_model, purpose=_TREATMENT_PURPOSE
    )
