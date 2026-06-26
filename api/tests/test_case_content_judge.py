"""Whole-opinion caselaw content judge tests (DE-280, P1-B1b).

``judge_case_content(*, passage, opinion_text, gateway, judge_model)``
feeds the full opinion text to an LLM judge and returns a
VerificationResult.  These tests cover:

* accept (yes/partial) → verified=True, method='paraphrase_judge'.
* reject (no) → MISS (verified=False, method=None).
* malformed / non-JSON output → MISS.
* prompt content: opinion_text AND passage both appear in the request.
* cost estimate scales with opinion length.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.citation.case_content_judge import (
    CHARS_PER_TOKEN,
    estimate_case_content_cost_usd,
    judge_case_content,
)
from app.schemas.gateway import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers — mirror the shape used in citation/test_paraphrase_judge.py.
# ---------------------------------------------------------------------------


def _judge_completion(verdict_json: str) -> ChatCompletionResponse:
    """Build a canned ChatCompletionResponse with the given content string."""
    return ChatCompletionResponse(
        id="chatcmpl-ccjudge",
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
    """Concatenate all message content fields for assertion convenience."""
    parts = []
    for msg in request.messages:
        if msg.content:
            parts.append(msg.content)
    return "\n".join(parts)


class _FakeGateway:
    """Minimal gateway stub — records the request and returns a canned response."""

    def __init__(self, verdict_json: str) -> None:
        self._verdict = verdict_json
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
        return _judge_completion(self._verdict)


# ---------------------------------------------------------------------------
# Happy paths.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_yields_paraphrase_judge() -> None:
    """yes verdict → verified=True, method='paraphrase_judge'."""
    gw = _FakeGateway(json.dumps({"verdict": "yes", "confidence": "high"}))
    r = await judge_case_content(
        passage="The court held X.",
        opinion_text="...full opinion...",
        gateway=gw,
        judge_model="fast",
    )
    assert r.verified is True
    assert r.method == "paraphrase_judge"
    assert gw.calls == 1


@pytest.mark.asyncio
async def test_partial_verdict_accepted() -> None:
    """partial verdict → verified=True, partial=True."""
    gw = _FakeGateway(json.dumps({"verdict": "partial", "confidence": "medium"}))
    r = await judge_case_content(
        passage="The court held X.",
        opinion_text="...full opinion...",
        gateway=gw,
        judge_model="fast",
    )
    assert r.verified is True
    assert r.partial is True
    assert r.method == "paraphrase_judge"


@pytest.mark.asyncio
async def test_reject_yields_miss() -> None:
    """no verdict → verified=False, method=None."""
    gw = _FakeGateway(json.dumps({"verdict": "no"}))
    r = await judge_case_content(
        passage="Fabricated holding.",
        opinion_text="...",
        gateway=gw,
        judge_model="fast",
    )
    assert r.verified is False
    assert r.method is None


@pytest.mark.asyncio
async def test_malformed_output_is_miss() -> None:
    """Non-JSON judge output → MISS, does not raise."""
    gw = _FakeGateway("not json at all")
    r = await judge_case_content(
        passage="x",
        opinion_text="...",
        gateway=gw,
        judge_model="fast",
    )
    assert r.verified is False


@pytest.mark.asyncio
async def test_gateway_error_returns_miss() -> None:
    """Gateway transport error → MISS, does not raise."""

    class _ErrorGW:
        async def chat_completion(
            self,
            request: ChatCompletionRequest,
            *,
            request_id: str | None = None,
        ) -> ChatCompletionResponse:
            raise RuntimeError("gateway down")

    r = await judge_case_content(
        passage="x",
        opinion_text="...",
        gateway=_ErrorGW(),
        judge_model="fast",
    )
    assert r.verified is False


# ---------------------------------------------------------------------------
# Prompt content — opinion + passage must appear in the request.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prompt_includes_opinion_and_passage() -> None:
    """The full opinion_text and the passage both appear in the gateway request."""
    captured: dict[str, ChatCompletionRequest] = {}

    class _CapGW:
        async def chat_completion(
            self,
            request: ChatCompletionRequest,
            *,
            request_id: str | None = None,
        ) -> ChatCompletionResponse:
            captured["request"] = request
            return _judge_completion(json.dumps({"verdict": "yes", "confidence": "medium"}))

    await judge_case_content(
        passage="UNIQUE_PASSAGE",
        opinion_text="UNIQUE_OPINION_BODY",
        gateway=_CapGW(),
        judge_model="fast",
    )
    assert "request" in captured
    text = _serialize_messages(captured["request"])
    assert "UNIQUE_PASSAGE" in text
    assert "UNIQUE_OPINION_BODY" in text


@pytest.mark.asyncio
async def test_request_purpose_is_judge_case_content() -> None:
    """The gateway request is tagged with lq_ai_purpose='judge_case_content'."""
    captured: dict[str, ChatCompletionRequest] = {}

    class _CapGW:
        async def chat_completion(
            self,
            request: ChatCompletionRequest,
            *,
            request_id: str | None = None,
        ) -> ChatCompletionResponse:
            captured["request"] = request
            return _judge_completion(json.dumps({"verdict": "yes", "confidence": "high"}))

    await judge_case_content(
        passage="some passage",
        opinion_text="some opinion",
        gateway=_CapGW(),
        judge_model="fast",
    )
    assert captured["request"].lq_ai_purpose == "judge_case_content"


# ---------------------------------------------------------------------------
# Cost estimate — scales with opinion length.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_estimate_scales_with_opinion_length() -> None:
    """A longer opinion yields a higher cost estimate than a short one."""
    short = await estimate_case_content_cost_usd(None, judge_model="fast", opinion_text="x" * 1000)
    long = await estimate_case_content_cost_usd(
        None, judge_model="fast", opinion_text="x" * (1000 * CHARS_PER_TOKEN * 50)
    )
    assert long > short


@pytest.mark.asyncio
async def test_cost_estimate_minimum_scale_is_one() -> None:
    """A very short opinion (under one typical chunk) still returns a positive cost."""
    cost = await estimate_case_content_cost_usd(None, judge_model="fast", opinion_text="x")
    assert cost > Decimal("0")
