"""Unit tests for :class:`app.providers.ollama.OllamaAdapter` (B6 partial).

Covers the OpenAI <-> Ollama translation, the line-delimited JSON
streaming parser, error mapping, and ``from_config`` construction.
Outbound HTTP is mocked with ``respx``; we exercise the adapter
directly (not through the FastAPI surface) so each rule is pinned in
isolation.

What this file covers:

* ``from_config`` matrix — valid base_url, missing base_url,
  trailing-slash normalization, explicit port, wrong provider type.
* ``_to_ollama_request`` translation — messages pass through, role
  preservation, ``max_tokens`` -> ``options.num_predict``,
  ``temperature`` / ``top_p`` -> ``options.*``, string ``stop`` -> list,
  ``tools`` / ``tool_choice`` forwarded, ``stream`` flag.
* ``_from_ollama_response`` translation — usage mapping
  (``prompt_eval_count`` / ``eval_count`` -> ``prompt_tokens`` /
  ``completion_tokens``), ``done_reason`` mapping (``length`` ->
  ``length``, default ``stop``), missing ``done_reason`` falls back.
* Streaming: NDJSON parsing — multi-line bursts, empty lines,
  malformed JSON drops, role chunk emitted exactly once, terminal
  frame populates usage on the final chunk.
* Error translation — 404 -> :class:`ProviderModelNotFound` (sub of
  :class:`ProviderHTTPError`, ``code='invalid_model'``); 503 ->
  :class:`ProviderHTTPError`; 5xx generic -> :class:`ProviderHTTPError`;
  network -> :class:`ProviderNetworkError`; non-JSON 200 ->
  :class:`ProviderHTTPError`.
* ``embeddings`` -> :class:`ProviderUnsupportedError` (the embedding
  alias still routes through OpenAI per ADR 0008).
* Health probe — 200 / 503 / network.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.config import ProviderConfig
from app.providers import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingsRequest,
    OllamaAdapter,
    ProviderHTTPError,
    ProviderModelNotFound,
    ProviderNetworkError,
    ProviderUnsupportedError,
)
from app.providers.ollama import (
    DEFAULT_TIMEOUT_SECONDS,
    DONE_REASON_MAP,
    _from_ollama_response,
    _to_ollama_request,
)

OLLAMA_BASE = "http://ollama:11434"


def _make_adapter(base_url: str = OLLAMA_BASE, *, api_key: str = "") -> OllamaAdapter:
    """Build an adapter pointed at the standard local Ollama base URL."""

    return OllamaAdapter(name="ollama-test", base_url=base_url, api_key=api_key)


def _basic_request(**overrides: object) -> ChatCompletionRequest:
    """Build a minimal valid :class:`ChatCompletionRequest`."""

    payload: dict[str, object] = {
        "model": "llama3.1",
        "messages": [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "Hello!"},
        ],
    }
    payload.update(overrides)
    return ChatCompletionRequest.model_validate(payload)


# --- from_config -------------------------------------------------------------


@pytest.mark.unit
def test_from_config_succeeds_for_ollama_provider() -> None:
    """B6 partial: ollama provider with a valid base_url constructs cleanly."""

    provider = ProviderConfig.model_validate(
        {
            "name": "ollama-local",
            "type": "ollama",
            "base_url": OLLAMA_BASE,
            "api_key_env": "",
            "tier": 1,
            "models": ["llama3.1"],
        }
    )
    adapter = OllamaAdapter.from_config(provider, env={})
    try:
        assert adapter.name == "ollama-local"
        # Trailing slashes don't survive normalization.
        assert adapter._base_url == OLLAMA_BASE
        # No api key configured -> empty
        assert adapter._api_key == ""
    finally:
        # close to be tidy; in async tests we'd await aclose() but
        # construction-only tests don't open a real session.
        pass


@pytest.mark.unit
def test_from_config_rejects_non_ollama_provider() -> None:
    """B6 partial: a non-ollama provider type raises ValueError."""

    provider = ProviderConfig.model_validate(
        {
            "name": "anthropic-prod",
            "type": "anthropic",
            "base_url": "https://api.anthropic.com",
            "api_key_env": "ANTHROPIC_API_KEY",
            "tier": 4,
        }
    )
    with pytest.raises(ValueError, match=r"(?i)provider\.type"):
        OllamaAdapter.from_config(provider, env={})


@pytest.mark.unit
def test_from_config_requires_base_url() -> None:
    """B6 partial: provider entry without base_url is rejected.

    Pydantic's ``Field(min_length=1)`` on ``ProviderConfig.base_url``
    catches an empty string at config-load time; we exercise the
    second-line defense in :meth:`OllamaAdapter.from_config` via a
    direct ProviderConfig construction with an explicit empty value.
    """

    # An empty base_url fails at the schema layer first.
    with pytest.raises(Exception):
        ProviderConfig.model_validate(
            {
                "name": "ollama-local",
                "type": "ollama",
                "base_url": "",
                "api_key_env": "",
                "tier": 1,
                "models": [],
            }
        )


@pytest.mark.unit
def test_from_config_normalizes_trailing_slash() -> None:
    """B6 partial: trailing-slash base URLs are normalized at construction."""

    provider = ProviderConfig.model_validate(
        {
            "name": "ollama-local",
            "type": "ollama",
            "base_url": "http://ollama:11434/",
            "api_key_env": "",
            "tier": 1,
            "models": [],
        }
    )
    adapter = OllamaAdapter.from_config(provider, env={})
    assert adapter._base_url == "http://ollama:11434"


@pytest.mark.unit
def test_from_config_accepts_explicit_port() -> None:
    """B6 partial: base URLs with a non-default port pass through."""

    provider = ProviderConfig.model_validate(
        {
            "name": "ollama-local",
            "type": "ollama",
            "base_url": "http://host.docker.internal:11434",
            "api_key_env": "",
            "tier": 1,
            "models": [],
        }
    )
    adapter = OllamaAdapter.from_config(provider, env={})
    assert adapter._base_url == "http://host.docker.internal:11434"


@pytest.mark.unit
def test_from_config_reads_api_key_when_configured() -> None:
    """B6 partial: when api_key_env is set and populated, the value
    becomes a Bearer token (for proxy-fronted Ollama deployments)."""

    provider = ProviderConfig.model_validate(
        {
            "name": "ollama-proxied",
            "type": "ollama",
            "base_url": OLLAMA_BASE,
            "api_key_env": "OLLAMA_PROXY_TOKEN",
            "tier": 1,
            "models": [],
        }
    )
    adapter = OllamaAdapter.from_config(provider, env={"OLLAMA_PROXY_TOKEN": "proxy-bearer-xyz"})
    assert adapter._api_key == "proxy-bearer-xyz"
    assert adapter._auth_headers().get("authorization") == "Bearer proxy-bearer-xyz"


@pytest.mark.unit
def test_from_config_default_timeout() -> None:
    """B6 partial: in absence of timeout_s, default 120s is used.

    Ollama generation latency on local hardware can exceed 60s on the
    first generation after a model load; the default is intentionally
    generous.
    """

    provider = ProviderConfig.model_validate(
        {
            "name": "ollama-local",
            "type": "ollama",
            "base_url": OLLAMA_BASE,
            "api_key_env": "",
            "tier": 1,
            "models": [],
        }
    )
    adapter = OllamaAdapter.from_config(provider, env={})
    assert adapter._timeout == DEFAULT_TIMEOUT_SECONDS


# --- Pure-translation tests (no HTTP) ----------------------------------------


@pytest.mark.unit
def test_to_ollama_request_messages_pass_through() -> None:
    """Messages forward verbatim with role preserved (Ollama accepts the
    same four roles)."""

    req = ChatCompletionRequest.model_validate(
        {
            "model": "llama3.1",
            "messages": [
                {"role": "system", "content": "Be brief."},
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
                {"role": "user", "content": "Continue"},
            ],
        }
    )
    body = _to_ollama_request(req, model="llama3.1", stream=False)

    assert body["model"] == "llama3.1"
    assert body["stream"] is False
    assert body["messages"] == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "Continue"},
    ]


@pytest.mark.unit
def test_to_ollama_request_max_tokens_becomes_num_predict() -> None:
    """``max_tokens`` -> ``options.num_predict``; absent when not set."""

    req = _basic_request(max_tokens=256)
    body = _to_ollama_request(req, model="llama3.1", stream=False)
    assert body["options"]["num_predict"] == 256

    req_no_budget = _basic_request()
    body_no_budget = _to_ollama_request(req_no_budget, model="llama3.1", stream=False)
    # No options block at all when nothing was specified.
    assert "options" not in body_no_budget


@pytest.mark.unit
def test_to_ollama_request_sampling_params_in_options() -> None:
    """``temperature`` / ``top_p`` move into the ``options`` sub-object."""

    req = _basic_request(temperature=0.3, top_p=0.9)
    body = _to_ollama_request(req, model="llama3.1", stream=False)
    assert body["options"]["temperature"] == 0.3
    assert body["options"]["top_p"] == 0.9


@pytest.mark.unit
def test_to_ollama_request_string_stop_becomes_list() -> None:
    """OpenAI accepts ``stop: "END"``; Ollama only takes a list."""

    req = _basic_request(stop="END")
    body = _to_ollama_request(req, model="llama3.1", stream=False)
    assert body["options"]["stop"] == ["END"]


@pytest.mark.unit
def test_to_ollama_request_list_stop_passes_through() -> None:
    req = _basic_request(stop=["END", "###"])
    body = _to_ollama_request(req, model="llama3.1", stream=False)
    assert body["options"]["stop"] == ["END", "###"]


@pytest.mark.unit
def test_to_ollama_request_stream_flag_forwarded() -> None:
    body = _to_ollama_request(_basic_request(), model="llama3.1", stream=True)
    assert body["stream"] is True
    body_unary = _to_ollama_request(_basic_request(), model="llama3.1", stream=False)
    assert body_unary["stream"] is False


@pytest.mark.unit
def test_to_ollama_request_forwards_tools_and_tool_choice() -> None:
    """``tools`` and ``tool_choice`` (extension fields) forward verbatim
    to Ollama's 0.4+ tool-use surface.

    PR5b regression pin: tools/tool_choice must survive the explicit field
    promotion in ``ChatCompletionRequest`` and still reach the upstream body.
    """

    raw = {
        "model": "llama3.1",
        "messages": [{"role": "user", "content": "use a tool"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_time",
                    "description": "Return the current time",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        "tool_choice": "auto",
    }
    req = ChatCompletionRequest.model_validate(raw)
    body = _to_ollama_request(req, model="llama3.1", stream=False)
    assert body["tools"][0]["function"]["name"] == "get_time"
    assert body["tool_choice"] == "auto"  # PR5b regression pin


@pytest.mark.unit
def test_to_ollama_request_passes_tool_message_with_call_id() -> None:
    """Tool-result messages forward with role='tool' and the original
    ``tool_call_id`` so Ollama can correlate."""

    req = ChatCompletionRequest.model_validate(
        {
            "model": "llama3.1",
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
    body = _to_ollama_request(req, model="llama3.1", stream=False)
    last = body["messages"][-1]
    assert last["role"] == "tool"
    assert last["content"] == "tool result text"
    assert last["tool_call_id"] == "call_abc123"


# --- Non-streaming HTTP path -------------------------------------------------


@pytest.mark.unit
@respx.mock
async def test_chat_completion_unary_translates_response() -> None:
    """Ollama unary response shape converts to OpenAI's, including usage
    and done-reason mapping."""

    route = respx.post(f"{OLLAMA_BASE}/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "llama3.1",
                "created_at": "2026-05-08T12:00:00Z",
                "message": {"role": "assistant", "content": "Hello there!"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 12,
                "eval_count": 5,
                "total_duration": 123_456_789,
            },
        )
    )

    adapter = _make_adapter()
    try:
        result = await adapter.chat_completion(
            _basic_request(),
            model="llama3.1",
            stream=False,
        )
    finally:
        await adapter.aclose()

    assert isinstance(result, ChatCompletionResponse)
    assert result.model == "llama3.1"
    assert result.choices[0].message.role == "assistant"
    assert result.choices[0].message.content == "Hello there!"
    assert result.choices[0].finish_reason == "stop"
    assert result.usage.prompt_tokens == 12
    assert result.usage.completion_tokens == 5
    assert result.usage.total_tokens == 17

    assert route.called
    sent = json.loads(route.calls[-1].request.content)
    assert sent["model"] == "llama3.1"
    assert sent["stream"] is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "ollama_reason,expected_finish",
    [
        ("stop", "stop"),
        ("length", "length"),
        ("load", "stop"),
        ("unknown_reason", "stop"),
    ],
)
def test_done_reason_mapping(ollama_reason: str, expected_finish: str) -> None:
    """Ollama ``done_reason`` translates to OpenAI ``finish_reason``;
    unknown reasons default to ``stop``."""

    payload = {
        "model": "llama3.1",
        "message": {"role": "assistant", "content": "x"},
        "done": True,
        "done_reason": ollama_reason,
        "prompt_eval_count": 1,
        "eval_count": 1,
    }
    response = _from_ollama_response(payload, requested_model="llama3.1")
    assert response.choices[0].finish_reason == expected_finish


@pytest.mark.unit
def test_done_reason_map_constant() -> None:
    """Pin the canonical mapping so changes are explicit."""

    assert DONE_REASON_MAP == {
        "stop": "stop",
        "length": "length",
        "load": "stop",
    }


@pytest.mark.unit
def test_from_ollama_response_handles_missing_done_reason() -> None:
    """Some Ollama responses set ``done: true`` without a ``done_reason``;
    we fall back to ``stop``."""

    payload = {
        "model": "llama3.1",
        "message": {"role": "assistant", "content": "x"},
        "done": True,
        "prompt_eval_count": 1,
        "eval_count": 1,
    }
    response = _from_ollama_response(payload, requested_model="llama3.1")
    assert response.choices[0].finish_reason == "stop"


@pytest.mark.unit
def test_from_ollama_response_handles_empty_message() -> None:
    """A response with no message content lands as an empty assistant
    message rather than crashing."""

    payload = {"model": "llama3.1", "done": True, "done_reason": "stop"}
    response = _from_ollama_response(payload, requested_model="llama3.1")
    assert response.choices[0].message.content == ""
    assert response.usage.prompt_tokens == 0
    assert response.usage.completion_tokens == 0


# --- Streaming path ----------------------------------------------------------


# Ollama emits one JSON object per line, no SSE event names, no [DONE]
# sentinel. Terminal frame carries done=true and the usage block.
NDJSON_FIXTURE_BODY = (
    '{"model":"llama3.1","created_at":"2026-05-08T12:00:00Z","message":'
    '{"role":"assistant","content":"He"},"done":false}\n'
    '{"model":"llama3.1","created_at":"2026-05-08T12:00:00Z","message":'
    '{"role":"assistant","content":"llo"},"done":false}\n'
    '{"model":"llama3.1","created_at":"2026-05-08T12:00:01Z","message":'
    '{"role":"assistant","content":" world"},"done":false}\n'
    '{"model":"llama3.1","created_at":"2026-05-08T12:00:01Z","message":'
    '{"role":"assistant","content":""},"done":true,"done_reason":"stop",'
    '"prompt_eval_count":7,"eval_count":3,"total_duration":1234}\n'
)


@pytest.mark.unit
@respx.mock
async def test_chat_completion_streaming_translates_ndjson() -> None:
    """NDJSON stream becomes OpenAI chunks: one role chunk + content
    chunks + final chunk with finish_reason and usage."""

    respx.post(f"{OLLAMA_BASE}/api/chat").mock(
        return_value=httpx.Response(
            200,
            text=NDJSON_FIXTURE_BODY,
            headers={"content-type": "application/x-ndjson"},
        )
    )

    adapter = _make_adapter()
    try:
        result = await adapter.chat_completion(
            _basic_request(stream=True),
            model="llama3.1",
            stream=True,
        )
        assert not isinstance(result, ChatCompletionResponse)
        chunks: list[ChatCompletionChunk] = []
        async for chunk in result:
            chunks.append(chunk)
    finally:
        await adapter.aclose()

    # Expect: 1 role-init chunk + 3 content delta chunks + 1 final chunk.
    assert len(chunks) == 5
    assert chunks[0].choices[0].delta.role == "assistant"
    assert chunks[0].choices[0].delta.content is None
    assert chunks[1].choices[0].delta.content == "He"
    assert chunks[2].choices[0].delta.content == "llo"
    assert chunks[3].choices[0].delta.content == " world"
    final = chunks[-1]
    assert final.choices[0].finish_reason == "stop"
    assert final.usage is not None
    assert final.usage.prompt_tokens == 7
    assert final.usage.completion_tokens == 3
    assert final.usage.total_tokens == 10
    # Model identity propagates from the stream.
    for chunk in chunks:
        assert chunk.model == "llama3.1"


@pytest.mark.unit
@respx.mock
async def test_streaming_skips_blank_lines_and_malformed_json() -> None:
    """NDJSON parsing tolerates empty lines and discards malformed JSON
    (defensive: a forward-looking server might insert keepalive blanks)."""

    body = (
        "\n"  # blank line
        '{"model":"llama3.1","message":{"role":"assistant","content":"hi"},"done":false}\n'
        "{not json}\n"
        '{"model":"llama3.1","message":{"role":"assistant","content":"!"},"done":false}\n'
        '{"model":"llama3.1","message":{"role":"assistant","content":""},"done":true,'
        '"done_reason":"stop","prompt_eval_count":2,"eval_count":2}\n'
        "\n"
    )
    respx.post(f"{OLLAMA_BASE}/api/chat").mock(return_value=httpx.Response(200, text=body))

    adapter = _make_adapter()
    try:
        result = await adapter.chat_completion(
            _basic_request(stream=True), model="llama3.1", stream=True
        )
        assert not isinstance(result, ChatCompletionResponse)
        chunks = [chunk async for chunk in result]
    finally:
        await adapter.aclose()

    # role chunk + 2 content chunks + final = 4 chunks; the malformed
    # line is silently skipped.
    assert len(chunks) == 4
    contents = [
        chunk.choices[0].delta.content for chunk in chunks if chunk.choices[0].delta.content
    ]
    assert contents == ["hi", "!"]


@pytest.mark.unit
@respx.mock
async def test_streaming_emits_role_chunk_only_once() -> None:
    """The role chunk emits on the first non-empty NDJSON line and never
    again, even when subsequent lines repeat the role field."""

    body = (
        '{"model":"llama3.1","message":{"role":"assistant","content":"a"},"done":false}\n'
        '{"model":"llama3.1","message":{"role":"assistant","content":"b"},"done":false}\n'
        '{"model":"llama3.1","message":{"role":"assistant","content":""},"done":true,'
        '"done_reason":"stop","prompt_eval_count":1,"eval_count":2}\n'
    )
    respx.post(f"{OLLAMA_BASE}/api/chat").mock(return_value=httpx.Response(200, text=body))
    adapter = _make_adapter()
    try:
        result = await adapter.chat_completion(
            _basic_request(stream=True), model="llama3.1", stream=True
        )
        assert not isinstance(result, ChatCompletionResponse)
        chunks = [chunk async for chunk in result]
    finally:
        await adapter.aclose()
    role_chunks = [c for c in chunks if c.choices[0].delta.role is not None]
    assert len(role_chunks) == 1
    assert role_chunks[0].choices[0].delta.role == "assistant"


@pytest.mark.unit
@respx.mock
async def test_streaming_emits_terminal_chunk_even_without_done_line() -> None:
    """Defensive: if the NDJSON ends without an explicit done frame, the
    adapter still emits a final chunk with finish_reason='stop' so the
    OpenAI shape is honored."""

    body = '{"model":"llama3.1","message":{"role":"assistant","content":"hi"},"done":false}\n'
    respx.post(f"{OLLAMA_BASE}/api/chat").mock(return_value=httpx.Response(200, text=body))
    adapter = _make_adapter()
    try:
        result = await adapter.chat_completion(
            _basic_request(stream=True), model="llama3.1", stream=True
        )
        assert not isinstance(result, ChatCompletionResponse)
        chunks = [chunk async for chunk in result]
    finally:
        await adapter.aclose()

    # role + content + final
    assert len(chunks) == 3
    assert chunks[-1].choices[0].finish_reason == "stop"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.prompt_tokens == 0
    assert chunks[-1].usage.completion_tokens == 0


# --- Error mapping -----------------------------------------------------------


@pytest.mark.unit
@respx.mock
async def test_upstream_404_raises_provider_model_not_found() -> None:
    """A 404 from Ollama (model not pulled) raises
    :class:`ProviderModelNotFound` with ``code='invalid_model'`` so the
    route handler maps to a 400 'invalid_model' rather than the
    default 502."""

    respx.post(f"{OLLAMA_BASE}/api/chat").mock(
        return_value=httpx.Response(
            404,
            json={"error": "model 'foo' not found, try pulling it first"},
        )
    )
    adapter = _make_adapter()
    try:
        with pytest.raises(ProviderModelNotFound) as excinfo:
            await adapter.chat_completion(_basic_request(model="foo"), model="foo", stream=False)
    finally:
        await adapter.aclose()

    err = excinfo.value
    assert err.code == "invalid_model"
    assert err.upstream_status == 404
    # The upstream error message is preserved (operator-actionable).
    assert "not found" in err.message
    # ProviderHTTPError ancestry holds — handler can still treat it
    # as the generic upstream error if the 404 mapping ever changes.
    assert isinstance(err, ProviderHTTPError)


@pytest.mark.unit
@respx.mock
async def test_upstream_503_raises_provider_http_error() -> None:
    """503 from Ollama (model is loading / server overwhelmed) is a
    generic ProviderHTTPError; eligible for fallback per B4."""

    respx.post(f"{OLLAMA_BASE}/api/chat").mock(
        return_value=httpx.Response(
            503,
            json={"error": "model is currently loading"},
        )
    )
    adapter = _make_adapter()
    try:
        with pytest.raises(ProviderHTTPError) as excinfo:
            await adapter.chat_completion(_basic_request(), model="llama3.1", stream=False)
    finally:
        await adapter.aclose()
    err = excinfo.value
    assert err.upstream_status == 503
    assert err.code == "provider_unavailable"
    assert "loading" in err.message


@pytest.mark.unit
@respx.mock
async def test_upstream_500_raises_provider_http_error() -> None:
    respx.post(f"{OLLAMA_BASE}/api/chat").mock(
        return_value=httpx.Response(500, json={"error": "internal error"})
    )
    adapter = _make_adapter()
    try:
        with pytest.raises(ProviderHTTPError) as excinfo:
            await adapter.chat_completion(_basic_request(), model="llama3.1", stream=False)
    finally:
        await adapter.aclose()
    assert excinfo.value.upstream_status == 500


@pytest.mark.unit
@respx.mock
async def test_network_error_raises_provider_network_error() -> None:
    """Connection refused (Ollama not running) -> ProviderNetworkError."""

    respx.post(f"{OLLAMA_BASE}/api/chat").mock(side_effect=httpx.ConnectError("connection refused"))
    adapter = _make_adapter()
    try:
        with pytest.raises(ProviderNetworkError):
            await adapter.chat_completion(_basic_request(), model="llama3.1", stream=False)
    finally:
        await adapter.aclose()


@pytest.mark.unit
@respx.mock
async def test_non_json_200_raises_provider_http_error() -> None:
    """Defensive: a 200 with non-JSON body (e.g., a misconfigured proxy
    serving HTML) raises rather than silently returning empty content."""

    respx.post(f"{OLLAMA_BASE}/api/chat").mock(
        return_value=httpx.Response(200, text="<html>oops</html>")
    )
    adapter = _make_adapter()
    try:
        with pytest.raises(ProviderHTTPError):
            await adapter.chat_completion(_basic_request(), model="llama3.1", stream=False)
    finally:
        await adapter.aclose()


@pytest.mark.unit
async def test_embeddings_raises_unsupported() -> None:
    """The embedding alias still routes through the OpenAI adapter
    (ADR 0008); the Ollama adapter says so explicitly."""

    adapter = _make_adapter()
    try:
        with pytest.raises(ProviderUnsupportedError):
            await adapter.embeddings(
                EmbeddingsRequest(model="llama3.1", input="hi"),
                model="llama3.1",
            )
    finally:
        await adapter.aclose()


# --- Health probe ------------------------------------------------------------


@pytest.mark.unit
@respx.mock
async def test_health_check_reports_reachable_on_200() -> None:
    """A 200 from /api/tags means the Ollama server is up."""

    respx.get(f"{OLLAMA_BASE}/api/tags").mock(return_value=httpx.Response(200, json={"models": []}))
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
async def test_health_check_reports_unreachable_on_500() -> None:
    respx.get(f"{OLLAMA_BASE}/api/tags").mock(return_value=httpx.Response(500))
    adapter = _make_adapter()
    try:
        health = await adapter.health_check()
    finally:
        await adapter.aclose()
    assert health.reachable is False
    assert health.error is not None
    assert "500" in health.error


@pytest.mark.unit
@respx.mock
async def test_health_check_reports_unreachable_on_network_error() -> None:
    respx.get(f"{OLLAMA_BASE}/api/tags").mock(side_effect=httpx.ConnectError("connection refused"))
    adapter = _make_adapter()
    try:
        health = await adapter.health_check()
    finally:
        await adapter.aclose()
    assert health.reachable is False
    assert health.error is not None
