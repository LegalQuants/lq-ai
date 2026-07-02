"""AWS Bedrock Mantle provider adapter — DE-035 (supersedes InvokeModel/SigV4).

AWS's ``bedrock-mantle.{region}.api.aws`` endpoint serves Bedrock models
over three native wire protocols, authenticated with a single Bearer
token (a Bedrock API key, IAM-backed) instead of per-request SigV4
signing:

* **Chat Completions** (``POST /v1/chat/completions``) — legacy/compat
  models. Identical wire shape to OpenAI's Chat Completions, so this
  tier reuses :class:`~app.providers.openai.OpenAIAdapter`'s
  translation helpers verbatim; ``BedrockMantleAdapter`` only overrides
  construction and auth.
* **Messages** (``POST /anthropic/v1/messages``, off the Mantle *domain
  root* — NOT ``/v1``-relative to ``base_url`` like the other two tiers)
  — current-generation Anthropic models (e.g. ``anthropic.claude-opus-4-8``).
  New translation adapted from :mod:`app.providers.anthropic`'s Messages
  parser — not assumed byte-identical to direct api.anthropic.com
  responses. Path bug fixed 2026-07-02: the original implementation
  posted the relative path against a client whose ``base_url`` already
  ends in ``/v1``, producing ``.../v1/anthropic/v1/messages`` — a bogus
  double-``/v1`` URL that 404s. Verified live against a real AWS
  account: the correct URL (domain root + ``/anthropic/v1/messages``)
  returns a real, structured entitlement response (403
  ``permission_error``) instead of an opaque 404.
* **Responses** — current-generation OpenAI models (e.g.
  ``openai.gpt-5.5``) and a handful of other model families. Entirely
  new translation; no existing gateway code speaks the Responses wire
  format. Two URL conventions coexist, selected per-model by
  :meth:`BedrockMantleAdapter._responses_url` — see
  :data:`RESPONSES_EXCEPTION_MODEL_PREFIXES` for the exception list and
  what's actually been live-tested (as of 2026-07-02: ``openai.gpt-oss-20b``
  on the general path; ``google.gemma-4-31b`` and ``xai.grok-4.3`` on the
  exception path; ``openai.gpt-5.4``/``openai.gpt-5.5`` blocked on account
  entitlement past the URL/transport layer).

Per-request protocol routing
-----------------------------

Live testing (2026-07-01) found that model support for these three
protocols is NOT uniform across models — each AWS model card
(https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards.html)
documents, per model, exactly which of ``bedrock-runtime``/
``bedrock-mantle`` and which wire protocols it supports, and that
support set varies. Operators adding a model to ``gateway.yaml``'s
``bedrock_mantle`` provider entry should check its model card first.
The adapter routes each request to a protocol tier by model-ID prefix:

* ``anthropic.*`` -> Messages
* ``openai.gpt-5.*`` and :data:`RESPONSES_EXCEPTION_MODEL_PREFIXES`
  (``google.gemma-4``, ``xai.grok-4.3``) -> Responses
* everything else -> Chat Completions

This is a heuristic, not an entitlement guarantee — a misrouted model
still surfaces a clean, distinguishable error (see error classes below)
rather than corrupting a response.

Why not one adapter reusing pure inheritance
----------------------------------------------

Unlike Azure OpenAI (thin subclass, same wire format), Mantle's three
tiers are three different wire formats behind one base URL and one auth
token. ``BedrockMantleAdapter`` therefore composes rather than
inherits: it dispatches ``chat_completion`` to one of three private
methods, each of which builds its own request/response translation.

Auth
----

``Authorization: Bearer <bedrock-api-key>`` on every call, for every
tier — confirmed live via direct testing and via the
``AnthropicBedrockMantle`` SDK client's header construction. This is
the base :class:`~app.providers.openai.OpenAIAdapter`'s default auth
header shape, so no override is needed.

Error mapping
-------------

Live testing found three distinct error classes that must not collapse
into a generic "unauthorized":

1. **403, Anthropic-native envelope** (``{"type": "error", "error":
   {"type": "permission_error", ...}}``) on the Messages surface —
   model not entitled on this AWS account.
2. **401, OpenAI-native envelope** (``{"error": {"type":
   "permission_denied_error", ...}}``) on the Responses surface —
   also an entitlement issue, despite the auth-shaped status code.
3. **400, OpenAI-native envelope** (``{"error": {"code":
   "validation_error", "type": "invalid_request_error", "message":
   "The model '<id>' does not support the '<path>' API"}}``) on the
   Responses surface — wrong API path for this model (a routed model
   doesn't actually support the tier ``_route_protocol`` sent it to).

All three map to :class:`~app.providers.base.ProviderHTTPError` with
``code="invalid_model"`` (never ``ProviderAuthError``/``unauthorized``)
so operators aren't misled into rotating a working credential.

Server-side tool calling (egress boundary, ADR 0014)
------------------------------------------------------

GPT-5.5's Responses surface supports AWS/OpenAI built-in server-side
tools. ``_to_responses_request`` only ever forwards the gateway's own
governed ``tools``/``tool_choice`` (per ADR 0015's operator-allowlist
model) — it never adds, defaults, or passes through a built-in tool
type. This keeps ADR 0014's single-audited-egress-boundary guarantee
intact for this tier; see ``test_bedrock_mantle_adapter.py`` for the
no-tools-configured assertion that pins this behavior.

We deliberately do not depend on the ``anthropic`` or ``openai`` Python
SDKs (PRD §4 / ADR 0008 "no LLM-SDK dependency" posture) — raw httpx,
matching every other adapter in this package.
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
from app.providers.openai import (
    DEFAULT_TIMEOUT_SECONDS,
    OpenAIAdapter,
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

MANTLE_ANTHROPIC_API_VERSION = "2023-06-01"
"""Pinned Anthropic API version sent on every Messages-tier call, mirroring
:data:`app.providers.anthropic.ANTHROPIC_API_VERSION`."""

MANTLE_DEFAULT_MAX_TOKENS = 4096
"""Anthropic Messages requires ``max_tokens``; substituted when the
OpenAI-format request omits it. Same default as the direct-Anthropic
adapter."""

RESPONSES_EXCEPTION_MODEL_PREFIXES: tuple[str, ...] = (
    "google.gemma-4",
    "xai.grok-4.3",
    "openai.gpt-5.4",
    "openai.gpt-5.5",
)
"""Model-ID prefixes confirmed (live or via their own AWS model card) to use
``openai/v1/responses`` off the Mantle domain root, per FR3.x/the routing
docstring below. Kept around as the known-good set feeding
:data:`RESPONSES_GENERAL_PATH_MODEL_PREFIXES`'s complement logic and unit
test fixtures; not read directly by ``_responses_url`` — see that method
and :data:`RESPONSES_GENERAL_PATH_MODEL_PREFIXES` for the routing rule
itself. Live-tested 2026-07-02: ``google.gemma-4-31b`` and ``xai.grok-4.3``
both returned 200 via ``openai/v1/responses``; ``gpt-oss-20b`` was
separately tested against this same path and returned 400 "does not
support" (see :data:`RESPONSES_GENERAL_PATH_MODEL_PREFIXES`) — i.e. every
model tested against ``openai/v1/responses`` either works there or is
explicitly rejected, never silently wrong."""

RESPONSES_GENERAL_PATH_MODEL_PREFIXES: tuple[str, ...] = (
    "openai.gpt-oss",
    "zai.glm",
)
"""Model-ID prefixes confirmed to need the general ``/v1/responses`` path
(relative to ``base_url``) rather than the ``openai/v1/responses`` exception
path. ``_responses_url`` defaults to the exception path for anything NOT
in this list, on the strength of the trend observed across every Mantle
model launched so far (Gemma 4, Grok 4.3, GPT-5.4/5.5 all need it) — this
is a real reversal from the adapter's first cut, which defaulted to the
general path and hardcoded Gemma/Grok/GPT-5.* as exceptions to it. Kept
deliberately small: ``openai.gpt-oss-20b`` live-tested 400 "does not
support" against the exception path (2026-07-02); ``zai.glm-5`` live-tested
400 "does not support" against BOTH paths (Chat-Completions-only via
Mantle — this adapter never sends it through Responses via normal routing,
this table only matters if something calls the Responses tier for it
directly). A model whose family isn't yet known falls through to the
exception-path default; :func:`BedrockMantleAdapter._responses_unary` /
:func:`_responses_stream_iter` retry on the general path if that guess
returns AWS's specific 400 ``validation_error``/"does not support the
'<path>' API" signature — see
:func:`BedrockMantleAdapter._responses_url_with_fallback`."""

STOP_REASON_MAP: dict[str, FinishReason] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "pause_turn": "stop",
}
"""Anthropic ``stop_reason`` -> OpenAI ``finish_reason``, identical to the
direct-Anthropic adapter's mapping."""

_RESPONSES_TOOL_CALL_ITEM_TYPES = frozenset({"function_call"})
_RESPONSES_MESSAGE_ITEM_TYPES = frozenset({"message"})
_RESPONSES_DROPPED_ITEM_TYPES = frozenset({"reasoning"})
"""``output[]`` item types the adapter drops silently (FR3.6) rather than
mapping into the response — consistent with the Chat Completions tier's
existing behavior of silently ignoring the ``reasoning`` field some
Bedrock models emit."""


class BedrockMantleAdapter(ProviderAdapter):
    """Concrete :class:`ProviderAdapter` for AWS Bedrock's Mantle endpoint.

    Construct via :meth:`from_config` from a ``provider.type ==
    'bedrock_mantle'`` :class:`ProviderConfig` entry. A single Bearer
    token (``api_key_env`` / ``api_key_encrypted``, typically sourced
    from ``AWS_BEARER_TOKEN_BEDROCK``) authenticates all three protocol
    tiers.

    ``chat_completion`` dispatches per-request by model-ID prefix (see
    module docstring); ``embeddings`` raises
    :class:`ProviderUnsupportedError` (Bedrock embedding models are out
    of scope for this unit, matching the original DE-035 draft's scope
    decision).
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
        # Per-model Responses-path cache (process-lifetime — one adapter
        # instance is built once at gateway startup and reused across
        # requests). Populated on the first fallback retry for a model not
        # in RESPONSES_GENERAL_PATH_MODEL_PREFIXES/RESPONSES_EXCEPTION_MODEL_PREFIXES,
        # so later calls for that model skip straight to the URL that
        # actually worked instead of re-guessing and re-failing.
        self._responses_url_cache: dict[str, str] = {}
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout_s,
        )
        # F1 reuses the OpenAI adapter's translation helpers directly
        # rather than via subclassing (Mantle's other two tiers speak
        # different wire formats, so plain inheritance from
        # OpenAIAdapter would be misleading for this adapter as a whole).
        self._openai_delegate = OpenAIAdapter(
            name=name,
            base_url=base_url,
            api_key=api_key,
            timeout_s=timeout_s,
            client=self._client,
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
    ) -> BedrockMantleAdapter:
        """Build a Mantle adapter from a loaded :class:`ProviderConfig`.

        Required provider fields:

        * ``type`` — must be ``"bedrock_mantle"``.
        * ``base_url`` — the Mantle endpoint
          (``https://bedrock-mantle.<region>.api.aws/v1``).
        * One of ``api_key_env`` or ``api_key_encrypted`` — the Bedrock
          API key (Bearer token). Defaults to reading
          ``AWS_BEARER_TOKEN_BEDROCK`` when neither is set, matching
          the convention already used for the underlying AWS SDK.
        """

        if provider.type != "bedrock_mantle":
            raise ValueError(
                f"BedrockMantleAdapter requires provider.type='bedrock_mantle'; "
                f"got {provider.type!r}"
            )
        if key_resolver is None:
            env_lookup = env if env is not None else dict(os.environ)
            key_resolver = ProviderKeyResolver(
                master_key=env_lookup.get("LQ_AI_GATEWAY_MASTER_KEY") or None,
                env=env_lookup,
            )
        effective_env = provider.api_key_env or (
            None if provider.api_key_encrypted else "AWS_BEARER_TOKEN_BEDROCK"
        )
        api_key = key_resolver.resolve(
            provider_name=provider.name,
            api_key_env=effective_env,
            api_key_encrypted=provider.api_key_encrypted,
        )
        if not api_key:
            raise ValueError(
                f"Bedrock Mantle provider {provider.name!r} requires either "
                f"api_key_encrypted or environment variable "
                f"{(effective_env or 'AWS_BEARER_TOKEN_BEDROCK')!r} to be set"
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
        """Dispatch to the Chat Completions, Messages, or Responses tier.

        Routing is by model-ID prefix (see module docstring) — a
        heuristic, not an entitlement check. A model that doesn't
        actually support the routed tier surfaces one of the three
        documented error classes rather than a silent misroute.
        """

        protocol = self._route_protocol(model)
        if protocol == "messages":
            return await self._messages_chat_completion(request, model=model, stream=stream)
        if protocol == "responses":
            return await self._responses_chat_completion(request, model=model, stream=stream)
        return await self._chat_completions_chat_completion(request, model=model, stream=stream)

    @staticmethod
    def _route_protocol(model: str) -> str:
        """Model-ID -> Mantle protocol tier.

        ``anthropic.*`` -> ``"messages"``; ``openai.gpt-5.*`` and the
        entries in :data:`RESPONSES_EXCEPTION_MODEL_PREFIXES`
        (``google.gemma-4``, ``xai.grok-4.3`` — live-tested 2026-07-02;
        both returned 401 access_denied on this account's Chat
        Completions tier but 200 on Responses) -> ``"responses"``;
        everything else (legacy/compat models, including
        ``openai.gpt-oss-*``) -> ``"chat_completions"``.
        """

        if model.startswith("anthropic."):
            return "messages"
        if model.startswith("openai.gpt-5"):
            return "responses"
        if any(model.startswith(p) for p in RESPONSES_EXCEPTION_MODEL_PREFIXES):
            return "responses"
        return "chat_completions"

    async def embeddings(
        self,
        request: EmbeddingsRequest,
        *,
        model: str,
    ) -> EmbeddingsResponse:
        """Bedrock embedding models are out of scope for this unit."""

        raise ProviderUnsupportedError(
            "Bedrock Mantle embeddings are out of scope for this adapter; "
            "route the 'embedding' alias to a provider that supports it",
            details={"provider": self.name, "model": model},
        )

    async def health_check(self) -> ProviderHealth:
        """Probe the Chat Completions tier's ``GET /models`` endpoint.

        Cheapest authenticated GET available across all three tiers
        (Messages/Responses have no equivalent list endpoint documented
        on Mantle); a 401/403 here still confirms reachability and
        surfaces credential status.
        """

        return await self._openai_delegate.health_check()

    async def aclose(self) -> None:
        """Close the owned ``httpx.AsyncClient`` (if we created it)."""

        if self._owns_client:
            await self._client.aclose()

    # --- Internals: auth -------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        """``Authorization: Bearer <key>`` — identical across all three
        Mantle tiers (confirmed live)."""

        headers: dict[str, str] = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        return headers

    # --- F1: Chat Completions tier ----------------------------------------------

    async def _chat_completions_chat_completion(
        self,
        request: ChatCompletionRequest,
        *,
        model: str,
        stream: bool,
    ) -> ChatCompletionResponse | AsyncIterator[ChatCompletionChunk]:
        """Legacy/compat models. Reuses the OpenAI adapter's translation
        helpers verbatim (FR1.2) — Mantle's Chat Completions response
        shape is a clean OpenAI Chat Completions payload, modulo two
        harmless extra fields observed live: ``moderation: null`` and a
        named ``reasoning`` field on some models' messages (both are
        silently ignored by pydantic's default field handling).
        """

        return await self._openai_delegate.chat_completion(request, model=model, stream=stream)

    # --- F2: Messages tier (current-gen Anthropic) ------------------------------

    async def _messages_chat_completion(
        self,
        request: ChatCompletionRequest,
        *,
        model: str,
        stream: bool,
    ) -> ChatCompletionResponse | AsyncIterator[ChatCompletionChunk]:
        body = _to_messages_request(request, model=model, stream=stream)
        headers = self._messages_auth_headers()

        if stream:
            return _messages_stream_iter(
                client=self._client,
                url=self._messages_url(),
                body=body,
                headers=headers,
                provider_name=self.name,
                requested_model=model,
            )
        return await self._messages_unary(body, headers, model=model)

    def _messages_auth_headers(self) -> dict[str, str]:
        """Messages tier: same Bearer auth as the base adapter, plus the
        Anthropic-version header the Messages API requires on every call
        (confirmed via AWS's documented Messages schema)."""

        headers = self._auth_headers()
        headers["anthropic-version"] = MANTLE_ANTHROPIC_API_VERSION
        return headers

    def _messages_url(self) -> str:
        """Absolute URL for the Messages tier.

        Unlike Chat Completions and Responses (both ``/v1``-relative to
        ``base_url``), Messages lives at ``/anthropic/v1/messages`` off the
        Mantle *domain root* — confirmed live: posting the relative path
        against ``self._client`` (whose ``base_url`` already ends in
        ``/v1``) produces ``.../v1/anthropic/v1/messages``, a bogus URL that
        404s (verified against a real AWS account). Strips exactly one
        trailing ``/v1`` segment from ``self._base_url`` rather than the
        whole domain, so a differently-shaped operator ``base_url`` still
        degrades predictably instead of silently mismatching."""

        root = self._base_url
        if root.endswith("/v1"):
            root = root[: -len("/v1")]
        return f"{root}/anthropic/v1/messages"

    async def _messages_unary(
        self,
        body: dict[str, Any],
        headers: dict[str, str],
        *,
        model: str,
    ) -> ChatCompletionResponse:
        try:
            response = await self._client.post(
                self._messages_url(),
                json=body,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise ProviderNetworkError(
                f"failed to reach Bedrock Mantle (Messages): {type(exc).__name__}",
                details={"provider": self.name},
            ) from exc

        _raise_for_mantle_status(response, provider=self.name)
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderHTTPError(
                "Bedrock Mantle (Messages) returned a non-JSON response",
                upstream_status=response.status_code,
                details={"provider": self.name},
            ) from exc

        return _from_messages_response(payload, requested_model=model)

    # --- F3: Responses tier (current-gen OpenAI) --------------------------------

    async def _responses_chat_completion(
        self,
        request: ChatCompletionRequest,
        *,
        model: str,
        stream: bool,
    ) -> ChatCompletionResponse | AsyncIterator[ChatCompletionChunk]:
        body = _to_responses_request(request, model=model, stream=stream)
        headers = self._auth_headers()
        url = self._responses_url(model)

        if stream:
            # No retry-on-wrong-path for streaming: once bytes start
            # flowing there is no clean way to discard a partial SSE
            # response and restart against a different URL. Streaming
            # relies on whatever _responses_url already knows (cache or
            # best-guess default) — the unary path is what actually
            # populates the cache for a previously-unseen model.
            return _responses_stream_iter(
                client=self._client,
                url=url,
                body=body,
                headers=headers,
                provider_name=self.name,
                requested_model=model,
            )
        return await self._responses_unary_with_fallback(url, body, headers, model=model)

    def _responses_exception_url(self) -> str:
        root = self._base_url
        if root.endswith("/v1"):
            root = root[: -len("/v1")]
        return f"{root}/openai/v1/responses"

    def _responses_url(self, model: str) -> str:
        """URL for the Responses tier, per-model.

        Every Mantle model family launched so far except
        :data:`RESPONSES_GENERAL_PATH_MODEL_PREFIXES` needs
        ``openai/v1/responses`` off the Mantle domain root rather than the
        general ``/responses`` path relative to ``base_url`` — see that
        constant's docstring. A model not in either known list defaults to
        the exception path (the more common case observed so far); if that
        guess is wrong, :meth:`_responses_unary_with_fallback` retries the
        general path on AWS's specific "does not support" 400 and caches
        whichever URL actually worked, so later calls skip straight to it."""

        if model in self._responses_url_cache:
            return self._responses_url_cache[model]
        if any(model.startswith(p) for p in RESPONSES_GENERAL_PATH_MODEL_PREFIXES):
            return "/responses"
        return self._responses_exception_url()

    async def _responses_unary_with_fallback(
        self,
        url: str,
        body: dict[str, Any],
        headers: dict[str, str],
        *,
        model: str,
    ) -> ChatCompletionResponse:
        try:
            return await self._responses_unary(url, body, headers, model=model)
        except ProviderHTTPError as exc:
            if exc.details.get("mantle_error_class") != "unsupported_api_for_model":
                raise
            fallback_url = "/responses" if url == self._responses_exception_url() else self._responses_exception_url()
            result = await self._responses_unary(fallback_url, body, headers, model=model)
            self._responses_url_cache[model] = fallback_url
            return result

    async def _responses_unary(
        self,
        url: str,
        body: dict[str, Any],
        headers: dict[str, str],
        *,
        model: str,
    ) -> ChatCompletionResponse:
        try:
            response = await self._client.post(
                url,
                json=body,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise ProviderNetworkError(
                f"failed to reach Bedrock Mantle (Responses): {type(exc).__name__}",
                details={"provider": self.name},
            ) from exc

        _raise_for_mantle_status(response, provider=self.name)
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderHTTPError(
                "Bedrock Mantle (Responses) returned a non-JSON response",
                upstream_status=response.status_code,
                details={"provider": self.name},
            ) from exc

        return _from_responses_response(payload, requested_model=model)


# --- F2 translation: gateway -> Messages --------------------------------------


def _to_messages_request(
    request: ChatCompletionRequest,
    *,
    model: str,
    stream: bool,
) -> dict[str, Any]:
    """Build the Mantle Messages request body.

    Adapted from :func:`app.providers.anthropic._to_anthropic_request` —
    same mapping rules (system-message extraction, tool_use/tool_result
    round-tripping, tools/tool_choice translation). Kept as a sibling
    function rather than an import because A4 (wire-compatibility with
    direct-Anthropic Messages) is unvalidated pending live entitlement;
    extracting shared logic now would be a premature abstraction over an
    unverified assumption.
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
        chat_messages.append({"role": msg.role, "content": content})

    body: dict[str, Any] = {
        "model": model,
        "messages": chat_messages,
        "max_tokens": request.max_tokens or MANTLE_DEFAULT_MAX_TOKENS,
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
            body.pop("tools", None)
        elif raw_choice == "required":
            body["tool_choice"] = {"type": "any"}
        elif isinstance(raw_choice, dict):
            fn_choice = raw_choice.get("function", {})
            if fn_choice.get("name"):
                body["tool_choice"] = {"type": "tool", "name": fn_choice["name"]}
    return body


# --- F2 translation: Messages -> gateway (non-streaming) ----------------------


def _from_messages_response(
    payload: dict[str, Any],
    *,
    requested_model: str,
) -> ChatCompletionResponse:
    """Translate a Mantle Messages response into :class:`ChatCompletionResponse`.

    Field mapping matches :func:`app.providers.anthropic._from_anthropic_response`.
    **Not yet live-verified** (spec A4/A5) — implemented against AWS's
    documented Messages schema; diff against a real captured response
    once account entitlement allows a 200-OK call, per
    ``.aidlc/bedrock-mantle-adapter/tasks.md`` Task 7's checkpoint.
    """

    blocks = payload.get("content") or []
    text_parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(str(block.get("text", "")))
    text = "".join(text_parts)

    tool_calls: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_calls.append(
                {
                    "id": str(block.get("id", "")),
                    "type": "function",
                    "function": {
                        "name": str(block.get("name", "")),
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


# --- F2 translation: Messages SSE -> gateway chunks ----------------------------


async def _messages_stream_iter(
    *,
    client: httpx.AsyncClient,
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    provider_name: str,
    requested_model: str,
) -> AsyncIterator[ChatCompletionChunk]:
    """Stream Mantle Messages SSE and translate to OpenAI chunks.

    Event vocabulary and translation logic mirror
    :func:`app.providers.anthropic._anthropic_stream_iter`. Not yet
    live-verified (A4) — same checkpoint as :func:`_from_messages_response`.
    """

    response_id = f"chatcmpl-{uuid.uuid4().hex}"
    response_model = requested_model
    created = int(time.time())
    finish_reason: FinishReason | None = None
    prompt_tokens = 0
    completion_tokens = 0
    role_emitted = False

    try:
        async with client.stream("POST", url, json=body, headers=headers) as response:
            if response.status_code >= 400:
                error_body = await response.aread()
                _raise_from_mantle_error_body(
                    status_code=response.status_code,
                    body=error_body,
                    provider=provider_name,
                )

            async for event_type, data in _iter_sse_events(response):
                if not data or data == "[DONE]":
                    continue
                try:
                    parsed = json.loads(data)
                except json.JSONDecodeError:
                    continue

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

                # message_stop / ping / unknown -> ignore.
    except httpx.HTTPError as exc:
        raise ProviderNetworkError(
            f"failed to stream from Bedrock Mantle (Messages): {type(exc).__name__}",
            details={"provider": provider_name},
        ) from exc

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
    """Iterate ``(event, data)`` tuples from an SSE response (Messages
    tier — named events). Identical subset-of-SSE handling to
    :func:`app.providers.anthropic._iter_sse_events`."""

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
            continue
        if line.startswith("event:"):
            event_type = line[len("event:") :].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip(" "))
            continue
    if data_lines:
        yield event_type, "\n".join(data_lines)


# --- F3 translation: gateway -> Responses --------------------------------------


def _to_responses_request(
    request: ChatCompletionRequest,
    *,
    model: str,
    stream: bool,
) -> dict[str, Any]:
    """Build the Mantle Responses request body.

    ``input`` mirrors the gateway's ``messages`` (Responses accepts the
    same role/content shape as Chat Completions for plain-text turns).
    ``tools``/``tool_choice`` are constructed **only** from the
    gateway's own governed ``ChatCompletionRequest.tools``/
    ``tool_choice`` (FR3.7 / EC3.3) — this function must never add,
    default, or pass through any AWS/OpenAI built-in/server-side tool
    type, which is what keeps ADR 0014's single-audited-egress-boundary
    guarantee intact for this tier.
    """

    input_messages: list[dict[str, Any]] = []
    for msg in request.messages:
        entry: dict[str, Any] = {"role": msg.role, "content": msg.content or ""}
        input_messages.append(entry)

    body: dict[str, Any] = {
        "model": model,
        "input": input_messages,
        "stream": stream,
    }
    if request.max_tokens is not None:
        body["max_output_tokens"] = request.max_tokens
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if request.top_p is not None:
        body["top_p"] = request.top_p

    extra = request.model_extra or {}
    raw_tools = request.tools if request.tools is not None else extra.get("tools")
    if raw_tools:
        responses_tools: list[dict[str, Any]] = []
        for t in raw_tools:
            fn = t.get("function", t) if isinstance(t, dict) else {}
            responses_tools.append(
                {
                    "type": "function",
                    "name": fn.get("name", ""),
                    "description": fn.get("description", "") or "",
                    "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                }
            )
        body["tools"] = responses_tools

        raw_choice = (
            request.tool_choice if request.tool_choice is not None else extra.get("tool_choice")
        )
        if raw_choice is not None:
            if isinstance(raw_choice, dict):
                fn_choice = raw_choice.get("function", {})
                if fn_choice.get("name"):
                    body["tool_choice"] = {"type": "function", "name": fn_choice["name"]}
            else:
                body["tool_choice"] = raw_choice
    return body


# --- F3 translation: Responses -> gateway (non-streaming) ---------------------


def _from_responses_response(
    payload: dict[str, Any],
    *,
    requested_model: str,
) -> ChatCompletionResponse:
    """Translate a Mantle Responses response into :class:`ChatCompletionResponse`.

    ``output[]`` is a typed-item list (message / function_call /
    reasoning / ...). Per FR3.4/FR3.5/FR3.6:

    * ``message`` items contribute text content.
    * ``function_call`` items map to the gateway's ``tool_calls`` shape
      (pure wire-format translation only — no governance logic here;
      that lives in the backend's tool-calling loop per ADR 0015).
      ``namespace`` is dropped (no equivalent concept in this gateway's
      tool-provider model).
    * ``reasoning`` items are dropped silently (FR3.6).
    * Any other item type is dropped-and-logged, never silently
      absorbed into ``content`` or ``tool_calls`` (FR3.5).

    Not yet live-verified (A5) — implemented against the OpenAI
    Responses SDK's own schema (``openai.types.responses.Response``).
    """

    output_items = payload.get("output") or []
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    for item in output_items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")

        if item_type in _RESPONSES_MESSAGE_ITEM_TYPES:
            for content_block in item.get("content") or []:
                if isinstance(content_block, dict) and content_block.get("type") in (
                    "output_text",
                    "text",
                ):
                    text_parts.append(str(content_block.get("text", "")))
            continue

        if item_type in _RESPONSES_TOOL_CALL_ITEM_TYPES:
            try:
                # Responses ships arguments as a JSON string already;
                # forward verbatim rather than round-tripping through
                # json.loads/json.dumps.
                arguments = item.get("arguments")
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments or {})
            except (TypeError, ValueError):
                arguments = "{}"
            tool_calls.append(
                {
                    "id": str(item.get("call_id") or item.get("id") or ""),
                    "type": "function",
                    "function": {
                        "name": str(item.get("name", "")),
                        "arguments": arguments,
                    },
                }
            )
            continue

        if item_type in _RESPONSES_DROPPED_ITEM_TYPES:
            continue

        # FR3.5: out-of-scope item type — log and drop, never silently
        # mis-map into content or tool_calls.
        logger.warning(
            "bedrock_mantle: dropping out-of-scope Responses output[] item type %r",
            item_type,
        )

    text = "".join(text_parts)
    finish_reason: FinishReason = "tool_calls" if tool_calls else "stop"

    usage_raw = payload.get("usage") or {}
    usage = ChatCompletionUsage(
        prompt_tokens=int(usage_raw.get("input_tokens", 0)),
        completion_tokens=int(usage_raw.get("output_tokens", 0)),
        total_tokens=int(usage_raw.get("input_tokens", 0)) + int(usage_raw.get("output_tokens", 0)),
    )

    response_id = str(payload.get("id") or f"chatcmpl-{uuid.uuid4().hex}")
    response_model = str(payload.get("model") or requested_model)
    created_raw = payload.get("created_at")
    created = int(created_raw) if isinstance(created_raw, (int, float)) else int(time.time())

    message = ChatCompletionMessage(
        role="assistant",
        content=text or None,
        tool_calls=tool_calls or None,
    )
    return ChatCompletionResponse(
        id=response_id,
        created=created,
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


# --- F3 translation: Responses SSE -> gateway chunks ---------------------------


async def _responses_stream_iter(
    *,
    client: httpx.AsyncClient,
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    provider_name: str,
    requested_model: str,
) -> AsyncIterator[ChatCompletionChunk]:
    """Stream Mantle Responses SSE and translate to OpenAI chunks.

    The Responses event family (``response.output_text.delta``,
    ``response.completed``, etc.) is structurally distinct from Chat
    Completions' ``chat.completion.chunk`` deltas — this is new
    translation code, not a reuse of the OpenAI adapter's SSE iterator.
    Named-event framing (``event: <type>`` / ``data: <json>``) matches
    the Messages tier's SSE subset, so :func:`_iter_sse_events` is
    reused for the low-level line parsing.
    """

    response_id = f"chatcmpl-{uuid.uuid4().hex}"
    response_model = requested_model
    created = int(time.time())
    finish_reason: FinishReason | None = None
    prompt_tokens = 0
    completion_tokens = 0
    role_emitted = False
    saw_tool_call = False

    try:
        async with client.stream("POST", url, json=body, headers=headers) as response:
            if response.status_code >= 400:
                error_body = await response.aread()
                _raise_from_mantle_error_body(
                    status_code=response.status_code,
                    body=error_body,
                    provider=provider_name,
                )

            async for event_type, data in _iter_sse_events(response):
                if not data or data == "[DONE]":
                    continue
                try:
                    parsed = json.loads(data)
                except json.JSONDecodeError:
                    continue

                kind = parsed.get("type") or event_type

                if kind == "response.created":
                    resp = parsed.get("response") or {}
                    response_id = str(resp.get("id") or response_id)
                    response_model = str(resp.get("model") or response_model)
                    if not role_emitted:
                        role_emitted = True
                        yield _make_chunk(
                            response_id=response_id,
                            created=created,
                            model=response_model,
                            delta=ChatCompletionDelta(role="assistant"),
                        )
                    continue

                if kind == "response.output_text.delta":
                    text = str(parsed.get("delta", ""))
                    if text:
                        yield _make_chunk(
                            response_id=response_id,
                            created=created,
                            model=response_model,
                            delta=ChatCompletionDelta(content=text),
                        )
                    continue

                if kind == "response.output_item.added":
                    item = parsed.get("item") or {}
                    if isinstance(item, dict) and item.get("type") == "function_call":
                        saw_tool_call = True
                    continue

                if kind == "response.completed":
                    resp = parsed.get("response") or {}
                    usage = resp.get("usage") or {}
                    if "input_tokens" in usage:
                        prompt_tokens = int(usage["input_tokens"])
                    if "output_tokens" in usage:
                        completion_tokens = int(usage["output_tokens"])
                    finish_reason = "tool_calls" if saw_tool_call else "stop"
                    continue

                # response.in_progress / reasoning deltas / unknown -> ignore.
    except httpx.HTTPError as exc:
        raise ProviderNetworkError(
            f"failed to stream from Bedrock Mantle (Responses): {type(exc).__name__}",
            details={"provider": provider_name},
        ) from exc

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


# --- Error mapping (shared across Messages + Responses tiers) -----------------


def _raise_for_mantle_status(response: httpx.Response, *, provider: str) -> None:
    """Translate an upstream non-success status to a structured adapter error."""

    if response.status_code < 400:
        return
    body = response.content
    _raise_from_mantle_error_body(status_code=response.status_code, body=body, provider=provider)


def _raise_from_mantle_error_body(
    *,
    status_code: int,
    body: bytes,
    provider: str,
) -> None:
    """Parse a Mantle error body (Anthropic- or OpenAI-native envelope) and
    raise the right adapter error.

    Covers three confirmed-live error classes (module docstring), none
    of which map to ``ProviderAuthError``/``unauthorized``:

    1. 403, Anthropic-native ``permission_error`` (Messages) — entitlement.
    2. 401, OpenAI-native ``permission_denied_error`` (Responses) — entitlement,
       despite the auth-shaped status code.
    3. 400, OpenAI-native ``validation_error``/``invalid_request_error``,
       message matching "does not support the '...' API" (Responses) —
       wrong API path for this model, distinguished from (1)/(2) via
       ``details["mantle_error_class"]``.

    All three surface as :class:`ProviderHTTPError` (``code=
    "provider_unavailable"`` at the base-class level; the route handler
    maps upstream 4xx to ``invalid_model`` using ``upstream_status`` +
    ``details``) rather than :class:`ProviderAuthError`, so operators
    aren't misled into rotating a working credential for what is
    actually an entitlement or model-routing issue.
    """

    upstream_type: str | None = None
    upstream_code: str | None = None
    upstream_message: str | None = None
    try:
        parsed = json.loads(body or b"{}")
    except json.JSONDecodeError:
        parsed = {}

    if isinstance(parsed, dict):
        # Anthropic-native envelope: {"type": "error", "error": {"type": ..., "message": ...}}
        # OpenAI-native envelope:    {"error": {"type": ..., "code": ..., "message": ...}}
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

    details: dict[str, object] = {"provider": provider, "upstream_status": status_code}
    if upstream_type:
        details["upstream_error_type"] = upstream_type
    if upstream_code:
        details["upstream_error_code"] = upstream_code

    mantle_error_class = _classify_mantle_error(
        status_code=status_code,
        upstream_type=upstream_type,
        upstream_code=upstream_code,
        upstream_message=upstream_message,
    )
    if mantle_error_class:
        details["mantle_error_class"] = mantle_error_class

    safe_message = upstream_message or f"Bedrock Mantle returned HTTP {status_code}"

    raise ProviderHTTPError(
        safe_message,
        upstream_status=status_code,
        details=details,
    )


def _classify_mantle_error(
    *,
    status_code: int,
    upstream_type: str | None,
    upstream_code: str | None,
    upstream_message: str | None,
) -> str | None:
    """Distinguish the three known Mantle error classes for
    ``details["mantle_error_class"]``, so operators (and error-mapping
    tests) can tell "not entitled" apart from "wrong model for this
    endpoint" instead of both collapsing into an opaque 4xx."""

    if status_code == 403 and upstream_type == "permission_error":
        return "entitlement_denied"
    if status_code == 401 and upstream_type == "permission_denied_error":
        return "entitlement_denied"
    if (
        status_code == 400
        and upstream_code == "validation_error"
        and upstream_type == "invalid_request_error"
        and upstream_message
        and "does not support the" in upstream_message
        and "API" in upstream_message
    ):
        return "unsupported_api_for_model"
    return None
