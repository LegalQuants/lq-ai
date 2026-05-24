"""Trace-context propagation regression tests for the api (M3-F1 / PRD §5.4).

The contract this file pins: a single chat-send must surface as **one
trace**, not three. The api receives the request (root span), calls the
gateway over httpx (client span), and the gateway must *join* that trace
(server span) rather than start a fresh root. If W3C ``traceparent``
propagation regresses — the api stops injecting, or the gateway stops
extracting — these tests fail.

Why an in-process harness instead of a live collector: the audit
(M3-F1) confirmed propagation works through OpenTelemetry's
auto-instrumentation under the **default global textmap propagator**
(W3C TraceContext + baggage). No code fix was needed; these tests are
the standing contract. We exercise the real injection routine —
:class:`AsyncOpenTelemetryTransport` shares
``opentelemetry.propagate.inject`` (and therefore the global propagator)
with the production global ``HTTPXClientInstrumentor().instrument()``
path — against an in-process FastAPI "gateway" instrumented for
extraction. An :class:`InMemorySpanExporter` stands in for the OTLP
collector so the assertion is deterministic and dependency-free.

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
async def test_chat_send_produces_single_trace_across_api_and_gateway(
    span_exporter: InMemorySpanExporter,
    gateway_app: FastAPI,
) -> None:
    """An api→gateway chat-send yields ONE trace ID across both services.

    The test models the wire boundary explicitly so it actually
    exercises *header*-based propagation, not in-process context
    leakage: with ``ASGITransport`` the gateway coroutine runs inside
    the caller's contextvars, so a naive single-call harness would
    "join" the trace even with propagation fully disabled. Instead we:

    1. **api half** — make the instrumented outbound call inside the api
       request span and capture the ``traceparent`` the api puts on the
       wire.
    2. **gateway half** — replay that header into the instrumented
       gateway from a *fresh* context (no active span, plain client), so
       the only way the gateway can join the trace is by extracting the
       header.

    If injection or extraction regresses, the gateway starts a fresh
    root and the two trace IDs diverge — this test fails.
    """

    tracer = trace.get_tracer("lq-ai-api-test")

    # --- api half: capture the traceparent the api emits on the wire ---
    wire: dict[str, str] = {}

    async def wire_tap(scope: dict, receive: object, send: object) -> None:  # type: ignore[type-arg]
        wire.update((k.decode(), v.decode()) for k, v in scope["headers"])
        await send({"type": "http.response.start", "status": 200, "headers": []})  # type: ignore[operator]
        await send({"type": "http.response.body", "body": b"ok"})  # type: ignore[operator]

    api_transport = AsyncOpenTelemetryTransport(httpx.ASGITransport(app=wire_tap))
    async with httpx.AsyncClient(transport=api_transport, base_url="http://gateway") as api_client:
        with tracer.start_as_current_span("POST /api/v1/chats/{chat_id}/messages") as api_span:
            api_trace_id = api_span.get_span_context().trace_id
            await api_client.post(_GATEWAY_ROUTE, json={})

    traceparent = wire.get("traceparent")
    assert traceparent is not None, "api emitted no traceparent on the outbound call"
    parent_match = _TRACEPARENT_RE.match(traceparent)
    assert parent_match is not None, f"malformed traceparent: {traceparent!r}"
    wire_parent_span_id = int(parent_match.group(2), 16)

    # --- gateway half: replay the wire header from a fresh context ---
    span_exporter.clear()
    assert trace.get_current_span().get_span_context().trace_id == 0, (
        "expected no active span when invoking the gateway half"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway_app), base_url="http://gateway"
    ) as gw_client:
        response = await gw_client.post(
            _GATEWAY_ROUTE, json={}, headers={"traceparent": traceparent}
        )
        assert response.status_code == 200

    gateway_span = _by_name(list(span_exporter.get_finished_spans()), f"POST {_GATEWAY_ROUTE}")

    # Headline contract: one trace across api + gateway, and the gateway
    # joined the api's span rather than starting a fresh root.
    assert gateway_span.context.trace_id == api_trace_id, (
        "gateway did not join the api trace — context was dropped on the hop"
    )
    assert gateway_span.parent is not None, "gateway span is a root — extraction regressed"
    assert gateway_span.parent.span_id == wire_parent_span_id


@pytest.mark.unit
async def test_api_outbound_injects_w3c_traceparent(
    span_exporter: InMemorySpanExporter,
) -> None:
    """The api's outbound httpx call carries a W3C ``traceparent`` whose
    trace-id matches the active span (the join key the gateway reads)."""

    captured: dict[str, str] = {}

    async def receiver(scope: dict, receive: object, send: object) -> None:  # type: ignore[type-arg]
        assert scope["type"] == "http"
        captured.update((k.decode(), v.decode()) for k, v in scope["headers"])
        await send(
            {  # type: ignore[operator]
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})  # type: ignore[operator]

    transport = AsyncOpenTelemetryTransport(httpx.ASGITransport(app=receiver))
    tracer = trace.get_tracer("lq-ai-api-test")
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        with tracer.start_as_current_span("POST /api/v1/chats/{chat_id}/messages") as span:
            active_trace_id = span.get_span_context().trace_id
            await client.post(_GATEWAY_ROUTE, json={})

    traceparent = captured.get("traceparent")
    assert traceparent is not None, "no traceparent header on the outbound request"
    match = _TRACEPARENT_RE.match(traceparent)
    assert match is not None, f"malformed traceparent: {traceparent!r}"
    assert match.group(1) == format(active_trace_id, "032x"), (
        "outbound traceparent carries a different trace than the active span"
    )
