"""Citation Engine Stage 3 — paraphrase judge tests (M2-C1).

``verify_paraphrase(candidate, document, *, gateway, judge_model)``
sends a structured JSON judge prompt to the gateway and parses the
verdict. These tests cover:

* The three pass verdicts (yes, partial) with all three confidence
  levels mapping to 0.90 / 0.70 / 0.50.
* The ``partial`` flag on the result.
* The fail verdict ('no') → MISS regardless of confidence.
* Failure modes that must not crash the pipeline: gateway raising,
  malformed JSON output, unknown verdict / confidence values, empty
  response content. All silently return MISS so the caller routes
  the candidate to the next stage (or to "unverified" if Stage 3 was
  the last stage).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import pytest

from app.citation.verification import (
    VerificationResult,
    verify_paraphrase,
)
from app.errors import GatewayUnreachable
from app.schemas.gateway import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
)

# ---------------------------------------------------------------------------
# Stubs.
# ---------------------------------------------------------------------------


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
    """Records the request and returns a canned chat-completion response."""

    def __init__(
        self,
        *,
        response_content: str | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._response_content = response_content
        self._raises = raises
        self.last_request: ChatCompletionRequest | None = None
        self.call_count = 0

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        *,
        request_id: str | None = None,
    ) -> ChatCompletionResponse:
        self.last_request = request
        self.call_count += 1
        if self._raises is not None:
            raise self._raises
        return ChatCompletionResponse(
            id="chatcmpl-judge",
            created=0,
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionMessage(
                        role="assistant",
                        content=self._response_content,
                    ),
                    finish_reason="stop",
                )
            ],
            usage=ChatCompletionUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )


def _doc(text: str = "The agreement was signed on the third of June.") -> _StubDocument:
    return _StubDocument(id=uuid.uuid4(), normalized_content=text)


def _candidate(
    doc: _StubDocument,
    *,
    source_text: str = "the agreement was signed",
    offsets: tuple[int, int] | None = None,
) -> _StubCandidate:
    if offsets is None:
        # Default: a slice that exists inside doc; the verifier reads
        # the slice to build the judge prompt, but tests can override
        # to exercise out-of-range offsets.
        offsets = (0, min(40, len(doc.normalized_content)))
    return _StubCandidate(
        source_file_id=uuid.uuid4(),
        source_document_id=doc.id,
        source_offset_start=offsets[0],
        source_offset_end=offsets[1],
        source_page=None,
        source_text=source_text,
    )


def _judge_json(
    *,
    verdict: str,
    confidence: str = "high",
    justification: str = "test",
) -> str:
    return json.dumps(
        {"verdict": verdict, "confidence": confidence, "justification": justification}
    )


# ---------------------------------------------------------------------------
# Happy paths — verdict + confidence mapping.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_yes_high_returns_verified_with_confidence_0_90() -> None:
    """yes/high → verified=True, confidence=0.90, partial=False, method='paraphrase_judge'."""

    gw = _StubGateway(response_content=_judge_json(verdict="yes", confidence="high"))
    doc = _doc()
    cand = _candidate(doc)

    result = await verify_paraphrase(cand, doc, gateway=gw, judge_model="fast")

    assert result == VerificationResult(
        verified=True,
        method="paraphrase_judge",
        confidence=pytest.approx(0.90),
        partial=False,
    )


@pytest.mark.unit
async def test_yes_medium_returns_confidence_0_70() -> None:
    gw = _StubGateway(response_content=_judge_json(verdict="yes", confidence="medium"))
    doc = _doc()
    cand = _candidate(doc)

    result = await verify_paraphrase(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is True
    assert result.confidence == pytest.approx(0.70)
    assert result.partial is False


@pytest.mark.unit
async def test_yes_low_returns_confidence_0_50() -> None:
    gw = _StubGateway(response_content=_judge_json(verdict="yes", confidence="low"))
    doc = _doc()
    cand = _candidate(doc)

    result = await verify_paraphrase(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is True
    assert result.confidence == pytest.approx(0.50)


@pytest.mark.unit
async def test_partial_verdict_sets_partial_true() -> None:
    """partial verdict → verified=True (rendered as verified-with-caveats), partial=True."""

    gw = _StubGateway(response_content=_judge_json(verdict="partial", confidence="high"))
    doc = _doc()
    cand = _candidate(doc)

    result = await verify_paraphrase(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is True
    assert result.partial is True
    assert result.confidence == pytest.approx(0.90)
    assert result.method == "paraphrase_judge"


@pytest.mark.unit
async def test_partial_with_medium_confidence_maps_to_0_70() -> None:
    gw = _StubGateway(response_content=_judge_json(verdict="partial", confidence="medium"))
    doc = _doc()
    cand = _candidate(doc)

    result = await verify_paraphrase(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is True
    assert result.partial is True
    assert result.confidence == pytest.approx(0.70)


# ---------------------------------------------------------------------------
# 'no' verdict → MISS (caller can render as unverified).
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_no_verdict_returns_miss() -> None:
    """no verdict → verified=False, regardless of confidence level."""

    gw = _StubGateway(response_content=_judge_json(verdict="no", confidence="high"))
    doc = _doc()
    cand = _candidate(doc)

    result = await verify_paraphrase(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is False
    assert result.method is None
    assert result.partial is False


# ---------------------------------------------------------------------------
# Failure modes — none must raise; all return MISS.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_gateway_raises_returns_miss() -> None:
    """Gateway transport failure (timeout, unreachable) → silent MISS."""

    gw = _StubGateway(raises=GatewayUnreachable("gateway down"))
    doc = _doc()
    cand = _candidate(doc)

    result = await verify_paraphrase(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is False


@pytest.mark.unit
async def test_malformed_json_returns_miss() -> None:
    """Judge produces non-JSON output → silent MISS."""

    gw = _StubGateway(response_content="not json at all")
    doc = _doc()
    cand = _candidate(doc)

    result = await verify_paraphrase(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is False


@pytest.mark.unit
async def test_empty_response_content_returns_miss() -> None:
    """Judge returns empty content → MISS."""

    gw = _StubGateway(response_content="")
    doc = _doc()
    cand = _candidate(doc)

    result = await verify_paraphrase(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is False


@pytest.mark.unit
async def test_none_response_content_returns_miss() -> None:
    """Judge returns null content (tool-call shape) → MISS."""

    gw = _StubGateway(response_content=None)
    doc = _doc()
    cand = _candidate(doc)

    result = await verify_paraphrase(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is False


@pytest.mark.unit
async def test_unknown_verdict_returns_miss() -> None:
    """Verdict outside the documented enum → MISS."""

    gw = _StubGateway(response_content=_judge_json(verdict="maybe", confidence="high"))
    doc = _doc()
    cand = _candidate(doc)

    result = await verify_paraphrase(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is False


@pytest.mark.unit
async def test_unknown_confidence_returns_miss() -> None:
    """Confidence outside the documented enum → MISS."""

    gw = _StubGateway(response_content=_judge_json(verdict="yes", confidence="extreme"))
    doc = _doc()
    cand = _candidate(doc)

    result = await verify_paraphrase(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is False


@pytest.mark.unit
async def test_missing_verdict_field_returns_miss() -> None:
    """JSON missing the verdict key → MISS."""

    gw = _StubGateway(response_content=json.dumps({"confidence": "high", "justification": "x"}))
    doc = _doc()
    cand = _candidate(doc)

    result = await verify_paraphrase(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is False


# ---------------------------------------------------------------------------
# Prompt construction — verify the right alias and shape go to the gateway.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_dispatches_with_configured_judge_model() -> None:
    """The ChatCompletionRequest sent to the gateway uses the passed judge_model."""

    gw = _StubGateway(response_content=_judge_json(verdict="yes"))
    doc = _doc()
    cand = _candidate(doc)

    await verify_paraphrase(cand, doc, gateway=gw, judge_model="budget")

    assert gw.last_request is not None
    assert gw.last_request.model == "budget"
    # Sanity: the prompt has system + user messages (Stage 3 prompt shape).
    assert len(gw.last_request.messages) >= 2
    roles = [m.role for m in gw.last_request.messages]
    assert "system" in roles
    assert "user" in roles


@pytest.mark.unit
async def test_dispatches_with_claim_text_in_user_message() -> None:
    """The candidate's source_text appears in the user prompt."""

    claim = "The plaintiff prevailed on the breach claim."
    gw = _StubGateway(response_content=_judge_json(verdict="yes"))
    doc = _doc()
    cand = _candidate(doc, source_text=claim)

    await verify_paraphrase(cand, doc, gateway=gw, judge_model="fast")

    assert gw.last_request is not None
    user_msg = next(m for m in gw.last_request.messages if m.role == "user")
    assert claim in (user_msg.content or "")


@pytest.mark.unit
async def test_dispatches_with_source_slice_in_user_message() -> None:
    """The cited document slice appears in the user prompt as context."""

    doc_text = "Header. Section 5.1: The plaintiff prevailed. Section 5.2: ..."
    doc = _doc(text=doc_text)
    cited_span = "The plaintiff prevailed"
    start = doc_text.index(cited_span)
    cand = _candidate(
        doc,
        source_text=cited_span,
        offsets=(start, start + len(cited_span)),
    )

    gw = _StubGateway(response_content=_judge_json(verdict="yes"))
    await verify_paraphrase(cand, doc, gateway=gw, judge_model="fast")

    assert gw.last_request is not None
    user_msg = next(m for m in gw.last_request.messages if m.role == "user")
    # The cited span (and the surrounding context) is included.
    assert cited_span in (user_msg.content or "")
