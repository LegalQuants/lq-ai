"""AWS compatible-API adapter, derived from @dropthejase's PR #265.

One provider entry selects one protocol and an explicit AWS base path.
Anthropic and OpenAI translation stays in the existing adapters. No SDK,
SigV4 signer, remote conversation state or automatic route discovery.
"""

from __future__ import annotations

import math
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.bedrock_config import validate_bedrock_base_url
from app.config import ProviderConfig
from app.providers.anthropic import AnthropicAdapter
from app.providers.base import (
    ProviderAdapter,
    ProviderAdapterError,
    ProviderAuthError,
    ProviderEmptyResponseError,
    ProviderHealth,
    ProviderHTTPError,
    ProviderNetworkError,
    ProviderTimeoutError,
    ProviderUnsupportedError,
)
from app.providers.bedrock_responses import (
    _function,
    from_responses_response,
    stream_responses,
    to_responses_request,
)
from app.providers.openai import DEFAULT_TIMEOUT_SECONDS, OpenAIAdapter
from app.providers.openai_schema import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingsRequest,
    EmbeddingsResponse,
)
from app.secrets import ProviderKeyResolver


class BedrockAdapter(ProviderAdapter):
    def __init__(
        self,
        provider: ProviderConfig,
        *,
        api_key: str,
        resolver: ProviderKeyResolver,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if provider.bedrock_protocol is None:
            raise ValueError("Bedrock compatible APIs require an explicit bedrock_protocol")
        self.name = provider.name
        self._protocol = provider.bedrock_protocol
        base_url = validate_bedrock_base_url(
            provider.base_url, self._protocol, provider.bedrock_endpoint
        )
        self._timeout = float(
            (provider.model_extra or {}).get("timeout_s", DEFAULT_TIMEOUT_SECONDS)
        )
        if not math.isfinite(self._timeout) or self._timeout <= 0:
            raise ValueError("Bedrock timeout_s must be finite and positive")
        default_max_tokens = (provider.model_extra or {}).get("default_max_tokens")
        if default_max_tokens is not None and int(default_max_tokens) < 1:
            raise ValueError("Bedrock default_max_tokens must be positive")
        self._api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url, timeout=self._timeout, trust_env=False, follow_redirects=False
        )
        self._response_hook = self._validate_response_status
        self._client.event_hooks["response"].append(self._response_hook)
        self._observed_success = False
        self._delegate: ProviderAdapter | None = None
        if self._protocol != "responses":
            delegate_config = provider.model_copy(
                update={
                    "type": "anthropic" if self._protocol == "messages" else "openai",
                }
            )
            factory = AnthropicAdapter if self._protocol == "messages" else OpenAIAdapter
            delegate = factory.from_config(
                delegate_config, client=self._client, key_resolver=resolver
            )
            delegate.strict_stream = True
            self._delegate = delegate

    @classmethod
    def from_config(
        cls,
        provider: ProviderConfig,
        *,
        env: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
        key_resolver: ProviderKeyResolver | None = None,
    ) -> BedrockAdapter:
        if provider.type != "bedrock" or provider.bedrock_protocol is None:
            raise ValueError("Bedrock requires type=bedrock and an explicit bedrock_protocol")
        values = dict(os.environ) if env is None else env
        resolver = key_resolver or ProviderKeyResolver(
            master_key=values.get("LQ_AI_GATEWAY_MASTER_KEY") or None, env=values
        )
        key = resolver.resolve(
            provider_name=provider.name,
            api_key_env=provider.api_key_env,
            api_key_encrypted=provider.api_key_encrypted,
        )
        if not key:
            raise ValueError("Bedrock requires an explicit api_key_env or api_key_encrypted source")
        return cls(provider, api_key=key, resolver=resolver, client=client)

    def _safe_error(self, exc: Exception) -> ProviderAdapterError:
        """Preserve the routing class, never an echoed upstream body or key."""
        self._observed_success = False
        details: dict[str, object] = {"provider": self.name}
        if isinstance(exc, (ProviderTimeoutError, httpx.TimeoutException)):
            return ProviderTimeoutError("Bedrock client-side request timeout", details=details)
        if isinstance(exc, ProviderAuthError):
            return ProviderAuthError(
                "Bedrock rejected the credential or model access", details=details
            )
        if isinstance(exc, ProviderHTTPError):
            return ProviderHTTPError(
                "Bedrock returned an upstream error",
                upstream_status=exc.upstream_status,
                details=details,
            )
        if isinstance(exc, (ProviderNetworkError, httpx.HTTPError)):
            return ProviderNetworkError("Bedrock network request failed", details=details)
        if isinstance(exc, ProviderAdapterError):
            return type(exc)("Bedrock could not serve this request", details=details)
        return ProviderHTTPError(
            "Bedrock returned an invalid protocol response", upstream_status=502, details=details
        )

    def _headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self._api_key}", "content-type": "application/json"}

    async def _validate_response_status(self, response: httpx.Response) -> None:
        self._check_status(response)

    @staticmethod
    def _check_status(response: httpx.Response) -> None:
        if response.status_code in (401, 403):
            raise ProviderAuthError("Bedrock rejected the credential or model access")
        if not 200 <= response.status_code < 300:
            raise ProviderHTTPError(
                "Bedrock returned an upstream error", upstream_status=response.status_code
            )

    async def chat_completion(
        self, request: ChatCompletionRequest, *, model: str, stream: bool
    ) -> ChatCompletionResponse | AsyncIterator[ChatCompletionChunk]:
        try:
            for tool in request.tools or []:
                _function(tool)
            if isinstance(request.tool_choice, dict):
                forced = _function(request.tool_choice)
                if forced["name"] not in {_function(tool)["name"] for tool in request.tools or []}:
                    raise ProviderUnsupportedError("The forced function is not governed")
            if self._delegate is not None:
                # Explicit schema allowlist: never pass arbitrary extras to AWS.
                safe = ChatCompletionRequest.model_validate(
                    {
                        k: value
                        for k, value in request.model_dump().items()
                        if k in ChatCompletionRequest.model_fields
                    }
                )
                result = await self._delegate.chat_completion(safe, model=model, stream=stream)
                if isinstance(result, ChatCompletionResponse):
                    if not any(
                        choice.message.content or choice.message.tool_calls
                        for choice in result.choices
                    ):
                        raise ProviderEmptyResponseError(
                            "Bedrock returned no content or tool calls"
                        )
                    self._observed_success = True
                    return result
                return self._guard_stream(result)
            body = to_responses_request(request, model=model, stream=stream)
            if stream:
                return self._guard_stream(self._responses_stream(body, model=model))
            response = await self._client.post("/responses", json=body, headers=self._headers())
            self._check_status(response)
            payload: Any = response.json()
            if not isinstance(payload, dict):
                raise ValueError("invalid response shape")
            result = from_responses_response(payload, model=model)
            self._observed_success = True
            return result
        except (
            ProviderAdapterError,
            httpx.HTTPError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ) as exc:
            raise self._safe_error(exc) from None

    async def _responses_stream(
        self, body: dict[str, Any], *, model: str
    ) -> AsyncIterator[ChatCompletionChunk]:
        async with self._client.stream(
            "POST", "/responses", json=body, headers=self._headers()
        ) as response:
            self._check_status(response)
            async for chunk in stream_responses(response, model=model):
                yield chunk

    async def _guard_stream(
        self, stream: AsyncIterator[ChatCompletionChunk]
    ) -> AsyncIterator[ChatCompletionChunk]:
        try:
            produced_output = False
            async for chunk in stream:
                produced_output |= any(
                    choice.delta.content or choice.delta.tool_calls for choice in chunk.choices
                )
                yield chunk
            if not produced_output:
                raise ProviderEmptyResponseError("Bedrock returned no content or tool calls")
            self._observed_success = True
        except (
            ProviderAdapterError,
            httpx.HTTPError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ) as exc:
            raise self._safe_error(exc) from None

    async def embeddings(self, request: EmbeddingsRequest, *, model: str) -> EmbeddingsResponse:
        raise ProviderUnsupportedError("Bedrock embeddings are outside this adapter's scope")

    async def health_check(self) -> ProviderHealth:
        # No shared non-billable catalogue probe establishes access to all three
        # APIs. Report observed inference health; never charge for a health poll.
        return ProviderHealth(
            name=self.name,
            reachable=self._observed_success,
            error=None
            if self._observed_success
            else ("Bedrock access has not been verified by a successful inference on this adapter"),
        )

    async def aclose(self) -> None:
        if self._response_hook in self._client.event_hooks["response"]:
            self._client.event_hooks["response"].remove(self._response_hook)
        if self._owns_client:
            await self._client.aclose()
