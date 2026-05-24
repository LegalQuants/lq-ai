"""OTel span emission tests for the citation verification cascade (M3-F2).

Verifies that :func:`app.citation.verification.verify` emits the expected
``citation.verify`` top-level span and per-stage child spans, short-circuit
events on exact/tolerant hits, and correct result attributes on every
return path.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Literal

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.citation.verification import verify
from app.schemas.gateway import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
)

# ---------------------------------------------------------------------------
# OTel fixture — module-scoped so the provider is set up once per module.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def span_exporter() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


# ---------------------------------------------------------------------------
# Stubs — mirrors what existing cascade tests use.
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


@dataclass(slots=True)
class _StubEnsembleConfig:
    judge_models: tuple[str, ...]
    aggregation_rule: Literal["strict", "majority"]
    envelope_tier: int | None = 3


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
            id="chatcmpl-span-test",
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
# Helpers.
# ---------------------------------------------------------------------------


def _spans_by_name(exporter: InMemorySpanExporter, name: str) -> list:
    return [s for s in exporter.get_finished_spans() if s.name == name]


def _event_names(span) -> list[str]:
    return [e.name for e in span.events]


# ---------------------------------------------------------------------------
# Test 1: exact_match hit → short-circuit event, no tolerant span.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_exact_match_hit_emits_short_circuit_event(
    span_exporter: InMemorySpanExporter,
) -> None:
    """Exact-match hit emits exact_match.hit event; tolerant stage span absent."""
    span_exporter.clear()

    text = "the agreement was signed on June 3rd."
    doc = _doc(text)
    cand = _cand(doc, start=0, end=len(text), source_text=text)

    # gateway would fail if reached
    gw = _StubGateway('{"verdict": "no"}')
    result = await verify(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is True
    assert result.method == "exact_match"
    assert result.confidence == pytest.approx(1.0)

    spans = span_exporter.get_finished_spans()
    span_names = [s.name for s in spans]

    # Top-level citation.verify span must exist.
    top_spans = _spans_by_name(span_exporter, "citation.verify")
    assert len(top_spans) == 1, f"Expected citation.verify span, got: {span_names}"
    top = top_spans[0]

    # Short-circuit event on the top span.
    assert "exact_match.hit" in _event_names(top), (
        f"Expected exact_match.hit event, got: {_event_names(top)}"
    )

    # Result attributes on top span.
    assert top.attributes.get("citation.method") == "exact_match"
    assert top.attributes.get("citation.confidence") == pytest.approx(1.0)

    # Stage span for exact_match exists.
    exact_spans = _spans_by_name(span_exporter, "citation.stage.exact_match")
    assert len(exact_spans) == 1, "Expected citation.stage.exact_match span"
    assert exact_spans[0].attributes.get("citation.stage.verified") is True

    # Tolerant-match stage span must NOT exist (short-circuited).
    tolerant_spans = _spans_by_name(span_exporter, "citation.stage.tolerant_match")
    assert len(tolerant_spans) == 0, (
        f"Expected NO tolerant_match span after exact hit, got {len(tolerant_spans)}"
    )

    # No gateway calls.
    assert gw.call_count == 0


# ---------------------------------------------------------------------------
# Test 2: tolerant_match hit → both stages run, no LLM stage span.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_tolerant_match_hit_sets_top_attributes(
    span_exporter: InMemorySpanExporter,
) -> None:
    """Tolerant-match hit: exact+tolerant stage spans exist, paraphrase absent."""
    span_exporter.clear()

    text = '"the agreement was signed on June 3rd."'
    doc = _doc(text)
    smart = "“the agreement was signed on June 3rd.”"
    cand = _cand(doc, start=0, end=len(text), source_text=smart)

    gw = _StubGateway('{"verdict": "no"}')
    result = await verify(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is True
    assert result.method == "tolerant_match"

    spans = span_exporter.get_finished_spans()
    span_names = [s.name for s in spans]

    top_spans = _spans_by_name(span_exporter, "citation.verify")
    assert len(top_spans) == 1, f"Expected citation.verify span, got: {span_names}"
    top = top_spans[0]

    # Short-circuit event on the top span.
    assert "tolerant_match.hit" in _event_names(top), (
        f"Expected tolerant_match.hit event, got: {_event_names(top)}"
    )

    # Result attributes on top span.
    assert top.attributes.get("citation.method") == "tolerant_match"

    # Both deterministic stage spans exist.
    assert len(_spans_by_name(span_exporter, "citation.stage.exact_match")) == 1
    assert len(_spans_by_name(span_exporter, "citation.stage.tolerant_match")) == 1

    # LLM stage spans absent (short-circuited before gateway).
    assert len(_spans_by_name(span_exporter, "citation.stage.paraphrase_judge")) == 0
    assert len(_spans_by_name(span_exporter, "citation.stage.ensemble")) == 0
    assert gw.call_count == 0


# ---------------------------------------------------------------------------
# Test 3: gateway=None → MISS with top span attrs set.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_miss_no_gateway_sets_top_span_attributes(
    span_exporter: InMemorySpanExporter,
) -> None:
    """All deterministic stages miss, no gateway → MISS; top span attrs set."""
    span_exporter.clear()

    text = "The plaintiff prevailed on the breach claim."
    doc = _doc(text)
    cand = _cand(doc, start=0, end=len(text), source_text="completely different text here")

    result = await verify(cand, doc, gateway=None)

    assert result.verified is False
    assert result.method is None

    top_spans = _spans_by_name(span_exporter, "citation.verify")
    assert len(top_spans) == 1
    top = top_spans[0]

    # citation.method should be absent (None dropped by record_attributes).
    assert "citation.method" not in (top.attributes or {})
    # citation.partial should be set (False is non-None).
    assert top.attributes.get("citation.partial") is False

    # Both deterministic stage spans present.
    assert len(_spans_by_name(span_exporter, "citation.stage.exact_match")) == 1
    assert len(_spans_by_name(span_exporter, "citation.stage.tolerant_match")) == 1

    # No LLM spans.
    assert len(_spans_by_name(span_exporter, "citation.stage.paraphrase_judge")) == 0


# ---------------------------------------------------------------------------
# Test 4: paraphrase judge stage → paraphrase_judge span + top attrs.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_paraphrase_judge_stage_emits_span(
    span_exporter: InMemorySpanExporter,
) -> None:
    """When Stages 1+2 miss and gateway is provided, paraphrase_judge span emitted."""
    span_exporter.clear()

    text = "The plaintiff prevailed on the breach claim after extensive discovery."
    doc = _doc(text)
    paraphrase = "The plaintiff won their breach case."
    cand = _cand(doc, start=0, end=len(text), source_text=paraphrase)

    gw = _StubGateway(
        json.dumps({"verdict": "yes", "confidence": "high", "justification": "supports"})
    )
    result = await verify(cand, doc, gateway=gw, judge_model="fast")

    assert result.verified is True
    assert result.method == "paraphrase_judge"

    top_spans = _spans_by_name(span_exporter, "citation.verify")
    assert len(top_spans) == 1
    top = top_spans[0]

    assert top.attributes.get("citation.method") == "paraphrase_judge"
    assert top.attributes.get("citation.confidence") == pytest.approx(0.90)

    assert len(_spans_by_name(span_exporter, "citation.stage.exact_match")) == 1
    assert len(_spans_by_name(span_exporter, "citation.stage.tolerant_match")) == 1
    paraphrase_spans = _spans_by_name(span_exporter, "citation.stage.paraphrase_judge")
    assert len(paraphrase_spans) == 1
    assert paraphrase_spans[0].attributes.get("citation.stage.verified") is True


# ---------------------------------------------------------------------------
# Test 5: ensemble stage → ensemble span + top attrs.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_ensemble_stage_emits_span(
    span_exporter: InMemorySpanExporter,
) -> None:
    """When ensemble_config supplied and Stages 1+2 miss, ensemble span emitted."""
    span_exporter.clear()

    text = "The plaintiff prevailed on the breach claim after extensive discovery."
    doc = _doc(text)
    paraphrase = "The plaintiff won their breach case in court."
    cand = _cand(doc, start=0, end=len(text), source_text=paraphrase)

    ensemble_cfg = _StubEnsembleConfig(
        judge_models=("fast", "fast"),
        aggregation_rule="strict",
        envelope_tier=3,
    )
    gw = _StubGateway(json.dumps({"verdict": "yes", "confidence": "high", "justification": "ok"}))
    result = await verify(cand, doc, gateway=gw, ensemble_config=ensemble_cfg)

    assert result.verified is True
    assert result.method in ("ensemble_strict", "ensemble_majority")

    top_spans = _spans_by_name(span_exporter, "citation.verify")
    assert len(top_spans) == 1
    top = top_spans[0]
    assert top.attributes.get("citation.method") in ("ensemble_strict", "ensemble_majority")

    ensemble_spans = _spans_by_name(span_exporter, "citation.stage.ensemble")
    assert len(ensemble_spans) == 1
    assert ensemble_spans[0].attributes.get("citation.stage.verified") is True
    assert ensemble_spans[0].attributes.get("citation.ensemble.n_judges") == 2
    assert ensemble_spans[0].attributes.get("citation.ensemble.rule") == "strict"

    # No separate paraphrase_judge stage span at the cascade level.
    assert len(_spans_by_name(span_exporter, "citation.stage.paraphrase_judge")) == 0
