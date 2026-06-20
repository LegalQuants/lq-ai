"""Ollama provider adapter (B6 partial — chat completions only).

Translates between the gateway's OpenAI-compatible surface and Ollama's
native ``POST /api/chat`` endpoint. Ollama is the LQ.AI Mode-2
(air-gapped local inference) backbone per PRD §1.5.1 / §6.1; the adapter
is what makes ``local-fast`` / ``local-thinking`` aliases route to
``http://ollama:11434`` inside the operator's deployment with no
outbound network.

Wire-format differences worth knowing
-------------------------------------

* OpenAI's ``messages: [{role, content}, ...]`` passes through directly.
  Ollama accepts the same four roles (``system`` / ``user`` /
  ``assistant`` / ``tool``) so no role re-mapping is needed; tool
  messages forward verbatim.
* Sampling parameters move into Ollama's ``options`` sub-object:
  ``max_tokens`` -> ``options.num_predict``, ``temperature`` ->
  ``options.temperature``, ``top_p`` -> ``options.top_p``, ``stop`` ->
  ``options.stop`` (list-only). The OpenAI ``stop: "END"`` form becomes
  ``["END"]``.
* Streaming is **line-delimited JSON**, not SSE. Each line is a JSON
  object carrying a ``message.content`` increment plus, on the terminal
  line, ``done: true`` and final usage fields (``prompt_eval_count``,
  ``eval_count``, ``done_reason``). No ``data:`` prefix, no event
  names, no ``[DONE]`` sentinel — just one JSON object per line. The
  adapter parses line-by-line and translates each into an OpenAI-shaped
  :class:`ChatCompletionChunk`.
* Ollama does not require a max-tokens budget the way Anthropic does;
  when the OpenAI-format request omits it, we omit ``num_predict`` and
  let the model run to its own stop. (Ollama treats ``-1`` as "infinite";
  we don't volunteer that — operator-tunable when it surfaces.)
* Token usage is reported as ``prompt_eval_count`` (input) and
  ``eval_count`` (output). Both arrive on the terminal frame.
* Ollama returns ``done_reason`` in {``stop``, ``length``, ``load``}
  on the terminal frame; we translate ``length`` → ``length`` and
  everything else → ``stop`` (Ollama doesn't surface tool-use as a
  stop reason — tool plumbing is request-side only as of 2026-05).

Error semantics
---------------

Ollama's most common failure modes are:

* **Connection refused / DNS failure** — the operator hasn't run the
  Compose ``ollama`` profile or the host is wrong. Translates to
  :class:`ProviderNetworkError` (gateway maps to 503 + ``provider_unavailable``).
* **HTTP 404** — the requested model isn't pulled / known. Ollama's body
  is ``{"error": "model 'foo' not found, try pulling it first"}``.
  Translates to :class:`ProviderHTTPError` with upstream status 404
  and ``code = "invalid_model"`` so the gateway returns 400 (the
  request named a model the deployment can't serve, which is the
  caller's class-of-mistake even though the upstream answered).
* **HTTP 503** — model is loading, or the server is overwhelmed.
  Translates to :class:`ProviderHTTPError` (eligible for fallback per
  B4's ``is_fallback_eligible``) and the request flips through the
  alias's fallback chain. From the caller's POV "the inference path
  isn't available right now" is the same shape whether it's
  model-not-loaded or upstream-down; the operator sees the upstream
  status + body in ``details`` for diagnosis.
* **Other 5xx** — same path as 503.

Why no ``ollama`` Python SDK
----------------------------

Same posture as B3 / Anthropic: PRD §4 calls for hand-rolled gateway
code in lieu of LLM-SDK dependencies, to keep the supply-chain surface
honest. ``httpx`` is the only outbound HTTP we need, and the Ollama
chat surface is small enough that a direct httpx call + a JSON parser
beats a transitive dependency.
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


DEFAULT_TIMEOUT_SECONDS = 120.0
"""Default per-request timeout. Ollama generation latency is bounded by
local hardware — slow CPUs or large models can take well over a minute
on the first generation after a model load. The default is generous;
``timeout_s`` on each provider entry overrides per-deployment."""


DONE_REASON_MAP: dict[str, FinishReason] = {
    "stop": "stop",
    "length": "length",
    # "load" appears when generation aborted because the model was being
    # loaded; we surface as "stop" so the OpenAI-shape stays clean. The
    # operator sees the underlying details on the routing-log row /
    # gateway logs.
    "load": "stop",
}
"""Translate Ollama ``done_reason`` values to OpenAI ``finish_reason``.

Unknown values default to ``"stop"`` — the OpenAI surface only has four
finish-reason values and ``stop`` is the safest fallback ("the model
finished generating" is true regardless of the underlying reason)."""


class OllamaAdapter(ProviderAdapter):
    """Concrete :class:`ProviderAdapter` for Ollama.

    Construct via :meth:`from_config` from a loaded ``ProviderConfig``.
    Ollama doesn't require an API key — the adapter intentionally does
    not read one. ``provider.api_key_env`` is honored for forward
    compatibility (some deployments front Ollama with a reverse proxy
    that adds a bearer token); when set, the adapter uses the env var's
    value as a Bearer token.
    """

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str = "",
        timeout_s: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        # Ollama URL normalization: trim trailing slashes so we can join
        # ``/api/chat`` cleanly. ``http://ollama:11434/`` and
        # ``http://ollama:11434`` end up identical post-normalization.
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
    ) -> OllamaAdapter:
        """Build an adapter from a loaded :class:`ProviderConfig`.

        ``provider.type`` must be ``"ollama"``. ``provider.base_url`` is
        required and points at the Ollama server (typically
        ``http://ollama:11434`` inside the Compose stack). ``api_key_env``
        is optional; when set and the env var is populated, the adapter
        sends ``Authorization: Bearer <value>`` (for proxy-fronted
        deployments). When unset / empty, no Authorization header is
        emitted — vanilla Ollama rejects nothing, but some local proxies
        reject any present-but-empty Authorization header.
        """

        if provider.type != "ollama":
            raise ValueError(
                f"OllamaAdapter requires provider.type == 'ollama'; got {provider.type!r}"
            )
        if not provider.base_url:
            raise ValueError(
                f"Ollama provider {provider.name!r} requires a base_url "
                "(typically http://ollama:11434)"
            )

        env_lookup = env if env is not None else dict(os.environ)
        if key_resolver is None:
            key_resolver = ProviderKeyResolver(
                master_key=env_lookup.get("LQ_AI_GATEWAY_MASTER_KEY") or None,
                env=env_lookup,
            )
        # Ollama keys are optional. The resolver returns "" when both
        # sources are unset, which the adapter treats as "no auth header".
        api_key = key_resolver.resolve(
            provider_name=provider.name,
            api_key_env=provider.api_key_env or None,
            api_key_encrypted=provider.api_key_encrypted,
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
        """Issue a chat-completion request against Ollama's ``/api/chat``.

        On success returns either a :class:`ChatCompletionResponse`
        (``stream=False``) or an async iterator over
        :class:`ChatCompletionChunk` objects (``stream=True``). Failure
        modes raise the appropriate :class:`ProviderAdapterError`
        subclass; the route handler maps these to HTTP responses.
        """

        ollama_body = _to_ollama_request(request, model=model, stream=stream)

        if stream:
            return _ollama_stream_iter(
                client=self._client,
                body=ollama_body,
                headers=self._auth_headers(),
                provider_name=self.name,
                requested_model=model,
            )
        return await self._chat_completion_unary(ollama_body, model=model)

    async def embeddings(
        self,
        request: EmbeddingsRequest,
        *,
        model: str,
    ) -> EmbeddingsResponse:
        """Ollama has an ``/api/embed`` endpoint; the adapter does not
        implement it in this revision.

        The KB / RAG layer (C6) routes the ``embedding`` alias to the
        OpenAI adapter per ADR 0008 (1536-dim matches the
        ``document_chunks.embedding`` column). When an operator wants
        local embeddings for Mode 2, the path is: implement
        ``/api/embed`` here, add a Tier-1 ``embedding-local`` alias in
        ``gateway.yaml``, and ALTER the embedding column to the
        Ollama-served model's dimension. That work is documented as a
        deferred-enhancement entry in M1-PROGRESS; until it lands the
        method raises :class:`ProviderUnsupportedError` so the
        embeddings handler's fallback walk picks the next candidate.
        """

        raise ProviderUnsupportedError(
            "Ollama embeddings are not yet wired through the gateway; "
            "route the 'embedding' alias to the OpenAI adapter or another "
            "embedding-capable provider (ADR 0008)",
            details={"provider": self.name, "model": model},
        )

    async def health_check(self) -> ProviderHealth:
        """Probe Ollama's ``GET /api/tags`` endpoint.

        ``/api/tags`` is the cheapest GET on the Ollama API — it returns
        the list of locally-available models without loading any of
        them. Health probes use a shorter timeout so admin endpoints
        stay responsive when the local server is misbehaving.
        """

        start = time.monotonic()
        try:
            response = await self._client.get(
                "/api/tags",
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
        """Headers required on every Ollama call.

        Vanilla Ollama doesn't authenticate; we send only ``content-type``.
        For proxy-fronted deployments where ``api_key_env`` is set and
        populated, we add ``Authorization: Bearer <value>``. We never
        send an empty Bearer header — some proxies reject any present
        Authorization outright.
        """

        headers: dict[str, str] = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        return headers

    async def _chat_completion_unary(
        self,
        ollama_body: dict[str, Any],
        *,
        model: str,
    ) -> ChatCompletionResponse:
        try:
            response = await self._client.post(
                "/api/chat",
                json=ollama_body,
                headers=self._auth_headers(),
            )
        except httpx.HTTPError as exc:
            raise ProviderNetworkError(
                f"failed to reach Ollama: {type(exc).__name__}",
                details={"provider": self.name},
            ) from exc

        _raise_for_status(response, provider=self.name)
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderHTTPError(
                "Ollama returned a non-JSON response",
                upstream_status=response.status_code,
                details={"provider": self.name},
            ) from exc

        return _from_ollama_response(payload, requested_model=model)


# --- Helpers ------------------------------------------------------------------


def _safe_int(value: Any) -> int:
    """Coerce a JSON-derived value to int, defaulting to 0 on anything weird.

    Ollama's count fields (``prompt_eval_count``, ``eval_count``) are
    always integers in practice, but defensive coercion makes the
    streaming path resilient to a malformed terminal frame (which we
    don't want to hard-crash the whole request over)."""

    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


# --- Translation: OpenAI -> Ollama --------------------------------------------


def _to_ollama_request(
    request: ChatCompletionRequest,
    *,
    model: str,
    stream: bool,
) -> dict[str, Any]:
    """Build the Ollama ``/api/chat`` request body.

    Mapping highlights:

    * ``messages`` pass through verbatim with role preserved (Ollama
      accepts the same four roles).
    * ``stream`` is forwarded; when ``False`` the gateway expects a
      single JSON response, when ``True`` we get newline-delimited JSON.
    * Sampling parameters move into ``options``: ``num_predict`` (from
      ``max_tokens``), ``temperature``, ``top_p``, and ``stop`` (Ollama
      uses ``stop`` directly, list-only).

    Tool messages (``role: tool``) flow through; Ollama 0.4+ accepts
    them in the ``messages`` array. Tool-call assistant messages (with
    ``tool_calls``) are passed through under their original role; the
    M1 starter skill corpus does not declare tools today (per the C2
    scope check in M1-PROGRESS), so this is unexercised but
    structurally correct.
    """

    ollama_messages: list[dict[str, Any]] = []
    for msg in request.messages:
        content = msg.content or ""
        # Ollama accepts the four standard roles unchanged. We do not
        # collapse system messages (Ollama supports multiple, though
        # most operators consolidate upstream). Tool messages forward
        # with role="tool" and content="..."; Ollama's chat surface
        # accepts that shape.
        message_obj: dict[str, Any] = {"role": msg.role, "content": content}
        if msg.tool_call_id:
            # Pass-through; Ollama expects ``tool_call_id`` on tool
            # messages too.
            message_obj["tool_call_id"] = msg.tool_call_id
        if msg.tool_calls:
            message_obj["tool_calls"] = msg.tool_calls
        if msg.name:
            message_obj["name"] = msg.name
        ollama_messages.append(message_obj)

    body: dict[str, Any] = {
        "model": model,
        "messages": ollama_messages,
        "stream": stream,
    }

    options: dict[str, Any] = {}
    if request.max_tokens is not None:
        # Ollama's ``num_predict`` is the analogue of OpenAI's
        # ``max_tokens``; -1 is "infinite". We forward only when the
        # caller specified a bound so callers that omit max_tokens get
        # the model's default behavior.
        options["num_predict"] = request.max_tokens
    if request.temperature is not None:
        options["temperature"] = request.temperature
    if request.top_p is not None:
        options["top_p"] = request.top_p
    if request.stop is not None:
        options["stop"] = [request.stop] if isinstance(request.stop, str) else list(request.stop)
    if options:
        body["options"] = options

    # Tool calls / tool choice forward through ``tools`` per Ollama's
    # 0.4+ tool-use surface. The OpenAI ``tools`` schema maps directly:
    # both use the OpenAI tool-definition shape. ``tool_choice``
    # similarly forwards verbatim.  Prefer the explicit typed field
    # (PR5b added ``tools``/``tool_choice`` as first-class fields on
    # ``ChatCompletionRequest``); fall back to ``model_extra`` so legacy
    # callers that passed them as unknown extras still work.
    extra = request.model_extra or {}
    tools = request.tools if request.tools is not None else extra.get("tools")
    if tools is not None:
        body["tools"] = tools
    tool_choice = (
        request.tool_choice if request.tool_choice is not None else extra.get("tool_choice")
    )
    if tool_choice is not None:
        body["tool_choice"] = tool_choice

    return body


# --- Translation: Ollama -> OpenAI (non-streaming) ----------------------------


def _from_ollama_response(
    payload: dict[str, Any],
    *,
    requested_model: str,
) -> ChatCompletionResponse:
    """Translate an Ollama ``/api/chat`` JSON response into the OpenAI shape.

    Ollama's non-streaming response shape::

        {
            "model": "llama3.1",
            "created_at": "2026-05-08T12:00:00Z",
            "message": {"role": "assistant", "content": "..."},
            "done": true,
            "done_reason": "stop",
            "prompt_eval_count": 12,
            "eval_count": 7,
            "total_duration": 123456789,
            ...
        }
    """

    message_block = payload.get("message") or {}
    content = ""
    if isinstance(message_block, dict):
        raw_content = message_block.get("content")
        if isinstance(raw_content, str):
            content = raw_content

    done_reason_raw = payload.get("done_reason")
    finish_reason: FinishReason | None = None
    if isinstance(done_reason_raw, str):
        finish_reason = DONE_REASON_MAP.get(done_reason_raw, "stop")
    elif payload.get("done") is True:
        # Ollama always sets ``done: true`` on the unary response; if
        # ``done_reason`` is missing we still surface a finish.
        finish_reason = "stop"

    prompt_tokens = _safe_int(payload.get("prompt_eval_count"))
    completion_tokens = _safe_int(payload.get("eval_count"))
    usage = ChatCompletionUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )

    response_id = f"chatcmpl-{uuid.uuid4().hex}"
    response_model = str(payload.get("model") or requested_model)

    return ChatCompletionResponse(
        id=response_id,
        created=int(time.time()),
        model=response_model,
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionMessage(role="assistant", content=content),
                finish_reason=finish_reason,
            )
        ],
        usage=usage,
    )


# --- Translation: Ollama line-delimited JSON -> OpenAI chunks ----------------


async def _ollama_stream_iter(
    *,
    client: httpx.AsyncClient,
    body: dict[str, Any],
    headers: dict[str, str],
    provider_name: str,
    requested_model: str,
) -> AsyncIterator[ChatCompletionChunk]:
    """Stream Ollama line-delimited JSON and translate to OpenAI chunks.

    Ollama emits one JSON object per line on the wire::

        {"model":"llama3.1","message":{"role":"assistant","content":"He"},"done":false}\\n
        {"model":"llama3.1","message":{"role":"assistant","content":"llo"},"done":false}\\n
        {"model":"llama3.1","message":{"role":"assistant","content":""},"done":true,
         "done_reason":"stop","prompt_eval_count":7,"eval_count":2,"total_duration":...}\\n

    OpenAI's streaming format wants:

    * One initial chunk with ``delta.role = "assistant"``.
    * One chunk per text delta with ``delta.content = "<text piece>"``.
    * One final chunk with ``finish_reason`` set, ``delta`` empty, and
      a ``usage`` block.

    The ``[DONE]`` sentinel is the gateway route handler's
    responsibility (it emits it after the iterator finishes); the
    adapter only yields data chunks.
    """

    response_id = f"chatcmpl-{uuid.uuid4().hex}"
    response_model = requested_model
    created = int(time.time())
    finish_reason: FinishReason | None = None
    prompt_tokens = 0
    completion_tokens = 0
    role_emitted = False

    try:
        async with client.stream("POST", "/api/chat", json=body, headers=headers) as response:
            if response.status_code >= 400:
                # Read the error body so callers see a structured error
                # rather than a hung stream.
                error_body = await response.aread()
                _raise_from_error_body(
                    status_code=response.status_code,
                    body=error_body,
                    provider=provider_name,
                )

            async for line in _iter_ndjson_lines(response):
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    # Defensive: skip malformed lines (heartbeats /
                    # partial reads should not break the stream).
                    continue
                if not isinstance(parsed, dict):
                    continue

                # Update model identity if the line carries one.
                model_field = parsed.get("model")
                if isinstance(model_field, str) and model_field:
                    response_model = model_field

                if not role_emitted:
                    role_emitted = True
                    yield _make_chunk(
                        response_id=response_id,
                        created=created,
                        model=response_model,
                        delta=ChatCompletionDelta(role="assistant"),
                    )

                message_block = parsed.get("message") or {}
                if isinstance(message_block, dict):
                    chunk_text = message_block.get("content")
                    if isinstance(chunk_text, str) and chunk_text:
                        yield _make_chunk(
                            response_id=response_id,
                            created=created,
                            model=response_model,
                            delta=ChatCompletionDelta(content=chunk_text),
                        )

                if parsed.get("done") is True:
                    done_reason_raw = parsed.get("done_reason")
                    if isinstance(done_reason_raw, str):
                        finish_reason = DONE_REASON_MAP.get(done_reason_raw, "stop")
                    else:
                        finish_reason = "stop"
                    prompt_tokens = _safe_int(parsed.get("prompt_eval_count"))
                    completion_tokens = _safe_int(parsed.get("eval_count"))
                    # Don't break — Ollama always terminates the body
                    # after the done line, but the loop will exit
                    # naturally on EOF. Breaking would skip any
                    # trailing whitespace lines that aiter_lines might
                    # surface.
    except httpx.HTTPError as exc:
        raise ProviderNetworkError(
            f"failed to stream from Ollama: {type(exc).__name__}",
            details={"provider": provider_name},
        ) from exc

    # Final chunk: finish_reason + usage. We always emit one — even if
    # we never saw a ``done: true`` line, the OpenAI surface expects a
    # terminal chunk and ``stop`` is the safest fallback.
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


async def _iter_ndjson_lines(response: httpx.Response) -> AsyncIterator[str]:
    """Iterate stripped, non-empty lines from an NDJSON response.

    httpx's ``aiter_lines`` already handles partial reads across the
    underlying TCP framing — the iterator yields complete lines once
    each newline boundary arrives. We strip whitespace and skip empty
    lines (Ollama doesn't emit them today, but a forward-looking
    server might insert keepalive blanks).
    """

    async for raw in response.aiter_lines():
        line = raw.strip()
        if not line:
            continue
        yield line


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
    """Parse an Ollama error body and raise the right adapter error.

    Ollama's error shape is plain::

        {"error": "model 'foo' not found, try pulling it first"}

    We surface the ``error`` string verbatim (Ollama doesn't return
    user secrets in its errors; the messages are operator-actionable
    by design — "model not found", "model is loading", etc.).

    Mapping rules:

    * 404 -> ``ProviderHTTPError`` with ``code = "invalid_model"`` so
      the gateway returns 400 (the request named a model the
      deployment can't serve). The error message names the model.
    * 503 -> ``ProviderHTTPError`` with ``code = "provider_unavailable"``;
      eligible for fallback per B4's policy. Both "model is loading"
      and "server is overwhelmed" land here — from the caller's POV
      both are "the inference path isn't available right now".
    * Other 4xx / 5xx -> ``ProviderHTTPError`` with the standard
      ``provider_unavailable`` code; gateway maps to 502.
    """

    upstream_message: str | None = None
    try:
        parsed = json.loads(body or b"{}")
    except json.JSONDecodeError:
        parsed = {}
    if isinstance(parsed, dict):
        raw_error = parsed.get("error")
        if isinstance(raw_error, str):
            upstream_message = raw_error

    details: dict[str, object] = {"provider": provider, "upstream_status": status_code}
    if upstream_message:
        details["upstream_error"] = upstream_message

    if status_code == 404:
        # Distinct error class so the route handler can map to a 400
        # ``invalid_model`` rather than the generic 502 the default
        # ``ProviderHTTPError`` path produces. We synthesize that
        # mapping by raising :class:`ProviderModelNotFound`, a
        # ProviderHTTPError subclass with a more specific ``code``.
        raise ProviderModelNotFound(
            upstream_message or f"Ollama returned HTTP {status_code}",
            upstream_status=status_code,
            details=details,
        )

    raise ProviderHTTPError(
        upstream_message or f"Ollama returned HTTP {status_code}",
        upstream_status=status_code,
        details=details,
    )


class ProviderModelNotFound(ProviderHTTPError):
    """Specialization of :class:`ProviderHTTPError` for "model not found".

    Used when an upstream returns 404 with an error body indicating the
    requested model isn't available locally (Ollama's most common
    operator-visible error: the model wasn't pulled). The route
    handler maps this to gateway HTTP 400 with ``code = "invalid_model"``
    rather than the default 502 ``provider_unavailable`` so callers see
    "your model name is wrong / not pulled" rather than "upstream
    flaked".

    Inherits ``code`` from the parent (``provider_unavailable``); the
    route handler reads ``isinstance(..., ProviderModelNotFound)`` to
    decide on the 400 mapping. Keeping the class name distinct avoids
    a more invasive change to the error-code enum (``invalid_model`` is
    already a gateway-level code on the model-resolution path; we're
    re-using it here for the same operator-class mistake).
    """

    code = "invalid_model"
