"""Unit tests for the api domain-span helpers (M3-F2)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.observability_helpers import quiet_span, record_attributes, traced


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
    assert s.attributes is not None
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


@pytest.mark.unit
def test_quiet_span_records_the_class_of_a_failure_and_never_its_text(
    span_exporter: InMemorySpanExporter,
) -> None:
    """The SDK's default would put the message on the span as an event and as the status."""
    span_exporter.clear()
    tracer = trace.get_tracer("test")
    echoed = "SQL parameter: Acme Corp, 12 Main Street"

    with pytest.raises(ValueError, match="Acme Corp"), quiet_span(tracer, "thing.quiet"):
        raise ValueError(echoed)

    (s,) = span_exporter.get_finished_spans()
    assert s.status.status_code.name == "ERROR"
    assert s.status.description == "ValueError"
    assert s.attributes is not None
    assert s.attributes["error.type"] == "ValueError"
    assert s.events == ()
    assert "Acme" not in repr((s.status, s.attributes, s.events))


# Every span that a worker job can run through, by name. The arq worker exports
# spans when an OTLP endpoint is set (ADR 0038 D2), and docs/observability.md
# says spans carry identifiers, counts and labels, not what an exception says.
# Only quiet_span keeps that true when the work inside a span fails.
_WORKER_SPANS = {
    "autonomous.execute": "app/autonomous/executor.py",
    "tabular.execute": "app/tabular/executor.py",
    "tabular.cell": "app/tabular/nodes.py",
    "citation.verify": "app/citation/verification.py",
    "citation.stage.exact_match": "app/citation/verification.py",
    "citation.stage.tolerant_match": "app/citation/verification.py",
    "citation.stage.ensemble": "app/citation/verification.py",
    "citation.stage.paraphrase_judge": "app/citation/verification.py",
}


@pytest.mark.unit
@pytest.mark.parametrize(("name", "module"), sorted(_WORKER_SPANS.items()))
def test_a_span_that_a_worker_job_runs_through_does_not_record_exception_text(
    name: str, module: str
) -> None:
    source = (Path(__file__).resolve().parent.parent / module).read_text()
    assert f'quiet_span(tracer, "{name}")' in source
    assert not re.search(rf'start_as_current_span\(\s*"{re.escape(name)}"', source)
