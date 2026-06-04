"""HTTP client for the LQ.AI Inference Gateway.

A4 landed the skeleton with ``health_check()`` only; B5 fleshes out the
full chat-completion surface. The client owns a long-lived
``httpx.AsyncClient`` pooled across calls (per CLAUDE.md "reuse the same
client across calls"; do not construct a fresh client per request).

Per ADR 0002 / ``.env.example``: every backend → gateway request includes
``X-LQ-AI-Gateway-Key``, the shared secret. The gateway rejects requests
that lack it. The default-headers approach below stamps the key on every
call.

Error translation
-----------------

Gateway errors (parsed from the ``GatewayError`` envelope) and transport
errors (timeout, network failure, malformed body) are translated to the
backend's ``LQAIError`` hierarchy (per :doc:`docs/adr/0003-error-handling.md`):

* Timeout → :class:`app.errors.GatewayTimeout` (HTTP 504).
* Network / DNS / TLS failure → :class:`app.errors.GatewayUnreachable`
  (HTTP 503).
* Gateway 5xx → :class:`app.errors.GatewayUnreachable` (HTTP 503; the
  operator sees "service unavailable" rather than the underlying detail
  per the brief).
* Gateway 401 (bad gateway key) → logged loudly and re-raised as
  :class:`app.errors.GatewayUnreachable` (the user must not see "the
  operator misconfigured the gateway key" — they see "service unavailable").
* Gateway 4xx with a parseable body → mapped via
  :func:`app.errors.map_gateway_error_code` to the right backend
  exception class (``provider_unavailable``, ``invalid_model``, etc.).
* Body that fails to parse → :class:`app.errors.GatewayInvalidResponse`
  (HTTP 502) — indicates contract drift.

Streaming
---------

``chat_completion_stream`` returns an :class:`AsyncIterator` of
:class:`ChatCompletionChunk` objects. The gateway emits OpenAI-format SSE
frames (``data: <json>\\n\\n``) terminated by ``data: [DONE]\\n\\n``;
the iterator parses each frame, decodes the JSON envelope, and yields
the parsed chunk. Mid-stream gateway errors come through as a final
SSE frame with ``{"error": {...}}`` — the iterator translates that to
the appropriate :class:`LQAIError` subclass and raises (so the caller
sees one stream and then an exception, not a mixed signal).

Embeddings
----------

The gateway's ``/v1/embeddings`` endpoint is 501 until B6 (OpenAI adapter
ships embeddings). The :meth:`GatewayClient.embeddings` method exists so
its callers (the future KB / RAG path) compile against a stable
signature; today it propagates the gateway's 501 directly.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import ValidationError as PydanticValidationError

from app.config import get_settings
from app.errors import (
    GatewayInvalidResponse,
    GatewayTimeout,
    GatewayUnreachable,
    InternalError,
    LQAIError,
    map_gateway_error_code,
)
from app.schemas.gateway import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    GatewayErrorEnvelope,
)

log = logging.getLogger(__name__)

GATEWAY_KEY_HEADER = "X-LQ-AI-Gateway-Key"
"""Shared-secret header sent on every backend → gateway call."""

REQUEST_ID_HEADER = "X-Request-Id"
"""Optional request-id forwarded so the gateway's audit row can correlate."""

TIER_RESPONSE_HEADER = "X-LQ-AI-Routed-Inference-Tier"
"""Response header set by the gateway (B4) carrying the routed Inference Tier."""

DEFAULT_TIMEOUT_SECONDS = 60.0
"""Default per-request timeout. Streaming overrides this (the stream is
expected to take longer than a single API call). Health check overrides
to a tight value separately."""


def _structured_log_extra(**fields: Any) -> dict[str, Any]:
    """Build a structured ``extra=`` dict for :func:`logging.Logger.log`.

    Centralized so all gateway-client logs surface the same field names
    (operator-grep-friendly).
    """

    return {"event": "gateway_client", **fields}


@dataclass(frozen=True, slots=True)
class EnsembleConfig:
    """Resolved Stage 4 ensemble config pulled from the gateway (M2-D1).

    Returned by :meth:`GatewayClient.get_citation_engine_ensemble_config`.
    Immutable; the gateway treats its YAML config as fixed for the
    process lifetime so the api/-side cache stays valid until restart.

    :attr:`envelope_tier` is server-computed by the gateway as the
    max ``routed_inference_tier`` across all aliases in
    :attr:`judge_models` (using each alias's primary target). The
    api/ persists this value on ``message_citations.tier_envelope``
    for ensemble-verified rows. ``None`` when the gateway couldn't
    resolve any judge alias to a tier.
    """

    default_enabled: bool
    judge_models: tuple[str, ...]
    aggregation_rule: Literal["strict", "majority"]
    max_cost_per_message_usd: float
    envelope_tier: int | None


class GatewayClient:
    """Async HTTP client wrapping calls to the Inference Gateway.

    Construct once at app startup (the lifespan in :mod:`app.main` does
    this implicitly via :func:`get_gateway_client`); the underlying
    ``httpx.AsyncClient`` is reused across all calls. Closing happens at
    shutdown via :func:`close_gateway_client`.
    """

    def __init__(
        self,
        base_url: str,
        gateway_key: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._gateway_key = gateway_key
        self._timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            headers={GATEWAY_KEY_HEADER: self._gateway_key} if self._gateway_key else {},
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Expose the underlying httpx client for advanced use (tests, streaming)."""

        return self._client

    # --- Citation engine config (M2-C1) -------------------------------------

    _citation_engine_judge_model: str | None = None
    """Process-cached judge model alias.

    Populated on first :meth:`get_citation_engine_judge_model` call.
    The gateway treats this config as immutable after startup
    (``gateway.yaml`` is loaded once on lifespan); the api/ caches
    the value for the same lifespan so we don't pay the round-trip
    on every Stage 3 invocation. A gateway restart-then-api restart
    is the deployment story for changing the alias.
    """

    async def get_citation_engine_judge_model(
        self,
        *,
        fallback: str = "fast",
    ) -> str:
        """Fetch the configured judge model alias from the gateway.

        Calls ``GET /v1/citation-engine/config`` once per process and
        caches the result. On any failure (network, non-200, malformed
        body) returns ``fallback`` — a missing config endpoint must not
        crash the Citation Engine; Stage 3 silently degrades to the
        default model.

        Returns:
            The configured ``judge_model`` (an alias the gateway can
            resolve), or ``fallback`` when the lookup failed.
        """

        if self._citation_engine_judge_model is not None:
            return self._citation_engine_judge_model

        try:
            response = await self._client.get(
                "/v1/citation-engine/config",
                timeout=5.0,
            )
        except Exception as exc:
            # Catch broadly: the judge-model lookup is best-effort
            # (the Stage 3 cascade still works with the fallback model).
            # We don't want a transient gateway problem — or a respx
            # test scenario that doesn't mock this endpoint — to crash
            # the chat-send pipeline. Production callers see network,
            # DNS, TLS, asyncio cancellation, etc. all in this slot.
            log.warning(
                "citation-engine config fetch failed: %s",
                exc,
                extra=_structured_log_extra(
                    op="get_citation_engine_judge_model",
                    error_type=type(exc).__name__,
                ),
            )
            return fallback

        if response.status_code != 200:
            log.warning(
                "citation-engine config endpoint returned %s",
                response.status_code,
                extra=_structured_log_extra(
                    op="get_citation_engine_judge_model",
                    status_code=response.status_code,
                ),
            )
            return fallback

        try:
            payload = response.json()
            judge_model = str(payload["judge_model"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            log.warning(
                "citation-engine config response malformed: %s",
                exc,
                extra=_structured_log_extra(
                    op="get_citation_engine_judge_model",
                    error_type=type(exc).__name__,
                ),
            )
            return fallback

        if not judge_model:
            return fallback

        self._citation_engine_judge_model = judge_model
        return judge_model

    _citation_engine_ensemble: EnsembleConfig | None = None
    """Process-cached ensemble config; same lifecycle as the judge_model cache."""

    _citation_engine_ensemble_loaded: bool = False
    """Whether the cache attempt has been made.

    Distinguishes "haven't fetched yet" from "fetched and got nothing
    back" — the second case caches a sentinel so a misconfigured
    gateway doesn't get re-polled on every Stage 4 evaluation.
    """

    async def get_citation_engine_ensemble_config(self) -> EnsembleConfig | None:
        """Fetch the configured ensemble verification config (M2-D1).

        Calls ``GET /v1/citation-engine/config`` once per process and
        caches the result. Returns ``None`` when the gateway has no
        ensemble configured (empty ``judge_models``), when the endpoint
        is unreachable, or when the response is missing the
        ``ensemble_verification`` block (older gateway). Callers treat
        ``None`` as "Stage 4 cannot run" — the cascade falls back to
        Stage 3 in that case.

        On failure, caches a ``None`` sentinel so the next call doesn't
        re-poll — the gateway config is immutable per-process and a
        misconfiguration is sticky.
        """

        if self._citation_engine_ensemble_loaded:
            return self._citation_engine_ensemble

        try:
            response = await self._client.get(
                "/v1/citation-engine/config",
                timeout=5.0,
            )
        except Exception as exc:
            log.warning(
                "citation-engine ensemble config fetch failed: %s",
                exc,
                extra=_structured_log_extra(
                    op="get_citation_engine_ensemble_config",
                    error_type=type(exc).__name__,
                ),
            )
            self._citation_engine_ensemble_loaded = True
            return None

        if response.status_code != 200:
            self._citation_engine_ensemble_loaded = True
            return None

        try:
            payload = response.json()
        except json.JSONDecodeError:
            self._citation_engine_ensemble_loaded = True
            return None

        ensemble_block = payload.get("ensemble_verification") if isinstance(payload, dict) else None
        if not isinstance(ensemble_block, dict):
            # Older gateway predates M2-D1; treat as "no ensemble".
            self._citation_engine_ensemble_loaded = True
            return None

        judge_models = ensemble_block.get("judge_models") or []
        if not isinstance(judge_models, list) or not judge_models:
            self._citation_engine_ensemble_loaded = True
            return None

        aggregation_rule = ensemble_block.get("aggregation_rule", "strict")
        if aggregation_rule not in ("strict", "majority"):
            log.warning(
                "citation-engine ensemble config has unknown aggregation_rule %r",
                aggregation_rule,
                extra=_structured_log_extra(
                    op="get_citation_engine_ensemble_config",
                    aggregation_rule=aggregation_rule,
                ),
            )
            self._citation_engine_ensemble_loaded = True
            return None

        envelope_tier_raw = ensemble_block.get("envelope_tier")
        envelope_tier: int | None
        if envelope_tier_raw is None:
            envelope_tier = None
        else:
            try:
                envelope_tier = int(envelope_tier_raw)
            except (TypeError, ValueError):
                envelope_tier = None

        try:
            max_cost = float(ensemble_block.get("max_cost_per_message_usd", 0.05))
        except (TypeError, ValueError):
            max_cost = 0.05

        self._citation_engine_ensemble = EnsembleConfig(
            default_enabled=bool(ensemble_block.get("default_enabled", False)),
            judge_models=tuple(str(m) for m in judge_models),
            aggregation_rule=aggregation_rule,
            max_cost_per_message_usd=max_cost,
            envelope_tier=envelope_tier,
        )
        self._citation_engine_ensemble_loaded = True
        return self._citation_engine_ensemble

    def _reset_citation_engine_cache_for_tests(self) -> None:
        """Drop both caches. Tests use this to test re-fetch."""

        self._citation_engine_judge_model = None
        self._citation_engine_ensemble = None
        self._citation_engine_ensemble_loaded = False

    # --- Health probe --------------------------------------------------------

    async def health_check(self) -> bool:
        """GET /health on the gateway; True iff the gateway returns 200.

        Used by the backend's /ready endpoint. Times out fast — the gateway
        being slow to respond is itself a not-ready signal. Readiness probes
        never raise.
        """

        try:
            response = await self._client.get("/health", timeout=5.0)
            return response.status_code == 200
        except Exception as exc:
            log.warning("Gateway health check failed: %s", exc)
            return False

    # --- Chat completion (non-streaming) ------------------------------------

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        *,
        request_id: str | None = None,
    ) -> ChatCompletionResponse:
        """POST a non-streaming chat-completion to the gateway.

        ``request.stream`` is forced to ``False`` here regardless of input
        because this method only handles the non-streaming path. Use
        :meth:`chat_completion_stream` for streaming.

        Raises one of the :class:`LQAIError` subclasses on any failure;
        the caller catches the typed error rather than the underlying
        transport exception.
        """

        # Defensive: ensure stream flag matches the path we're taking.
        if request.stream:
            request = request.model_copy(update={"stream": False})

        body = request.model_dump(mode="json", exclude_none=True)
        headers = self._build_headers(request_id=request_id)

        try:
            response = await self._client.post(
                "/v1/chat/completions",
                json=body,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            log.warning(
                "Gateway request timed out",
                extra=_structured_log_extra(
                    op="chat_completion",
                    timeout=self._timeout,
                    request_id=request_id,
                ),
            )
            raise GatewayTimeout(
                "Gateway did not respond within the configured timeout",
                details={"timeout_seconds": self._timeout},
            ) from exc
        except httpx.HTTPError as exc:
            log.warning(
                "Gateway transport failure: %s",
                exc,
                extra=_structured_log_extra(
                    op="chat_completion",
                    request_id=request_id,
                    error_type=type(exc).__name__,
                ),
            )
            raise GatewayUnreachable(
                "Could not reach the Inference Gateway",
                details={"transport_error": type(exc).__name__},
            ) from exc

        if response.status_code >= 400:
            self._raise_for_gateway_error(
                status_code=response.status_code,
                body_bytes=response.content,
                op="chat_completion",
                request_id=request_id,
            )

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise GatewayInvalidResponse(
                "Gateway returned a non-JSON success response",
                details={"status_code": response.status_code},
            ) from exc

        try:
            parsed = ChatCompletionResponse.model_validate(payload)
        except PydanticValidationError as exc:
            raise GatewayInvalidResponse(
                "Gateway response failed schema validation",
                details={"validation_errors": exc.errors()},
            ) from exc

        # If the body lacks the tier annotation but the header carries it,
        # backfill from the header so the caller doesn't have to know about
        # both surfaces. (Per B4 the body always carries it; this is a
        # forward-compat belt-and-suspenders.)
        if parsed.routed_inference_tier is None:
            header_tier = response.headers.get(TIER_RESPONSE_HEADER)
            if header_tier is not None:
                with contextlib.suppress(ValueError):
                    parsed.routed_inference_tier = int(header_tier)

        return parsed

    # --- Chat completion (streaming) -----------------------------------------

    async def chat_completion_stream(
        self,
        request: ChatCompletionRequest,
        *,
        request_id: str | None = None,
    ) -> AsyncIterator[ChatCompletionChunk]:
        """POST a streaming chat-completion; yield chunks as they arrive.

        Yields :class:`ChatCompletionChunk` envelopes parsed from each
        OpenAI-format SSE frame. Stream termination signals:

        * ``data: [DONE]`` → iterator ends normally.
        * Mid-stream ``{"error": ...}`` SSE frame → iterator raises the
          mapped :class:`LQAIError` subclass.
        * Transport failure → iterator raises
          :class:`GatewayUnreachable` / :class:`GatewayTimeout`.

        The caller iterates with ``async for`` and catches
        :class:`LQAIError` to translate the failure to an HTTP response.
        """

        if not request.stream:
            request = request.model_copy(update={"stream": True})

        body = request.model_dump(mode="json", exclude_none=True)
        headers = self._build_headers(request_id=request_id)

        # Streaming uses ``client.stream`` so we don't buffer the whole
        # body. Timeouts are handled per-line by httpx; the overall
        # connect timeout is the same as non-streaming.
        try:
            async with self._client.stream(
                "POST",
                "/v1/chat/completions",
                json=body,
                headers=headers,
            ) as response:
                if response.status_code >= 400:
                    # Read the body so we can map the structured error.
                    raw = await response.aread()
                    self._raise_for_gateway_error(
                        status_code=response.status_code,
                        body_bytes=raw,
                        op="chat_completion_stream",
                        request_id=request_id,
                    )

                async for chunk in self._iter_sse_chunks(response):
                    yield chunk
        except httpx.TimeoutException as exc:
            log.warning(
                "Gateway streaming timed out",
                extra=_structured_log_extra(
                    op="chat_completion_stream",
                    request_id=request_id,
                ),
            )
            raise GatewayTimeout(
                "Gateway streaming did not respond within the configured timeout",
                details={"timeout_seconds": self._timeout},
            ) from exc
        except httpx.HTTPError as exc:
            # If we're already raising an LQAIError (from
            # _raise_for_gateway_error), don't wrap it twice.
            if isinstance(exc, LQAIError):
                raise
            log.warning(
                "Gateway streaming transport failure: %s",
                exc,
                extra=_structured_log_extra(
                    op="chat_completion_stream",
                    request_id=request_id,
                    error_type=type(exc).__name__,
                ),
            )
            raise GatewayUnreachable(
                "Could not reach the Inference Gateway for streaming",
                details={"transport_error": type(exc).__name__},
            ) from exc

    # --- Embeddings ----------------------------------------------------------

    async def embeddings(
        self,
        *,
        model: str,
        input_: str | list[str],
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """POST to the gateway's ``/v1/embeddings``.

        Today the gateway returns 501 (B6 lands the OpenAI adapter that
        ships the embeddings path). This method exists so callers (the
        KB / RAG layer) compile against a stable signature; the 501 is
        translated to :class:`InternalError` so the wire shape matches
        the rest of the typed-error path. When B6 lands the embeddings
        body, this method gains a real Pydantic response model and stops
        returning a dict.
        """

        body: dict[str, Any] = {"model": model, "input": input_}
        headers = self._build_headers(request_id=request_id)

        try:
            response = await self._client.post("/v1/embeddings", json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise GatewayTimeout(
                "Gateway embeddings did not respond within the configured timeout",
                details={"timeout_seconds": self._timeout},
            ) from exc
        except httpx.HTTPError as exc:
            raise GatewayUnreachable(
                "Could not reach the Inference Gateway",
                details={"transport_error": type(exc).__name__},
            ) from exc

        if response.status_code >= 400:
            self._raise_for_gateway_error(
                status_code=response.status_code,
                body_bytes=response.content,
                op="embeddings",
                request_id=request_id,
            )

        try:
            payload: dict[str, Any] = response.json()
            return payload
        except json.JSONDecodeError as exc:
            raise GatewayInvalidResponse(
                "Gateway embeddings returned a non-JSON success response",
                details={"status_code": response.status_code},
            ) from exc

    # --- Model list (D0) -----------------------------------------------------

    async def list_models(
        self,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """GET /v1/models on the gateway.

        Returns the merged ``{object: "list", data: [...]}`` payload
        per ``docs/api/gateway-openapi.yaml`` (D0). The response shape
        is forwarded verbatim so the backend's ``/api/v1/models`` proxy
        can hand it to clients without translation.

        Errors translate the same way as ``chat_completion``: timeout
        → :class:`GatewayTimeout`, transport failure →
        :class:`GatewayUnreachable`, gateway 401 → logged warning +
        :class:`GatewayUnreachable`, structured 4xx → mapped via
        :func:`map_gateway_error_code`. Per the brief: a 401 from the
        gateway must NOT leak the underlying "wrong gateway key"
        signal to the user.
        """

        headers = self._build_headers(request_id=request_id)
        try:
            response = await self._client.get("/v1/models", headers=headers)
        except httpx.TimeoutException as exc:
            log.warning(
                "Gateway list_models timed out",
                extra=_structured_log_extra(
                    op="list_models",
                    timeout=self._timeout,
                    request_id=request_id,
                ),
            )
            raise GatewayTimeout(
                "Gateway did not respond within the configured timeout",
                details={"timeout_seconds": self._timeout},
            ) from exc
        except httpx.HTTPError as exc:
            log.warning(
                "Gateway list_models transport failure: %s",
                exc,
                extra=_structured_log_extra(
                    op="list_models",
                    request_id=request_id,
                    error_type=type(exc).__name__,
                ),
            )
            raise GatewayUnreachable(
                "Could not reach the Inference Gateway",
                details={"transport_error": type(exc).__name__},
            ) from exc

        if response.status_code >= 400:
            self._raise_for_gateway_error(
                status_code=response.status_code,
                body_bytes=response.content,
                op="list_models",
                request_id=request_id,
            )

        try:
            payload: dict[str, Any] = response.json()
            return payload
        except json.JSONDecodeError as exc:
            raise GatewayInvalidResponse(
                "Gateway list_models returned a non-JSON success response",
                details={"status_code": response.status_code},
            ) from exc

    # --- Admin: alias CRUD (D0.5) -------------------------------------------

    async def list_aliases(
        self,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """GET /admin/v1/aliases. Returns the gateway's full alias list."""

        return await self._admin_request(
            method="GET",
            path="/admin/v1/aliases",
            op="list_aliases",
            request_id=request_id,
        )

    async def get_alias(
        self,
        name: str,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """GET /admin/v1/aliases/{name}. 404 surfaces as :class:`NotFound`."""

        return await self._admin_request(
            method="GET",
            path=f"/admin/v1/aliases/{name}",
            op="get_alias",
            request_id=request_id,
        )

    async def create_alias(
        self,
        body: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """POST /admin/v1/aliases. 409 surfaces as :class:`Conflict`."""

        return await self._admin_request(
            method="POST",
            path="/admin/v1/aliases",
            op="create_alias",
            request_id=request_id,
            body=body,
        )

    async def update_alias(
        self,
        name: str,
        body: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """PATCH /admin/v1/aliases/{name}. 404 surfaces as :class:`NotFound`."""

        return await self._admin_request(
            method="PATCH",
            path=f"/admin/v1/aliases/{name}",
            op="update_alias",
            request_id=request_id,
            body=body,
        )

    async def delete_alias(
        self,
        name: str,
        *,
        request_id: str | None = None,
    ) -> None:
        """DELETE /admin/v1/aliases/{name}. 404 surfaces as :class:`NotFound`."""

        await self._admin_request(
            method="DELETE",
            path=f"/admin/v1/aliases/{name}",
            op="delete_alias",
            request_id=request_id,
            allow_204=True,
        )

    # --- Admin: provider-key CRUD (Donna #7) --------------------------------

    async def list_provider_keys(
        self,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """GET /admin/v1/provider-keys. Returns the secret-safe status list.

        The response is ``{"provider_keys": [...]}`` where each row is
        ``{provider, type, configured, last4, source}`` — never a full key.
        """

        return await self._admin_request(
            method="GET",
            path="/admin/v1/provider-keys",
            op="list_provider_keys",
            request_id=request_id,
        )

    async def set_provider_key(
        self,
        body: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """POST /admin/v1/provider-keys. Set/replace a runtime key and hot-apply.

        400 (``failed_precondition``) surfaces when the gateway master key
        is unset; 404 (``not_found``) when the provider isn't configured.
        Returns the provider's secret-safe status dict.
        """

        return await self._admin_request(
            method="POST",
            path="/admin/v1/provider-keys",
            op="set_provider_key",
            request_id=request_id,
            body=body,
        )

    async def rotate_provider_key(
        self,
        provider: str,
        body: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """PATCH /admin/v1/provider-keys/{provider}. Rotate a configured key.

        Same mechanics as :meth:`set_provider_key`; the provider comes from
        the path. 400 master-key-missing / 404 unknown-provider surface as
        on the set path.
        """

        return await self._admin_request(
            method="PATCH",
            path=f"/admin/v1/provider-keys/{provider}",
            op="rotate_provider_key",
            request_id=request_id,
            body=body,
        )

    async def delete_provider_key(
        self,
        provider: str,
        *,
        request_id: str | None = None,
    ) -> None:
        """DELETE /admin/v1/provider-keys/{provider}. Revoke a runtime key.

        404 (``not_found``) surfaces for an unknown provider; 409
        (``conflict``) when the provider has no runtime key to revoke (e.g.
        an env-sourced key). 204 on success.
        """

        await self._admin_request(
            method="DELETE",
            path=f"/admin/v1/provider-keys/{provider}",
            op="delete_provider_key",
            request_id=request_id,
            allow_204=True,
        )

    async def get_admin_config(
        self,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """GET /admin/v1/config — sanitized current config payload."""

        return await self._admin_request(
            method="GET",
            path="/admin/v1/config",
            op="get_admin_config",
            request_id=request_id,
        )

    async def get_tier_config(
        self,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """GET /admin/v1/tier-config — operator tier policy (Wave B)."""

        return await self._admin_request(
            method="GET",
            path="/admin/v1/tier-config",
            op="get_tier_config",
            request_id=request_id,
        )

    async def patch_tier_config(
        self,
        *,
        body: dict[str, Any],
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """PATCH /admin/v1/tier-config — partial-update tier_policy (Wave B)."""

        return await self._admin_request(
            method="PATCH",
            path="/admin/v1/tier-config",
            op="patch_tier_config",
            request_id=request_id,
            body=body,
        )

    async def _admin_request(
        self,
        *,
        method: str,
        path: str,
        op: str,
        request_id: str | None,
        body: dict[str, Any] | None = None,
        allow_204: bool = False,
    ) -> dict[str, Any]:
        """Shared admin-request transport. Returns parsed JSON or {}.

        Translates errors via the same path :meth:`chat_completion`
        uses (timeout → :class:`GatewayTimeout`, transport → :class:`GatewayUnreachable`,
        structured 4xx → mapped via :func:`map_gateway_error_code`).
        """

        headers = self._build_headers(request_id=request_id)
        try:
            if body is not None:
                response = await self._client.request(
                    method,
                    path,
                    json=body,
                    headers=headers,
                )
            else:
                response = await self._client.request(method, path, headers=headers)
        except httpx.TimeoutException as exc:
            raise GatewayTimeout(
                "Gateway did not respond within the configured timeout",
                details={"timeout_seconds": self._timeout},
            ) from exc
        except httpx.HTTPError as exc:
            raise GatewayUnreachable(
                "Could not reach the Inference Gateway",
                details={"transport_error": type(exc).__name__},
            ) from exc

        if response.status_code >= 400:
            self._raise_for_gateway_error(
                status_code=response.status_code,
                body_bytes=response.content,
                op=op,
                request_id=request_id,
            )

        if response.status_code == 204 or (allow_204 and not response.content):
            return {}

        try:
            payload: dict[str, Any] = response.json()
            return payload
        except json.JSONDecodeError as exc:
            raise GatewayInvalidResponse(
                f"Gateway {op} returned a non-JSON success response",
                details={"status_code": response.status_code},
            ) from exc

    # --- Lifecycle -----------------------------------------------------------

    async def aclose(self) -> None:
        """Close the underlying httpx client. Idempotent."""

        await self._client.aclose()

    # --- Internals -----------------------------------------------------------

    def _build_headers(self, *, request_id: str | None) -> dict[str, str]:
        """Build per-request headers; X-Request-Id is forwarded when set."""

        headers: dict[str, str] = {}
        if request_id is not None:
            headers[REQUEST_ID_HEADER] = request_id
        return headers

    def _raise_for_gateway_error(
        self,
        *,
        status_code: int,
        body_bytes: bytes,
        op: str,
        request_id: str | None,
    ) -> None:
        """Parse a non-2xx gateway response and raise the right LQAIError.

        ``status_code == 401`` is special-cased per the brief: the user
        must not see "the operator misconfigured the gateway key", they
        see "service unavailable". The operator sees a WARNING log with
        enough context to find the misconfiguration.

        ``status_code >= 500`` is mapped to :class:`GatewayUnreachable`
        rather than ``ProviderUnavailable`` (the wrapping is "we couldn't
        reach the gateway service", not "the gateway said the upstream
        provider was down" — the latter comes through as a 502 with
        ``error.code == "provider_unavailable"`` which we DO map onward).
        """

        # 401 from the gateway = backend's own auth header was rejected.
        # This is a deployment misconfiguration; the user must not see it.
        if status_code == 401:
            log.warning(
                "Gateway rejected the backend's gateway-key header (401). "
                "Check that LQ_AI_GATEWAY_KEY matches between api/ and "
                "gateway/ deployments.",
                extra=_structured_log_extra(
                    op=op,
                    request_id=request_id,
                    status_code=status_code,
                ),
            )
            raise GatewayUnreachable(
                "Inference Gateway is unavailable",
                details={"reason": "operator-configuration"},
            )

        # 5xx from the gateway itself (not from a wrapped provider call —
        # that would be a structured 502 with provider_unavailable).
        # Treat as gateway service unavailable.
        if status_code >= 500 and not _looks_like_structured_body(body_bytes):
            log.warning(
                "Gateway returned 5xx without a parseable structured body",
                extra=_structured_log_extra(
                    op=op,
                    request_id=request_id,
                    status_code=status_code,
                ),
            )
            raise GatewayUnreachable(
                "Inference Gateway returned an unexpected server error",
                details={"status_code": status_code},
            )

        # Try to parse the structured GatewayError envelope.
        try:
            envelope = GatewayErrorEnvelope.model_validate_json(body_bytes)
        except PydanticValidationError as exc:
            log.warning(
                "Gateway returned non-conforming error body",
                extra=_structured_log_extra(
                    op=op,
                    request_id=request_id,
                    status_code=status_code,
                    validation_errors=str(exc),
                ),
            )
            raise GatewayInvalidResponse(
                "Gateway returned an error response that did not match the schema",
                details={"status_code": status_code},
            ) from exc

        payload = envelope.error
        # Map the gateway code to the backend exception class. Unknown
        # codes fall back to InternalError per app.errors.map_gateway_error_code.
        exception_cls = map_gateway_error_code(payload.code)

        # If the exception class is InternalError because the code was
        # unknown, log so operators see drift quickly.
        if exception_cls is InternalError and payload.code not in {
            "anonymization_failed",
            "not_implemented",
        }:
            log.warning(
                "Gateway returned an unknown error code; mapping to InternalError",
                extra=_structured_log_extra(
                    op=op,
                    request_id=request_id,
                    gateway_code=payload.code,
                    status_code=status_code,
                ),
            )

        raise exception_cls(
            payload.message,
            details={**payload.details, "gateway_code": payload.code},
        )

    @staticmethod
    async def _iter_sse_chunks(
        response: httpx.Response,
    ) -> AsyncIterator[ChatCompletionChunk]:
        """Parse OpenAI-format SSE frames into typed chunks.

        The gateway emits ``data: <json>\\n\\n`` frames terminated by
        ``data: [DONE]\\n\\n``. Mid-stream errors come through as a
        regular ``data:`` frame whose JSON has ``{"error": {...}}``;
        the parser detects this, raises the mapped LQAIError subclass,
        and ends the stream.
        """

        buffer = ""
        async for raw_line in response.aiter_lines():
            line = raw_line.rstrip("\r")
            # Blank line = frame separator. We use a buffer rather than
            # one-line-per-frame because the SSE spec allows multi-line
            # data fields (``data: foo\ndata: bar`` joined). The gateway
            # only emits single-line frames today; the buffer is forward-
            # compatible.
            if line == "":
                if buffer:
                    chunk = _parse_sse_data(buffer)
                    buffer = ""
                    if chunk is not None:
                        yield chunk
                continue
            if line.startswith("data:"):
                payload = line[len("data:") :].lstrip()
                if payload == "[DONE]":
                    return
                # Append to the buffer; flush on the next blank line.
                # In practice the gateway emits exactly one data: per
                # frame followed by a blank line.
                if buffer:
                    buffer += "\n" + payload
                else:
                    buffer = payload
            # Other SSE field lines (event:, id:, retry:) are ignored —
            # the gateway never emits them.
        # Stream ended without a [DONE] terminator. Flush any remaining
        # buffer so the last chunk is delivered.
        if buffer:
            chunk = _parse_sse_data(buffer)
            if chunk is not None:
                yield chunk


def _parse_sse_data(payload: str) -> ChatCompletionChunk | None:
    """Parse one SSE ``data:`` payload into a chunk; raise on error frames.

    The gateway emits two payload shapes:

    * Normal ``ChatCompletionChunk`` — parsed as a typed object.
    * Error frame ``{"error": {"code": ..., "message": ..., ...}}`` —
      mapped to an :class:`LQAIError` subclass and raised.

    Anything else (malformed JSON, unrecognized shape) is treated as a
    drift between subsystems and raises :class:`GatewayInvalidResponse`.
    Returns ``None`` only for whitespace-only payloads (which we skip
    silently — defensive against gateway side stripping).
    """

    if not payload.strip():
        return None

    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise GatewayInvalidResponse(
            "Gateway emitted an SSE frame that wasn't valid JSON",
            details={"payload_preview": payload[:120]},
        ) from exc

    if isinstance(decoded, dict) and "error" in decoded:
        # Mid-stream error envelope. Map to the right typed exception.
        try:
            envelope = GatewayErrorEnvelope.model_validate(decoded)
        except PydanticValidationError as exc:
            raise GatewayInvalidResponse(
                "Gateway emitted an error frame that did not match the schema",
                details={"payload_preview": payload[:120]},
            ) from exc
        exception_cls = map_gateway_error_code(envelope.error.code)
        raise exception_cls(
            envelope.error.message,
            details={**envelope.error.details, "gateway_code": envelope.error.code},
        )

    try:
        return ChatCompletionChunk.model_validate(decoded)
    except PydanticValidationError as exc:
        raise GatewayInvalidResponse(
            "Gateway emitted a streaming chunk that did not match the schema",
            details={"validation_errors": exc.errors()},
        ) from exc


def _looks_like_structured_body(body_bytes: bytes) -> bool:
    """Cheap heuristic: does the body look like a JSON object with ``error``?

    Used by ``_raise_for_gateway_error`` to decide whether to attempt
    schema validation or treat the response as opaque server breakage.
    The full validation happens after this; we just want to avoid
    confusing log lines for bodies that aren't even close.
    """

    if not body_bytes:
        return False
    try:
        decoded = json.loads(body_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return isinstance(decoded, dict) and "error" in decoded


_client: GatewayClient | None = None


def get_gateway_client() -> GatewayClient:
    """Return the process-global gateway client, building it on first call."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = GatewayClient(
            base_url=settings.lq_ai_gateway_url,
            gateway_key=settings.lq_ai_gateway_key,
        )
    return _client


def set_gateway_client(client: GatewayClient | None) -> None:
    """Override the process-global gateway client.

    Used by tests to inject a respx-backed client. Pass ``None`` to clear.
    """

    global _client
    _client = client


async def close_gateway_client() -> None:
    """Close the gateway HTTP client on shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None
