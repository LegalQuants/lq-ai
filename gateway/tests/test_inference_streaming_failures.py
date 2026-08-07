"""Streaming failures must reach the client as failures.

Regression coverage for the defect in issue #503: the streaming path
could finish a turn *successfully* while having produced nothing, so a
provider outage was indistinguishable from a thin answer. For a legal
tool that distinction matters — a lawyer cannot tell "the system broke"
from "the analysis is weak" if both render as an empty reply.

Two masking paths are covered here:

1. **Zero content.** ``_stream_openai_sse`` iterated an upstream that
   yielded nothing, exited the loop normally, and fell through to the
   success path: routing-log row with ``usage=None`` and a clean
   ``[DONE]``. No exception was ever raised, so nothing upstream of it
   could tell.
2. **Unexpected exceptions.** Only :class:`ProviderAdapterError` was
   caught. Anything else — a read timeout, a protocol error — escaped
   the generator *after* FastAPI had already sent ``200`` and the
   headers, leaving the client with a truncated stream, no error frame
   and no ``[DONE]``.

Plus the reasoning-budget case: ``finish_reason: length`` with no
visible text means the output budget was spent on thinking. That is a
failure the operator needs named, not an empty success.

Mocked with respx per CONTRIBUTING.md; no network. The happy-path test
at the end exists so a future change cannot make these fire on healthy
streams.
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

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


@asynccontextmanager
async def _run_lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with app.router.lifespan_context(app):
        yield


@pytest_asyncio.fixture
async def streaming_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    """Gateway app whose lifespan saw an Anthropic key, so the adapter exists."""

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
async def streaming_client(streaming_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=streaming_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


async def _stream(client: AsyncClient, **overrides: object) -> list[dict[str, object]]:
    """POST a streaming request and return the parsed non-``[DONE]`` frames."""

    payload: dict[str, object] = {
        "model": "smart",
        "messages": [{"role": "user", "content": "ping"}],
        "stream": True,
    }
    payload.update(overrides)
    response = await client.post("/v1/chat/completions", json=payload)
    frames = [f for f in response.text.split("\n\n") if f.strip().startswith("data: ")]
    parsed: list[dict[str, object]] = []
    for frame in frames:
        body = frame.removeprefix("data: ").strip()
        if body == "[DONE]":
            continue
        parsed.append(json.loads(body))
    return parsed


def _errors(frames: list[dict[str, object]]) -> list[dict[str, object]]:
    return [f["error"] for f in frames if isinstance(f.get("error"), dict)]  # type: ignore[misc]


@pytest.mark.integration
@respx.mock
async def test_stream_that_produces_no_content_is_an_error(
    streaming_client: AsyncClient,
) -> None:
    """An upstream that opens a stream and closes it without emitting any
    text must not read as a successful empty answer."""

    # A well-formed Anthropic stream that carries no content_block_delta:
    # message_start then straight to message_stop. This is what an upstream
    # that accepted the request and then produced nothing looks like.
    sse_body = (
        "event: message_start\n"
        'data: {"type":"message_start","message":{"id":"msg_empty",'
        '"model":"claude-opus-4-7","usage":{"input_tokens":5,"output_tokens":0}}}\n\n'
        "event: message_stop\n"
        'data: {"type":"message_stop"}\n\n'
    )
    respx.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(
            200, text=sse_body, headers={"content-type": "text/event-stream"}
        )
    )

    frames = await _stream(streaming_client)

    errors = _errors(frames)
    assert errors, (
        "a stream that produced no content must emit an error frame; "
        f"got frames without one: {frames!r}"
    )
    assert errors[0]["code"] == "provider_unavailable"

    # And it must not also claim success: no frame may carry content.
    for frame in frames:
        for choice in frame.get("choices", []) or []:  # type: ignore[union-attr]
            assert not (choice.get("delta") or {}).get("content")


@pytest.mark.integration
@respx.mock
async def test_unexpected_exception_mid_stream_yields_an_error_frame(
    streaming_client: AsyncClient,
) -> None:
    """A non-ProviderAdapterError raised while streaming must still reach the
    client as an error frame rather than killing the generator silently.

    Before the fix only ``ProviderAdapterError`` was caught, so a read
    timeout escaped after ``200`` had already gone out on the wire.
    """

    respx.post(ANTHROPIC_URL).mock(side_effect=httpx.ReadTimeout("upstream stalled"))

    frames = await _stream(streaming_client)

    errors = _errors(frames)
    assert errors, f"a mid-stream timeout must emit an error frame; got {frames!r}"
    assert errors[0]["code"] in {"provider_unavailable", "provider_timeout"}


@pytest.mark.integration
@respx.mock
async def test_budget_consumed_by_reasoning_is_an_error_not_an_empty_success(
    streaming_client: AsyncClient,
) -> None:
    """``finish_reason: length`` with no visible text means the output budget
    was spent on thinking. Naming that beats returning an empty string."""

    sse_body = (
        "event: message_start\n"
        'data: {"type":"message_start","message":{"id":"msg_len",'
        '"model":"claude-opus-4-7","usage":{"input_tokens":5,"output_tokens":0}}}\n\n'
        "event: message_delta\n"
        'data: {"type":"message_delta","delta":{"stop_reason":"max_tokens"},'
        '"usage":{"output_tokens":4096}}\n\n'
        "event: message_stop\n"
        'data: {"type":"message_stop"}\n\n'
    )
    respx.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(
            200, text=sse_body, headers={"content-type": "text/event-stream"}
        )
    )

    frames = await _stream(streaming_client)

    errors = _errors(frames)
    assert errors, f"an exhausted output budget must be named, not silent; got {frames!r}"
    message = str(errors[0].get("message", "")).lower()
    assert "token" in message or "budget" in message or "max_tokens" in message


@pytest.mark.integration
@respx.mock
async def test_healthy_stream_still_succeeds(streaming_client: AsyncClient) -> None:
    """Guard against over-firing: a normal stream must carry its content and
    no error frame. If this breaks, the checks above are too aggressive."""

    sse_body = (
        "event: message_start\n"
        'data: {"type":"message_start","message":{"id":"msg_ok",'
        '"model":"claude-opus-4-7","usage":{"input_tokens":3,"output_tokens":0}}}\n\n'
        "event: content_block_delta\n"
        'data: {"type":"content_block_delta","index":0,'
        '"delta":{"type":"text_delta","text":"hi"}}\n\n'
        "event: message_delta\n"
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},'
        '"usage":{"output_tokens":1}}\n\n'
        "event: message_stop\n"
        'data: {"type":"message_stop"}\n\n'
    )
    respx.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(
            200, text=sse_body, headers={"content-type": "text/event-stream"}
        )
    )

    frames = await _stream(streaming_client)

    assert not _errors(frames), f"a healthy stream must not error; got {frames!r}"
    contents = [
        (choice.get("delta") or {}).get("content")
        for frame in frames
        for choice in (frame.get("choices") or [])  # type: ignore[union-attr]
    ]
    assert "hi" in [c for c in contents if c]
