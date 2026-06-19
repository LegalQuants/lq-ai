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
  back to :data:`DEFAULT_MAX_TOKENS` (4096) when the caller omits it.
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

from app.config import ProviderConfig
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
    ToolDefinition,
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
responses on requests that didn't specify a budget."""

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
        """Issue a chat-completion request against Anthropic Messages.

        On success returns either a :class:`ChatCompletionResponse`
        (``stream=False``) or an async iterator over
        :class:`ChatCompletionChunk` objects (``stream=True``). Failure
        modes raise the appropriate :class:`ProviderAdapterError`
        subclass; the route handler maps these to HTTP responses.
        """

        anthropic_body = _to_anthropic_request(request, model=model, stream=stream)

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
) -> dict[str, Any]:
    """Build the Anthropic ``/v1/messages`` request body.

    The mapping is:

    * ``messages[role=system]`` are pulled out and concatenated into the
      top-level ``system`` string.
    * ``messages[role=user|assistant]`` keep their order. Tool messages
      are passed through as ``role="user"`` with content blocks shaped
      ``{"type": "tool_result", ...}``; tool-call assistant messages are
      currently passed through as text only (see DE note below).
    * ``max_tokens`` is required by Anthropic; we substitute
      :data:`DEFAULT_MAX_TOKENS` if the caller omits it.
    * ``temperature`` and ``top_p`` are forwarded if set; otherwise
      Anthropic uses its defaults.
    * ``stop`` (OpenAI) becomes ``stop_sequences`` (Anthropic, list-only).

    Tool calling (PR5b / WS4): when ``request.tools`` is set, each OpenAI
    function-tool becomes an Anthropic tool block (``input_schema``) and
    ``tool_choice`` is translated to Anthropic's shape. Assistant messages
    that carry ``tool_calls`` (the multi-step loop replaying its own prior
    calls) are rebuilt as ``tool_use`` content blocks, and ``role="tool"``
    results are sent as ``tool_result`` blocks (already handled below).
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
            # Assistant turn that issued tool calls (multi-step loop): rebuild
            # Anthropic ``tool_use`` content blocks so the model sees its own
            # prior calls. Any leading assistant text is preserved first.
            assistant_blocks: list[dict[str, Any]] = []
            if content:
                assistant_blocks.append({"type": "text", "text": content})
            for call in msg.tool_calls:
                assistant_blocks.append(_tool_call_to_tool_use(call))
            chat_messages.append({"role": "assistant", "content": assistant_blocks})
            continue
        # user / assistant (text only)
        chat_messages.append({"role": msg.role, "content": content})

    body: dict[str, Any] = {
        "model": model,
        "messages": chat_messages,
        "max_tokens": request.max_tokens or DEFAULT_MAX_TOKENS,
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
    # PR5b: tool allowlist + choice. ``tool_choice="none"`` means "don't use
    # tools this turn", so we omit the tools block entirely rather than send
    # an unusable Anthropic ``tool_choice``.
    if request.tools and request.tool_choice != "none":
        body["tools"] = [_tool_to_anthropic(tool) for tool in request.tools]
        choice = _tool_choice_to_anthropic(request.tool_choice)
        if choice is not None:
            body["tool_choice"] = choice
    return body


def _tool_to_anthropic(tool: ToolDefinition) -> dict[str, Any]:
    """Translate an OpenAI function-tool to an Anthropic tool block.

    Anthropic requires an ``input_schema`` (JSON Schema object); we pass the
    OpenAI ``parameters`` through and substitute an empty-object schema when
    the caller omits it (a no-argument tool).
    """

    schema = tool.function.parameters or {"type": "object", "properties": {}}
    block: dict[str, Any] = {"name": tool.function.name, "input_schema": schema}
    if tool.function.description:
        block["description"] = tool.function.description
    return block


def _tool_choice_to_anthropic(choice: str | dict[str, Any] | None) -> dict[str, Any] | None:
    """Translate an OpenAI ``tool_choice`` to Anthropic's shape.

    ``auto`` / ``None`` -> Anthropic default (auto), so we return ``None`` and
    omit the field. ``required`` -> ``{"type": "any"}``. A specific
    ``{"type": "function", "function": {"name": N}}`` -> ``{"type": "tool",
    "name": N}``. (``"none"`` is handled by the caller, which drops tools.)
    """

    if choice is None or choice == "auto":
        return None
    if choice == "required":
        return {"type": "any"}
    if isinstance(choice, dict):
        fn = choice.get("function")
        if isinstance(fn, dict) and isinstance(fn.get("name"), str):
            return {"type": "tool", "name": fn["name"]}
    return None


def _tool_call_to_tool_use(call: dict[str, Any]) -> dict[str, Any]:
    """Rebuild an Anthropic ``tool_use`` block from an OpenAI tool_call dict.

    OpenAI carries arguments as a JSON *string*; Anthropic wants a parsed
    object in ``input``. A malformed/empty arguments string degrades to an
    empty object rather than failing the whole turn.
    """

    fn = call.get("function") or {}
    raw_args = fn.get("arguments")
    parsed_args: Any
    if isinstance(raw_args, str):
        try:
            parsed_args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            parsed_args = {}
    elif isinstance(raw_args, dict):
        parsed_args = raw_args
    else:
        parsed_args = {}
    return {
        "type": "tool_use",
        "id": str(call.get("id") or ""),
        "name": str(fn.get("name") or ""),
        "input": parsed_args,
    }


def _tool_use_to_tool_call(block: dict[str, Any]) -> dict[str, Any]:
    """Translate an Anthropic ``tool_use`` content block to an OpenAI tool_call.

    Anthropic carries ``input`` as a parsed object; OpenAI wants arguments as
    a JSON string. A missing id is synthesized so downstream correlation (the
    chat loop's ``tool_result`` reply) always has a handle.
    """

    call_id = str(block.get("id") or f"call_{uuid.uuid4().hex}")
    name = str(block.get("name") or "")
    raw_input = block.get("input")
    arguments = json.dumps(raw_input if isinstance(raw_input, dict) else {})
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


# --- Translation: Anthropic -> OpenAI (non-streaming) -------------------------


def _from_anthropic_response(
    payload: dict[str, Any],
    *,
    requested_model: str,
) -> ChatCompletionResponse:
    """Translate an Anthropic ``message`` response into the OpenAI shape."""

    blocks = payload.get("content") or []
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(str(block.get("text", "")))
        elif block_type == "tool_use":
            tool_calls.append(_tool_use_to_tool_call(block))
    text = "".join(text_parts)

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

    return ChatCompletionResponse(
        id=response_id,
        created=int(time.time()),
        model=response_model,
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionMessage(
                    role="assistant",
                    # OpenAI convention: ``content`` may be null on a pure
                    # tool-call turn. Preserve "" for ordinary text responses
                    # (no behavior change) but null it when only tool calls.
                    content=text if text else (None if tool_calls else ""),
                    tool_calls=tool_calls or None,
                ),
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
    # PR5b: accumulate streamed tool_use blocks keyed by Anthropic content
    # block index; emit an OpenAI tool_calls delta when each block stops.
    tool_uses: dict[int, dict[str, Any]] = {}

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

                if kind == "content_block_start":
                    cb = parsed.get("content_block") or {}
                    idx = parsed.get("index")
                    if cb.get("type") == "tool_use" and isinstance(idx, int):
                        if not role_emitted:
                            role_emitted = True
                            yield _make_chunk(
                                response_id=response_id,
                                created=created,
                                model=response_model,
                                delta=ChatCompletionDelta(role="assistant"),
                            )
                        tool_uses[idx] = {
                            "ordinal": len(tool_uses),
                            "id": str(cb.get("id") or f"call_{uuid.uuid4().hex}"),
                            "name": str(cb.get("name") or ""),
                            "args": "",
                        }
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
                    elif delta_block.get("type") == "input_json_delta":
                        idx = parsed.get("index")
                        if isinstance(idx, int) and idx in tool_uses:
                            tool_uses[idx]["args"] += str(delta_block.get("partial_json", ""))
                    continue

                if kind == "content_block_stop":
                    idx = parsed.get("index")
                    if isinstance(idx, int) and idx in tool_uses:
                        tu = tool_uses[idx]
                        yield _make_chunk(
                            response_id=response_id,
                            created=created,
                            model=response_model,
                            delta=ChatCompletionDelta(
                                tool_calls=[
                                    {
                                        "index": tu["ordinal"],
                                        "id": tu["id"],
                                        "type": "function",
                                        "function": {
                                            "name": tu["name"],
                                            "arguments": tu["args"] or "",
                                        },
                                    }
                                ]
                            ),
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
