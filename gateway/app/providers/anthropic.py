"""Anthropic provider adapter.

Translates between the gateway's OpenAI-compatible surface and the
Anthropic Messages API (``POST /v1/messages``). B3 covers the chat
completion path, both streaming and non-streaming. Embeddings raise
:class:`ProviderUnsupportedError` because Anthropic has no embeddings
endpoint as of 2026-05-07.

Wire-format differences worth knowing
-------------------------------------

* OpenAI's ``messages: [{role: "system", ...}, ...]`` becomes Anthropic's
  ``system: "<text>"`` (top-level field) plus
  ``messages: [{role: "user"|"assistant", ...}]``. Multiple system
  messages concatenate with a blank line.
* Anthropic requires ``max_tokens``. OpenAI doesn't. The adapter falls
  back to the provider's configured ``default_max_tokens`` — or
  :data:`DEFAULT_MAX_TOKENS` (4096) when unconfigured — when the caller
  omits it.
* Anthropic requires ``anthropic-version`` on every request; we pin
  :data:`ANTHROPIC_API_VERSION`.
* Anthropic returns ``stop_reason`` in {``end_turn``, ``max_tokens``,
  ``stop_sequence``, ``tool_use``, ``pause_turn``}. Mapping table is in
  :data:`STOP_REASON_MAP`.
* Anthropic streams via SSE with named events
  (``message_start``, ``content_block_start``, ``content_block_delta``,
  ``content_block_stop``, ``message_delta``, ``message_stop``,
  plus heartbeat ``ping`` events). The adapter consumes those and emits
  OpenAI-shaped chunks.

We deliberately do not depend on the ``anthropic`` Python SDK. PRD §4
calls for ~3,000 lines of hand-rolled gateway code in lieu of LLM-SDK
dependencies; raw httpx keeps the supply-chain surface honest.
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

from app.config import ProviderConfig, RequestValidationConfig
from app.providers.base import (
    ProviderAdapter,
    ProviderAuthError,
    ProviderHealth,
    ProviderHTTPError,
    ProviderNetworkError,
    ProviderUnsupportedError,
)
from app.providers.openai_schema import (
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionDelta,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
    EmbeddingsRequest,
    EmbeddingsResponse,
    FinishReason,
)
from app.secrets import ProviderKeyResolver

logger = logging.getLogger(__name__)

ANTHROPIC_API_VERSION = "2023-06-01"
"""Pinned Anthropic API version. Update deliberately; bump in lockstep
with changes to the request/response translation below."""

DEFAULT_TIMEOUT_SECONDS = 60.0
"""Default per-request timeout. PRD §4.4 / gateway.yaml.example exposes
``timeout_s`` on each provider; if absent we use this default."""

DEFAULT_MAX_TOKENS = 4096
"""Anthropic Messages requires ``max_tokens``. When the OpenAI-format
request omits it, the gateway sends this default. Keeping it modest
(rather than the per-model ceiling) avoids accidentally enormous
responses on requests that didn't specify a budget.

Operators can raise (or lower) this per provider via the
``default_max_tokens`` field on the provider entry; see
:meth:`AnthropicAdapter.from_config`."""

STOP_REASON_MAP: dict[str, FinishReason] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "pause_turn": "stop",
}
"""Translate Anthropic ``stop_reason`` values to OpenAI ``finish_reason``."""


class AnthropicAdapter(ProviderAdapter):
    """Concrete :class:`ProviderAdapter` for Anthropic.

    Construct via :meth:`from_config` from a loaded ``ProviderConfig``.
    The adapter resolves the API key by reading the env var named in
    ``api_key_env`` (typically ``ANTHROPIC_API_KEY``). If that var is
    unset, construction raises :class:`ValueError` so the failure is
    visible at startup rather than per-request.
    """

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        timeout_s: float = DEFAULT_TIMEOUT_SECONDS,
        default_max_tokens: int = DEFAULT_MAX_TOKENS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_s
        self._default_max_tokens = default_max_tokens
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
    ) -> AnthropicAdapter:
        """Build an adapter from a loaded :class:`ProviderConfig`.

        ``env`` defaults to :data:`os.environ`; tests can pass an override
        to avoid mutating real environment state.

        ``key_resolver`` (ADR 0011) handles ``api_key_encrypted`` paths in
        addition to ``api_key_env``. When ``None`` the factory builds a
        resolver from process env — which transparently handles both
        paths if ``LQ_AI_GATEWAY_MASTER_KEY`` is set, and the env-only
        path otherwise.
        """

        if provider.type != "anthropic":
            raise ValueError(
                f"AnthropicAdapter requires provider.type == 'anthropic'; got {provider.type!r}"
            )
        if key_resolver is None:
            env_lookup = env if env is not None else dict(os.environ)
            key_resolver = ProviderKeyResolver(
                master_key=env_lookup.get("LQ_AI_GATEWAY_MASTER_KEY") or None,
                env=env_lookup,
            )
        # api_key_env defaults to ANTHROPIC_API_KEY when neither key
        # source is set on the provider entry; the resolver returns ""
        # if the env var is unset, which we treat as a config error.
        effective_env = provider.api_key_env or (
            None if provider.api_key_encrypted else "ANTHROPIC_API_KEY"
        )
        api_key = key_resolver.resolve(
            provider_name=provider.name,
            api_key_env=effective_env,
            api_key_encrypted=provider.api_key_encrypted,
        )
        if not api_key:
            raise ValueError(
                f"Anthropic provider {provider.name!r} requires either "
                f"api_key_encrypted or environment variable "
                f"{(effective_env or 'ANTHROPIC_API_KEY')!r} to be set"
            )

        # ``timeout_s`` is a forward-looking field on ProviderConfig per
        # PRD §4.4. Today it lives in extra-allow territory, so read it
        # defensively via ``model_extra``.
        extra = provider.model_extra or {}
        timeout_raw = extra.get("timeout_s")
        timeout_s = float(timeout_raw) if timeout_raw is not None else DEFAULT_TIMEOUT_SECONDS

        # ``default_max_tokens`` mirrors ``timeout_s``: a forward-looking
        # per-provider field (#18) that today lives in extra-allow
        # territory, so read it defensively via ``model_extra``. Falls
        # back to the module constant when absent. Clamped to the
        # request-validation ceiling (RequestValidationConfig.max_max_tokens)
        # so a generous per-provider default can never inject a budget
        # larger than the gateway would accept on an explicit request.
        default_max_tokens_raw = extra.get("default_max_tokens")
        default_max_tokens = (
            int(default_max_tokens_raw)
            if default_max_tokens_raw is not None
            else DEFAULT_MAX_TOKENS
        )
        default_max_tokens = min(default_max_tokens, RequestValidationConfig().max_max_tokens)

        return cls(
            name=provider.name,
            base_url=provider.base_url,
            api_key=api_key,
            timeout_s=timeout_s,
            default_max_tokens=default_max_tokens,
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
        """Issue a chat-completion request against Anthropic Messages.

        On success returns either a :class:`ChatCompletionResponse`
        (``stream=False``) or an async iterator over
        :class:`ChatCompletionChunk` objects (``stream=True``). Failure
        modes raise the appropriate :class:`ProviderAdapterError`
        subclass; the route handler maps these to HTTP responses.
        """

        anthropic_body = _to_anthropic_request(
            request,
            model=model,
            stream=stream,
            default_max_tokens=self._default_max_tokens,
        )

        if stream:
            return _anthropic_stream_iter(
                client=self._client,
                body=anthropic_body,
                headers=self._auth_headers(),
                provider_name=self.name,
                requested_model=model,
            )
        return await self._chat_completion_unary(anthropic_body, model=model)

    async def embeddings(
        self,
        request: EmbeddingsRequest,
        *,
        model: str,
    ) -> EmbeddingsResponse:
        """Anthropic has no first-party embeddings endpoint.

        Operators wanting embeddings configure a different provider
        (OpenAI ``text-embedding-3-*`` is the typical choice; ``embedding``
        in ``gateway.yaml.example`` already points there).
        """

        raise ProviderUnsupportedError(
            "Anthropic does not provide an embeddings endpoint; route the "
            "'embedding' alias to a provider that does (e.g., OpenAI)",
            details={"provider": self.name, "model": model},
        )

    async def health_check(self) -> ProviderHealth:
        """Probe Anthropic's ``GET /v1/models`` endpoint.

        ``/v1/models`` is the cheapest authenticated GET on the Messages
        API and validates that our key is accepted. Health probes use a
        shorter timeout so admin endpoints stay responsive when a
        provider is misbehaving.
        """

        start = time.monotonic()
        try:
            response = await self._client.get(
                "/v1/models",
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
        """Close the owned ``httpx.AsyncClient`` (if we created it)."""

        if self._owns_client:
            await self._client.aclose()

    # --- Internals -----------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        """Headers required on every Anthropic call.

        ``x-api-key`` and ``anthropic-version`` are mandatory; the
        ``content-type`` is set per-call by httpx for JSON bodies but
        we include it explicitly so streaming requests with empty
        bodies still negotiate correctly.
        """

        return {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        }

    async def _chat_completion_unary(
        self,
        anthropic_body: dict[str, Any],
        *,
        model: str,
    ) -> ChatCompletionResponse:
        try:
            response = await self._client.post(
                "/v1/messages",
                json=anthropic_body,
                headers=self._auth_headers(),
            )
        except httpx.HTTPError as exc:
            raise ProviderNetworkError(
                f"failed to reach Anthropic: {type(exc).__name__}",
                details={"provider": self.name},
            ) from exc

        _raise_for_status(response, provider=self.name)
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderHTTPError(
                "Anthropic returned a non-JSON response",
                upstream_status=response.status_code,
                details={"provider": self.name},
            ) from exc

        return _from_anthropic_response(payload, requested_model=model)


# --- Translation: OpenAI -> Anthropic -----------------------------------------


def _to_anthropic_request(
    request: ChatCompletionRequest,
    *,
    model: str,
    stream: bool,
    default_max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    """Build the Anthropic ``/v1/messages`` request body.

    The mapping is:

    * ``messages[role=system]`` are pulled out and concatenated into the
      top-level ``system`` string.
    * ``messages[role=user|assistant]`` keep their order. Tool messages
      are translated to ``role="user"`` with ``tool_result`` content blocks.
      Assistant messages with ``tool_calls`` are translated to ``role="assistant"``
      with ``tool_use`` content blocks so a follow-up ``tool_result`` is accepted.
    * ``tools`` (OpenAI ``{type:function,function:{name,description,parameters}}``)
      are translated to Anthropic ``{name,description,input_schema}`` and forwarded.
      ``tool_choice`` is mapped: ``auto``->``{type:auto}``, ``required``->``{type:any}``,
      ``none``->drop tools, forced function->``{type:tool,name}``.
    * ``max_tokens`` is required by Anthropic; we substitute
      ``default_max_tokens`` (the provider's configured default, falling
      back to :data:`DEFAULT_MAX_TOKENS`) if the caller omits it.
    * ``temperature`` and ``top_p`` are forwarded if set; otherwise
      Anthropic uses its defaults.
    * ``stop`` (OpenAI) becomes ``stop_sequences`` (Anthropic, list-only).
    """

    system_chunks: list[str] = []
    chat_messages: list[dict[str, Any]] = []
    for msg in request.messages:
        content = msg.content or ""
        if msg.role == "system":
            if content:
                system_chunks.append(content)
            continue
        if msg.role == "tool":
            # Translate to a user message with a tool_result content block
            # so Anthropic accepts it as conversation context.
            chat_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id or "",
                            "content": content,
                        }
                    ],
                }
            )
            continue
        if msg.role == "assistant" and msg.tool_calls:
            # Round-trip the assistant tool_use turn as Anthropic content
            # blocks so a follow-up tool_result is accepted.
            content_blocks: list[dict[str, Any]] = []
            if msg.content:
                content_blocks.append({"type": "text", "text": msg.content})
            for tc in msg.tool_calls:
                fn = tc.get("function", {})
                try:
                    parsed_input = json.loads(fn.get("arguments") or "{}")
                except (ValueError, TypeError):
                    parsed_input = {}
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": parsed_input,
                    }
                )
            chat_messages.append({"role": "assistant", "content": content_blocks})
            continue
        # user / assistant (no tool_calls)
        chat_messages.append({"role": msg.role, "content": content})

    body: dict[str, Any] = {
        "model": model,
        "messages": chat_messages,
        "max_tokens": request.max_tokens or default_max_tokens,
        "stream": stream,
    }
    if system_chunks:
        body["system"] = "\n\n".join(system_chunks)
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if request.top_p is not None:
        body["top_p"] = request.top_p
    if request.stop is not None:
        body["stop_sequences"] = (
            [request.stop] if isinstance(request.stop, str) else list(request.stop)
        )
    # PR5b: forward tools / tool_choice (OpenAI shape -> Anthropic shape).
    extra = request.model_extra or {}
    raw_tools = request.tools if request.tools is not None else extra.get("tools")
    if raw_tools:
        anthropic_tools: list[dict[str, Any]] = []
        for t in raw_tools:
            fn = t.get("function", t) if isinstance(t, dict) else {}
            anthropic_tools.append(
                {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", "") or "",
                    "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
                }
            )
        body["tools"] = anthropic_tools

        raw_choice = (
            request.tool_choice if request.tool_choice is not None else extra.get("tool_choice")
        )
        if raw_choice is None or raw_choice == "auto":
            body["tool_choice"] = {"type": "auto"}
        elif raw_choice == "none":
            # Anthropic has no "none"; honor by dropping tools entirely.
            body.pop("tools", None)
        elif raw_choice == "required":
            body["tool_choice"] = {"type": "any"}
        elif isinstance(raw_choice, dict):
            fn_choice = raw_choice.get("function", {})
            if fn_choice.get("name"):
                body["tool_choice"] = {"type": "tool", "name": fn_choice["name"]}
    return body


# --- Translation: Anthropic -> OpenAI (non-streaming) -------------------------


def _from_anthropic_response(
    payload: dict[str, Any],
    *,
    requested_model: str,
) -> ChatCompletionResponse:
    """Translate an Anthropic ``message`` response into the OpenAI shape."""

    blocks = payload.get("content") or []
    text_parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(str(block.get("text", "")))
    text = "".join(text_parts)

    # PR5b: extract tool_use blocks into OpenAI-shaped tool_calls.
    tool_calls: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_calls.append(
                {
                    "id": str(block.get("id", "")),
                    "type": "function",
                    "function": {
                        "name": str(block.get("name", "")),
                        # OpenAI tool_calls carry arguments as a JSON STRING.
                        "arguments": json.dumps(block.get("input") or {}),
                    },
                }
            )

    stop_reason_raw = payload.get("stop_reason")
    finish_reason: FinishReason | None = None
    if isinstance(stop_reason_raw, str):
        finish_reason = STOP_REASON_MAP.get(stop_reason_raw, "stop")

    usage_raw = payload.get("usage") or {}
    usage = ChatCompletionUsage(
        prompt_tokens=int(usage_raw.get("input_tokens", 0)),
        completion_tokens=int(usage_raw.get("output_tokens", 0)),
        total_tokens=int(usage_raw.get("input_tokens", 0)) + int(usage_raw.get("output_tokens", 0)),
    )

    response_id = str(payload.get("id") or f"chatcmpl-{uuid.uuid4().hex}")
    # Anthropic's ``model`` field echoes the resolved model. Prefer it
    # when present so downstream consumers see what actually ran.
    response_model = str(payload.get("model") or requested_model)

    message = ChatCompletionMessage(
        role="assistant",
        content=text or None,
        tool_calls=tool_calls or None,
    )
    return ChatCompletionResponse(
        id=response_id,
        created=int(time.time()),
        model=response_model,
        choices=[
            ChatCompletionChoice(
                index=0,
                message=message,
                finish_reason=finish_reason,
            )
        ],
        usage=usage,
    )


# --- Translation: Anthropic SSE -> OpenAI chunks -----------------------------


async def _anthropic_stream_iter(
    *,
    client: httpx.AsyncClient,
    body: dict[str, Any],
    headers: dict[str, str],
    provider_name: str,
    requested_model: str,
) -> AsyncIterator[ChatCompletionChunk]:
    """Stream Anthropic Messages SSE and translate to OpenAI chunks.

    Anthropic emits SSE events of the form::

        event: message_start
        data: {"type": "message_start", "message": {...}}

        event: content_block_start
        data: {"type": "content_block_start", "index": 0, "content_block": {...}}

        event: content_block_delta
        data: {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hello"},
        }

        event: content_block_stop
        data: {"type": "content_block_stop", "index": 0}

        event: message_delta
        data: {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 7},
        }

        event: message_stop
        data: {"type": "message_stop"}

    OpenAI's streaming format wants:

    * One initial chunk with ``delta.role = "assistant"``.
    * One chunk per text delta with ``delta.content = "<text piece>"``.
    * One final chunk with ``finish_reason`` set, ``delta`` empty, and
      a ``usage`` block.

    The ``[DONE]`` sentinel is the gateway's responsibility (the route
    handler emits it after the iterator finishes); the adapter only
    yields data chunks.
    """

    response_id = f"chatcmpl-{uuid.uuid4().hex}"
    response_model = requested_model
    created = int(time.time())
    finish_reason: FinishReason | None = None
    prompt_tokens = 0
    completion_tokens = 0
    role_emitted = False

    try:
        async with client.stream("POST", "/v1/messages", json=body, headers=headers) as response:
            if response.status_code >= 400:
                # Read the error body so callers see a structured error
                # rather than a hung stream.
                error_body = await response.aread()
                _raise_from_error_body(
                    status_code=response.status_code,
                    body=error_body,
                    provider=provider_name,
                )

            async for raw_event in _iter_sse_events(response):
                event_type, data = raw_event
                if not data or data == "[DONE]":
                    continue
                try:
                    parsed = json.loads(data)
                except json.JSONDecodeError:
                    continue

                # Anthropic includes ``type`` inside data; some events
                # rely on the ``event:`` line — we accept either.
                kind = parsed.get("type") or event_type

                if kind == "message_start":
                    message = parsed.get("message") or {}
                    response_id = str(message.get("id") or response_id)
                    response_model = str(message.get("model") or response_model)
                    usage = message.get("usage") or {}
                    prompt_tokens = int(usage.get("input_tokens", prompt_tokens))
                    if not role_emitted:
                        role_emitted = True
                        yield _make_chunk(
                            response_id=response_id,
                            created=created,
                            model=response_model,
                            delta=ChatCompletionDelta(role="assistant"),
                        )
                    continue

                if kind == "content_block_delta":
                    delta_block = parsed.get("delta") or {}
                    if delta_block.get("type") == "text_delta":
                        text = str(delta_block.get("text", ""))
                        if text:
                            yield _make_chunk(
                                response_id=response_id,
                                created=created,
                                model=response_model,
                                delta=ChatCompletionDelta(content=text),
                            )
                    continue

                if kind == "message_delta":
                    delta_block = parsed.get("delta") or {}
                    stop_reason_raw = delta_block.get("stop_reason")
                    if isinstance(stop_reason_raw, str):
                        finish_reason = STOP_REASON_MAP.get(stop_reason_raw, "stop")
                    usage = parsed.get("usage") or {}
                    if "output_tokens" in usage:
                        completion_tokens = int(usage["output_tokens"])
                    continue

                if kind == "message_stop":
                    # We emit the final chunk after the loop so we can
                    # incorporate the message_delta's usage even if a
                    # different ordering ever appears.
                    continue

                # ping / unknown -> ignore
    except httpx.HTTPError as exc:
        raise ProviderNetworkError(
            f"failed to stream from Anthropic: {type(exc).__name__}",
            details={"provider": provider_name},
        ) from exc

    # Final chunk: finish_reason + usage.
    yield ChatCompletionChunk(
        id=response_id,
        created=created,
        model=response_model,
        choices=[
            ChatCompletionChunkChoice(
                index=0,
                delta=ChatCompletionDelta(),
                finish_reason=finish_reason or "stop",
            )
        ],
        usage=ChatCompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


def _make_chunk(
    *,
    response_id: str,
    created: int,
    model: str,
    delta: ChatCompletionDelta,
) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id=response_id,
        created=created,
        model=model,
        choices=[ChatCompletionChunkChoice(index=0, delta=delta, finish_reason=None)],
    )


async def _iter_sse_events(
    response: httpx.Response,
) -> AsyncIterator[tuple[str | None, str]]:
    """Iterate ``(event, data)`` tuples from an SSE response.

    Implements the subset of the SSE spec Anthropic uses: ``event:`` and
    ``data:`` lines, blank-line frame terminators, ignores ``id:`` /
    ``retry:``. Multi-line ``data:`` values join with ``\\n``.
    """

    event_type: str | None = None
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                yield event_type, "\n".join(data_lines)
            event_type = None
            data_lines = []
            continue
        if line.startswith(":"):
            # SSE comment / heartbeat
            continue
        if line.startswith("event:"):
            event_type = line[len("event:") :].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip(" "))
            continue
        # Unknown field — ignore per SSE spec.

    # Trailing frame without blank-line terminator (rare; defensive).
    if data_lines:
        yield event_type, "\n".join(data_lines)


# --- Error mapping ------------------------------------------------------------


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
    """Parse an Anthropic error body and raise the right adapter error.

    Anthropic error shape::

        {"type": "error", "error": {"type": "invalid_request_error", "message": "..."}}

    We surface ``error.message`` to the operator (it's API-key-free by
    Anthropic's convention) and tag the error type in ``details``. We
    deliberately do not echo the raw body when parsing fails — that's
    where accidental key/PII leakage would happen.
    """

    upstream_type: str | None = None
    upstream_message: str | None = None
    try:
        parsed = json.loads(body or b"{}")
    except json.JSONDecodeError:
        parsed = {}
    if isinstance(parsed, dict):
        error_block = parsed.get("error")
        if isinstance(error_block, dict):
            raw_type = error_block.get("type")
            raw_message = error_block.get("message")
            if isinstance(raw_type, str):
                upstream_type = raw_type
            if isinstance(raw_message, str):
                upstream_message = raw_message

    details: dict[str, object] = {"provider": provider}
    if upstream_type:
        details["upstream_error_type"] = upstream_type

    safe_message = upstream_message or f"Anthropic returned HTTP {status_code}"

    if status_code in (401, 403):
        details["upstream_status"] = status_code
        raise ProviderAuthError(
            f"Anthropic rejected the gateway's credentials ({status_code})",
            details=details,
        )
    raise ProviderHTTPError(
        safe_message,
        upstream_status=status_code,
        details=details,
    )
