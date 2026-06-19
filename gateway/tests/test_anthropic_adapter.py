"""Unit tests for :class:`app.providers.anthropic.AnthropicAdapter`.

Covers the translation logic and HTTP handling without going through
the FastAPI surface. Outbound HTTP is mocked with ``respx``.

Test surface:

* System-message extraction from OpenAI ``messages`` into Anthropic's
  top-level ``system`` field.
* ``stop_reason`` mapping (``end_turn`` -> ``stop``, ``max_tokens`` ->
  ``length``, ``tool_use`` -> ``tool_calls``, ``stop_sequence`` ->
  ``stop``).
* Token-usage translation (``input_tokens`` / ``output_tokens`` ->
  ``prompt_tokens`` / ``completion_tokens`` / ``total_tokens``).
* Streaming: SSE event sequence is translated into OpenAI chunks with
  the expected role-then-deltas-then-finish ordering.
* Network failure -> :class:`ProviderNetworkError`.
* Upstream 401 -> :class:`ProviderAuthError` with no key in the
  surfaced message or details.
* ``embeddings`` -> :class:`ProviderUnsupportedError`.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.providers import (
    AnthropicAdapter,
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingsRequest,
    ProviderAuthError,
    ProviderHTTPError,
    ProviderNetworkError,
    ProviderUnsupportedError,
)
from app.providers.anthropic import (
    DEFAULT_MAX_TOKENS,
    _to_anthropic_request,
)

ANTHROPIC_BASE = "https://api.anthropic.com"


def _make_adapter(api_key: str = "sk-ant-test") -> AnthropicAdapter:
    """Build an adapter pointed at the standard production base URL."""

    return AnthropicAdapter(
        name="anthropic-test",
        base_url=ANTHROPIC_BASE,
        api_key=api_key,
    )


def _basic_request(**overrides: object) -> ChatCompletionRequest:
    """Build a minimal valid :class:`ChatCompletionRequest`."""

    payload: dict[str, object] = {
        "model": "claude-sonnet-4-6",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"},
        ],
    }
    payload.update(overrides)
    return ChatCompletionRequest.model_validate(payload)


# --- Pure-translation tests (no HTTP) -----------------------------------------


@pytest.mark.unit
def test_to_anthropic_request_extracts_system_message() -> None:
    """System messages move to the top-level ``system`` field; user /
    assistant messages stay in ``messages`` in order."""

    req = ChatCompletionRequest.model_validate(
        {
            "model": "claude-sonnet-4-6",
            "messages": [
                {"role": "system", "content": "You are concise."},
                {"role": "system", "content": "Always cite."},
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
                {"role": "user", "content": "Continue"},
            ],
        }
    )

    body = _to_anthropic_request(req, model="claude-sonnet-4-6", stream=False)

    assert body["system"] == "You are concise.\n\nAlways cite."
    assert body["messages"] == [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "Continue"},
    ]
    # max_tokens default is applied
    assert body["max_tokens"] == DEFAULT_MAX_TOKENS
    # Stream flag is forwarded
    assert body["stream"] is False


@pytest.mark.unit
def test_to_anthropic_request_passes_through_optional_fields() -> None:
    req = ChatCompletionRequest.model_validate(
        {
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 256,
            "temperature": 0.3,
            "top_p": 0.9,
            "stop": ["END"],
        }
    )

    body = _to_anthropic_request(req, model="claude-sonnet-4-6", stream=True)

    assert body["max_tokens"] == 256
    assert body["temperature"] == 0.3
    assert body["top_p"] == 0.9
    assert body["stop_sequences"] == ["END"]
    assert body["stream"] is True


@pytest.mark.unit
def test_to_anthropic_request_string_stop_becomes_list() -> None:
    """OpenAI accepts ``stop: "END"``; Anthropic only takes a list."""

    req = ChatCompletionRequest.model_validate(
        {
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "hi"}],
            "stop": "END",
        }
    )
    body = _to_anthropic_request(req, model="claude-sonnet-4-6", stream=False)
    assert body["stop_sequences"] == ["END"]


@pytest.mark.unit
def test_to_anthropic_request_no_system_when_no_system_messages() -> None:
    """If the OpenAI request has no system messages, ``system`` is omitted
    rather than sent as an empty string."""

    req = _basic_request(messages=[{"role": "user", "content": "hi"}])
    body = _to_anthropic_request(req, model="claude-sonnet-4-6", stream=False)
    assert "system" not in body


@pytest.mark.unit
def test_to_anthropic_request_translates_tool_messages() -> None:
    """OpenAI ``tool`` role messages become Anthropic ``tool_result`` blocks
    nested in a user message."""

    req = ChatCompletionRequest.model_validate(
        {
            "model": "claude-sonnet-4-6",
            "messages": [
                {"role": "user", "content": "use a tool"},
                {"role": "assistant", "content": "calling..."},
                {
                    "role": "tool",
                    "content": "tool result text",
                    "tool_call_id": "call_abc123",
                },
            ],
        }
    )
    body = _to_anthropic_request(req, model="claude-sonnet-4-6", stream=False)
    assert body["messages"][-1] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "call_abc123",
                "content": "tool result text",
            }
        ],
    }


# --- Non-streaming HTTP path --------------------------------------------------


@pytest.mark.unit
@respx.mock
async def test_chat_completion_unary_translates_response() -> None:
    """Anthropic response shape is converted to OpenAI's, including usage
    and stop-reason."""

    route = respx.post(f"{ANTHROPIC_BASE}/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_01ABC",
                "model": "claude-sonnet-4-6",
                "content": [
                    {"type": "text", "text": "Hello there!"},
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 12, "output_tokens": 5},
            },
        )
    )

    adapter = _make_adapter()
    try:
        result = await adapter.chat_completion(
            _basic_request(),
            model="claude-sonnet-4-6",
            stream=False,
        )
    finally:
        await adapter.aclose()

    assert isinstance(result, ChatCompletionResponse)
    assert result.id == "msg_01ABC"
    assert result.model == "claude-sonnet-4-6"
    assert len(result.choices) == 1
    choice = result.choices[0]
    assert choice.message.role == "assistant"
    assert choice.message.content == "Hello there!"
    assert choice.finish_reason == "stop"
    assert result.usage.prompt_tokens == 12
    assert result.usage.completion_tokens == 5
    assert result.usage.total_tokens == 17

    # Headers we sent upstream are correct.
    assert route.called
    sent = route.calls[-1].request
    assert sent.headers["x-api-key"] == "sk-ant-test"
    assert sent.headers["anthropic-version"]
    body = json.loads(sent.content)
    assert body["model"] == "claude-sonnet-4-6"
    assert body["stream"] is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "anthropic_reason,expected_finish",
    [
        ("end_turn", "stop"),
        ("max_tokens", "length"),
        ("stop_sequence", "stop"),
        ("tool_use", "tool_calls"),
    ],
)
@respx.mock
async def test_stop_reason_mapping(anthropic_reason: str, expected_finish: str) -> None:
    respx.post(f"{ANTHROPIC_BASE}/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg",
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": "x"}],
                "stop_reason": anthropic_reason,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )
    )
    adapter = _make_adapter()
    try:
        result = await adapter.chat_completion(
            _basic_request(), model="claude-sonnet-4-6", stream=False
        )
    finally:
        await adapter.aclose()
    assert isinstance(result, ChatCompletionResponse)
    assert result.choices[0].finish_reason == expected_finish


@pytest.mark.unit
@respx.mock
async def test_chat_completion_concatenates_multiple_text_blocks() -> None:
    """Anthropic occasionally returns multiple text blocks in one
    response; the adapter joins them into a single OpenAI message."""

    respx.post(f"{ANTHROPIC_BASE}/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg",
                "model": "claude-sonnet-4-6",
                "content": [
                    {"type": "text", "text": "Part 1. "},
                    {"type": "text", "text": "Part 2."},
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 3, "output_tokens": 6},
            },
        )
    )
    adapter = _make_adapter()
    try:
        result = await adapter.chat_completion(
            _basic_request(), model="claude-sonnet-4-6", stream=False
        )
    finally:
        await adapter.aclose()
    assert isinstance(result, ChatCompletionResponse)
    assert result.choices[0].message.content == "Part 1. Part 2."


# --- Streaming path -----------------------------------------------------------


SSE_FIXTURE_BODY = (
    "event: message_start\n"
    'data: {"type":"message_start","message":{"id":"msg_stream","model":"claude-sonnet-4-6",'
    '"usage":{"input_tokens":7,"output_tokens":0}}}\n\n'
    "event: content_block_start\n"
    'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
    "event: content_block_delta\n"
    'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n'
    "event: content_block_delta\n"
    'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" world"}}\n\n'
    "event: content_block_stop\n"
    'data: {"type":"content_block_stop","index":0}\n\n'
    "event: message_delta\n"
    'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":2}}\n\n'
    "event: message_stop\n"
    'data: {"type":"message_stop"}\n\n'
)


@pytest.mark.unit
@respx.mock
async def test_chat_completion_streaming_translates_sse() -> None:
    """SSE event sequence becomes OpenAI chunks: role chunk, delta
    chunks, final chunk with finish_reason and usage."""

    respx.post(f"{ANTHROPIC_BASE}/v1/messages").mock(
        return_value=httpx.Response(
            200,
            text=SSE_FIXTURE_BODY,
            headers={"content-type": "text/event-stream"},
        )
    )

    adapter = _make_adapter()
    try:
        result = await adapter.chat_completion(
            _basic_request(stream=True),
            model="claude-sonnet-4-6",
            stream=True,
        )
        assert not isinstance(result, ChatCompletionResponse)
        chunks: list[ChatCompletionChunk] = []
        async for chunk in result:
            chunks.append(chunk)
    finally:
        await adapter.aclose()

    # Expect: 1 role-init chunk + 2 content delta chunks + 1 final chunk.
    assert len(chunks) == 4
    assert chunks[0].choices[0].delta.role == "assistant"
    assert chunks[0].choices[0].delta.content is None
    assert chunks[1].choices[0].delta.content == "Hello"
    assert chunks[2].choices[0].delta.content == " world"
    final = chunks[-1]
    assert final.choices[0].finish_reason == "stop"
    assert final.usage is not None
    assert final.usage.prompt_tokens == 7
    assert final.usage.completion_tokens == 2
    assert final.usage.total_tokens == 9
    # Anthropic's message_start id is preserved across the stream.
    for chunk in chunks:
        assert chunk.id == "msg_stream"
        assert chunk.model == "claude-sonnet-4-6"


# --- Error mapping ------------------------------------------------------------


@pytest.mark.unit
@respx.mock
async def test_upstream_401_raises_provider_auth_error_without_leaking_key() -> None:
    """A 401 from Anthropic raises :class:`ProviderAuthError`; neither the
    error message nor its details echo the API key value."""

    respx.post(f"{ANTHROPIC_BASE}/v1/messages").mock(
        return_value=httpx.Response(
            401,
            json={
                "type": "error",
                "error": {"type": "authentication_error", "message": "invalid x-api-key"},
            },
        )
    )
    secret = "sk-ant-secret-do-not-leak"
    adapter = _make_adapter(api_key=secret)
    try:
        with pytest.raises(ProviderAuthError) as excinfo:
            await adapter.chat_completion(_basic_request(), model="claude-sonnet-4-6", stream=False)
    finally:
        await adapter.aclose()

    err = excinfo.value
    serialized = json.dumps(err.to_envelope())
    assert secret not in serialized
    assert err.details["upstream_status"] == 401
    assert err.details.get("upstream_error_type") == "authentication_error"


@pytest.mark.unit
@respx.mock
async def test_upstream_500_raises_provider_http_error() -> None:
    respx.post(f"{ANTHROPIC_BASE}/v1/messages").mock(
        return_value=httpx.Response(
            500,
            json={"type": "error", "error": {"type": "api_error", "message": "internal"}},
        )
    )
    adapter = _make_adapter()
    try:
        with pytest.raises(ProviderHTTPError) as excinfo:
            await adapter.chat_completion(_basic_request(), model="claude-sonnet-4-6", stream=False)
    finally:
        await adapter.aclose()
    assert excinfo.value.upstream_status == 500


@pytest.mark.unit
@respx.mock
async def test_network_error_raises_provider_network_error() -> None:
    respx.post(f"{ANTHROPIC_BASE}/v1/messages").mock(side_effect=httpx.ConnectError("dns failure"))
    adapter = _make_adapter()
    try:
        with pytest.raises(ProviderNetworkError):
            await adapter.chat_completion(_basic_request(), model="claude-sonnet-4-6", stream=False)
    finally:
        await adapter.aclose()


@pytest.mark.unit
async def test_embeddings_raises_unsupported() -> None:
    """Anthropic has no embeddings endpoint; the adapter says so explicitly."""

    adapter = _make_adapter()
    try:
        with pytest.raises(ProviderUnsupportedError):
            await adapter.embeddings(
                EmbeddingsRequest(model="claude-sonnet-4-6", input="hi"),
                model="claude-sonnet-4-6",
            )
    finally:
        await adapter.aclose()


# --- Health check -------------------------------------------------------------


@pytest.mark.unit
@respx.mock
async def test_health_check_reports_reachable_on_200() -> None:
    respx.get(f"{ANTHROPIC_BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    adapter = _make_adapter()
    try:
        health = await adapter.health_check()
    finally:
        await adapter.aclose()
    assert health.reachable is True
    assert health.error is None
    assert health.latency_ms is not None


@pytest.mark.unit
@respx.mock
async def test_health_check_reports_auth_error_distinctly() -> None:
    """A 401 to /v1/models means the upstream is reachable but our
    credentials are bad — distinct from a network failure."""

    respx.get(f"{ANTHROPIC_BASE}/v1/models").mock(return_value=httpx.Response(401))
    adapter = _make_adapter()
    try:
        health = await adapter.health_check()
    finally:
        await adapter.aclose()
    assert health.reachable is True
    assert "auth" in (health.error or "").lower()


@pytest.mark.unit
@respx.mock
async def test_health_check_reports_unreachable_on_network_error() -> None:
    respx.get(f"{ANTHROPIC_BASE}/v1/models").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    adapter = _make_adapter()
    try:
        health = await adapter.health_check()
    finally:
        await adapter.aclose()
    assert health.reachable is False
    assert health.error is not None


# --- from_config -------------------------------------------------------------


@pytest.mark.unit
def test_from_config_missing_env_raises_clearly() -> None:
    """Construction-time failure (env var unset) raises a ValueError that
    names the missing variable and the provider — operators should see a
    legible message at startup, not at first request."""

    from app.config import ProviderConfig

    provider = ProviderConfig.model_validate(
        {
            "name": "anthropic-test",
            "type": "anthropic",
            "base_url": "https://api.anthropic.com",
            "api_key_env": "ANTHROPIC_API_KEY_DOES_NOT_EXIST_SHOULD_BE_UNSET",
            "tier": 4,
        }
    )
    with pytest.raises(ValueError) as excinfo:
        AnthropicAdapter.from_config(provider, env={})
    assert "ANTHROPIC_API_KEY_DOES_NOT_EXIST_SHOULD_BE_UNSET" in str(excinfo.value)
    assert "anthropic-test" in str(excinfo.value)


@pytest.mark.unit
def test_from_config_rejects_non_anthropic_provider() -> None:
    from app.config import ProviderConfig

    provider = ProviderConfig.model_validate(
        {
            "name": "openai-prod",
            "type": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "tier": 4,
        }
    )
    with pytest.raises(ValueError):
        AnthropicAdapter.from_config(provider, env={"OPENAI_API_KEY": "x"})


@pytest.mark.unit
def test_from_config_succeeds_with_env_set() -> None:
    from app.config import ProviderConfig

    provider = ProviderConfig.model_validate(
        {
            "name": "anthropic-test",
            "type": "anthropic",
            "base_url": "https://api.anthropic.com",
            "api_key_env": "ANTHROPIC_API_KEY",
            "tier": 4,
        }
    )
    adapter = AnthropicAdapter.from_config(provider, env={"ANTHROPIC_API_KEY": "sk-ant-x"})
    assert adapter.name == "anthropic-test"


# --- PR5b: tool-calling bridge ------------------------------------------------


_WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Look up the weather.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}


@pytest.mark.unit
def test_to_anthropic_request_translates_tools_and_auto_choice() -> None:
    """OpenAI ``tools`` become Anthropic tool blocks (name / description /
    input_schema). ``tool_choice="auto"`` is Anthropic's default, so it is
    omitted from the body."""

    req = _basic_request(tools=[_WEATHER_TOOL], tool_choice="auto")
    body = _to_anthropic_request(req, model="claude-sonnet-4-6", stream=False)
    assert body["tools"] == [
        {
            "name": "get_weather",
            "description": "Look up the weather.",
            "input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        }
    ]
    assert "tool_choice" not in body


@pytest.mark.unit
def test_to_anthropic_request_tool_choice_required_and_specific() -> None:
    """``required`` -> Anthropic ``any``; a specific function -> ``tool``."""

    req = _basic_request(tools=[_WEATHER_TOOL], tool_choice="required")
    body = _to_anthropic_request(req, model="claude-sonnet-4-6", stream=False)
    assert body["tool_choice"] == {"type": "any"}

    req2 = _basic_request(
        tools=[_WEATHER_TOOL],
        tool_choice={"type": "function", "function": {"name": "get_weather"}},
    )
    body2 = _to_anthropic_request(req2, model="claude-sonnet-4-6", stream=False)
    assert body2["tool_choice"] == {"type": "tool", "name": "get_weather"}


@pytest.mark.unit
def test_to_anthropic_request_tool_choice_none_drops_tools() -> None:
    """``tool_choice="none"`` means do not use tools this turn; we omit the
    tools block entirely rather than send an unusable Anthropic choice."""

    req = _basic_request(tools=[_WEATHER_TOOL], tool_choice="none")
    body = _to_anthropic_request(req, model="claude-sonnet-4-6", stream=False)
    assert "tools" not in body
    assert "tool_choice" not in body


@pytest.mark.unit
def test_to_anthropic_request_tool_without_params_gets_empty_schema() -> None:
    """A no-argument tool still needs a valid Anthropic ``input_schema``."""

    tool = {"type": "function", "function": {"name": "ping"}}
    req = _basic_request(tools=[tool])
    body = _to_anthropic_request(req, model="claude-sonnet-4-6", stream=False)
    assert body["tools"] == [{"name": "ping", "input_schema": {"type": "object", "properties": {}}}]


@pytest.mark.unit
def test_to_anthropic_request_assistant_tool_calls_become_tool_use() -> None:
    """An assistant message replaying its own tool_calls (the multi-step
    loop) becomes Anthropic ``tool_use`` blocks; JSON-string arguments are
    parsed into ``input``. The following ``tool`` result stays a
    ``tool_result`` block."""

    req = ChatCompletionRequest.model_validate(
        {
            "model": "claude-sonnet-4-6",
            "messages": [
                {"role": "user", "content": "weather in Paris?"},
                {
                    "role": "assistant",
                    "content": "Let me check.",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"city": "Paris"}',
                            },
                        }
                    ],
                },
                {"role": "tool", "content": "Sunny", "tool_call_id": "call_1"},
            ],
        }
    )
    body = _to_anthropic_request(req, model="claude-sonnet-4-6", stream=False)
    assert body["messages"][1] == {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Let me check."},
            {
                "type": "tool_use",
                "id": "call_1",
                "name": "get_weather",
                "input": {"city": "Paris"},
            },
        ],
    }
    assert body["messages"][2]["content"][0]["type"] == "tool_result"


@pytest.mark.unit
@respx.mock
async def test_from_anthropic_response_reconstructs_tool_calls() -> None:
    """A ``tool_use`` content block becomes an OpenAI ``tool_calls`` entry
    with JSON-string arguments; ``content`` is null on a pure tool turn and
    ``finish_reason`` is ``tool_calls``."""

    respx.post(f"{ANTHROPIC_BASE}/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_tool",
                "model": "claude-sonnet-4-6",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_01",
                        "name": "get_weather",
                        "input": {"city": "Paris"},
                    }
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 10, "output_tokens": 4},
            },
        )
    )
    adapter = _make_adapter()
    try:
        result = await adapter.chat_completion(
            _basic_request(), model="claude-sonnet-4-6", stream=False
        )
    finally:
        await adapter.aclose()
    assert isinstance(result, ChatCompletionResponse)
    msg = result.choices[0].message
    assert msg.content is None
    assert result.choices[0].finish_reason == "tool_calls"
    assert msg.tool_calls is not None
    assert len(msg.tool_calls) == 1
    call = msg.tool_calls[0]
    assert call["id"] == "toolu_01"
    assert call["type"] == "function"
    assert call["function"]["name"] == "get_weather"
    assert json.loads(call["function"]["arguments"]) == {"city": "Paris"}


@pytest.mark.unit
@respx.mock
async def test_from_anthropic_response_text_plus_tool_call() -> None:
    """Text *and* a tool call both survive: ``content`` is the text,
    ``tool_calls`` carries the call."""

    respx.post(f"{ANTHROPIC_BASE}/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_mix",
                "model": "claude-sonnet-4-6",
                "content": [
                    {"type": "text", "text": "Checking the weather."},
                    {
                        "type": "tool_use",
                        "id": "toolu_02",
                        "name": "get_weather",
                        "input": {"city": "Lyon"},
                    },
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 8, "output_tokens": 6},
            },
        )
    )
    adapter = _make_adapter()
    try:
        result = await adapter.chat_completion(
            _basic_request(), model="claude-sonnet-4-6", stream=False
        )
    finally:
        await adapter.aclose()
    assert isinstance(result, ChatCompletionResponse)
    msg = result.choices[0].message
    assert msg.content == "Checking the weather."
    assert msg.tool_calls is not None and len(msg.tool_calls) == 1


SSE_TOOL_FIXTURE_BODY = (
    "event: message_start\n"
    'data: {"type":"message_start","message":{"id":"msg_tstream","model":"claude-sonnet-4-6",'
    '"usage":{"input_tokens":9,"output_tokens":0}}}\n\n'
    "event: content_block_start\n"
    'data: {"type":"content_block_start","index":0,"content_block":'
    '{"type":"tool_use","id":"toolu_s1","name":"get_weather","input":{}}}\n\n'
    "event: content_block_delta\n"
    'data: {"type":"content_block_delta","index":0,"delta":'
    '{"type":"input_json_delta","partial_json":"{\\"city\\":"}}\n\n'
    "event: content_block_delta\n"
    'data: {"type":"content_block_delta","index":0,"delta":'
    '{"type":"input_json_delta","partial_json":" \\"Paris\\"}"}}\n\n'
    "event: content_block_stop\n"
    'data: {"type":"content_block_stop","index":0}\n\n'
    "event: message_delta\n"
    'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},'
    '"usage":{"output_tokens":12}}\n\n'
    "event: message_stop\n"
    'data: {"type":"message_stop"}\n\n'
)


@pytest.mark.unit
@respx.mock
async def test_streaming_accumulates_tool_use_into_tool_calls_delta() -> None:
    """Streamed ``tool_use`` (content_block_start + input_json_delta chunks +
    stop) becomes ONE OpenAI ``tool_calls`` delta carrying the full
    accumulated JSON arguments; the final chunk reports
    ``finish_reason="tool_calls"``."""

    respx.post(f"{ANTHROPIC_BASE}/v1/messages").mock(
        return_value=httpx.Response(
            200,
            text=SSE_TOOL_FIXTURE_BODY,
            headers={"content-type": "text/event-stream"},
        )
    )
    adapter = _make_adapter()
    try:
        result = await adapter.chat_completion(
            _basic_request(stream=True), model="claude-sonnet-4-6", stream=True
        )
        assert not isinstance(result, ChatCompletionResponse)
        chunks = [chunk async for chunk in result]
    finally:
        await adapter.aclose()

    tool_chunks = [c for c in chunks if c.choices[0].delta.tool_calls]
    assert len(tool_chunks) == 1
    call = tool_chunks[0].choices[0].delta.tool_calls[0]
    assert call["index"] == 0
    assert call["id"] == "toolu_s1"
    assert call["function"]["name"] == "get_weather"
    assert json.loads(call["function"]["arguments"]) == {"city": "Paris"}
    assert chunks[-1].choices[0].finish_reason == "tool_calls"
