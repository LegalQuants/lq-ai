"""Keyless regressions for explicit Bedrock protocol routing and privacy."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet

from app.config import ProviderConfig
from app.providers.base import (
    ProviderAuthError,
    ProviderEmptyResponseError,
    ProviderHTTPError,
    ProviderTimeoutError,
    ProviderUnsupportedError,
)
from app.providers.bedrock import BedrockAdapter
from app.providers.bedrock_responses import from_responses_response, to_responses_request
from app.providers.openai_schema import (
    ChatCompletionRequest,
    ChatCompletionResponse,
)

AWS = "https://bedrock-runtime.us-east-1.amazonaws.com"
KEY = "synthetic-bedrock-key-not-a-credential"
FUNCTION = {
    "type": "function",
    "function": {"name": "lookup", "parameters": {"type": "object", "properties": {}}},
}


def provider(protocol: str, **overrides: Any) -> ProviderConfig:
    return ProviderConfig.model_validate(
        {
            "name": "aws-test",
            "type": "bedrock",
            "tier": 3,
            "bedrock_protocol": protocol,
            "api_key_env": "BEDROCK_TEST_KEY",
            "base_url": AWS + ("/anthropic" if protocol == "messages" else "/openai/v1"),
            **overrides,
        }
    )


def request(**overrides: Any) -> ChatCompletionRequest:
    return ChatCompletionRequest.model_validate(
        {"model": "alias", "messages": [{"role": "user", "content": "hello"}], **overrides}
    )


def response_payload(output: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": "resp-test",
        "model": "native-model",
        "created_at": 1,
        "status": "completed",
        "output": output
        if output is not None
        else [{"type": "message", "content": [{"type": "output_text", "text": "hello"}]}],
        "usage": {"input_tokens": 3, "output_tokens": 2},
    }


def sse(events: list[dict[str, Any]]) -> bytes:
    return "".join(f"event: {x['type']}\ndata: {json.dumps(x)}\n\n" for x in events).encode()


@pytest.mark.parametrize(
    "url",
    [
        "http://bedrock-runtime.us-east-1.amazonaws.com/openai/v1",
        "https://attacker.example/openai/v1",
        "https://bedrock-runtime.us-east-1.amazonaws.com.attacker.example/openai/v1",
        "https://secret@bedrock-runtime.us-east-1.amazonaws.com/openai/v1",
        AWS + "/openai/v1?token=bad",
        AWS + "/openai/v1#fragment",
        AWS + "/v1",
        "https://bedrock-runtime.us-east-1.amazonaws.com:444/openai/v1",
    ],
)
def test_refuses_unselected_origins_and_paths(url: str) -> None:
    with pytest.raises(ValueError):
        provider("responses", base_url=url)


@pytest.mark.parametrize("protocol", ["messages", "chat_completions", "responses"])
def test_accepts_explicit_protocols(protocol: str) -> None:
    assert provider(protocol).bedrock_protocol == protocol


def test_mantle_path_is_explicit() -> None:
    url = "https://bedrock-mantle.us-east-1.api.aws/openai/v1"
    assert provider("responses", bedrock_endpoint="mantle", base_url=url).base_url == url
    with pytest.raises(ValueError):
        provider("responses", base_url=url)


@pytest.mark.parametrize("protocol", ["messages", "chat_completions", "responses"])
def test_missing_key_source_does_not_use_ambient_credentials(protocol: str) -> None:
    with pytest.raises(ValueError, match="explicit api_key_env"):
        BedrockAdapter.from_config(
            provider(protocol, api_key_env=None),
            env={"AWS_BEARER_TOKEN_BEDROCK": KEY},
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("store", True),
        ("background", True),
        ("previous_response_id", "resp-old"),
        ("conversation", "remote-state"),
    ],
)
def test_refuses_remote_state(field: str, value: object) -> None:
    with pytest.raises(ProviderUnsupportedError):
        to_responses_request(request(**{field: value}), model="native", stream=False)


def test_responses_preserves_complete_function_history_and_strips_extras() -> None:
    body = to_responses_request(
        request(
            messages=[
                {"role": "system", "content": "system"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "lookup", "arguments": '{"x":1}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call-1", "content": "result"},
            ],
            tools=[FUNCTION],
            previous_response_id=None,
            injected="do-not-forward",
        ),
        model="native",
        stream=False,
    )
    assert body["store"] is False and body["background"] is False
    assert "injected" not in body and "previous_response_id" not in body
    assert body["input"][1] == {
        "type": "function_call",
        "call_id": "call-1",
        "name": "lookup",
        "arguments": '{"x":1}',
    }
    assert body["input"][2] == {
        "type": "function_call_output",
        "call_id": "call-1",
        "output": "result",
    }
    assert body["tools"][0]["type"] == "function"


@pytest.mark.parametrize("tool", [{"type": "web_search"}, {"type": "mcp", "server_url": "bad"}])
def test_refuses_server_side_tools(tool: dict[str, Any]) -> None:
    with pytest.raises(ProviderUnsupportedError):
        to_responses_request(request(tools=[tool]), model="native", stream=False)


@pytest.mark.parametrize("status", ["failed", "cancelled", "queued", "in_progress"])
def test_failed_responses_are_not_success(status: str) -> None:
    with pytest.raises(ProviderHTTPError):
        from_responses_response({**response_payload(), "status": status}, model="native")


def test_incomplete_and_unknown_output_are_explicit() -> None:
    result = from_responses_response(
        {
            **response_payload(),
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
        },
        model="native",
    )
    assert result.choices[0].finish_reason == "length"
    with pytest.raises(ProviderUnsupportedError):
        from_responses_response(response_payload([{"type": "web_search_call"}]), model="native")


@pytest.mark.parametrize(
    "updates",
    [
        {"id": None},
        {"created_at": float("inf")},
        {"usage": {"input_tokens": True, "output_tokens": 2}},
        {"output": [{"type": "message", "content": [None]}]},
        {
            "output": [
                {"type": "function_call", "call_id": "call-1", "name": "lookup", "arguments": "[]"}
            ]
        },
    ],
)
def test_malformed_responses_do_not_report_success(updates: dict[str, Any]) -> None:
    with pytest.raises(ProviderHTTPError):
        from_responses_response({**response_payload(), **updates}, model="native")


@pytest.mark.parametrize(
    "protocol,path,payload",
    [
        (
            "messages",
            "/anthropic/v1/messages",
            {
                "id": "msg-1",
                "model": "native",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "hello"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 3, "output_tokens": 2},
            },
        ),
        (
            "chat_completions",
            "/openai/v1/chat/completions",
            {
                "id": "chat-1",
                "model": "native",
                "created": 1,
                "choices": [
                    {"message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        ),
        ("responses", "/openai/v1/responses", response_payload()),
    ],
)
async def test_unary_uses_configured_route_and_auth(
    protocol: str, path: str, payload: dict[str, Any]
) -> None:
    sent: list[httpx.Request] = []

    async def handle(req: httpx.Request) -> httpx.Response:
        sent.append(req)
        assert req.url.path == path
        return httpx.Response(200, json=payload)

    cfg = provider(protocol)
    async with httpx.AsyncClient(
        base_url=cfg.base_url, transport=httpx.MockTransport(handle)
    ) as client:
        adapter = BedrockAdapter.from_config(cfg, env={"BEDROCK_TEST_KEY": KEY}, client=client)
        assert not (await adapter.health_check()).reachable
        result = await adapter.chat_completion(
            request(injected="secret-extra"), model="native", stream=False
        )
        assert isinstance(result, ChatCompletionResponse)
        assert result.choices[0].message.content == "hello"
        assert result.usage.total_tokens == 5
        assert (await adapter.health_check()).reachable
    assert sent[0].headers.get("x-api-key" if protocol == "messages" else "authorization") == (
        KEY if protocol == "messages" else "Bearer " + KEY
    )
    assert "injected" not in json.loads(sent[0].content)


@pytest.mark.parametrize("protocol", ["messages", "chat_completions", "responses"])
@pytest.mark.parametrize("stream", [False, True])
async def test_timeout_classification_is_preserved(protocol: str, stream: bool) -> None:
    async def handle(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(KEY, request=req)

    cfg = provider(protocol)
    async with httpx.AsyncClient(
        base_url=cfg.base_url, transport=httpx.MockTransport(handle)
    ) as client:
        adapter = BedrockAdapter.from_config(cfg, env={"BEDROCK_TEST_KEY": KEY}, client=client)
        with pytest.raises(ProviderTimeoutError) as error:
            result = await adapter.chat_completion(request(), model="native", stream=stream)
            if not isinstance(result, ChatCompletionResponse):
                _ = [x async for x in result]
        assert KEY not in str(error.value.to_envelope())


@pytest.mark.parametrize("protocol", ["messages", "chat_completions", "responses"])
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_error_bodies_never_escape(protocol: str, status: int) -> None:
    async def handle(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={"error": {"message": KEY}},
            headers={"location": "https://attacker.example"},
        )

    cfg = provider(protocol)
    async with httpx.AsyncClient(
        base_url=cfg.base_url, transport=httpx.MockTransport(handle)
    ) as client:
        adapter = BedrockAdapter.from_config(cfg, env={"BEDROCK_TEST_KEY": KEY}, client=client)
        with pytest.raises((ProviderAuthError, ProviderHTTPError)) as error:
            await adapter.chat_completion(request(), model="native", stream=False)
        assert KEY not in str(error.value.to_envelope())


async def test_streaming_arguments_and_tool_continuation() -> None:
    call = {
        "type": "function_call",
        "id": "fc-1",
        "call_id": "call-1",
        "name": "lookup",
        "arguments": '{"x":1}',
    }
    events = [
        {"type": "response.created", "response": {"id": "resp-test"}},
        {
            "type": "response.output_item.added",
            "output_index": 1,
            "item": {**call, "arguments": ""},
        },
        {"type": "response.function_call_arguments.delta", "output_index": 1, "delta": '{"x":'},
        {"type": "response.function_call_arguments.delta", "output_index": 1, "delta": "1}"},
        {"type": "response.completed", "response": response_payload([call])},
    ]

    async def handle(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse(events))

    cfg = provider("responses")
    async with httpx.AsyncClient(
        base_url=cfg.base_url, transport=httpx.MockTransport(handle)
    ) as client:
        adapter = BedrockAdapter.from_config(cfg, env={"BEDROCK_TEST_KEY": KEY}, client=client)
        result = await adapter.chat_completion(
            request(tools=[FUNCTION]), model="native", stream=True
        )
        assert not isinstance(result, ChatCompletionResponse)
        chunks = [x async for x in result]
    deltas = [t for x in chunks for t in (x.choices[0].delta.tool_calls or [])]
    assert deltas[0]["id"] == "call-1"
    assert "".join(t["function"]["arguments"] for t in deltas) == '{"x":1}'
    assert chunks[-1].choices[0].finish_reason == "tool_calls"
    assert chunks[-1].usage is not None and chunks[-1].usage.total_tokens == 5


async def test_truncated_stream_fails() -> None:
    events = [
        {"type": "response.created", "response": {"id": "resp-test"}},
        {"type": "response.output_text.delta", "delta": "partial"},
    ]

    async def handle(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse(events))

    cfg = provider("responses")
    async with httpx.AsyncClient(
        base_url=cfg.base_url, transport=httpx.MockTransport(handle)
    ) as client:
        adapter = BedrockAdapter.from_config(cfg, env={"BEDROCK_TEST_KEY": KEY}, client=client)
        result = await adapter.chat_completion(request(), model="native", stream=True)
        assert isinstance(result, AsyncIterator)
        chunks = []
        with pytest.raises(ProviderHTTPError):
            async for chunk in result:
                chunks.append(chunk)
        assert any(x.choices[0].delta.content == "partial" for x in chunks)
        assert not any(x.choices[0].finish_reason for x in chunks)


@pytest.mark.parametrize("protocol", ["messages", "chat_completions"])
@pytest.mark.parametrize("failure", ["truncated", "error"])
async def test_delegated_stream_failure_is_not_a_clean_success(protocol: str, failure: str) -> None:
    if protocol == "messages":
        events = [
            {"type": "message_start", "message": {"id": "msg-1", "model": "native"}},
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "partial"},
            },
        ]
        if failure == "error":
            events.extend(
                [
                    {"type": "error", "error": {"message": KEY}},
                    {"type": "message_stop"},
                ]
            )
        content = sse(events)
    else:
        common = {"id": "chat-1", "created": 1, "model": "native"}
        frames = [{**common, "choices": [{"index": 0, "delta": {"content": "partial"}}]}]
        if failure == "error":
            frames.extend(
                [
                    {**common, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                    {"error": {"message": KEY}},
                ]
            )
        content = "".join(f"data: {json.dumps(frame)}\n\n" for frame in frames).encode()
        if failure == "error":
            content += b"data: [DONE]\n\n"

    async def handle(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    cfg = provider(protocol)
    async with httpx.AsyncClient(
        base_url=cfg.base_url, transport=httpx.MockTransport(handle)
    ) as client:
        adapter = BedrockAdapter.from_config(cfg, env={"BEDROCK_TEST_KEY": KEY}, client=client)
        result = await adapter.chat_completion(request(), model="native", stream=True)
        assert isinstance(result, AsyncIterator)
        with pytest.raises(ProviderHTTPError) as error:
            _ = [chunk async for chunk in result]
        assert KEY not in str(error.value.to_envelope())
        assert not (await adapter.health_check()).reachable


@pytest.mark.parametrize("protocol", ["messages", "chat_completions"])
@pytest.mark.parametrize("stream", [False, True])
async def test_malformed_delegated_payload_is_sanitized(protocol: str, stream: bool) -> None:
    async def handle(req: httpx.Request) -> httpx.Response:
        if stream:
            return httpx.Response(200, content=f"data: {json.dumps([KEY])}\n\n".encode())
        return httpx.Response(200, json=[KEY])

    cfg = provider(protocol)
    async with httpx.AsyncClient(
        base_url=cfg.base_url, transport=httpx.MockTransport(handle)
    ) as client:
        adapter = BedrockAdapter.from_config(cfg, env={"BEDROCK_TEST_KEY": KEY}, client=client)
        with pytest.raises(ProviderHTTPError) as error:
            result = await adapter.chat_completion(request(), model="native", stream=stream)
            if isinstance(result, AsyncIterator):
                _ = [chunk async for chunk in result]
        assert KEY not in str(error.value.to_envelope())


@pytest.mark.parametrize("protocol", ["messages", "chat_completions"])
async def test_empty_delegated_stream_is_not_healthy(protocol: str) -> None:
    if protocol == "messages":
        content = sse(
            [
                {"type": "message_start", "message": {"id": "msg-1", "model": "native"}},
                {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
                {"type": "message_stop"},
            ]
        )
    else:
        payload = {
            "id": "chat-1",
            "created": 1,
            "model": "native",
            "choices": [{"delta": {}, "finish_reason": "stop"}],
        }
        content = f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n".encode()

    async def handle(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    cfg = provider(protocol)
    async with httpx.AsyncClient(
        base_url=cfg.base_url, transport=httpx.MockTransport(handle)
    ) as client:
        adapter = BedrockAdapter.from_config(cfg, env={"BEDROCK_TEST_KEY": KEY}, client=client)
        result = await adapter.chat_completion(request(), model="native", stream=True)
        assert isinstance(result, AsyncIterator)
        with pytest.raises(ProviderEmptyResponseError):
            _ = [chunk async for chunk in result]
        assert not (await adapter.health_check()).reachable


async def test_encrypted_key_is_resolved_and_client_remains_owned_by_caller() -> None:
    master = Fernet.generate_key()
    cfg = provider(
        "responses",
        api_key_env=None,
        api_key_encrypted=Fernet(master).encrypt(KEY.encode()).decode(),
    )
    async with httpx.AsyncClient(base_url=cfg.base_url) as client:
        adapter = BedrockAdapter.from_config(
            cfg, env={"LQ_AI_GATEWAY_MASTER_KEY": master.decode()}, client=client
        )
        await adapter.aclose()
        assert not client.is_closed
