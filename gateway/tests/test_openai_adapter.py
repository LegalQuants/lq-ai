"""Unit tests for the OpenAI provider adapter (Task C6 / ADR 0008).

Targets the embeddings translation, the auth-header wiring, the
chat-completion-stub posture, error mapping (auth, network, HTTP), and
``from_config`` construction.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.config import ProviderConfig
from app.providers import (
    ChatCompletionChunk,
    ChatCompletionResponse,
    OpenAIAdapter,
    ProviderAuthError,
    ProviderHTTPError,
    ProviderNetworkError,
)
from app.providers.openai_schema import (
    ChatCompletionMessage,
    ChatCompletionRequest,
    EmbeddingsRequest,
)

# --- Construction -------------------------------------------------------


def _provider(provider_type: str = "openai") -> ProviderConfig:
    return ProviderConfig.model_validate(
        {
            "name": "openai-prod",
            "type": provider_type,
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY_TEST",
            "tier": 4,
            "models": ["text-embedding-3-small"],
        }
    )


@pytest.mark.unit
def test_from_config_accepts_openai_provider_with_key() -> None:
    """C6: OpenAI provider with a key in env constructs cleanly."""

    adapter = OpenAIAdapter.from_config(
        _provider(),
        env={"OPENAI_API_KEY_TEST": "sk-test-123"},
    )
    assert adapter.name == "openai-prod"


@pytest.mark.unit
def test_from_config_rejects_wrong_type() -> None:
    """C6: a non-openai provider type raises ValueError."""

    bogus = ProviderConfig.model_validate(
        {
            "name": "x",
            "type": "anthropic",
            "base_url": "https://api.anthropic.com",
            "api_key_env": "ANTHROPIC_API_KEY",
            "tier": 4,
            "models": [],
        }
    )
    with pytest.raises(ValueError, match=r"(?i)provider\.type"):
        OpenAIAdapter.from_config(bogus, env={})


@pytest.mark.unit
def test_from_config_cloud_openai_requires_key() -> None:
    """C6: cloud OpenAI without OPENAI_API_KEY raises ValueError."""

    with pytest.raises(ValueError, match=r"(?i)environment variable"):
        OpenAIAdapter.from_config(_provider(), env={})


@pytest.mark.unit
def test_from_config_openai_compatible_no_key_ok() -> None:
    """C6: openai_compatible (local vLLM/llama-cpp) accepts a missing key."""

    config = ProviderConfig.model_validate(
        {
            "name": "vllm-local",
            "type": "openai_compatible",
            "base_url": "http://vllm:8000/v1",
            "api_key_env": "",
            "tier": 1,
            "models": [],
        }
    )
    adapter = OpenAIAdapter.from_config(config, env={})
    assert adapter.name == "vllm-local"


# --- Embeddings ---------------------------------------------------------


@pytest.mark.unit
async def test_embeddings_happy_path() -> None:
    """C6: a 200 response from upstream translates to EmbeddingsResponse."""

    payload = {
        "object": "list",
        "data": [{"object": "embedding", "embedding": [0.1, 0.2, 0.3], "index": 0}],
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": 5, "total_tokens": 5},
    }
    with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/embeddings").mock(return_value=httpx.Response(200, json=payload))
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                client=client,
            )
            response = await adapter.embeddings(
                EmbeddingsRequest(model="text-embedding-3-small", input="hello"),
                model="text-embedding-3-small",
            )
        finally:
            await client.aclose()
    assert len(response.data) == 1
    assert response.data[0].embedding == [0.1, 0.2, 0.3]
    assert response.usage.prompt_tokens == 5


@pytest.mark.unit
async def test_embeddings_batch_input() -> None:
    """C6: batched input produces multiple data entries."""

    payload = {
        "object": "list",
        "data": [
            {"object": "embedding", "embedding": [0.1], "index": 0},
            {"object": "embedding", "embedding": [0.2], "index": 1},
        ],
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": 4, "total_tokens": 4},
    }
    with respx.mock(base_url="https://api.openai.com/v1") as router:
        route = router.post("/embeddings").mock(return_value=httpx.Response(200, json=payload))
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                client=client,
            )
            response = await adapter.embeddings(
                EmbeddingsRequest(
                    model="text-embedding-3-small",
                    input=["a", "b"],
                ),
                model="text-embedding-3-small",
            )
        finally:
            await client.aclose()
    assert len(response.data) == 2
    # Check the request body had list input.
    sent = route.calls.last.request
    body = sent.content
    assert b'"input":["a","b"]' in body or b'"input": ["a", "b"]' in body


@pytest.mark.unit
async def test_embeddings_dimensions_passthrough() -> None:
    """C6: caller-set ``dimensions`` flows through to the upstream body."""

    payload = {
        "object": "list",
        "data": [{"object": "embedding", "embedding": [0.1], "index": 0}],
        "model": "text-embedding-3-large",
        "usage": {"prompt_tokens": 1, "total_tokens": 1},
    }
    with respx.mock(base_url="https://api.openai.com/v1") as router:
        route = router.post("/embeddings").mock(return_value=httpx.Response(200, json=payload))
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                client=client,
            )
            await adapter.embeddings(
                EmbeddingsRequest(
                    model="text-embedding-3-large",
                    input="hello",
                    dimensions=512,
                ),
                model="text-embedding-3-large",
            )
        finally:
            await client.aclose()
    sent = route.calls.last.request
    assert b'"dimensions":512' in sent.content or b'"dimensions": 512' in sent.content


@pytest.mark.unit
async def test_embeddings_auth_error_translates_to_provider_auth_error() -> None:
    """C6: 401 from upstream raises ProviderAuthError."""

    error_body = {
        "error": {
            "message": "Incorrect API key provided",
            "type": "invalid_request_error",
            "code": "invalid_api_key",
        }
    }
    with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/embeddings").mock(return_value=httpx.Response(401, json=error_body))
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                client=client,
            )
            with pytest.raises(ProviderAuthError):
                await adapter.embeddings(
                    EmbeddingsRequest(model="x", input="y"),
                    model="x",
                )
        finally:
            await client.aclose()


@pytest.mark.unit
async def test_embeddings_500_translates_to_provider_http_error() -> None:
    """C6: 500 from upstream raises ProviderHTTPError with upstream_status."""

    with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/embeddings").mock(
            return_value=httpx.Response(500, json={"error": {"message": "boom"}})
        )
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                client=client,
            )
            with pytest.raises(ProviderHTTPError) as exc_info:
                await adapter.embeddings(
                    EmbeddingsRequest(model="x", input="y"),
                    model="x",
                )
            assert exc_info.value.upstream_status == 500
        finally:
            await client.aclose()


@pytest.mark.unit
async def test_embeddings_network_error_translates() -> None:
    """C6: a transport failure (DNS/TCP) raises ProviderNetworkError."""

    with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/embeddings").mock(side_effect=httpx.ConnectError("boom"))
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                client=client,
            )
            with pytest.raises(ProviderNetworkError):
                await adapter.embeddings(
                    EmbeddingsRequest(model="x", input="y"),
                    model="x",
                )
        finally:
            await client.aclose()


@pytest.mark.unit
async def test_embeddings_authorization_header_set() -> None:
    """C6: cloud OpenAI calls carry a Bearer Authorization header."""

    payload = {
        "object": "list",
        "data": [{"object": "embedding", "embedding": [0.1], "index": 0}],
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": 1, "total_tokens": 1},
    }
    with respx.mock(base_url="https://api.openai.com/v1") as router:
        route = router.post("/embeddings").mock(return_value=httpx.Response(200, json=payload))
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key="sk-test-123",
                client=client,
            )
            await adapter.embeddings(
                EmbeddingsRequest(model="x", input="y"),
                model="x",
            )
        finally:
            await client.aclose()
    sent = route.calls.last.request
    assert sent.headers.get("authorization") == "Bearer sk-test-123"


@pytest.mark.unit
async def test_embeddings_no_authorization_when_no_key() -> None:
    """C6: openai_compatible providers without keys omit the header entirely.

    Some local servers reject any Authorization header outright; we skip
    rather than send 'Bearer ' (empty).
    """

    payload = {
        "object": "list",
        "data": [{"object": "embedding", "embedding": [0.1], "index": 0}],
        "model": "x",
        "usage": {"prompt_tokens": 1, "total_tokens": 1},
    }
    with respx.mock(base_url="http://vllm:8000/v1") as router:
        route = router.post("/embeddings").mock(return_value=httpx.Response(200, json=payload))
        client = httpx.AsyncClient(base_url="http://vllm:8000/v1")
        try:
            adapter = OpenAIAdapter(
                name="vllm-local",
                base_url="http://vllm:8000/v1",
                api_key="",
                client=client,
            )
            await adapter.embeddings(
                EmbeddingsRequest(model="x", input="y"),
                model="x",
            )
        finally:
            await client.aclose()
    sent = route.calls.last.request
    assert "authorization" not in {k.lower() for k in sent.headers}


# --- Chat completions (B6) ----------------------------------------------


def _basic_chat_request(stream: bool = False) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="gpt-4o",
        messages=[
            ChatCompletionMessage(role="system", content="be brief"),
            ChatCompletionMessage(role="user", content="say hi"),
        ],
        max_tokens=64,
        stream=stream,
    )


@pytest.mark.unit
async def test_chat_completion_unary_happy_path() -> None:
    """B6: a 200 response translates to ChatCompletionResponse with usage."""

    payload = {
        "id": "chatcmpl-abc123",
        "object": "chat.completion",
        "created": 1715000000,
        "model": "gpt-4o-2024-08-06",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hi there!"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
    }
    with respx.mock(base_url="https://api.openai.com/v1") as router:
        route = router.post("/chat/completions").mock(
            return_value=httpx.Response(200, json=payload)
        )
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                client=client,
            )
            result = await adapter.chat_completion(
                _basic_chat_request(), model="gpt-4o", stream=False
            )
        finally:
            await client.aclose()
    assert isinstance(result, ChatCompletionResponse)
    assert result.id == "chatcmpl-abc123"
    assert result.choices[0].message.content == "Hi there!"
    assert result.choices[0].finish_reason == "stop"
    assert result.usage.total_tokens == 14
    # The request we sent upstream uses the provider-native model name
    # (not whatever the alias resolved from) and stream=False.
    sent = json.loads(route.calls.last.request.content)
    assert sent["model"] == "gpt-4o"
    assert sent["stream"] is False


@pytest.mark.unit
async def test_chat_completion_strips_lq_ai_extension_keys() -> None:
    """B6: LQ.AI extension fields never leak to OpenAI (it 400s on unknowns)."""

    payload = {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-4o",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1},
    }
    request = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatCompletionMessage(role="user", content="hi")],
        minimum_inference_tier=3,
        skill_name="nda-review",
        lq_ai_skills=["nda-review"],
        lq_ai_chat_id="11111111-1111-1111-1111-111111111111",
        lq_ai_message_id="22222222-2222-2222-2222-222222222222",
        lq_ai_user_id="33333333-3333-3333-3333-333333333333",
        lq_ai_purpose="judge_paraphrase",
        chat_id="audit-tag",
        anonymize=True,
    )
    with respx.mock(base_url="https://api.openai.com/v1") as router:
        route = router.post("/chat/completions").mock(
            return_value=httpx.Response(200, json=payload)
        )
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                client=client,
            )
            await adapter.chat_completion(request, model="gpt-4o", stream=False)
        finally:
            await client.aclose()
    sent = json.loads(route.calls.last.request.content)
    for forbidden in (
        "minimum_inference_tier",
        "lq_ai_project_minimum_inference_tier",
        "skill_name",
        "chat_id",
        "anonymize",
        "lq_ai_skills",
        "lq_ai_skill_inputs",
        "lq_ai_inline_skills",
        "lq_ai_chat_id",
        "lq_ai_message_id",
        "lq_ai_user_id",
        "lq_ai_purpose",
    ):
        assert forbidden not in sent, f"LQ.AI extension {forbidden!r} leaked to OpenAI"


@pytest.mark.unit
async def test_chat_completion_strips_per_message_lq_ai_skip_anonymization() -> None:
    """M2-D2: per-message ``lq_ai_skip_anonymization`` is stripped before sending.

    OpenAI's body validation rejects unknown fields, including
    unknown per-message fields. The api/ sets this flag on the
    retrieval-context system message so the gateway middleware
    leaves the content un-pseudonymized, but the flag itself must
    never leave the gateway — OpenAI would 400.
    """

    payload = {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-4o",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1},
    }
    request = ChatCompletionRequest(
        model="gpt-4o",
        messages=[
            ChatCompletionMessage(
                role="system",
                content="Retrieved context: ...",
                lq_ai_skip_anonymization=True,
            ),
            ChatCompletionMessage(role="user", content="hi"),
        ],
    )
    with respx.mock(base_url="https://api.openai.com/v1") as router:
        route = router.post("/chat/completions").mock(
            return_value=httpx.Response(200, json=payload)
        )
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                client=client,
            )
            await adapter.chat_completion(request, model="gpt-4o", stream=False)
        finally:
            await client.aclose()
    sent = json.loads(route.calls.last.request.content)
    for msg in sent["messages"]:
        assert "lq_ai_skip_anonymization" not in msg, (
            f"per-message LQ.AI extension leaked to OpenAI: {msg}"
        )


@pytest.mark.unit
async def test_chat_completion_inline_skill_body_does_not_leak_to_openai() -> None:
    """Wave D.2 Task 3.0 security — ``lq_ai_inline_skills`` (and the
    verbatim user-drafted body inside it) must NEVER reach OpenAI.

    Regression for the C1 finding in the Task 3.0 code+security review:
    ``lq_ai_inline_skills`` was missing from ``_LQ_AI_EXTENSION_KEYS`` so
    a chat routed through an openai-protocol provider transmitted the
    inline body to ``api.openai.com``. OpenAI 400s on unknown fields but
    the body has already left our gateway by then and lands in OpenAI's
    request logs / error telemetry.
    """

    from app.providers.openai_schema import InlineSkillRef

    payload = {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-4o",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1},
    }
    sentinel = "THIS-MUST-NOT-LEAK-TO-OPENAI-INLINE-BODY-SENTINEL"
    request = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatCompletionMessage(role="user", content="hi")],
        lq_ai_inline_skills=[
            InlineSkillRef(name="__inline__deadbeef", body=sentinel, source="wizard-tryout")
        ],
    )
    with respx.mock(base_url="https://api.openai.com/v1") as router:
        route = router.post("/chat/completions").mock(
            return_value=httpx.Response(200, json=payload)
        )
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                client=client,
            )
            await adapter.chat_completion(request, model="gpt-4o", stream=False)
        finally:
            await client.aclose()

    sent_raw = route.calls.last.request.content
    sent = json.loads(sent_raw)
    assert "lq_ai_inline_skills" not in sent, (
        "lq_ai_inline_skills leaked to OpenAI provider request body"
    )
    # Defense-in-depth: the inline-body sentinel must not appear ANYWHERE
    # in the serialized outbound payload, regardless of which key it
    # nested under.
    assert sentinel not in sent_raw.decode("utf-8"), (
        "verbatim inline_body content leaked to OpenAI provider request body"
    )


@pytest.mark.unit
async def test_chat_completion_forces_model_and_stream() -> None:
    """B6: model + stream on the body are overwritten by adapter args."""

    payload = {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-4o",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1},
    }
    # Caller set model="alias-name" + stream=True; adapter args override.
    request = ChatCompletionRequest(
        model="some-alias",
        messages=[ChatCompletionMessage(role="user", content="hi")],
        stream=True,
    )
    with respx.mock(base_url="https://api.openai.com/v1") as router:
        route = router.post("/chat/completions").mock(
            return_value=httpx.Response(200, json=payload)
        )
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                client=client,
            )
            await adapter.chat_completion(request, model="gpt-4o-mini", stream=False)
        finally:
            await client.aclose()
    sent = json.loads(route.calls.last.request.content)
    assert sent["model"] == "gpt-4o-mini"
    assert sent["stream"] is False


@pytest.mark.unit
async def test_chat_completion_streaming_translates_sse() -> None:
    """B6: OpenAI SSE chunks pass through to ChatCompletionChunk objects."""

    sse_body = (
        'data: {"id":"chatcmpl-s1","object":"chat.completion.chunk","created":1,'
        '"model":"gpt-4o","choices":[{"index":0,"delta":{"role":"assistant"},'
        '"finish_reason":null}]}\n\n'
        'data: {"id":"chatcmpl-s1","object":"chat.completion.chunk","created":1,'
        '"model":"gpt-4o","choices":[{"index":0,"delta":{"content":"Hel"},'
        '"finish_reason":null}]}\n\n'
        'data: {"id":"chatcmpl-s1","object":"chat.completion.chunk","created":1,'
        '"model":"gpt-4o","choices":[{"index":0,"delta":{"content":"lo"},'
        '"finish_reason":null}]}\n\n'
        'data: {"id":"chatcmpl-s1","object":"chat.completion.chunk","created":1,'
        '"model":"gpt-4o","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":7,"completion_tokens":2,"total_tokens":9}}\n\n'
        "data: [DONE]\n\n"
    )
    with respx.mock(base_url="https://api.openai.com/v1") as router:
        route = router.post("/chat/completions").mock(
            return_value=httpx.Response(
                200, text=sse_body, headers={"content-type": "text/event-stream"}
            )
        )
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                client=client,
            )
            result = await adapter.chat_completion(
                _basic_chat_request(stream=True), model="gpt-4o", stream=True
            )
            assert not isinstance(result, ChatCompletionResponse)
            chunks: list[ChatCompletionChunk] = [c async for c in result]
        finally:
            await client.aclose()
    # 1 role chunk + 2 content chunks + 1 final chunk with finish_reason + usage.
    assert len(chunks) == 4
    assert chunks[0].choices[0].delta.role == "assistant"
    assert chunks[1].choices[0].delta.content == "Hel"
    assert chunks[2].choices[0].delta.content == "lo"
    final = chunks[-1]
    assert final.choices[0].finish_reason == "stop"
    assert final.usage is not None
    assert final.usage.total_tokens == 9
    # Streaming opts include_usage so the final usage block arrives.
    sent = json.loads(route.calls.last.request.content)
    assert sent["stream"] is True
    assert sent.get("stream_options", {}).get("include_usage") is True


@pytest.mark.unit
async def test_chat_completion_401_translates_to_auth_error() -> None:
    """B6: a 401 from chat completions raises ProviderAuthError; key not echoed."""

    error_body = {
        "error": {
            "message": "Incorrect API key provided",
            "type": "invalid_request_error",
            "code": "invalid_api_key",
        }
    }
    with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/chat/completions").mock(return_value=httpx.Response(401, json=error_body))
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        secret = "sk-test-do-not-leak"
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key=secret,
                client=client,
            )
            with pytest.raises(ProviderAuthError) as excinfo:
                await adapter.chat_completion(_basic_chat_request(), model="gpt-4o", stream=False)
        finally:
            await client.aclose()
    serialized = json.dumps(excinfo.value.to_envelope())
    assert secret not in serialized
    assert excinfo.value.details.get("upstream_status") == 401


@pytest.mark.unit
async def test_chat_completion_500_translates_to_http_error() -> None:
    """B6: a 500 from chat completions raises ProviderHTTPError."""

    with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/chat/completions").mock(
            return_value=httpx.Response(500, json={"error": {"message": "boom"}})
        )
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                client=client,
            )
            with pytest.raises(ProviderHTTPError) as excinfo:
                await adapter.chat_completion(_basic_chat_request(), model="gpt-4o", stream=False)
        finally:
            await client.aclose()
    assert excinfo.value.upstream_status == 500


@pytest.mark.unit
async def test_chat_completion_network_error_translates() -> None:
    """B6: transport failures raise ProviderNetworkError."""

    with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/chat/completions").mock(side_effect=httpx.ConnectError("boom"))
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                client=client,
            )
            with pytest.raises(ProviderNetworkError):
                await adapter.chat_completion(_basic_chat_request(), model="gpt-4o", stream=False)
        finally:
            await client.aclose()


@pytest.mark.unit
async def test_chat_completion_streaming_upstream_error_raises() -> None:
    """B6: a non-200 on the streaming POST surfaces a structured error,
    not a hung generator."""

    with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/chat/completions").mock(
            return_value=httpx.Response(
                429,
                json={"error": {"message": "rate limited", "type": "rate_limit_error"}},
            )
        )
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                client=client,
            )
            result = await adapter.chat_completion(
                _basic_chat_request(stream=True), model="gpt-4o", stream=True
            )
            with pytest.raises(ProviderHTTPError) as excinfo:
                async for _ in result:  # type: ignore[union-attr]
                    pass
        finally:
            await client.aclose()
    assert excinfo.value.upstream_status == 429


# --- Health --------------------------------------------------------------


@pytest.mark.unit
async def test_health_check_ok() -> None:
    """C6: GET /models 200 means reachable + key accepted."""

    with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.get("/models").mock(return_value=httpx.Response(200, json={"data": []}))
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                client=client,
            )
            health = await adapter.health_check()
        finally:
            await client.aclose()
    assert health.reachable is True
    assert health.error is None


@pytest.mark.unit
async def test_health_check_auth_rejected() -> None:
    """C6: GET /models 401 reports reachable but auth-rejected."""

    with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.get("/models").mock(return_value=httpx.Response(401, json={}))
        client = httpx.AsyncClient(base_url="https://api.openai.com/v1")
        try:
            adapter = OpenAIAdapter(
                name="openai-prod",
                base_url="https://api.openai.com/v1",
                api_key="bad",
                client=client,
            )
            health = await adapter.health_check()
        finally:
            await client.aclose()
    assert health.reachable is True
    assert "auth" in (health.error or "").lower()
