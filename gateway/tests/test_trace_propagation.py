"""Trace-context propagation regression tests for the gateway (M3-F1 / PRD §5.4).

The gateway sits in the middle of the ``api → gateway → provider`` call
chain, so it owns two halves of the single-trace contract:

1. **Inbound** — a request arriving from the api with a W3C
   ``traceparent`` must *join* that trace (the gateway's request span is
   a child of the api's client span), not start a fresh root.
2. **Outbound** — when the gateway dispatches to a provider over httpx,
   it must re-inject the active context so the provider hop stays on the
   same trace.

Together with ``api/tests/test_trace_propagation.py`` these pin "one
chat-send = one trace, not three." The M3-F1 audit confirmed this works
through OpenTelemetry auto-instrumentation under the default global
textmap propagator (W3C TraceContext + baggage); no code fix was needed.
These tests are the standing contract — if injection or extraction
regresses, they fail.

We use an :class:`InMemorySpanExporter` in place of a live OTLP
collector for deterministic, dependency-free assertions, and exercise
the real injection routine via :class:`AsyncOpenTelemetryTransport`
(which shares ``opentelemetry.propagate.inject`` with the production
global ``HTTPXClientInstrumentor().instrument()`` path).

See ``docs/architecture.md`` §OBS and
``docs/proposals/opentelemetry-deepening.md`` (PR 1).
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import httpx
import pytest
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import AsyncOpenTelemetryTransport
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

# W3C traceparent: version "-" trace-id(32 hex) "-" parent-id(16 hex) "-" flags(2 hex)
_TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")

_GATEWAY_ROUTE = "/v1/chat/completions"
_PROVIDER_ROUTE = "/v1/messages"

# A fixed upstream context representing what the api put on the wire.
_UPSTREAM_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
_UPSTREAM_SPAN_ID = "00f067aa0ba902b7"
_UPSTREAM_TRACEPARENT = f"00-{_UPSTREAM_TRACE_ID}-{_UPSTREAM_SPAN_ID}-01"


@pytest.fixture(scope="module")
def span_exporter() -> InMemorySpanExporter:
    """A process TracerProvider exporting to memory.

    The OTel SDK allows the global TracerProvider to be set exactly once
    per process, so we install ours (or reuse an SDK one another module
    already installed) and attach an in-memory exporter. Tests clear the
    exporter between cases.
    """

    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


@pytest.fixture()
def gateway_app(span_exporter: InMemorySpanExporter) -> Iterator[FastAPI]:
    """A minimal FastAPI app standing in for the gateway, instrumented
    for inbound trace-context extraction."""

    app = FastAPI()

    @app.post(_GATEWAY_ROUTE)
    async def chat_completions() -> dict[str, bool]:
        return {"ok": True}

    FastAPIInstrumentor.instrument_app(app)
    span_exporter.clear()
    try:
        yield app
    finally:
        FastAPIInstrumentor.uninstrument_app(app)
        span_exporter.clear()


def _by_name(spans: list[ReadableSpan], name: str) -> ReadableSpan:
    matches = [s for s in spans if s.name == name]
    assert len(matches) == 1, f"expected exactly one {name!r} span, got {len(matches)}"
    return matches[0]


@pytest.mark.unit
async def test_gateway_joins_upstream_trace_from_traceparent(
    span_exporter: InMemorySpanExporter,
    gateway_app: FastAPI,
) -> None:
    """An inbound request carrying a ``traceparent`` joins that trace.

    Sent from a fresh context (no active span) so the only way the
    gateway's request span can adopt the upstream trace ID + parent is
    by extracting the header. If extraction regresses, the gateway
    starts a fresh root and the trace ID diverges — this test fails.
    """

    assert trace.get_current_span().get_span_context().trace_id == 0, (
        "expected no active span — the gateway must join via the header alone"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway_app), base_url="http://gateway"
    ) as client:
        response = await client.post(
            _GATEWAY_ROUTE, json={}, headers={"traceparent": _UPSTREAM_TRACEPARENT}
        )
        assert response.status_code == 200

    gateway_span = _by_name(list(span_exporter.get_finished_spans()), f"POST {_GATEWAY_ROUTE}")
    assert format(gateway_span.context.trace_id, "032x") == _UPSTREAM_TRACE_ID, (
        "gateway started a fresh trace instead of joining the upstream one"
    )
    assert gateway_span.parent is not None, "gateway span is a root — extraction regressed"
    assert format(gateway_span.parent.span_id, "016x") == _UPSTREAM_SPAN_ID


@pytest.mark.unit
async def test_gateway_outbound_injects_w3c_traceparent_to_provider(
    span_exporter: InMemorySpanExporter,
) -> None:
    """The gateway's outbound provider call carries a W3C ``traceparent``
    whose trace-id matches the active span — so the provider hop stays on
    the same trace as the upstream chat-send."""

    captured: dict[str, str] = {}

    async def provider(scope: dict, receive: object, send: object) -> None:  # type: ignore[type-arg]
        assert scope["type"] == "http"
        captured.update((k.decode(), v.decode()) for k, v in scope["headers"])
        await send(
            {  # type: ignore[operator]
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b"{}"})  # type: ignore[operator]

    transport = AsyncOpenTelemetryTransport(httpx.ASGITransport(app=provider))
    tracer = trace.get_tracer("lq-ai-gateway-test")
    async with httpx.AsyncClient(transport=transport, base_url="http://provider") as client:
        with tracer.start_as_current_span("inference.dispatch") as span:
            active_trace_id = span.get_span_context().trace_id
            await client.post(_PROVIDER_ROUTE, json={})

    traceparent = captured.get("traceparent")
    assert traceparent is not None, "no traceparent header on the outbound provider request"
    match = _TRACEPARENT_RE.match(traceparent)
    assert match is not None, f"malformed traceparent: {traceparent!r}"
    assert match.group(1) == format(active_trace_id, "032x"), (
        "outbound traceparent carries a different trace than the active span"
    )
