"""Unit tests for the Bedrock Mantle provider adapter (DE-035 / F1-F3).

Covers construction, per-request protocol routing, all three wire-format
tiers (Chat Completions / Messages / Responses) — happy path unary +
streaming, tool-call mapping, dropped/out-of-scope Responses item types,
the server-side-tool-calling egress-boundary guard (FR3.7), and the
three live-verified error classes (entitlement-403, entitlement-401,
wrong-API-for-model-400).

F2 reuses app.providers.anthropic's request/response/SSE translation
directly (see bedrock_mantle.py's module docstring), so its tests
exercise the same functions already covered by test_anthropic_provider.py
and test_anthropic_adapter.py. F3 response-shape tests run against
fixtures built from the OpenAI Responses SDK schema; live-tested paths
and remaining entitlement-blocked gaps are listed in
BedrockMantleAdapter's RESPONSES_EXCEPTION_MODEL_PREFIXES docstring.
"""

from __future__ import annotations

import json
import os

import httpx
import pytest
import respx

from app.config import ProviderConfig
from app.providers.base import ProviderHTTPError, ProviderUnsupportedError
from app.providers.bedrock_mantle import BedrockMantleAdapter
from app.providers.openai_schema import (
    ChatCompletionChunk,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingsRequest,
)

MANTLE_BASE = "https://bedrock-mantle.us-east-1.api.aws/v1"
# Messages lives off the Mantle domain root, NOT /v1-relative to MANTLE_BASE
# like Chat Completions/Responses (see bedrock_mantle.py::_messages_url).
MANTLE_MESSAGES_URL = "https://bedrock-mantle.us-east-1.api.aws/anthropic/v1/messages"
# RESPONSES_MODEL (openai.gpt-5.5) is in RESPONSES_EXCEPTION_MODEL_PREFIXES,
# so its Responses tier also lives off the domain root, not MANTLE_BASE
# (see bedrock_mantle.py::_responses_url).
MANTLE_RESPONSES_EXCEPTION_URL = "https://bedrock-mantle.us-east-1.api.aws/openai/v1/responses"
CHAT_COMPLETIONS_MODEL = "openai.gpt-oss-20b"
MESSAGES_MODEL = "anthropic.claude-opus-4-8"
RESPONSES_MODEL = "openai.gpt-5.5"

DEFAULT_LIVE_TEST_MODEL = os.environ.get("LQ_AI_BEDROCK_MANTLE_TEST_MODEL", CHAT_COMPLETIONS_MODEL)
DEFAULT_LIVE_TEST_REGION = os.environ.get("LQ_AI_BEDROCK_MANTLE_TEST_REGION", "us-east-1")


def _mantle_provider(
    *,
    api_key_env: str = "AWS_BEARER_TOKEN_BEDROCK_TEST",
) -> ProviderConfig:
    return ProviderConfig.model_validate(
        {
            "name": "bedrock-mantle-test",
            "type": "bedrock_mantle",
            "base_url": MANTLE_BASE,
            "api_key_env": api_key_env,
            "tier": 3,
            "models": [CHAT_COMPLETIONS_MODEL, MESSAGES_MODEL, RESPONSES_MODEL],
        }
    )


def _adapter(client: httpx.AsyncClient) -> BedrockMantleAdapter:
    return BedrockMantleAdapter(
        name="bedrock-mantle-test",
        base_url=MANTLE_BASE,
        api_key="mantle-key-do-not-leak",
        client=client,
    )


# --- Construction -------------------------------------------------------


@pytest.mark.unit
def test_from_config_accepts_bedrock_mantle_provider_with_key() -> None:
    adapter = BedrockMantleAdapter.from_config(
        _mantle_provider(),
        env={"AWS_BEARER_TOKEN_BEDROCK_TEST": "mantle-key-123"},
    )
    assert adapter.name == "bedrock-mantle-test"


@pytest.mark.unit
def test_from_config_rejects_wrong_type() -> None:
    bogus = ProviderConfig.model_validate(
        {
            "name": "x",
            "type": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "tier": 4,
            "models": [],
        }
    )
    with pytest.raises(ValueError, match=r"(?i)provider\.type"):
        BedrockMantleAdapter.from_config(bogus, env={})


@pytest.mark.unit
def test_from_config_requires_key() -> None:
    with pytest.raises(ValueError, match=r"(?i)environment variable"):
        BedrockMantleAdapter.from_config(_mantle_provider(), env={})


@pytest.mark.unit
def test_from_config_defaults_to_aws_bearer_token_bedrock_env() -> None:
    """No explicit api_key_env -> falls back to AWS_BEARER_TOKEN_BEDROCK."""

    provider = ProviderConfig.model_validate(
        {
            "name": "bedrock-mantle-default",
            "type": "bedrock_mantle",
            "base_url": MANTLE_BASE,
            "tier": 3,
            "models": [],
        }
    )
    adapter = BedrockMantleAdapter.from_config(
        provider, env={"AWS_BEARER_TOKEN_BEDROCK": "default-key"}
    )
    assert adapter.name == "bedrock-mantle-default"


@pytest.mark.unit
async def test_embeddings_unsupported() -> None:
    """FR1.4: Bedrock embedding models are out of scope for this adapter."""

    client = httpx.AsyncClient(base_url=MANTLE_BASE)
    try:
        adapter = _adapter(client)
        with pytest.raises(ProviderUnsupportedError):
            await adapter.embeddings(
                EmbeddingsRequest(model=CHAT_COMPLETIONS_MODEL, input="hi"),
                model=CHAT_COMPLETIONS_MODEL,
            )
    finally:
        await client.aclose()


# --- Routing --------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("anthropic.claude-opus-4-8", "messages"),
        ("anthropic.claude-haiku-4-5", "messages"),
        ("openai.gpt-5.5", "responses"),
        ("openai.gpt-5-mini", "responses"),
        # Live-tested 2026-07-02: 401 access_denied on Chat Completions,
        # 200 on Responses, on this account.
        ("google.gemma-4-31b", "responses"),
        ("xai.grok-4.3", "responses"),
        ("openai.gpt-oss-20b", "chat_completions"),
        ("meta.llama3-70b", "chat_completions"),
    ],
)
def test_route_protocol(model: str, expected: str) -> None:
    assert BedrockMantleAdapter._route_protocol(model) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("model", "expected_url"),
    [
        # Exception path — live-tested 2026-07-02 (see
        # RESPONSES_EXCEPTION_MODEL_PREFIXES docstring).
        ("google.gemma-4-31b", MANTLE_RESPONSES_EXCEPTION_URL),
        ("xai.grok-4.3", MANTLE_RESPONSES_EXCEPTION_URL),
        ("openai.gpt-5.4", MANTLE_RESPONSES_EXCEPTION_URL),
        ("openai.gpt-5.5", MANTLE_RESPONSES_EXCEPTION_URL),
        # Exception path is also the DEFAULT for any model not in
        # RESPONSES_GENERAL_PATH_MODEL_PREFIXES — untested for this specific
        # model, but the best-evidenced guess per the observed trend.
        ("openai.gpt-5-mini", MANTLE_RESPONSES_EXCEPTION_URL),
        # General path — /responses relative to base_url. Only models
        # confirmed to need it are in RESPONSES_GENERAL_PATH_MODEL_PREFIXES.
        ("openai.gpt-oss-20b", "/responses"),
        ("zai.glm-5", "/responses"),
    ],
)
def test_responses_url_per_model(model: str, expected_url: str) -> None:
    client = httpx.AsyncClient(base_url=MANTLE_BASE)
    try:
        adapter = _adapter(client)
        assert adapter._responses_url(model) == expected_url
    finally:
        pass


# --- F1: Chat Completions tier --------------------------------------------


@pytest.mark.unit
async def test_chat_completions_tier_happy_path_unary() -> None:
    payload = {
        "id": "chatcmpl-cc-1",
        "object": "chat.completion",
        "created": 0,
        "model": CHAT_COMPLETIONS_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hi there"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }
    with respx.mock(base_url=MANTLE_BASE) as router:
        route = router.post("/chat/completions").mock(
            return_value=httpx.Response(200, json=payload)
        )
        client = httpx.AsyncClient(base_url=MANTLE_BASE)
        try:
            adapter = _adapter(client)
            result = await adapter.chat_completion(
                ChatCompletionRequest(
                    model="alias",
                    messages=[ChatCompletionMessage(role="user", content="hi")],
                ),
                model=CHAT_COMPLETIONS_MODEL,
                stream=False,
            )
        finally:
            await client.aclose()
    assert isinstance(result, ChatCompletionResponse)
    assert result.choices[0].message.content == "hi there"
    sent = route.calls.last.request
    assert sent.headers.get("authorization") == "Bearer mantle-key-do-not-leak"


# --- F2: Messages tier ------------------------------------------------------


@pytest.mark.unit
async def test_messages_tier_happy_path_unary() -> None:
    """Fixture built from AWS's documented Messages schema (A4 unvalidated)."""

    payload = {
        "id": "msg_01ABC",
        "type": "message",
        "role": "assistant",
        "model": MESSAGES_MODEL,
        "content": [{"type": "text", "text": "hello from messages"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 4},
    }
    with respx.mock(base_url=MANTLE_BASE) as router:
        route = router.post(MANTLE_MESSAGES_URL).mock(
            return_value=httpx.Response(200, json=payload)
        )
        client = httpx.AsyncClient(base_url=MANTLE_BASE)
        try:
            adapter = _adapter(client)
            result = await adapter.chat_completion(
                ChatCompletionRequest(
                    model="alias",
                    messages=[ChatCompletionMessage(role="user", content="hi")],
                ),
                model=MESSAGES_MODEL,
                stream=False,
            )
        finally:
            await client.aclose()
    assert isinstance(result, ChatCompletionResponse)
    assert result.choices[0].message.content == "hello from messages"
    assert result.choices[0].finish_reason == "stop"
    assert result.usage.prompt_tokens == 10
    assert result.usage.completion_tokens == 4
    sent = route.calls.last.request
    assert sent.headers.get("authorization") == "Bearer mantle-key-do-not-leak"
    assert sent.headers.get("anthropic-version") == "2023-06-01"


@pytest.mark.unit
async def test_messages_tier_tool_use_mapping() -> None:
    payload = {
        "id": "msg_01TOOL",
        "type": "message",
        "role": "assistant",
        "model": MESSAGES_MODEL,
        "content": [
            {"type": "text", "text": "let me check"},
            {
                "type": "tool_use",
                "id": "toolu_01",
                "name": "get_weather",
                "input": {"city": "London"},
            },
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 5, "output_tokens": 5},
    }
    with respx.mock(base_url=MANTLE_BASE) as router:
        router.post(MANTLE_MESSAGES_URL).mock(return_value=httpx.Response(200, json=payload))
        client = httpx.AsyncClient(base_url=MANTLE_BASE)
        try:
            adapter = _adapter(client)
            result = await adapter.chat_completion(
                ChatCompletionRequest(
                    model="alias",
                    messages=[ChatCompletionMessage(role="user", content="weather?")],
                ),
                model=MESSAGES_MODEL,
                stream=False,
            )
        finally:
            await client.aclose()
    assert isinstance(result, ChatCompletionResponse)
    assert result.choices[0].finish_reason == "tool_calls"
    tool_calls = result.choices[0].message.tool_calls
    assert tool_calls is not None
    assert tool_calls[0]["function"]["name"] == "get_weather"
    assert json.loads(tool_calls[0]["function"]["arguments"]) == {"city": "London"}


@pytest.mark.unit
async def test_messages_tier_streaming_happy_path() -> None:
    sse_body = (
        "event: message_start\n"
        'data: {"type":"message_start","message":{"id":"msg_1","model":"'
        + MESSAGES_MODEL
        + '","usage":{"input_tokens":2}}}\n\n'
        "event: content_block_delta\n"
        'data: {"type":"content_block_delta","index":0,'
        '"delta":{"type":"text_delta","text":"hi"}}\n\n'
        "event: message_delta\n"
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},'
        '"usage":{"output_tokens":1}}\n\n'
        "event: message_stop\n"
        'data: {"type":"message_stop"}\n\n'
    )
    with respx.mock(base_url=MANTLE_BASE) as router:
        router.post(MANTLE_MESSAGES_URL).mock(
            return_value=httpx.Response(
                200, content=sse_body.encode(), headers={"content-type": "text/event-stream"}
            )
        )
        client = httpx.AsyncClient(base_url=MANTLE_BASE)
        try:
            adapter = _adapter(client)
            result = await adapter.chat_completion(
                ChatCompletionRequest(
                    model="alias",
                    messages=[ChatCompletionMessage(role="user", content="hi")],
                ),
                model=MESSAGES_MODEL,
                stream=True,
            )
            assert not isinstance(result, ChatCompletionResponse)
            chunks: list[ChatCompletionChunk] = [c async for c in result]
        finally:
            await client.aclose()
    assert any(c.choices[0].delta.role == "assistant" for c in chunks)
    assert any(c.choices[0].delta.content == "hi" for c in chunks)
    assert chunks[-1].choices[0].finish_reason == "stop"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.completion_tokens == 1


# --- F3: Responses tier ------------------------------------------------------


@pytest.mark.unit
async def test_responses_tier_happy_path_unary() -> None:
    """Fixture built from openai.types.responses.Response schema (A5 unvalidated)."""

    payload = {
        "id": "resp_01ABC",
        "object": "response",
        "created_at": 1234567890,
        "model": RESPONSES_MODEL,
        "output": [
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "hello from responses"}],
            }
        ],
        "usage": {"input_tokens": 8, "output_tokens": 3},
    }
    with respx.mock(base_url=MANTLE_BASE) as router:
        route = router.post(MANTLE_RESPONSES_EXCEPTION_URL).mock(
            return_value=httpx.Response(200, json=payload)
        )
        client = httpx.AsyncClient(base_url=MANTLE_BASE)
        try:
            adapter = _adapter(client)
            result = await adapter.chat_completion(
                ChatCompletionRequest(
                    model="alias",
                    messages=[ChatCompletionMessage(role="user", content="hi")],
                ),
                model=RESPONSES_MODEL,
                stream=False,
            )
        finally:
            await client.aclose()
    assert isinstance(result, ChatCompletionResponse)
    assert result.choices[0].message.content == "hello from responses"
    assert result.choices[0].finish_reason == "stop"
    assert result.usage.prompt_tokens == 8
    assert result.usage.completion_tokens == 3
    sent = route.calls.last.request
    assert sent.headers.get("authorization") == "Bearer mantle-key-do-not-leak"


@pytest.mark.unit
async def test_responses_tier_function_call_mapping() -> None:
    """FR3.4: function_call output[] item -> gateway tool_calls; namespace dropped."""

    payload = {
        "id": "resp_01TOOL",
        "object": "response",
        "created_at": 1234567890,
        "model": RESPONSES_MODEL,
        "output": [
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_abc123",
                "name": "get_weather",
                "arguments": '{"city": "Paris"}',
                "namespace": "some-namespace-value",
                "status": "completed",
            }
        ],
        "usage": {"input_tokens": 6, "output_tokens": 4},
    }
    with respx.mock(base_url=MANTLE_BASE) as router:
        router.post(MANTLE_RESPONSES_EXCEPTION_URL).mock(
            return_value=httpx.Response(200, json=payload)
        )
        client = httpx.AsyncClient(base_url=MANTLE_BASE)
        try:
            adapter = _adapter(client)
            result = await adapter.chat_completion(
                ChatCompletionRequest(
                    model="alias",
                    messages=[ChatCompletionMessage(role="user", content="weather?")],
                ),
                model=RESPONSES_MODEL,
                stream=False,
            )
        finally:
            await client.aclose()
    assert isinstance(result, ChatCompletionResponse)
    assert result.choices[0].finish_reason == "tool_calls"
    tool_calls = result.choices[0].message.tool_calls
    assert tool_calls is not None
    assert tool_calls[0]["id"] == "call_abc123"
    assert tool_calls[0]["function"]["name"] == "get_weather"
    assert json.loads(tool_calls[0]["function"]["arguments"]) == {"city": "Paris"}
    # namespace is resolved-dropped (FR3.4) -- not present anywhere on the
    # translated tool_calls entry.
    assert "namespace" not in tool_calls[0]
    assert "namespace" not in tool_calls[0]["function"]


@pytest.mark.unit
async def test_responses_tier_drops_reasoning_items() -> None:
    """FR3.6: reasoning output[] items are dropped silently, not surfaced."""

    payload = {
        "id": "resp_01R",
        "object": "response",
        "created_at": 1234567890,
        "model": RESPONSES_MODEL,
        "output": [
            {
                "type": "reasoning",
                "id": "rs_1",
                "summary": [],
                "content": [{"type": "reasoning_text", "text": "internal chain of thought"}],
                "encrypted_content": "abcdef",
                "status": "completed",
            },
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "final answer"}],
            },
        ],
        "usage": {"input_tokens": 4, "output_tokens": 2},
    }
    with respx.mock(base_url=MANTLE_BASE) as router:
        router.post(MANTLE_RESPONSES_EXCEPTION_URL).mock(
            return_value=httpx.Response(200, json=payload)
        )
        client = httpx.AsyncClient(base_url=MANTLE_BASE)
        try:
            adapter = _adapter(client)
            result = await adapter.chat_completion(
                ChatCompletionRequest(
                    model="alias",
                    messages=[ChatCompletionMessage(role="user", content="hi")],
                ),
                model=RESPONSES_MODEL,
                stream=False,
            )
        finally:
            await client.aclose()
    assert isinstance(result, ChatCompletionResponse)
    assert result.choices[0].message.content == "final answer"
    assert "chain of thought" not in (result.choices[0].message.content or "")


@pytest.mark.unit
async def test_responses_tier_out_of_scope_item_type_dropped_not_corrupted() -> None:
    """FR3.5: an out-of-scope output[] item type must not corrupt the mapped
    response — it's dropped (and logged), never absorbed into content/tool_calls."""

    payload = {
        "id": "resp_01X",
        "object": "response",
        "created_at": 1234567890,
        "model": RESPONSES_MODEL,
        "output": [
            {
                "type": "mcp_call",
                "id": "mcp_1",
                "name": "some_mcp_tool",
                "arguments": "{}",
                "server_label": "example",
                "status": "completed",
            },
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "still works"}],
            },
        ],
        "usage": {"input_tokens": 4, "output_tokens": 2},
    }
    with respx.mock(base_url=MANTLE_BASE) as router:
        router.post(MANTLE_RESPONSES_EXCEPTION_URL).mock(
            return_value=httpx.Response(200, json=payload)
        )
        client = httpx.AsyncClient(base_url=MANTLE_BASE)
        try:
            adapter = _adapter(client)
            result = await adapter.chat_completion(
                ChatCompletionRequest(
                    model="alias",
                    messages=[ChatCompletionMessage(role="user", content="hi")],
                ),
                model=RESPONSES_MODEL,
                stream=False,
            )
        finally:
            await client.aclose()
    assert isinstance(result, ChatCompletionResponse)
    assert result.choices[0].message.content == "still works"
    assert result.choices[0].message.tool_calls is None


@pytest.mark.unit
async def test_responses_tier_streaming_happy_path() -> None:
    sse_body = (
        "event: response.created\n"
        'data: {"type":"response.created","response":{"id":"resp_1","model":"'
        + RESPONSES_MODEL
        + '"}}\n\n'
        "event: response.output_text.delta\n"
        'data: {"type":"response.output_text.delta","delta":"hi"}\n\n'
        "event: response.completed\n"
        'data: {"type":"response.completed","response":{"usage":'
        '{"input_tokens":3,"output_tokens":1}}}\n\n'
    )
    with respx.mock(base_url=MANTLE_BASE) as router:
        router.post(MANTLE_RESPONSES_EXCEPTION_URL).mock(
            return_value=httpx.Response(
                200, content=sse_body.encode(), headers={"content-type": "text/event-stream"}
            )
        )
        client = httpx.AsyncClient(base_url=MANTLE_BASE)
        try:
            adapter = _adapter(client)
            result = await adapter.chat_completion(
                ChatCompletionRequest(
                    model="alias",
                    messages=[ChatCompletionMessage(role="user", content="hi")],
                ),
                model=RESPONSES_MODEL,
                stream=True,
            )
            assert not isinstance(result, ChatCompletionResponse)
            chunks: list[ChatCompletionChunk] = [c async for c in result]
        finally:
            await client.aclose()
    assert any(c.choices[0].delta.role == "assistant" for c in chunks)
    assert any(c.choices[0].delta.content == "hi" for c in chunks)
    assert chunks[-1].choices[0].finish_reason == "stop"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.prompt_tokens == 3
    assert chunks[-1].usage.completion_tokens == 1


@pytest.mark.unit
async def test_responses_tier_no_tools_configured_sends_no_tools_field() -> None:
    """FR3.7 / ADR 0014 egress boundary: a request with no gateway-level
    tools configured must not produce a Responses body containing any
    tools field — the adapter must never default-add or pass through a
    built-in/server-side AWS/OpenAI tool type."""

    payload = {
        "id": "resp_01N",
        "object": "response",
        "created_at": 1234567890,
        "model": RESPONSES_MODEL,
        "output": [
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "no tools here"}],
            }
        ],
        "usage": {"input_tokens": 2, "output_tokens": 2},
    }
    with respx.mock(base_url=MANTLE_BASE) as router:
        route = router.post(MANTLE_RESPONSES_EXCEPTION_URL).mock(
            return_value=httpx.Response(200, json=payload)
        )
        client = httpx.AsyncClient(base_url=MANTLE_BASE)
        try:
            adapter = _adapter(client)
            await adapter.chat_completion(
                ChatCompletionRequest(
                    model="alias",
                    messages=[ChatCompletionMessage(role="user", content="hi")],
                ),
                model=RESPONSES_MODEL,
                stream=False,
            )
        finally:
            await client.aclose()
    sent_body = json.loads(route.calls.last.request.content)
    assert "tools" not in sent_body


@pytest.mark.unit
async def test_responses_tier_governed_tools_translate_correctly() -> None:
    """A gateway-governed tool list translates into the Responses tools shape."""

    payload = {
        "id": "resp_01T",
        "object": "response",
        "created_at": 1234567890,
        "model": RESPONSES_MODEL,
        "output": [
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "ok"}],
            }
        ],
        "usage": {"input_tokens": 2, "output_tokens": 2},
    }
    with respx.mock(base_url=MANTLE_BASE) as router:
        route = router.post(MANTLE_RESPONSES_EXCEPTION_URL).mock(
            return_value=httpx.Response(200, json=payload)
        )
        client = httpx.AsyncClient(base_url=MANTLE_BASE)
        try:
            adapter = _adapter(client)
            await adapter.chat_completion(
                ChatCompletionRequest(
                    model="alias",
                    messages=[ChatCompletionMessage(role="user", content="hi")],
                    tools=[
                        {
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "description": "Get weather",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"city": {"type": "string"}},
                                },
                            },
                        }
                    ],
                ),
                model=RESPONSES_MODEL,
                stream=False,
            )
        finally:
            await client.aclose()
    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body["tools"] == [
        {
            "type": "function",
            "name": "get_weather",
            "description": "Get weather",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
        }
    ]


# --- Error mapping: three live-verified classes -----------------------------


@pytest.mark.unit
async def test_messages_tier_entitlement_403_maps_to_http_error_not_auth_error() -> None:
    """Error class 1: 403, Anthropic-native permission_error (Messages)."""

    error_body = {
        "type": "error",
        "error": {"type": "permission_error", "message": "You do not have access to this model."},
    }
    with respx.mock(base_url=MANTLE_BASE) as router:
        router.post(MANTLE_MESSAGES_URL).mock(return_value=httpx.Response(403, json=error_body))
        client = httpx.AsyncClient(base_url=MANTLE_BASE)
        try:
            adapter = _adapter(client)
            with pytest.raises(ProviderHTTPError) as excinfo:
                await adapter.chat_completion(
                    ChatCompletionRequest(
                        model="alias",
                        messages=[ChatCompletionMessage(role="user", content="hi")],
                    ),
                    model=MESSAGES_MODEL,
                    stream=False,
                )
        finally:
            await client.aclose()
    assert excinfo.value.upstream_status == 403
    assert excinfo.value.details["mantle_error_class"] == "entitlement_denied"
    assert "mantle-key-do-not-leak" not in str(excinfo.value.details)
    assert "mantle-key-do-not-leak" not in excinfo.value.message


@pytest.mark.unit
async def test_responses_tier_entitlement_401_maps_to_http_error_not_auth_error() -> None:
    """Error class 2: 401, OpenAI-native permission_denied_error (Responses)."""

    error_body = {
        "error": {
            "type": "permission_denied_error",
            "code": "access_denied",
            "message": "Access denied.",
        }
    }
    with respx.mock(base_url=MANTLE_BASE) as router:
        router.post(MANTLE_RESPONSES_EXCEPTION_URL).mock(
            return_value=httpx.Response(401, json=error_body)
        )
        client = httpx.AsyncClient(base_url=MANTLE_BASE)
        try:
            adapter = _adapter(client)
            with pytest.raises(ProviderHTTPError) as excinfo:
                await adapter.chat_completion(
                    ChatCompletionRequest(
                        model="alias",
                        messages=[ChatCompletionMessage(role="user", content="hi")],
                    ),
                    model=RESPONSES_MODEL,
                    stream=False,
                )
        finally:
            await client.aclose()
    assert excinfo.value.upstream_status == 401
    assert excinfo.value.details["mantle_error_class"] == "entitlement_denied"


@pytest.mark.unit
async def test_responses_tier_wrong_path_guess_falls_back_and_succeeds() -> None:
    """A model not in either known-model list defaults to the exception
    path; if that guess is wrong (AWS's 400 "does not support" signature),
    the adapter retries the general path once and succeeds — matching
    live-observed behavior for a hypothetical unknown model family."""

    unknown_model = "some-vendor.new-model-1"
    error_body = {
        "error": {
            "code": "validation_error",
            "type": "invalid_request_error",
            "message": f"The model '{unknown_model}' does not support the "
            "'/openai/v1/responses' API",
        }
    }
    payload = {
        "id": "resp_fallback",
        "object": "response",
        "model": unknown_model,
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "hi from fallback"}],
            }
        ],
        "usage": {"input_tokens": 3, "output_tokens": 2},
    }
    exception_url = "https://bedrock-mantle.us-east-1.api.aws/openai/v1/responses"
    with respx.mock(base_url=MANTLE_BASE) as router:
        router.post(exception_url).mock(return_value=httpx.Response(400, json=error_body))
        router.post("/responses").mock(return_value=httpx.Response(200, json=payload))
        client = httpx.AsyncClient(base_url=MANTLE_BASE)
        try:
            adapter = _adapter(client)
            assert unknown_model not in adapter._responses_url_cache
            # _route_protocol doesn't know this model family; bypass
            # routing to exercise the Responses-tier fallback directly,
            # matching how an operator-configured alias would explicitly
            # route an unrecognized model to this tier.
            result = await adapter._responses_chat_completion(
                ChatCompletionRequest(
                    model="alias",
                    messages=[ChatCompletionMessage(role="user", content="hi")],
                ),
                model=unknown_model,
                stream=False,
            )
        finally:
            await client.aclose()
    assert isinstance(result, ChatCompletionResponse)
    assert result.choices[0].message.content == "hi from fallback"
    # Cached so a second call for the same model skips straight to the
    # path that actually worked.
    assert adapter._responses_url_cache[unknown_model] == "/responses"


@pytest.mark.unit
async def test_responses_tier_wrong_api_for_model_400_both_paths_reject() -> None:
    """Error class 3: 400, wrong API path — when BOTH paths reject the
    model (e.g. a Chat-Completions-only model like zai.glm-5, live-tested
    2026-07-02), the fallback's own failure must still be distinguishable
    from the entitlement classes (1)/(2), not swallowed or misreported."""

    error_body = {
        "error": {
            "code": "validation_error",
            "type": "invalid_request_error",
            "message": f"The model '{RESPONSES_MODEL}' does not support the "
            "'/openai/v1/responses' API",
        }
    }
    with respx.mock(base_url=MANTLE_BASE) as router:
        router.post(MANTLE_RESPONSES_EXCEPTION_URL).mock(
            return_value=httpx.Response(400, json=error_body)
        )
        router.post("/responses").mock(return_value=httpx.Response(400, json=error_body))
        client = httpx.AsyncClient(base_url=MANTLE_BASE)
        try:
            adapter = _adapter(client)
            with pytest.raises(ProviderHTTPError) as excinfo:
                await adapter.chat_completion(
                    ChatCompletionRequest(
                        model="alias",
                        messages=[ChatCompletionMessage(role="user", content="hi")],
                    ),
                    model=RESPONSES_MODEL,
                    stream=False,
                )
        finally:
            await client.aclose()
    assert excinfo.value.upstream_status == 400
    assert excinfo.value.details["mantle_error_class"] == "unsupported_api_for_model"


@pytest.mark.unit
async def test_error_mapping_never_leaks_api_key() -> None:
    """NFR2: the Bearer token must never appear in a surfaced error."""

    error_body = {"error": {"type": "permission_error", "message": "denied"}}
    with respx.mock(base_url=MANTLE_BASE) as router:
        router.post(MANTLE_MESSAGES_URL).mock(return_value=httpx.Response(403, json=error_body))
        client = httpx.AsyncClient(base_url=MANTLE_BASE)
        try:
            adapter = _adapter(client)
            with pytest.raises(ProviderHTTPError) as excinfo:
                await adapter.chat_completion(
                    ChatCompletionRequest(
                        model="alias",
                        messages=[ChatCompletionMessage(role="user", content="hi")],
                    ),
                    model=MESSAGES_MODEL,
                    stream=False,
                )
        finally:
            await client.aclose()
    envelope = json.dumps(excinfo.value.to_envelope())
    assert "mantle-key-do-not-leak" not in envelope


# --- Live provider test (Task 5 / AC1.1) ---------------------------------


@pytest.mark.provider
async def test_real_bedrock_mantle_chat_completion_roundtrip() -> None:
    """Live call against bedrock-mantle.{region}.api.aws — only runs when
    ``AWS_BEARER_TOKEN_BEDROCK`` is set.

    Chat Completions tier only (AC1.1) — Messages/Responses tiers remain
    blocked on account entitlement for a current-generation model (AC2.1/
    AC3.1; see spec.md A3/A4/A5). Default model is ``openai.gpt-oss-20b``,
    the legacy/compat model live-verified during this unit's design phase;
    override via ``LQ_AI_BEDROCK_MANTLE_TEST_MODEL`` /
    ``LQ_AI_BEDROCK_MANTLE_TEST_REGION`` for a different account's catalogue.
    """

    api_key = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
    if not api_key:
        pytest.skip("AWS_BEARER_TOKEN_BEDROCK not set; skipping real-provider test")

    base_url = f"https://bedrock-mantle.{DEFAULT_LIVE_TEST_REGION}.api.aws/v1"
    adapter = BedrockMantleAdapter(
        name="bedrock-mantle-real",
        base_url=base_url,
        api_key=api_key,
        timeout_s=30.0,
    )
    try:
        request = ChatCompletionRequest.model_validate(
            {
                "model": DEFAULT_LIVE_TEST_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": "Reply with the single word PONG and nothing else.",
                    }
                ],
                # gpt-oss-20b is a reasoning model: it spends part of the
                # token budget on an internal `reasoning` field (visible on
                # ChatCompletionMessage, silently ignored per FR1.3) before
                # emitting visible content. A tight budget can exhaust
                # itself on reasoning alone (finish_reason="length", empty
                # content) even though the call succeeded. 256 leaves
                # enough headroom for both.
                "max_tokens": 256,
                "temperature": 0.0,
            }
        )
        result = await adapter.chat_completion(request, model=DEFAULT_LIVE_TEST_MODEL, stream=False)
    except httpx.HTTPError as exc:
        pytest.skip(f"network failure reaching Bedrock Mantle: {exc}")
    finally:
        await adapter.aclose()

    assert isinstance(result, ChatCompletionResponse)
    assert result.choices, "Bedrock Mantle returned no choices"
    content = result.choices[0].message.content or ""
    assert "PONG" in content.upper()
    assert result.usage.prompt_tokens > 0
    assert result.usage.completion_tokens > 0
