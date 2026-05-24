"""Unit tests for the gateway domain-span helpers (M3-F2)."""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.observability_helpers import record_attributes, traced


@pytest.fixture(scope="module")
def span_exporter() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


@pytest.mark.unit
async def test_traced_async_emits_span(span_exporter: InMemorySpanExporter) -> None:
    span_exporter.clear()

    @traced("thing.do")
    async def do_thing() -> int:
        return 7

    assert await do_thing() == 7
    spans = span_exporter.get_finished_spans()
    assert [s.name for s in spans] == ["thing.do"]


@pytest.mark.unit
def test_traced_sync_emits_span(span_exporter: InMemorySpanExporter) -> None:
    span_exporter.clear()

    @traced("thing.sync")
    def do_thing() -> int:
        return 3

    assert do_thing() == 3
    assert [s.name for s in span_exporter.get_finished_spans()] == ["thing.sync"]


@pytest.mark.unit
def test_record_attributes_drops_none_and_keeps_values(
    span_exporter: InMemorySpanExporter,
) -> None:
    span_exporter.clear()
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("s") as span:
        record_attributes(span, foo="bar", missing=None, count=5)
    (s,) = span_exporter.get_finished_spans()
    assert s.attributes["foo"] == "bar"
    assert s.attributes["count"] == 5
    assert "missing" not in s.attributes


@pytest.mark.unit
async def test_traced_records_exception_and_reraises(
    span_exporter: InMemorySpanExporter,
) -> None:
    span_exporter.clear()

    @traced("thing.boom")
    async def boom() -> None:
        raise ValueError("nope")

    with pytest.raises(ValueError):
        await boom()
    (s,) = span_exporter.get_finished_spans()
    assert s.status.status_code.name == "ERROR"
    # Exactly one exception event — the decorator must not double-record
    # alongside the SDK's automatic exception handling.
    assert len(s.events) == 1
    assert s.events[0].name == "exception"
