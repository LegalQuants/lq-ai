"""OpenAI provider adapter — embeddings (C6) + chat completions (B6).

C6 shipped the embeddings path; B6 fills in chat completions (the LLM
gateway's main load-bearing path for OpenAI). Auth-header wiring,
error translation, and the long-lived httpx pool are shared.

Wire-format notes
-----------------

* **Embeddings.** ``POST /embeddings`` with body
  ``{"model": ..., "input": "..." | [...]}``. Response shape matches
  the gateway's :class:`EmbeddingsResponse` verbatim.
* **Chat completions.** ``POST /chat/completions`` with body
  ``{"model": ..., "messages": [...], "max_tokens": ..., "stream": ...}``.
  OpenAI's wire format IS the gateway's wire format
  (:class:`ChatCompletionRequest` / :class:`ChatCompletionResponse`),
  so translation is a pass-through — we serialize the request through
  pydantic, send what the schema produces (with the LQ.AI extension
  fields stripped, since OpenAI rejects unknown body keys with HTTP
  400), and parse the response back through the same model.
* **Streaming.** OpenAI emits SSE frames with ``data: <json>\\n\\n`` for
  each :class:`ChatCompletionChunk`, terminated by ``data: [DONE]\\n\\n``.
  The adapter parses these directly into :class:`ChatCompletionChunk`
  instances and yields them; the route handler is responsible for
  re-emitting ``[DONE]`` on the wire (the adapter only yields data
  chunks per the contract in :mod:`app.providers.anthropic`).
* The base URL convention is ``https://api.openai.com/v1`` (with the
  ``/v1`` already in ``base_url`` per ``gateway.yaml.example``); we do
  NOT prepend ``/v1`` to the path here.
* Authentication: ``Authorization: Bearer <key>``.

LQ.AI extension fields
----------------------

OpenAI rejects unknown body fields with HTTP 400, so the adapter
strips the LQ.AI-specific keys (``minimum_inference_tier``,
``skill_name``, ``chat_id``, ``anonymize``, ``lq_ai_*``) before
serialization. The router has already consumed any of these that
mattered for routing; the upstream provider never sees them.

Why no ``openai`` SDK dependency
--------------------------------

Per PRD §4 / ADR 0008 §"Adapter scope" — the gateway hand-rolls httpx
to keep the supply-chain surface honest. The chat-completion surface
is large but the translation is pass-through; a pydantic schema + a
single POST + an SSE iterator is cleaner than pulling the full openai
SDK with its transitive dep tree.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import ProviderConfig
from app.providers.base import (
    ProviderAdapter,
    ProviderAuthError,
    ProviderHealth,
    ProviderHTTPError,
    ProviderNetworkError,
)
from app.providers.openai_schema import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingObject,
    EmbeddingsRequest,
    EmbeddingsResponse,
    EmbeddingsUsage,
)
from app.secrets import ProviderKeyResolver

# Body keys that the gateway adds on top of OpenAI's schema (per
# ``docs/api/gateway-openapi.yaml``) and that OpenAI itself rejects with
# HTTP 400 if forwarded. The router consumes everything in this set
# before dispatch; the adapter strips them defensively in case the
# request landed here without going through the router (tests, direct
# adapter use, future code paths).
_LQ_AI_EXTENSION_KEYS = frozenset(
    {
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
    }
)

# M2-D2: per-message LQ.AI extension keys that must not reach OpenAI.
# Anthropic / Ollama adapters build message dicts field-by-field so
# they ignore these implicitly; the OpenAI adapter uses ``model_dump``
# and needs the explicit strip.
_LQ_AI_MESSAGE_EXTENSION_KEYS = frozenset({"lq_ai_skip_anonymization"})

logger = logging.getLogger(__name__)


DEFAULT_TIMEOUT_SECONDS = 60.0
"""Default per-request timeout. ``timeout_s`` on each provider entry
overrides; if absent we use this default."""


class OpenAIAdapter(ProviderAdapter):
    """Concrete :class:`ProviderAdapter` for OpenAI.

    M1 scope (per ADR 0008): :meth:`embeddings` is the load-bearing
    path. :meth:`chat_completion` raises :class:`ProviderUnsupportedError`
    until B6 fills in the OpenAI Chat Completions translation surface.

    Construct via :meth:`from_config` from a loaded ``ProviderConfig``.
    The adapter resolves the API key from the env var named in
    ``api_key_env`` (default ``OPENAI_API_KEY``); if unset, construction
    raises :class:`ValueError` so the failure is visible at startup.
    """

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        timeout_s: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_s
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout_s,
        )

    # --- Construction --------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        provider: ProviderConfig,
        *,
        env: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
        key_resolver: ProviderKeyResolver | None = None,
    ) -> OpenAIAdapter:
        """Build an adapter from a loaded :class:`ProviderConfig`.

        Accepts both ``type="openai"`` and ``type="openai_compatible"``
        provider entries (the latter for vLLM / llama-cpp servers that
        speak the OpenAI wire format). The API-key check is skipped when
        the provider is ``openai_compatible`` and no key source is
        configured — many local OpenAI-compatible servers don't require
        a key.

        ``env`` defaults to :data:`os.environ`; tests override.
        ``key_resolver`` (ADR 0011) handles ``api_key_encrypted`` paths.
        When ``None`` the factory builds a resolver from process env.
        """

        if provider.type not in ("openai", "openai_compatible"):
            raise ValueError(
                f"OpenAIAdapter requires provider.type in {{'openai', "
                f"'openai_compatible'}}; got {provider.type!r}"
            )
        if key_resolver is None:
            env_lookup = env if env is not None else dict(os.environ)
            key_resolver = ProviderKeyResolver(
                master_key=env_lookup.get("LQ_AI_GATEWAY_MASTER_KEY") or None,
                env=env_lookup,
            )
        # OPENAI_API_KEY default applies only when neither encrypted nor
        # env-named source is set; openai_compatible local servers may
        # legitimately have no key at all.
        effective_env = provider.api_key_env or (
            None
            if (provider.api_key_encrypted or provider.type == "openai_compatible")
            else "OPENAI_API_KEY"
        )
        api_key = key_resolver.resolve(
            provider_name=provider.name,
            api_key_env=effective_env,
            api_key_encrypted=provider.api_key_encrypted,
        )
        if not api_key and provider.type == "openai":
            raise ValueError(
                f"OpenAI provider {provider.name!r} requires either "
                f"api_key_encrypted or environment variable "
                f"{(effective_env or 'OPENAI_API_KEY')!r} to be set"
            )

        extra = provider.model_extra or {}
        timeout_raw = extra.get("timeout_s")
        timeout_s = float(timeout_raw) if timeout_raw is not None else DEFAULT_TIMEOUT_SECONDS

        return cls(
            name=provider.name,
            base_url=provider.base_url,
            api_key=api_key,
            timeout_s=timeout_s,
            client=client,
        )

    # --- ProviderAdapter contract --------------------------------------------

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        *,
        model: str,
        stream: bool,
    ) -> ChatCompletionResponse | AsyncIterator[ChatCompletionChunk]:
        """Issue a chat-completion request against ``POST /chat/completions``.

        OpenAI's wire format is what the gateway already speaks. The
        translation is mostly identity: serialize the pydantic request,
        strip the LQ.AI extension keys OpenAI doesn't accept, force the
        ``model`` field to the provider-native value, and overwrite
        ``stream`` to match the route handler's decision.
        """

        body = _to_openai_request(request, model=model, stream=stream)

        if stream:
            return _openai_stream_iter(
                client=self._client,
                body=body,
                headers=self._auth_headers(),
                provider_name=self.name,
                requested_model=model,
            )
        return await self._chat_completion_unary(body, model=model)

    async def _chat_completion_unary(
        self,
        body: dict[str, Any],
        *,
        model: str,
    ) -> ChatCompletionResponse:
        try:
            response = await self._client.post(
                "/chat/completions",
                json=body,
                headers=self._auth_headers(),
            )
        except httpx.HTTPError as exc:
            raise ProviderNetworkError(
                f"failed to reach OpenAI: {type(exc).__name__}",
                details={"provider": self.name},
            ) from exc

        _raise_for_status(response, provider=self.name)
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderHTTPError(
                "OpenAI returned a non-JSON response",
                upstream_status=response.status_code,
                details={"provider": self.name},
            ) from exc

        return _from_openai_chat_response(payload, requested_model=model)

    async def embeddings(
        self,
        request: EmbeddingsRequest,
        *,
        model: str,
    ) -> EmbeddingsResponse:
        """POST to OpenAI's ``/embeddings`` and translate the response.

        OpenAI's wire format is what the gateway's OpenAI-compatible
        schema is modeled on; the translation is mostly identity. The
        only field that needs adapter-specific handling is the
        ``index`` integer (we trust OpenAI's numbering) and the
        ``encoding_format`` (we always send the default ``float`` —
        ``base64`` is a future optimization for bandwidth-constrained
        deployments).
        """

        body: dict[str, Any] = {
            "model": model,
            "input": request.input,
        }
        # OpenAI's text-embedding-3-* models support a ``dimensions``
        # parameter that returns shorter vectors. We pass through if the
        # caller set it (the route handler may set this; the KB layer
        # default-omits to use the model's native dim).
        if request.dimensions is not None:
            body["dimensions"] = request.dimensions
        if request.encoding_format is not None:
            body["encoding_format"] = request.encoding_format
        if request.user is not None:
            body["user"] = request.user

        try:
            response = await self._client.post(
                "/embeddings",
                json=body,
                headers=self._auth_headers(),
            )
        except httpx.HTTPError as exc:
            raise ProviderNetworkError(
                f"failed to reach OpenAI: {type(exc).__name__}",
                details={"provider": self.name},
            ) from exc

        _raise_for_status(response, provider=self.name)
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderHTTPError(
                "OpenAI returned a non-JSON response",
                upstream_status=response.status_code,
                details={"provider": self.name},
            ) from exc

        return _from_openai_embeddings_response(payload, requested_model=model)

    async def health_check(self) -> ProviderHealth:
        """Probe OpenAI's ``GET /models`` endpoint.

        Cheapest authenticated GET; validates that our key is accepted.
        Health probes use a shorter timeout so admin endpoints stay
        responsive when a provider is misbehaving.
        """

        start = time.monotonic()
        try:
            response = await self._client.get(
                "/models",
                headers=self._auth_headers(),
                timeout=min(self._timeout, 10.0),
            )
        except httpx.HTTPError as exc:
            return ProviderHealth(
                name=self.name,
                reachable=False,
                latency_ms=None,
                error=f"network error: {type(exc).__name__}",
            )

        latency_ms = int((time.monotonic() - start) * 1000)
        if response.status_code == 200:
            return ProviderHealth(name=self.name, reachable=True, latency_ms=latency_ms)
        if response.status_code in (401, 403):
            return ProviderHealth(
                name=self.name,
                reachable=True,
                latency_ms=latency_ms,
                error=f"upstream auth rejected ({response.status_code})",
            )
        return ProviderHealth(
            name=self.name,
            reachable=False,
            latency_ms=latency_ms,
            error=f"upstream returned HTTP {response.status_code}",
        )

    async def aclose(self) -> None:
        """Close the owned httpx client (if we created it)."""

        if self._owns_client:
            await self._client.aclose()

    # --- Internals -----------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        """Headers required on every OpenAI call.

        ``Authorization: Bearer <key>`` is the OpenAI auth convention.
        For ``openai_compatible`` providers with no key configured we
        omit the header entirely (some local servers reject any
        ``Authorization`` header outright).
        """

        headers: dict[str, str] = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        return headers


# --- Translation helpers -----------------------------------------------------


def _from_openai_embeddings_response(
    payload: dict[str, Any],
    *,
    requested_model: str,
) -> EmbeddingsResponse:
    """Translate OpenAI's embeddings JSON into :class:`EmbeddingsResponse`.

    OpenAI's body shape::

        {
            "object": "list",
            "data": [{"object": "embedding", "embedding": [0.1, 0.2, ...], "index": 0}, ...],
            "model": "text-embedding-3-small",
            "usage": {"prompt_tokens": 5, "total_tokens": 5},
        }

    We accept the response verbatim into our pydantic models. Defensive
    fallbacks: if ``data`` is missing the request had no embeddings to
    return (we surface as an empty response rather than raising — the
    caller's empty-input case lands here).
    """

    data_raw = payload.get("data") or []
    items: list[EmbeddingObject] = []
    if isinstance(data_raw, list):
        for entry in data_raw:
            if not isinstance(entry, dict):
                continue
            embedding = entry.get("embedding")
            index = entry.get("index", 0)
            if isinstance(embedding, list):
                items.append(
                    EmbeddingObject(
                        embedding=[float(v) for v in embedding],
                        index=int(index) if isinstance(index, int) else 0,
                    )
                )

    usage_raw = payload.get("usage") or {}
    usage = EmbeddingsUsage(
        prompt_tokens=int(usage_raw.get("prompt_tokens", 0)) if isinstance(usage_raw, dict) else 0,
        total_tokens=int(usage_raw.get("total_tokens", 0)) if isinstance(usage_raw, dict) else 0,
    )

    response_model = str(payload.get("model") or requested_model)

    return EmbeddingsResponse(
        data=items,
        model=response_model,
        usage=usage,
    )


# --- Translation: gateway -> OpenAI chat completions ------------------------


def _to_openai_request(
    request: ChatCompletionRequest,
    *,
    model: str,
    stream: bool,
) -> dict[str, Any]:
    """Build the OpenAI ``POST /chat/completions`` request body.

    Translation is identity in shape; the only edits are:

    * ``model`` is forced to the provider-native name (the alias may
      have resolved to a different model than the caller asked for).
    * ``stream`` is forced to the route handler's decision (the body's
      original ``stream`` was a hint, not authoritative).
    * LQ.AI extension keys (per :data:`_LQ_AI_EXTENSION_KEYS`) are
      stripped — OpenAI rejects unknown body fields with HTTP 400.
    * ``messages`` is serialized via pydantic so role/content/tool_calls
      are normalized; pydantic's ``mode="json"`` produces wire-shaped
      dicts (``None`` fields dropped via ``exclude_none``).

    The serializer preserves any caller-set OpenAI-specific extras
    (``tools``, ``tool_choice``, ``response_format``, ``seed``, etc.)
    that landed in ``model_extra`` after the request was parsed with
    ``extra="allow"``.
    """

    body = request.model_dump(mode="json", exclude_none=True)
    for key in _LQ_AI_EXTENSION_KEYS:
        body.pop(key, None)
    # M2-D2: per-message LQ.AI keys (e.g., lq_ai_skip_anonymization)
    # are api-internal markers; strip from each message so OpenAI's
    # strict body validation doesn't reject the request.
    messages = body.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, dict):
                for key in _LQ_AI_MESSAGE_EXTENSION_KEYS:
                    msg.pop(key, None)
    body["model"] = model
    body["stream"] = stream
    # ``stream_options.include_usage`` is required for OpenAI to emit a
    # usage block on the final streaming chunk. The gateway expects that
    # data to populate the routing log + cost estimate, so opt in.
    if stream:
        existing = body.get("stream_options")
        if isinstance(existing, dict):
            existing.setdefault("include_usage", True)
        else:
            body["stream_options"] = {"include_usage": True}
    return body


# --- Translation: OpenAI -> gateway (non-streaming) -------------------------


def _from_openai_chat_response(
    payload: dict[str, Any],
    *,
    requested_model: str,
) -> ChatCompletionResponse:
    """Translate an OpenAI chat-completion JSON response into the gateway shape.

    OpenAI's body matches :class:`ChatCompletionResponse` directly; we
    parse through pydantic so the response model validates and the
    LQ.AI extension fields default to ``None`` (the route handler
    stamps them post-adapter).

    Defensive: if ``model`` is missing we fall back to ``requested_model``
    so downstream consumers always see a model identifier on the row.
    """

    if "model" not in payload or not payload.get("model"):
        payload = dict(payload)
        payload["model"] = requested_model
    return ChatCompletionResponse.model_validate(payload)


# --- Translation: OpenAI SSE -> gateway chunks -------------------------------


async def _openai_stream_iter(
    *,
    client: httpx.AsyncClient,
    body: dict[str, Any],
    headers: dict[str, str],
    provider_name: str,
    requested_model: str,
    path: str = "/chat/completions",
) -> AsyncIterator[ChatCompletionChunk]:
    """Stream OpenAI SSE and yield :class:`ChatCompletionChunk` objects.

    OpenAI emits SSE frames of the form ``data: <json>\\n\\n`` terminated
    by ``data: [DONE]\\n\\n``. Each ``<json>`` payload is already shaped
    as a :class:`ChatCompletionChunk` (object="chat.completion.chunk"),
    so the adapter parses each line and validates through pydantic.

    Per the adapter contract, the ``[DONE]`` sentinel is the route
    handler's responsibility — the adapter only yields data chunks.
    Empty lines, ``:`` comments, and ``event:`` / ``id:`` / ``retry:``
    fields are ignored (we don't depend on them).

    ``path`` defaults to OpenAI's ``/chat/completions``; Azure OpenAI
    (M2-E1) reuses this iterator with its deployment-scoped path.
    """

    fallback_id = f"chatcmpl-{uuid.uuid4().hex}"

    try:
        async with client.stream("POST", path, json=body, headers=headers) as response:
            if response.status_code >= 400:
                error_body = await response.aread()
                _raise_from_error_body(
                    status_code=response.status_code,
                    body=error_body,
                    provider=provider_name,
                )

            async for raw_data in _iter_sse_data(response):
                if not raw_data or raw_data == "[DONE]":
                    continue
                try:
                    parsed = json.loads(raw_data)
                except json.JSONDecodeError:
                    continue
                if not isinstance(parsed, dict):
                    continue
                if not parsed.get("model"):
                    parsed["model"] = requested_model
                if not parsed.get("id"):
                    parsed["id"] = fallback_id
                try:
                    yield ChatCompletionChunk.model_validate(parsed)
                except Exception:
                    # Defensive: skip malformed chunks rather than killing
                    # the whole stream. The route handler still emits
                    # [DONE] when the iterator finishes.
                    continue
    except httpx.HTTPError as exc:
        raise ProviderNetworkError(
            f"failed to stream from OpenAI: {type(exc).__name__}",
            details={"provider": provider_name},
        ) from exc


async def _iter_sse_data(response: httpx.Response) -> AsyncIterator[str]:
    """Yield ``data:`` payloads from an SSE response.

    Implements the subset of SSE that OpenAI uses: only ``data:`` lines
    matter; blank lines terminate frames; multi-line ``data:`` values
    concatenate with ``\\n``. ``event:`` / ``id:`` / ``retry:`` / comment
    (``:``) lines are ignored.
    """

    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                yield "\n".join(data_lines)
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip(" "))
            continue
        # event: / id: / retry: / unknown -> ignore.
    # Trailing frame without blank-line terminator (rare; defensive).
    if data_lines:
        yield "\n".join(data_lines)


# --- Error mapping -----------------------------------------------------------


def _raise_for_status(response: httpx.Response, *, provider: str) -> None:
    """Translate an upstream non-success status to a structured adapter error."""

    if response.status_code < 400:
        return
    body = response.content
    _raise_from_error_body(status_code=response.status_code, body=body, provider=provider)


def _raise_from_error_body(
    *,
    status_code: int,
    body: bytes,
    provider: str,
) -> None:
    """Parse an OpenAI error body and raise the right adapter error.

    OpenAI's error shape::

        {"error": {"message": "...", "type": "...", "code": "..."}}

    We surface ``error.message`` to the operator (it's API-key-free by
    OpenAI's convention) and tag the type/code in ``details``. The raw
    body is *not* echoed — protects against accidental key/PII leakage
    if a request is malformed in ways that echo the input back.
    """

    upstream_type: str | None = None
    upstream_code: str | None = None
    upstream_message: str | None = None
    try:
        parsed = json.loads(body or b"{}")
    except json.JSONDecodeError:
        parsed = {}
    if isinstance(parsed, dict):
        error_block = parsed.get("error")
        if isinstance(error_block, dict):
            raw_type = error_block.get("type")
            raw_code = error_block.get("code")
            raw_message = error_block.get("message")
            if isinstance(raw_type, str):
                upstream_type = raw_type
            if isinstance(raw_code, str):
                upstream_code = raw_code
            if isinstance(raw_message, str):
                upstream_message = raw_message

    details: dict[str, object] = {"provider": provider}
    if upstream_type:
        details["upstream_error_type"] = upstream_type
    if upstream_code:
        details["upstream_error_code"] = upstream_code

    safe_message = upstream_message or f"OpenAI returned HTTP {status_code}"

    if status_code in (401, 403):
        details["upstream_status"] = status_code
        raise ProviderAuthError(
            f"OpenAI rejected the gateway's credentials ({status_code})",
            details=details,
        )
    raise ProviderHTTPError(
        safe_message,
        upstream_status=status_code,
        details=details,
    )
