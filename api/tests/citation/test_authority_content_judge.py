"""Whole-body authority content judge tests (WS-E PR1c, SUPPORTED tier).

``judge_authority_content(*, passage, authority_text, gateway, judge_model)``
feeds the full fetched authority body (statute / regulation text) to an LLM
judge and returns a VerificationResult. Mirrors
tests/test_case_content_judge.py (the caselaw B1b judge) — same gateway-stub
shape, same accept/reject/error/cost-scaling coverage, renamed for authority.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.citation.authority_content_judge import (
    _PURPOSE,
    AUTHORITY_CONTENT_JUDGE_BUDGET_USD,
    estimate_authority_content_cost_usd,
    judge_authority_content,
)
from app.schemas.gateway import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
)

pytestmark = pytest.mark.unit


def _judge_completion(verdict_json: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl-authjudge",
        created=0,
        model="fast",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionMessage(role="assistant", content=verdict_json),
                finish_reason="stop",
            )
        ],
        usage=ChatCompletionUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    )


def _serialize_messages(request: ChatCompletionRequest) -> str:
    parts = []
    for msg in request.messages:
        if msg.content:
            parts.append(msg.content)
    return "\n".join(parts)


class _YesGateway:
    """Records calls and returns a canned 'yes' judge verdict."""

    def __init__(self) -> None:
        self.calls = 0
        self.last_request: ChatCompletionRequest | None = None

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        *,
        request_id: str | None = None,
    ) -> ChatCompletionResponse:
        self.calls += 1
        self.last_request = request
        return _judge_completion(json.dumps({"verdict": "yes", "confidence": "high"}))


class _BoomGateway:
    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        *,
        request_id: str | None = None,
    ) -> ChatCompletionResponse:
        raise RuntimeError("gateway down")


# ---------------------------------------------------------------------------
# Happy paths / error paths.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_judge_accepts_returns_paraphrase_judge() -> None:
    gw = _YesGateway()
    result = await judge_authority_content(
        passage="the fair use of a copyrighted work is not an infringement",
        authority_text=(
            "... the fair use of a copyrighted work ... is not an infringement of copyright ..."
        ),
        gateway=gw,
        judge_model="fast",
    )
    assert result.verified is True
    assert result.method == "paraphrase_judge"
    assert gw.calls == 1


@pytest.mark.asyncio
async def test_judge_gateway_error_is_miss_not_raise() -> None:
    result = await judge_authority_content(
        passage="x",
        authority_text="y",
        gateway=_BoomGateway(),
        judge_model="fast",
    )
    assert result.verified is False


@pytest.mark.asyncio
async def test_judge_reject_yields_miss() -> None:
    class _NoGateway:
        async def chat_completion(
            self,
            request: ChatCompletionRequest,
            *,
            request_id: str | None = None,
        ) -> ChatCompletionResponse:
            return _judge_completion(json.dumps({"verdict": "no"}))

    result = await judge_authority_content(
        passage="Fabricated statutory text.",
        authority_text="...",
        gateway=_NoGateway(),
        judge_model="fast",
    )
    assert result.verified is False
    assert result.method is None


@pytest.mark.asyncio
async def test_judge_malformed_output_is_miss() -> None:
    class _GarbageGateway:
        async def chat_completion(
            self,
            request: ChatCompletionRequest,
            *,
            request_id: str | None = None,
        ) -> ChatCompletionResponse:
            return _judge_completion("not json at all")

    result = await judge_authority_content(
        passage="x",
        authority_text="...",
        gateway=_GarbageGateway(),
        judge_model="fast",
    )
    assert result.verified is False


@pytest.mark.asyncio
async def test_purpose_tag_is_authority_specific() -> None:
    assert _PURPOSE == "judge_authority_content"


@pytest.mark.asyncio
async def test_prompt_includes_authority_text_and_passage() -> None:
    gw = _YesGateway()
    await judge_authority_content(
        passage="UNIQUE_PASSAGE",
        authority_text="UNIQUE_AUTHORITY_BODY",
        gateway=gw,
        judge_model="fast",
    )
    assert gw.last_request is not None
    text = _serialize_messages(gw.last_request)
    assert "UNIQUE_PASSAGE" in text
    assert "UNIQUE_AUTHORITY_BODY" in text
    assert gw.last_request.lq_ai_purpose == "judge_authority_content"


# ---------------------------------------------------------------------------
# Cost estimate — scales with body length.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_estimate_db_none_scales_with_length() -> None:
    short = await estimate_authority_content_cost_usd(
        None, judge_model="fast", authority_text="a" * 100
    )
    long = await estimate_authority_content_cost_usd(
        None, judge_model="fast", authority_text="a" * 100_000
    )
    assert long >= short >= Decimal("0")
    assert long > short


@pytest.mark.asyncio
async def test_cost_estimate_minimum_scale_is_one() -> None:
    cost = await estimate_authority_content_cost_usd(None, judge_model="fast", authority_text="a")
    assert cost > Decimal("0")


def test_budget_constant_matches_caselaw() -> None:
    assert Decimal("0.25") == AUTHORITY_CONTENT_JUDGE_BUDGET_USD
