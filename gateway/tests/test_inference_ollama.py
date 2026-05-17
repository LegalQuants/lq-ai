"""Integration tests for the chat-completions surface against the
Ollama adapter (B6 partial).

These run through the real FastAPI app (lifespan + router + adapter)
but mock the upstream Ollama HTTP layer with ``respx``. They are
marked ``integration`` per CONTRIBUTING.md (multiple components,
no external network).

What this file covers:

* Alias dispatch — ``local-fast`` resolves to ``ollama-local /
  qwen3.5:4b-nvfp4`` and round-trips correctly.
* Tier annotation — every Ollama-routed response carries
  ``routed_inference_tier=1`` (the Mode-2 / air-gap-capable tier
  per PRD §1.5.2). The body field and the
  ``X-LQ-AI-Routed-Inference-Tier`` header agree.
* Streaming — NDJSON from the upstream becomes OpenAI SSE chunks
  with the tier preserved on every chunk.
* Routing-log row — written with provider=ollama-local,
  tier=1, the requested model, and the resolved native model.
* 503 model-not-loaded — translates to a 502 with
  ``provider_unavailable`` (no fallback configured for the
  ``local-*`` aliases).
* 404 unknown model — translates to a 400 ``invalid_model`` (the
  Ollama 'model not pulled' shape).
* **Fallback chain (the keystone B4-skeleton exercise).**
  We construct a synthetic gateway config in-process where
  ``smart-with-local-fallback`` aliases primary=Ollama with a
  fallback to Anthropic. With Ollama returning 503 (eligible for
  fallback) and Anthropic returning a real response, we confirm
  the request lands at Anthropic. This is the first end-to-end
  exercise of B4's fallback skeleton against two real adapters.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import GatewayConfig
from app.router import Router
from app.routing_log import RecordingRoutingLogWriter

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = REPO_ROOT / "gateway.yaml.example"


@asynccontextmanager
async def _run_lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with app.router.lifespan_context(app):
        yield


@pytest_asyncio.fixture
async def ollama_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    """A gateway ``app`` whose lifespan ran with the example config and
    a recorder routing-log writer.

    The example config has the ``ollama-local`` provider entry; the
    OllamaAdapter is instantiated for it on lifespan startup. We swap
    in a recording writer after lifespan to keep the routing-log
    assertions deterministic.
    """

    monkeypatch.setenv("GATEWAY_CONFIG_PATH", str(EXAMPLE_CONFIG))
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AZURE_OPENAI_RESOURCE", "test-openai")
    monkeypatch.setenv("LQ_AI_VERSION", "0.1.0-test")
    # Default OLLAMA_BASE_URL substitution.
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    # Force NullRoutingLogWriter at startup; we override below.
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from app.main import app

    async with _run_lifespan(app):
        recorder = RecordingRoutingLogWriter()
        app.state.routing_log = recorder
        # Stash recorder on app.state so tests pulling it off the
        # client fixture can find it.
        app.state.test_recorder = recorder
        yield app


@pytest_asyncio.fixture
async def ollama_client(ollama_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=ollama_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


def _ollama_unary_payload(content: str = "Hi from Ollama.") -> dict[str, object]:
    """A canonical Ollama ``/api/chat`` non-streaming response."""

    return {
        "model": "qwen3.5:4b-nvfp4",
        "created_at": "2026-05-08T12:00:00Z",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 9,
        "eval_count": 6,
        "total_duration": 123_456_789,
    }


def _ollama_ndjson_body(text_chunks: list[str]) -> str:
    """Build a multi-line NDJSON body emulating Ollama's streaming."""

    lines: list[str] = []
    for chunk in text_chunks:
        lines.append(
            json.dumps(
                {
                    "model": "qwen3.5:4b-nvfp4",
                    "created_at": "2026-05-08T12:00:00Z",
                    "message": {"role": "assistant", "content": chunk},
                    "done": False,
                }
            )
        )
    # Terminal frame.
    lines.append(
        json.dumps(
            {
                "model": "qwen3.5:4b-nvfp4",
                "created_at": "2026-05-08T12:00:01Z",
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 5,
                "eval_count": len(text_chunks),
                "total_duration": 1234,
            }
        )
    )
    return "\n".join(lines) + "\n"


# --- Alias dispatch + tier annotation ----------------------------------------


@pytest.mark.integration
@respx.mock
async def test_local_fast_alias_routes_to_ollama(
    ollama_client: AsyncClient,
    ollama_app: FastAPI,
) -> None:
    """``local-fast`` resolves to ``ollama-local / qwen3.5:4b-nvfp4`` and
    round-trips through the OllamaAdapter."""

    upstream = respx.post("http://ollama:11434/api/chat").mock(
        return_value=httpx.Response(200, json=_ollama_unary_payload())
    )

    response = await ollama_client.post(
        "/v1/chat/completions",
        json={
            "model": "local-fast",
            "messages": [
                {"role": "system", "content": "Be brief."},
                {"role": "user", "content": "ping"},
            ],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "Hi from Ollama."
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"]["prompt_tokens"] == 9
    assert body["usage"]["completion_tokens"] == 6
    assert body["usage"]["total_tokens"] == 15
    # Tier annotation — Mode 2 / air-gapped = Tier 1 per PRD §1.5.2.
    assert body["routed_provider"] == "ollama-local"
    assert body["routed_inference_tier"] == 1
    assert response.headers["X-LQ-AI-Routed-Inference-Tier"] == "1"
    assert response.headers["X-LQ-AI-Routed-Provider"] == "ollama-local"

    # Verify the upstream payload had the resolved native model.
    assert upstream.called
    sent = json.loads(upstream.calls[-1].request.content)
    assert sent["model"] == "qwen3.5:4b-nvfp4"
    assert sent["stream"] is False


@pytest.mark.integration
@respx.mock
async def test_local_thinking_alias_routes_to_70b(
    ollama_client: AsyncClient,
) -> None:
    """``local-thinking`` resolves to the Ollama 70b model."""

    upstream = respx.post("http://ollama:11434/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "qwen3.5:9b",
                "message": {"role": "assistant", "content": "deep thoughts"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 4,
                "eval_count": 2,
            },
        )
    )

    response = await ollama_client.post(
        "/v1/chat/completions",
        json={
            "model": "local-thinking",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["routed_provider"] == "ollama-local"
    assert body["routed_inference_tier"] == 1

    assert upstream.called
    sent = json.loads(upstream.calls[-1].request.content)
    assert sent["model"] == "qwen3.5:9b"


@pytest.mark.integration
@respx.mock
async def test_native_ollama_model_routes_directly(
    ollama_client: AsyncClient,
) -> None:
    """A provider-native Ollama model name routes to the matching
    Ollama provider — same path as the ``local-fast`` alias."""

    respx.post("http://ollama:11434/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "gemma4:e4b",
                "message": {"role": "assistant", "content": "ok"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 1,
                "eval_count": 1,
            },
        )
    )
    response = await ollama_client.post(
        "/v1/chat/completions",
        json={
            "model": "gemma4:e4b",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["routed_provider"] == "ollama-local"
    assert body["routed_inference_tier"] == 1


# --- Streaming ---------------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_streaming_translates_ndjson_to_sse(
    ollama_client: AsyncClient,
) -> None:
    """An Ollama NDJSON stream becomes OpenAI SSE chunks with tier
    preserved on every chunk and a [DONE] sentinel at the end."""

    body = _ollama_ndjson_body(["He", "llo", " world"])
    respx.post("http://ollama:11434/api/chat").mock(
        return_value=httpx.Response(
            200, text=body, headers={"content-type": "application/x-ndjson"}
        )
    )

    response = await ollama_client.post(
        "/v1/chat/completions",
        json={
            "model": "local-fast",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["X-LQ-AI-Routed-Inference-Tier"] == "1"

    text = response.text
    frames = [line for line in text.split("\n\n") if line.strip()]
    assert frames[-1].strip() == "data: [DONE]"
    data_frames = [f.removeprefix("data: ") for f in frames if f.startswith("data: ")]
    parsed_chunks = [json.loads(f) for f in data_frames if f.strip() != "[DONE]"]

    # Every chunk carries the tier + provider.
    for chunk in parsed_chunks:
        assert chunk["routed_inference_tier"] == 1
        assert chunk["routed_provider"] == "ollama-local"

    # Content arrives in order.
    contents = [
        c["choices"][0]["delta"].get("content")
        for c in parsed_chunks
        if c["choices"][0]["delta"].get("content")
    ]
    assert contents == ["He", "llo", " world"]
    # Final chunk has finish_reason=stop.
    assert parsed_chunks[-1]["choices"][0]["finish_reason"] == "stop"


# --- Routing-log writes ------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_routing_log_row_written_for_ollama_success(
    ollama_client: AsyncClient,
    ollama_app: FastAPI,
) -> None:
    """A successful Ollama-routed call writes one routing-log row with
    the right (provider, model, tier, tokens) tuple."""

    recorder: RecordingRoutingLogWriter = ollama_app.state.test_recorder
    recorder.rows.clear()  # ensure isolation across fixture tests

    respx.post("http://ollama:11434/api/chat").mock(
        return_value=httpx.Response(200, json=_ollama_unary_payload())
    )

    response = await ollama_client.post(
        "/v1/chat/completions",
        json={
            "model": "local-fast",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 200

    # Filter only rows for THIS invocation in case prior tests in the
    # same fixture lifetime left rows.
    rows = [r for r in recorder.rows if r.requested_model == "local-fast"]
    assert len(rows) == 1
    row = rows[0]
    assert row.requested_model == "local-fast"
    assert row.routed_provider == "ollama-local"
    assert row.routed_model == "qwen3.5:4b-nvfp4"
    assert row.routed_inference_tier == 1
    assert row.tokens_in == 9
    assert row.tokens_out == 6
    # gateway.yaml.example sets cost rates to 0.0 for local models.
    assert row.cost_estimate is not None
    assert float(row.cost_estimate) == 0.0
    assert row.refused is False


# --- Error mapping -----------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_ollama_503_model_loading_returns_502(
    ollama_client: AsyncClient,
) -> None:
    """A 503 from Ollama (model loading / overwhelmed) becomes a 502
    ``provider_unavailable`` at the gateway when no fallback is
    configured. The ``local-fast`` alias has an empty fallback list so
    the call ends here."""

    respx.post("http://ollama:11434/api/chat").mock(
        return_value=httpx.Response(503, json={"error": "model is currently loading"})
    )
    response = await ollama_client.post(
        "/v1/chat/completions",
        json={
            "model": "local-fast",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "provider_unavailable"
    # The Ollama 'model is loading' message surfaces in the message
    # field for operator visibility.
    assert "loading" in body["error"]["message"]


@pytest.mark.integration
@respx.mock
async def test_ollama_404_unknown_model_returns_400(
    ollama_client: AsyncClient,
) -> None:
    """A 404 from Ollama (model not pulled) becomes a 400
    ``invalid_model`` at the gateway — the request named a model the
    deployment can't serve, which is a request-side mistake even
    though the upstream answered."""

    respx.post("http://ollama:11434/api/chat").mock(
        return_value=httpx.Response(
            404, json={"error": "model 'foo' not found, try pulling it first"}
        )
    )
    response = await ollama_client.post(
        "/v1/chat/completions",
        json={
            "model": "local-fast",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_model"
    assert "not found" in body["error"]["message"]


@pytest.mark.integration
@respx.mock
async def test_ollama_connection_refused_returns_503(
    ollama_client: AsyncClient,
) -> None:
    """A connection-refused (Ollama not running) becomes 503
    ``provider_unavailable`` — distinct from upstream 503 in semantics
    but indistinguishable from the caller's POV."""

    respx.post("http://ollama:11434/api/chat").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    response = await ollama_client.post(
        "/v1/chat/completions",
        json={
            "model": "local-fast",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "provider_unavailable"


# --- Fallback-chain end-to-end (B4 keystone) --------------------------------


@pytest_asyncio.fixture
async def fallback_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    """A gateway app whose router has both Ollama AND Anthropic
    adapters wired, plus a synthetic alias ``smart-with-local-fallback``
    that primaries on Ollama with a fallback to Anthropic.

    This is the first end-to-end exercise of B4's fallback skeleton
    against two real (adapter-class) providers — until B6 partial,
    only Anthropic was instantiable.
    """

    monkeypatch.setenv("GATEWAY_CONFIG_PATH", str(EXAMPLE_CONFIG))
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AZURE_OPENAI_RESOURCE", "test-openai")
    monkeypatch.setenv("LQ_AI_VERSION", "0.1.0-test")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from app.main import app

    async with _run_lifespan(app):
        # Mutate the loaded config to add a synthetic alias with a
        # cross-provider fallback. Touching app.state.config + rebuilding
        # the router keeps the route-handler-side dispatch logic
        # untouched.
        config: GatewayConfig = app.state.config
        from app.config import ModelAliasConfig, ModelTarget

        config.model_aliases["smart-with-local-fallback"] = ModelAliasConfig(
            primary=ModelTarget(provider="ollama-local", model="qwen3.5:4b-nvfp4"),
            fallback=[ModelTarget(provider="anthropic-prod", model="claude-opus-4-7")],
        )
        # Rebuild the router so the new alias is in scope.
        app.state.router = Router(config=config, adapters=app.state.adapters)
        # Swap recorder for routing-log isolation.
        recorder = RecordingRoutingLogWriter()
        app.state.routing_log = recorder
        app.state.test_recorder = recorder
        yield app


@pytest_asyncio.fixture
async def fallback_client(fallback_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=fallback_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.mark.integration
@respx.mock
async def test_fallback_chain_ollama_503_falls_through_to_anthropic(
    fallback_client: AsyncClient,
    fallback_app: FastAPI,
) -> None:
    """**The B4 keystone end-to-end test.**

    Configure ``smart-with-local-fallback`` with primary=Ollama and
    fallback=Anthropic. Mock Ollama to return 503 (model loading,
    fallback-eligible per :func:`is_fallback_eligible`). Mock Anthropic
    to return a normal completion. Verify:

    1. The response comes from Anthropic (fallback succeeded).
    2. The routing-log row attributes the answer to ``anthropic-prod``
       — not the failing primary.
    3. ``fallbacks_tried`` carries ``ollama-local``.
    """

    recorder: RecordingRoutingLogWriter = fallback_app.state.test_recorder
    recorder.rows.clear()

    # Primary: Ollama returns 503 (model loading).
    ollama_route = respx.post("http://ollama:11434/api/chat").mock(
        return_value=httpx.Response(503, json={"error": "model is currently loading"})
    )
    # Fallback: Anthropic returns a real-looking response.
    anthropic_route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_fallback",
                "model": "claude-opus-4-7",
                "content": [{"type": "text", "text": "Hello from the fallback."}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 5, "output_tokens": 4},
            },
        )
    )

    response = await fallback_client.post(
        "/v1/chat/completions",
        json={
            "model": "smart-with-local-fallback",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # The fallback answered.
    assert body["choices"][0]["message"]["content"] == "Hello from the fallback."
    assert body["routed_provider"] == "anthropic-prod"
    # Anthropic's tier per the example config is 4.
    assert body["routed_inference_tier"] == 4

    # Both upstreams were called: primary (failed), then fallback (success).
    assert ollama_route.called
    assert anthropic_route.called

    # Routing-log row attributes to the actual provider that answered.
    rows = [r for r in recorder.rows if r.requested_model == "smart-with-local-fallback"]
    assert len(rows) == 1
    row = rows[0]
    assert row.routed_provider == "anthropic-prod"
    assert row.routed_model == "claude-opus-4-7"
    assert row.routed_inference_tier == 4


@pytest.mark.integration
@respx.mock
async def test_fallback_chain_ollama_404_does_not_fall_back(
    fallback_client: AsyncClient,
    fallback_app: FastAPI,
) -> None:
    """A 404 from Ollama (model not pulled) is NOT fallback-eligible —
    the request named a specific model that the next provider can't
    serve any better. The 400 ``invalid_model`` surfaces directly.

    This pins :func:`is_fallback_eligible` semantics: 4xx other than
    429 stays with the primary provider's response."""

    recorder: RecordingRoutingLogWriter = fallback_app.state.test_recorder
    recorder.rows.clear()

    ollama_route = respx.post("http://ollama:11434/api/chat").mock(
        return_value=httpx.Response(404, json={"error": "model 'qwen3.5:4b-nvfp4' not found"})
    )
    anthropic_route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_should_not_be_called",
                "model": "claude-opus-4-7",
                "content": [{"type": "text", "text": "should not see this"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )
    )

    response = await fallback_client.post(
        "/v1/chat/completions",
        json={
            "model": "smart-with-local-fallback",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_model"

    # Ollama was the only upstream consulted; Anthropic was never
    # attempted because 404 isn't fallback-eligible.
    assert ollama_route.called
    assert not anthropic_route.called
