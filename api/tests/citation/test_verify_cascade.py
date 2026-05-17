"""Tests for the async :func:`verify` cascade with Stage 3 wired in (M2-C1).

``verify()`` was a sync function in M2-A2 / M2-B1 because Stages 1
and 2 are pure-Python. M2-C1 makes it async because Stage 3 dispatches
to the LLM judge through the gateway. The cascade order:

1. Stage 1 (exact-match) — fast, byte-for-byte.
2. Stage 2 (tolerant-match) — normalized fuzzy ratio at threshold 95.
3. Stage 3 (paraphrase judge) — LLM call, only runs when a gateway is
   supplied AND Stages 1+2 missed.

The cascade short-circuits on the first hit. The gateway parameter is
optional so callers without an LLM (smoke tests, eval scripts) can
still run Stages 1+2 without scaffolding a gateway client.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import pytest

from app.citation.verification import VerificationResult, verify
from app.schemas.gateway import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
)


@dataclass(slots=True)
class _StubDocument:
    id: uuid.UUID
    normalized_content: str
    was_ocrd: bool = False


@dataclass(slots=True)
class _StubCandidate:
    source_file_id: uuid.UUID
    source_document_id: uuid.UUID
    source_offset_start: int
    source_offset_end: int
    source_page: int | None
    source_text: str


class _StubGateway:
    def __init__(self, response_content: str) -> None:
        self._content = response_content
        self.call_count = 0

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        *,
        request_id: str | None = None,
    ) -> ChatCompletionResponse:
        self.call_count += 1
        return ChatCompletionResponse(
            id="chatcmpl-test",
            created=0,
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionMessage(role="assistant", content=self._content),
                    finish_reason="stop",
                )
            ],
            usage=ChatCompletionUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


def _doc(text: str) -> _StubDocument:
    return _StubDocument(id=uuid.uuid4(), normalized_content=text)


def _cand(
    doc: _StubDocument,
    *,
    start: int,
    end: int,
    source_text: str,
) -> _StubCandidate:
    return _StubCandidate(
        source_file_id=uuid.uuid4(),
        source_document_id=doc.id,
        source_offset_start=start,
        source_offset_end=end,
        source_page=None,
        source_text=source_text,
    )


# ---------------------------------------------------------------------------
# Stage 1 short-circuit.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_stage_1_hit_short_circuits_cascade() -> None:
    """Exact match returns immediately without touching Stages 2 or 3."""

    text = "the agreement was signed on June 3rd."
    doc = _doc(text)
    cand = _cand(doc, start=0, end=len(text), source_text=text)

    gw = _StubGateway('{"verdict": "no"}')  # Would fail if reached.
    result = await verify(cand, doc, gateway=gw, judge_model="fast")

    assert result == VerificationResult(
        verified=True,
        method="exact_match",
        confidence=1.0,
        partial=False,
    )
    assert gw.call_count == 0


# ---------------------------------------------------------------------------
# Stage 2 short-circuit.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_stage_2_hit_short_circuits_stage_3() -> None:
    """Tolerant match (smart vs straight quotes) doesn't trigger Stage 3."""

    text = '"the agreement was signed on June 3rd."'
    doc = _doc(text)
    smart = "“the agreement was signed on June 3rd.”"
    cand = _cand(doc, start=0, end=len(text), source_text=smart)

    gw = _StubGateway('{"verdict": "no"}')
    result = await verify(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is True
    assert result.method == "tolerant_match"
    assert gw.call_count == 0


# ---------------------------------------------------------------------------
# Stage 3 — fires when 1+2 miss.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_stage_3_runs_when_1_and_2_miss() -> None:
    """Paraphrased citation passes Stage 3 after Stages 1+2 miss."""

    text = "The plaintiff prevailed on the breach claim after extensive discovery."
    doc = _doc(text)
    # Paraphrase that doesn't byte-match and is below the 95 fuzz
    # ratio threshold (Stage 2 also misses).
    paraphrase = "The plaintiff won their breach case."
    cand = _cand(doc, start=0, end=len(text), source_text=paraphrase)

    gw = _StubGateway(
        json.dumps({"verdict": "yes", "confidence": "high", "justification": "supports"})
    )
    result = await verify(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is True
    assert result.method == "paraphrase_judge"
    assert result.confidence == pytest.approx(0.90)
    assert result.partial is False
    assert gw.call_count == 1


@pytest.mark.unit
async def test_stage_3_partial_verdict_propagates() -> None:
    """Stage 3 'partial' verdict surfaces with partial=True."""

    text = "The plaintiff prevailed on the breach claim after extensive discovery."
    doc = _doc(text)
    paraphrase = "The plaintiff won their case on all counts."
    cand = _cand(doc, start=0, end=len(text), source_text=paraphrase)

    gw = _StubGateway(
        json.dumps({"verdict": "partial", "confidence": "medium", "justification": "y"})
    )
    result = await verify(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is True
    assert result.partial is True
    assert result.method == "paraphrase_judge"
    assert result.confidence == pytest.approx(0.70)


@pytest.mark.unit
async def test_stage_3_no_verdict_returns_miss() -> None:
    """All stages miss → cascade returns the MISS sentinel."""

    text = "The plaintiff prevailed on the breach claim."
    doc = _doc(text)
    cand = _cand(doc, start=0, end=len(text), source_text="An unrelated statement.")

    gw = _StubGateway(json.dumps({"verdict": "no", "confidence": "high"}))
    result = await verify(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is False
    assert result.method is None
    assert result.partial is False
    assert gw.call_count == 1


# ---------------------------------------------------------------------------
# Stage 3 — skipped when no gateway is provided.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_stage_3_skipped_when_no_gateway() -> None:
    """Without a gateway, Stages 1+2 miss → MISS; no judge call attempted."""

    text = "The plaintiff prevailed on the breach claim."
    doc = _doc(text)
    cand = _cand(doc, start=0, end=len(text), source_text="paraphrased claim")

    result = await verify(cand, doc, gateway=None, judge_model="fast")

    assert result.verified is False
    assert result.method is None


@pytest.mark.unit
async def test_existing_callers_can_omit_gateway_kwargs() -> None:
    """``await verify(cand, doc)`` is still valid — gateway/judge_model default."""

    text = "the agreement was signed."
    doc = _doc(text)
    cand = _cand(doc, start=0, end=len(text), source_text=text)

    result = await verify(cand, doc)

    # Stage 1 hits — gateway never needed.
    assert result.verified is True
    assert result.method == "exact_match"
