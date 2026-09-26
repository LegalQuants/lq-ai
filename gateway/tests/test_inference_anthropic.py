"""Integration-style tests for the chat-completions surface against
the Anthropic adapter.

These tests run through the real FastAPI app (lifespan + router +
adapter) but mock the upstream Anthropic HTTP layer with ``respx``.
They are marked ``integration`` per CONTRIBUTING.md (they exercise
multiple components but require no external network).

Real-key end-to-end coverage is in :mod:`tests.test_anthropic_provider`
and is gated on ``@pytest.mark.provider``; that file is skipped in PRs
and runs nightly per the test policy.
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

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = REPO_ROOT / "gateway.yaml.example"


@asynccontextmanager
async def _run_lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with app.router.lifespan_context(app):
        yield


@pytest_asyncio.fixture
async def anthropic_app(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[FastAPI]:
    """A gateway ``app`` whose lifespan saw a valid ``ANTHROPIC_API_KEY``,
    so :class:`AnthropicAdapter` was instantiated and is in
    ``app.state.adapters``.

    ``respx`` mocking happens **inside** the test function, after this
    fixture yields, so the adapter's ``httpx.AsyncClient`` is intercepted
    on its first request.
    """

    monkeypatch.setenv("GATEWAY_CONFIG_PATH", str(EXAMPLE_CONFIG))
    # Same env vars conftest.example_env sets, plus the Anthropic key.
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
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-LQ-AI-Gateway-Key": "test-gateway-key"},
    ) as http_client:
        yield http_client


@pytest.mark.integration
@respx.mock
async def test_chat_completions_routes_smart_alias_to_anthropic(
    anthropic_client: AsyncClient,
) -> None:
    """The ``smart`` alias resolves to ``anthropic-prod / claude-opus-4-7``;
    the gateway translates and returns OpenAI-shaped output."""

    upstream = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_integration_001",
                "model": "claude-opus-4-7",
                "content": [{"type": "text", "text": "Hi from Anthropic stub."}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 9, "output_tokens": 6},
            },
        )
    )

    response = await anthropic_client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [
                {"role": "system", "content": "Be brief."},
                {"role": "user", "content": "ping"},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "Hi from Anthropic stub."
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"]["prompt_tokens"] == 9
    assert body["usage"]["completion_tokens"] == 6
    assert body["usage"]["total_tokens"] == 15
    assert body["routed_provider"] == "anthropic-prod"

    # Verify the upstream payload had the resolved model + system field.
    assert upstream.called
    sent = json.loads(upstream.calls[-1].request.content)
    assert sent["model"] == "claude-opus-4-7"
    assert sent["system"] == "Be brief."
    assert sent["messages"] == [{"role": "user", "content": "ping"}]


@pytest.mark.integration
@respx.mock
async def test_chat_completions_routes_native_anthropic_model_directly(
    anthropic_client: AsyncClient,
) -> None:
    """Requests using a provider-native model name (``claude-sonnet-4-6``)
    route directly to the matching Anthropic provider — this is the
    M1-IMPLEMENTATION-ORDER B3 verification path."""

    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_native",
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": "hello"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )
    )

    response = await anthropic_client.post(
        "/v1/chat/completions",
        json={
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "claude-sonnet-4-6"
    assert body["routed_provider"] == "anthropic-prod"


@pytest.mark.integration
@respx.mock
async def test_chat_completions_streams_sse_frames(
    anthropic_client: AsyncClient,
) -> None:
    """Streaming requests return ``text/event-stream`` with OpenAI chunks
    and a ``[DONE]`` sentinel."""

    sse_body = (
        "event: message_start\n"
        'data: {"type":"message_start","message":{"id":"msg_stream","model":"claude-opus-4-7","usage":{"input_tokens":3,"output_tokens":0}}}\n\n'
        "event: content_block_delta\n"
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hi"}}\n\n'
        "event: message_delta\n"
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":1}}\n\n'
        "event: message_stop\n"
        'data: {"type":"message_stop"}\n\n'
    )
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200, text=sse_body, headers={"content-type": "text/event-stream"}
        )
    )

    response = await anthropic_client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    # Parse the SSE body manually.
    text = response.text
    frames = [line for line in text.split("\n\n") if line.strip()]
    # Expect role chunk + content chunk + final chunk + [DONE].
    assert frames[-1].strip() == "data: [DONE]"
    data_frames = [f.removeprefix("data: ") for f in frames if f.startswith("data: ")]
    assert "[DONE]" in data_frames[-1]

    parsed_chunks = [json.loads(f) for f in data_frames if f.strip() != "[DONE]"]
    # First non-[DONE] chunk has the assistant role; one carries the
    # actual text; the last carries finish_reason.
    assert parsed_chunks[0]["choices"][0]["delta"].get("role") == "assistant"
    contents = [
        c["choices"][0]["delta"].get("content")
        for c in parsed_chunks
        if c["choices"][0]["delta"].get("content")
    ]
    assert "hi" in contents
    assert parsed_chunks[-1]["choices"][0]["finish_reason"] == "stop"
    # routed_provider is stamped on every chunk.
    for chunk in parsed_chunks:
        assert chunk["routed_provider"] == "anthropic-prod"


@pytest.mark.integration
@respx.mock
async def test_chat_completions_propagates_upstream_401_as_502(
    anthropic_client: AsyncClient,
) -> None:
    """Auth failures upstream become 502 ``unauthorized`` at the gateway.

    They do not become 401 — the gateway is its own auth domain; an
    upstream credential failure is a misconfiguration, not the caller's
    fault."""

    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            401,
            json={"type": "error", "error": {"type": "authentication_error", "message": "bad key"}},
        )
    )
    response = await anthropic_client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "unauthorized"
    # The fake key we set in the lifespan must not appear in the response.
    assert "sk-ant-test-fake" not in response.text


@pytest.mark.integration
@respx.mock
async def test_chat_completions_maps_upstream_429_to_429(
    anthropic_client: AsyncClient,
) -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            429,
            json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}},
        )
    )
    response = await anthropic_client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "rate_limit_exceeded"


@pytest.mark.integration
async def test_chat_completions_rejects_invalid_request(
    anthropic_client: AsyncClient,
) -> None:
    """Request body that fails Pydantic validation surfaces a 400 with a
    structured ``invalid_request`` envelope."""

    response = await anthropic_client.post(
        "/v1/chat/completions",
        json={"model": "smart"},  # missing messages
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_request"


@pytest.mark.integration
async def test_chat_completions_handles_malformed_json(
    anthropic_client: AsyncClient,
) -> None:
    response = await anthropic_client.post(
        "/v1/chat/completions",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


# --- D0: raw provider/model passthrough --------------------------------------


@pytest.mark.integration
@respx.mock
async def test_chat_completions_accepts_raw_provider_model_form(
    anthropic_client: AsyncClient,
) -> None:
    """``model: "anthropic-prod/claude-haiku-4-5"`` dispatches directly to
    the Anthropic adapter without going through the alias map (D0).

    This is the form the LQ.AI shell's model picker emits when the user
    selects a provider-native model from the Anthropic group.
    """

    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_d0_raw_passthrough",
                "model": "claude-haiku-4-5",
                "content": [{"type": "text", "text": "Hi from haiku."}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 4, "output_tokens": 5},
            },
        )
    )

    response = await anthropic_client.post(
        "/v1/chat/completions",
        json={
            "model": "anthropic-prod/claude-haiku-4-5",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    # Tier comes from the inference_tiers.defaults.anthropic = 4 in the example.
    assert body["routed_inference_tier"] == 4
    assert body["routed_provider"] == "anthropic-prod"


@pytest.mark.integration
async def test_chat_completions_rejects_unknown_provider_in_raw_form(
    anthropic_client: AsyncClient,
) -> None:
    """``unknown-provider/some-model`` -> 400 invalid_model with helpful message."""

    response = await anthropic_client.post(
        "/v1/chat/completions",
        json={
            "model": "definitely-not-a-provider/x",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_model"
    assert "definitely-not-a-provider" in body["error"]["message"]
