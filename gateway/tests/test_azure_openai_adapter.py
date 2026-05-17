"""Unit tests for the Azure OpenAI provider adapter (M2-E1 / DE-267).

The Azure adapter subclasses :class:`OpenAIAdapter` so most behavior
(body translation, LQ.AI extension-key strip, SSE parsing, error
mapping) is exercised by the OpenAI test suite. This file targets the
Azure-specific differences:

* URL construction (deployment-scoped path + ``api-version`` query).
* Auth header shape (``api-key`` vs ``Authorization: Bearer``).
* ``from_config`` validation of ``type``, ``api_version``, and key.

Plus enough chat/embeddings/streaming/health round-trips to pin the
wiring against drift from the OpenAI side.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.config import ProviderConfig
from app.providers import (
    AzureOpenAIAdapter,
    ChatCompletionChunk,
    ChatCompletionResponse,
    ProviderAuthError,
    ProviderHTTPError,
    ProviderNetworkError,
)
from app.providers.openai_schema import (
    ChatCompletionMessage,
    ChatCompletionRequest,
    EmbeddingsRequest,
)

AZURE_BASE = "https://test-resource.openai.azure.com"
AZURE_API_VERSION = "2024-10-21"
AZURE_DEPLOYMENT = "gpt-4o-prod"
AZURE_CHAT_PATH = (
    f"/openai/deployments/{AZURE_DEPLOYMENT}/chat/completions?api-version={AZURE_API_VERSION}"
)
AZURE_EMBED_PATH = (
    f"/openai/deployments/{AZURE_DEPLOYMENT}/embeddings?api-version={AZURE_API_VERSION}"
)
AZURE_MODELS_PATH = f"/openai/models?api-version={AZURE_API_VERSION}"


# --- Construction -------------------------------------------------------


def _azure_provider(
    *,
    api_version: str | None = AZURE_API_VERSION,
    api_key_env: str = "AZURE_OPENAI_API_KEY_TEST",
) -> ProviderConfig:
    payload: dict[str, object] = {
        "name": "azure-test",
        "type": "azure_openai",
        "base_url": AZURE_BASE,
        "api_key_env": api_key_env,
        "tier": 3,
        "models": [AZURE_DEPLOYMENT],
    }
    if api_version is not None:
        payload["api_version"] = api_version
    return ProviderConfig.model_validate(payload)


@pytest.mark.unit
def test_from_config_accepts_azure_provider_with_key() -> None:
    """M2-E1: a fully configured Azure provider constructs cleanly."""

    adapter = AzureOpenAIAdapter.from_config(
        _azure_provider(),
        env={"AZURE_OPENAI_API_KEY_TEST": "az-key-123"},
    )
    assert adapter.name == "azure-test"


@pytest.mark.unit
def test_from_config_rejects_wrong_type() -> None:
    """M2-E1: a non-azure_openai type raises ValueError."""

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
        AzureOpenAIAdapter.from_config(bogus, env={})


@pytest.mark.unit
def test_from_config_requires_key() -> None:
    """M2-E1: Azure without the API key in env raises ValueError.

    M2-E1 ships API-key auth only; Azure AD is deferred to a follow-on
    DE. Operators without a key cannot construct the adapter.
    """

    with pytest.raises(ValueError, match=r"(?i)environment variable"):
        AzureOpenAIAdapter.from_config(_azure_provider(), env={})


@pytest.mark.unit
def test_from_config_requires_api_version() -> None:
    """M2-E1: ``api_version`` is required (no silent default).

    Azure rolls capabilities in/out per api-version; a default would
    mask capability changes. Operators must pin a version explicitly.
    """

    with pytest.raises(ValueError, match=r"(?i)api_version"):
        AzureOpenAIAdapter.from_config(
            _azure_provider(api_version=None),
            env={"AZURE_OPENAI_API_KEY_TEST": "az-key-123"},
        )


# --- Auth header --------------------------------------------------------


@pytest.mark.unit
async def test_chat_completion_uses_api_key_header() -> None:
    """M2-E1: Azure auth is ``api-key: <key>``, not Bearer."""

    payload = {
        "id": "chatcmpl-az-1",
        "object": "chat.completion",
        "created": 0,
        "model": AZURE_DEPLOYMENT,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hi"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    with respx.mock(base_url=AZURE_BASE) as router:
        route = router.post(AZURE_CHAT_PATH).mock(return_value=httpx.Response(200, json=payload))
        client = httpx.AsyncClient(base_url=AZURE_BASE)
        try:
            adapter = AzureOpenAIAdapter(
                name="azure-test",
                base_url=AZURE_BASE,
                api_key="az-key-do-not-leak",
                api_version=AZURE_API_VERSION,
                client=client,
            )
            await adapter.chat_completion(
                ChatCompletionRequest(
                    model="alias",
                    messages=[ChatCompletionMessage(role="user", content="hi")],
                ),
                model=AZURE_DEPLOYMENT,
                stream=False,
            )
        finally:
            await client.aclose()
    sent = route.calls.last.request
    assert sent.headers.get("api-key") == "az-key-do-not-leak"
    # OpenAI's Bearer auth must not be set on Azure calls.
    assert "authorization" not in {k.lower() for k in sent.headers}


# --- URL construction ---------------------------------------------------


@pytest.mark.unit
async def test_chat_completion_uses_deployment_scoped_url() -> None:
    """M2-E1: the ``model`` argument is the Azure deployment-id.

    The gateway's alias map resolves the caller's alias to a
    deployment-id; the adapter substitutes it into the URL path and
    appends ``api-version`` as a query parameter.
    """

    payload = {
        "id": "chatcmpl-az-2",
        "object": "chat.completion",
        "created": 0,
        "model": AZURE_DEPLOYMENT,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    with respx.mock(base_url=AZURE_BASE) as router:
        route = router.post(AZURE_CHAT_PATH).mock(return_value=httpx.Response(200, json=payload))
        client = httpx.AsyncClient(base_url=AZURE_BASE)
        try:
            adapter = AzureOpenAIAdapter(
                name="azure-test",
                base_url=AZURE_BASE,
                api_key="az-key",
                api_version=AZURE_API_VERSION,
                client=client,
            )
            result = await adapter.chat_completion(
                ChatCompletionRequest(
                    model="alias",
                    messages=[ChatCompletionMessage(role="user", content="hi")],
                ),
                model=AZURE_DEPLOYMENT,
                stream=False,
            )
        finally:
            await client.aclose()
    assert isinstance(result, ChatCompletionResponse)
    sent = route.calls.last.request
    assert AZURE_DEPLOYMENT in str(sent.url)
    assert f"api-version={AZURE_API_VERSION}" in str(sent.url)


# --- Inherited behavior: extension-key strip ----------------------------


@pytest.mark.unit
async def test_chat_completion_strips_lq_ai_extension_keys() -> None:
    """M2-E1: LQ.AI extension fields must not leak to Azure either.

    Azure mirrors OpenAI's body validation — unknown fields produce a
    400. The strip happens in ``_to_openai_request`` which the Azure
    subclass reuses verbatim; this test pins that the path is exercised.
    """

    payload = {
        "id": "az-x",
        "object": "chat.completion",
        "created": 0,
        "model": AZURE_DEPLOYMENT,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": ""},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1},
    }
    request = ChatCompletionRequest(
        model="alias",
        messages=[ChatCompletionMessage(role="user", content="hi")],
        minimum_inference_tier=3,
        skill_name="nda-review",
        lq_ai_skills=["nda-review"],
        lq_ai_chat_id="11111111-1111-1111-1111-111111111111",
    )
    with respx.mock(base_url=AZURE_BASE) as router:
        route = router.post(AZURE_CHAT_PATH).mock(return_value=httpx.Response(200, json=payload))
        client = httpx.AsyncClient(base_url=AZURE_BASE)
        try:
            adapter = AzureOpenAIAdapter(
                name="azure-test",
                base_url=AZURE_BASE,
                api_key="az-key",
                api_version=AZURE_API_VERSION,
                client=client,
            )
            await adapter.chat_completion(request, model=AZURE_DEPLOYMENT, stream=False)
        finally:
            await client.aclose()
    sent = json.loads(route.calls.last.request.content)
    for forbidden in (
        "minimum_inference_tier",
        "skill_name",
        "lq_ai_skills",
        "lq_ai_chat_id",
    ):
        assert forbidden not in sent, f"LQ.AI extension {forbidden!r} leaked to Azure"
    # Body still carries the provider-native deployment-id under "model".
    assert sent["model"] == AZURE_DEPLOYMENT


# --- Streaming ----------------------------------------------------------


@pytest.mark.unit
async def test_chat_completion_streaming_translates_sse() -> None:
    """M2-E1: Azure SSE streaming reuses the OpenAI iterator with the
    Azure deployment-scoped path."""

    sse_body = (
        'data: {"id":"az-s1","object":"chat.completion.chunk","created":1,'
        f'"model":"{AZURE_DEPLOYMENT}","choices":[{{"index":0,'
        '"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
        'data: {"id":"az-s1","object":"chat.completion.chunk","created":1,'
        f'"model":"{AZURE_DEPLOYMENT}","choices":[{{"index":0,'
        '"delta":{"content":"Hi"},"finish_reason":null}]}\n\n'
        'data: {"id":"az-s1","object":"chat.completion.chunk","created":1,'
        f'"model":"{AZURE_DEPLOYMENT}","choices":[{{"index":0,'
        '"delta":{},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":3,"completion_tokens":1,"total_tokens":4}}\n\n'
        "data: [DONE]\n\n"
    )
    with respx.mock(base_url=AZURE_BASE) as router:
        route = router.post(AZURE_CHAT_PATH).mock(
            return_value=httpx.Response(
                200, text=sse_body, headers={"content-type": "text/event-stream"}
            )
        )
        client = httpx.AsyncClient(base_url=AZURE_BASE)
        try:
            adapter = AzureOpenAIAdapter(
                name="azure-test",
                base_url=AZURE_BASE,
                api_key="az-key",
                api_version=AZURE_API_VERSION,
                client=client,
            )
            result = await adapter.chat_completion(
                ChatCompletionRequest(
                    model="alias",
                    messages=[ChatCompletionMessage(role="user", content="hi")],
                    stream=True,
                ),
                model=AZURE_DEPLOYMENT,
                stream=True,
            )
            assert not isinstance(result, ChatCompletionResponse)
            chunks: list[ChatCompletionChunk] = [c async for c in result]
        finally:
            await client.aclose()
    assert len(chunks) == 3
    assert chunks[0].choices[0].delta.role == "assistant"
    assert chunks[1].choices[0].delta.content == "Hi"
    final = chunks[-1]
    assert final.choices[0].finish_reason == "stop"
    # ``include_usage`` is opt-in on the OpenAI side; the strip-and-reuse
    # path means Azure also opts in, and Azure honors it.
    sent = json.loads(route.calls.last.request.content)
    assert sent["stream"] is True
    assert sent.get("stream_options", {}).get("include_usage") is True


# --- Error mapping ------------------------------------------------------


@pytest.mark.unit
async def test_chat_completion_401_translates_to_auth_error() -> None:
    """M2-E1: a 401 from Azure raises ProviderAuthError; key not echoed."""

    error_body = {
        "error": {
            "message": "Access denied due to invalid subscription key",
            "type": "invalid_request_error",
            "code": "401",
        }
    }
    secret = "az-key-do-not-leak"
    with respx.mock(base_url=AZURE_BASE) as router:
        router.post(AZURE_CHAT_PATH).mock(return_value=httpx.Response(401, json=error_body))
        client = httpx.AsyncClient(base_url=AZURE_BASE)
        try:
            adapter = AzureOpenAIAdapter(
                name="azure-test",
                base_url=AZURE_BASE,
                api_key=secret,
                api_version=AZURE_API_VERSION,
                client=client,
            )
            with pytest.raises(ProviderAuthError) as excinfo:
                await adapter.chat_completion(
                    ChatCompletionRequest(
                        model="alias",
                        messages=[ChatCompletionMessage(role="user", content="hi")],
                    ),
                    model=AZURE_DEPLOYMENT,
                    stream=False,
                )
        finally:
            await client.aclose()
    serialized = json.dumps(excinfo.value.to_envelope())
    assert secret not in serialized
    assert excinfo.value.details.get("upstream_status") == 401


@pytest.mark.unit
async def test_chat_completion_500_translates_to_http_error() -> None:
    """M2-E1: a 500 from Azure raises ProviderHTTPError."""

    with respx.mock(base_url=AZURE_BASE) as router:
        router.post(AZURE_CHAT_PATH).mock(
            return_value=httpx.Response(500, json={"error": {"message": "boom"}})
        )
        client = httpx.AsyncClient(base_url=AZURE_BASE)
        try:
            adapter = AzureOpenAIAdapter(
                name="azure-test",
                base_url=AZURE_BASE,
                api_key="az-key",
                api_version=AZURE_API_VERSION,
                client=client,
            )
            with pytest.raises(ProviderHTTPError) as excinfo:
                await adapter.chat_completion(
                    ChatCompletionRequest(
                        model="alias",
                        messages=[ChatCompletionMessage(role="user", content="hi")],
                    ),
                    model=AZURE_DEPLOYMENT,
                    stream=False,
                )
        finally:
            await client.aclose()
    assert excinfo.value.upstream_status == 500


@pytest.mark.unit
async def test_chat_completion_network_error_translates() -> None:
    """M2-E1: a transport failure raises ProviderNetworkError."""

    with respx.mock(base_url=AZURE_BASE) as router:
        router.post(AZURE_CHAT_PATH).mock(side_effect=httpx.ConnectError("boom"))
        client = httpx.AsyncClient(base_url=AZURE_BASE)
        try:
            adapter = AzureOpenAIAdapter(
                name="azure-test",
                base_url=AZURE_BASE,
                api_key="az-key",
                api_version=AZURE_API_VERSION,
                client=client,
            )
            with pytest.raises(ProviderNetworkError):
                await adapter.chat_completion(
                    ChatCompletionRequest(
                        model="alias",
                        messages=[ChatCompletionMessage(role="user", content="hi")],
                    ),
                    model=AZURE_DEPLOYMENT,
                    stream=False,
                )
        finally:
            await client.aclose()


# --- Embeddings ---------------------------------------------------------


@pytest.mark.unit
async def test_embeddings_happy_path() -> None:
    """M2-E1: embeddings post to the deployment-scoped path with api-key auth."""

    payload = {
        "object": "list",
        "data": [{"object": "embedding", "embedding": [0.1, 0.2], "index": 0}],
        "model": AZURE_DEPLOYMENT,
        "usage": {"prompt_tokens": 3, "total_tokens": 3},
    }
    with respx.mock(base_url=AZURE_BASE) as router:
        route = router.post(AZURE_EMBED_PATH).mock(return_value=httpx.Response(200, json=payload))
        client = httpx.AsyncClient(base_url=AZURE_BASE)
        try:
            adapter = AzureOpenAIAdapter(
                name="azure-test",
                base_url=AZURE_BASE,
                api_key="az-key-emb",
                api_version=AZURE_API_VERSION,
                client=client,
            )
            response = await adapter.embeddings(
                EmbeddingsRequest(
                    model="alias",
                    input="hello",
                ),
                model=AZURE_DEPLOYMENT,
            )
        finally:
            await client.aclose()
    assert len(response.data) == 1
    assert response.data[0].embedding == [0.1, 0.2]
    sent = route.calls.last.request
    assert sent.headers.get("api-key") == "az-key-emb"
    assert AZURE_DEPLOYMENT in str(sent.url)
    assert f"api-version={AZURE_API_VERSION}" in str(sent.url)


# --- Health -------------------------------------------------------------


@pytest.mark.unit
async def test_health_check_uses_models_endpoint_with_api_version() -> None:
    """M2-E1: health probe hits ``/openai/models?api-version=...``."""

    with respx.mock(base_url=AZURE_BASE) as router:
        route = router.get(AZURE_MODELS_PATH).mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        client = httpx.AsyncClient(base_url=AZURE_BASE)
        try:
            adapter = AzureOpenAIAdapter(
                name="azure-test",
                base_url=AZURE_BASE,
                api_key="az-key",
                api_version=AZURE_API_VERSION,
                client=client,
            )
            health = await adapter.health_check()
        finally:
            await client.aclose()
    assert health.reachable is True
    assert health.error is None
    sent = route.calls.last.request
    assert sent.headers.get("api-key") == "az-key"
    assert f"api-version={AZURE_API_VERSION}" in str(sent.url)


@pytest.mark.unit
async def test_health_check_auth_rejected() -> None:
    """M2-E1: 401 from health probe surfaces reachable+auth-rejected."""

    with respx.mock(base_url=AZURE_BASE) as router:
        router.get(AZURE_MODELS_PATH).mock(return_value=httpx.Response(401, json={}))
        client = httpx.AsyncClient(base_url=AZURE_BASE)
        try:
            adapter = AzureOpenAIAdapter(
                name="azure-test",
                base_url=AZURE_BASE,
                api_key="bad",
                api_version=AZURE_API_VERSION,
                client=client,
            )
            health = await adapter.health_check()
        finally:
            await client.aclose()
    assert health.reachable is True
    assert health.error is not None
    assert "401" in health.error
