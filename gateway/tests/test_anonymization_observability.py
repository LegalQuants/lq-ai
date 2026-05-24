"""Observability tests for anonymization.pre / .post spans (M3-F2, Task 3).

Verifies three guarantees:

1. The ``anonymization.entity_count`` attribute is always an int; the
   injected raw entity name never appears in any span attribute value.
   (The "anonymization-of-attributes" promise: counts + type names only.)
2. Privileged requests set ``anonymization.skip_reason = "privileged"``
   and ``anonymization.entity_count = 0``.
3. Disabled config sets ``anonymization.skip_reason = "disabled"`` and
   ``anonymization.entity_count = 0``.

Span collection uses :class:`InMemorySpanExporter` wired through a
module-scoped :class:`TracerProvider`, matching the pattern in
:mod:`tests.test_observability_helpers`.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.anonymization.engine import Anonymizer
from app.anonymization.middleware import pre_anonymize_request
from app.config import AnonymizationConfig
from app.providers.openai_schema import ChatCompletionMessage, ChatCompletionRequest

# ---------------------------------------------------------------------------
# Span exporter fixture (module-scoped — one provider per test module).
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
# Stub analyzer — same pattern as test_middleware.py (duplicated to avoid
# cross-module test imports).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Span:
    entity_type: str
    start: int
    end: int
    score: float = 0.85


class _StubAnalyzer:
    """Returns canned spans from a (text → spans) lookup table."""

    def __init__(self, by_text: dict[str, list[_Span]]) -> None:
        self._by_text = by_text

    def analyze(self, *, text: str, language: str = "en", **_kwargs: object) -> list[_Span]:
        return list(self._by_text.get(text, []))


# Injected test value — a name the stub analyzer will detect as PERSON.
_INJECTED_NAME = "Alexandra Pemberton"
_INJECTED_TEXT = f"Please review the contract signed by {_INJECTED_NAME}."
_INJECTED_SPAN = _Span(
    "PERSON",
    _INJECTED_TEXT.index(_INJECTED_NAME),
    _INJECTED_TEXT.index(_INJECTED_NAME) + len(_INJECTED_NAME),  # exclusive end
)


def _make_request(
    *,
    content: str = _INJECTED_TEXT,
    anonymize: bool = True,
    privileged: bool = False,
) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="smart",
        messages=[ChatCompletionMessage(role="user", content=content)],
        anonymize=anonymize,
        lq_ai_privileged=privileged,
        lq_ai_skill_inputs={},
    )


def _default_config(*, enabled: bool = True) -> AnonymizationConfig:
    return AnonymizationConfig(enabled=enabled, apply_at_tiers=[3, 4, 5])


def _default_analyzer() -> Anonymizer:
    return Anonymizer(analyzer=_StubAnalyzer({_INJECTED_TEXT: [_INJECTED_SPAN]}))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_entity_count_attribute_is_int_never_names(
    span_exporter: InMemorySpanExporter,
) -> None:
    """anonymization.entity_count is int >= 1; raw name never in any attr value.

    This is the core "anonymization-of-attributes" guarantee: telemetry
    records counts and type names, never the original entity text.
    """
    span_exporter.clear()

    mapper = pre_anonymize_request(
        chat_request=_make_request(),
        config=_default_config(),
        routed_tier=4,
        anonymizer=_default_analyzer(),
    )

    assert mapper is not None, "Expected mapper (not None) for a firing request"

    finished = span_exporter.get_finished_spans()
    pre_spans = [s for s in finished if s.name == "anonymization.pre"]
    assert len(pre_spans) == 1, f"Expected 1 anonymization.pre span, got {len(pre_spans)}"

    attrs = pre_spans[0].attributes or {}

    # The always-present header attributes are set before the skip check.
    assert attrs["anonymization.enabled"] is True
    assert attrs["anonymization.tier"] == 4

    # Count is an int (not a float, not a string).
    assert isinstance(attrs["anonymization.entity_count"], int), (
        f"anonymization.entity_count must be int, got {type(attrs['anonymization.entity_count'])}"
    )
    assert attrs["anonymization.entity_count"] >= 1, (
        f"Expected at least 1 entity, got {attrs['anonymization.entity_count']}"
    )

    # Type names include PERSON.
    entity_types = attrs.get("anonymization.entity_types")
    assert entity_types is not None, "anonymization.entity_types attribute missing"
    assert "PERSON" in entity_types, f"Expected PERSON in entity_types, got {entity_types}"

    # The raw injected name must NOT appear in any attribute value.
    flat = " ".join(str(v) for v in attrs.values())
    assert _INJECTED_NAME not in flat, (
        f"Raw entity name '{_INJECTED_NAME}' leaked into span attributes: {flat!r}"
    )


@pytest.mark.unit
def test_skip_reason_recorded_when_privileged(
    span_exporter: InMemorySpanExporter,
) -> None:
    """Privileged request → skip_reason='privileged', entity_count=0."""
    span_exporter.clear()

    mapper = pre_anonymize_request(
        chat_request=_make_request(privileged=True),
        config=_default_config(),
        routed_tier=4,
        anonymizer=_default_analyzer(),
    )

    assert mapper is None

    finished = span_exporter.get_finished_spans()
    pre_spans = [s for s in finished if s.name == "anonymization.pre"]
    assert len(pre_spans) == 1, f"Expected 1 anonymization.pre span, got {len(pre_spans)}"

    attrs = pre_spans[0].attributes or {}
    assert attrs["anonymization.skip_reason"] == "privileged", (
        f"Expected skip_reason='privileged', got {attrs.get('anonymization.skip_reason')!r}"
    )
    assert attrs["anonymization.entity_count"] == 0, (
        f"Expected entity_count=0 on skip, got {attrs.get('anonymization.entity_count')}"
    )


@pytest.mark.unit
def test_disabled_config_skips(
    span_exporter: InMemorySpanExporter,
) -> None:
    """config.enabled=False → skip_reason='disabled', entity_count=0."""
    span_exporter.clear()

    mapper = pre_anonymize_request(
        chat_request=_make_request(),
        config=_default_config(enabled=False),
        routed_tier=4,
        anonymizer=_default_analyzer(),
    )

    assert mapper is None

    finished = span_exporter.get_finished_spans()
    pre_spans = [s for s in finished if s.name == "anonymization.pre"]
    assert len(pre_spans) == 1, f"Expected 1 anonymization.pre span, got {len(pre_spans)}"

    attrs = pre_spans[0].attributes or {}
    assert attrs["anonymization.skip_reason"] == "disabled", (
        f"Expected skip_reason='disabled', got {attrs.get('anonymization.skip_reason')!r}"
    )
    assert attrs["anonymization.entity_count"] == 0, (
        f"Expected entity_count=0 on skip, got {attrs.get('anonymization.entity_count')}"
    )
