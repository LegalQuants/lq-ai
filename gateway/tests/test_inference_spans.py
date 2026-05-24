"""TDD tests for the ``inference.dispatch`` handler-level span (M3-F2).

These tests drive the real gateway FastAPI app (lifespan + router +
Anthropic adapter) through ``respx``-mocked upstream HTTP, then inspect
the in-memory span exporter to assert that:

* a successful non-streaming call emits an ``inference.dispatch`` span
  with the correct provider / tier / outcome / tokens / cost attributes.
* a failed call (upstream 401 → RoutedProviderError) emits an
  ``inference.dispatch`` span with the appropriate error-outcome label.

Streaming path is out of scope (deferred per task spec).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = REPO_ROOT / "gateway.yaml.example"


# ---------------------------------------------------------------------------
# OTel span exporter — module-scoped so one TracerProvider is shared across
# all tests in this module (the global provider can only be set once per
# process).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def span_exporter() -> InMemorySpanExporter:
    """Install an in-memory exporter on the (possibly already set) SDK provider."""

    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


# ---------------------------------------------------------------------------
# Gateway app fixture — mirrors test_inference_anthropic.py exactly.
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _run_lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with app.router.lifespan_context(app):
        yield


@pytest_asyncio.fixture
async def anthropic_app(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[FastAPI]:
    """Gateway app lifespan started with a fake Anthropic key so the adapter
    is instantiated.  respx mocking happens inside individual tests."""

    monkeypatch.setenv("GATEWAY_CONFIG_PATH", str(EXAMPLE_CONFIG))
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AZURE_OPENAI_RESOURCE", "test-openai")
    monkeypatch.setenv("LQ_AI_VERSION", "0.1.0-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake")

    from app.main import app

    async with _run_lifespan(app):
        yield app


@pytest_asyncio.fixture
async def anthropic_client(anthropic_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=anthropic_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_inference_dispatch_span_success(
    span_exporter: InMemorySpanExporter,
    anthropic_client: AsyncClient,
) -> None:
    """A successful non-streaming call emits an ``inference.dispatch`` span
    with provider / tier / outcome / tokens / cost populated."""

    span_exporter.clear()

    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_span_test_001",
                "model": "claude-opus-4-7",
                "content": [{"type": "text", "text": "Span test response."}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )
    )

    response = await anthropic_client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "ping"}],
        },
    )

    assert response.status_code == 200

    finished = span_exporter.get_finished_spans()
    dispatch_spans = [s for s in finished if s.name == "inference.dispatch"]
    assert len(dispatch_spans) == 1, (
        f"Expected exactly one 'inference.dispatch' span; got {len(dispatch_spans)}. "
        f"All span names: {[s.name for s in finished]}"
    )
    (s,) = dispatch_spans

    assert s.attributes["inference.outcome"] == "success"
    assert s.attributes["inference.provider"]  # non-empty string
    assert isinstance(s.attributes["inference.tier"], int)
    assert "inference.tokens_in" in s.attributes
    assert "inference.cost_usd" in s.attributes
    # Sanity-check the values make sense.
    assert s.attributes["inference.tokens_in"] == 10
    assert s.attributes["inference.tokens_out"] == 5
    assert s.attributes["inference.model"]  # non-empty string


@pytest.mark.integration
@respx.mock
async def test_inference_dispatch_span_provider_error(
    span_exporter: InMemorySpanExporter,
    anthropic_client: AsyncClient,
) -> None:
    """An upstream 401 flows through RoutedProviderError; the span should
    carry an error-outcome label (not 'success')."""

    span_exporter.clear()

    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            401,
            json={
                "type": "error",
                "error": {"type": "authentication_error", "message": "bad key"},
            },
        )
    )

    response = await anthropic_client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    # The gateway maps the upstream 401 → 502.
    assert response.status_code == 502

    finished = span_exporter.get_finished_spans()
    dispatch_spans = [s for s in finished if s.name == "inference.dispatch"]
    assert len(dispatch_spans) == 1, (
        f"Expected one 'inference.dispatch' span; got {len(dispatch_spans)}. "
        f"All span names: {[s.name for s in finished]}"
    )
    (s,) = dispatch_spans

    # The outcome must NOT be "success" — it should be one of the
    # _outcome_label_from_error labels ("provider_error", "network_error", …).
    assert s.attributes.get("inference.outcome") != "success"
    assert s.attributes.get("inference.provider")  # still populated from wrapped.target
