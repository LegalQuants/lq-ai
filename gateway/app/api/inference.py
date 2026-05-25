"""OpenAI-compatible inference endpoints (B4 router + C6 embeddings).

Surface:

* ``POST /v1/chat/completions`` — accepts an OpenAI-format chat-completion
  request, runs it through :class:`app.router.Router`, returns the
  OpenAI-shaped response stamped with ``routed_inference_tier`` and
  ``routed_provider``. The HTTP response also carries the tier in a
  dedicated header (:data:`TIER_HEADER`) so header-only consumers
  (proxies, instrumentation) don't need to parse the body.
* ``POST /v1/embeddings`` — real handler (C6, per ADR 0008). Resolves
  the model through B4's router, dispatches to whichever adapter
  supports embeddings (currently :class:`OpenAIAdapter`), annotates
  tier + provider on the response, writes the routing-log row.
  ``ProviderUnsupportedError`` is fallback-eligible on this path
  (overriding the chat default) so an Anthropic-routed alias falls
  through to the next embedding-capable provider.
* ``GET  /v1/models`` — returns the configured ``model_aliases`` from
  ``gateway.yaml``.

What B4 added on top of B3
--------------------------

* **Real router.** The B3-era ``_resolve_anthropic_target`` is gone;
  alias resolution + tier derivation + dispatch + fallback live in
  :mod:`app.router`. Anthropic remains the only adapter; the dispatch
  is registry-based, so B6 plugs in additional adapters by registering
  themselves rather than touching this handler.
* **Tier annotation.** Every routed request is annotated with
  ``routed_inference_tier`` (1-5). The annotation appears in:

  * The HTTP response header :data:`TIER_HEADER` (header-only consumers).
  * The response body's ``routed_inference_tier`` extension field
    (already documented in ``docs/api/gateway-openapi.yaml``).
  * The ``inference_routing_log`` audit row (DB-backed audit trail).

  Both surfaces are populated for parity. Documented in
  ``docs/api/gateway-openapi.yaml`` and ``docs/PRD.md`` §4.
* **Routing-log writes.** Every request — successful or failed — writes
  one row to ``inference_routing_log`` via the configured
  :class:`app.routing_log.RoutingLogWriter`. The writer never raises
  out of :meth:`write`, so audit-log unavailability cannot block an
  inference call.
* **Fallback chain.** When the primary provider returns a
  fallback-eligible error, the router walks the alias's configured
  ``fallback`` list. With only Anthropic shipped today this is dead
  code in production, but unit-tested with mocked adapters so it's
  ready when B6 lands additional providers.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any, Final

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from app.anonymization.engine import Anonymizer
from app.anonymization.mapper import PseudonymMapper
from app.anonymization.middleware import (
    StreamingRehydrator,
    post_anonymize_response,
    pre_anonymize_request,
)
from app.clients.backend import BackendClient, Skill, get_backend_client
from app.config import GatewayConfig
from app.errors import LQAIError
from app.model_discovery import ModelDiscoverer
from app.observability_helpers import get_tracer, record_attributes
from app.providers import (
    ChatCompletionChunk,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
    EmbeddingsRequest,
    EmbeddingsResponse,
    InlineSkillRef,
    ProviderAdapter,
    ProviderAdapterError,
    ProviderAuthError,
    ProviderHTTPError,
    ProviderNetworkError,
    ProviderUnsupportedError,
)
from app.router import (
    ChatCompletionRoutedResult,
    ModelResolutionError,
    NoAdapterAvailableError,
    ResolvedTarget,
    RoutedProviderError,
    Router,
    estimate_cost,
    outcome_label_from_error,
    resolve_alias_chain,
    synthesize_request_id,
)
from app.routing_log import (
    InferenceRoutingLogRow,
    NullRoutingLogWriter,
    RoutingLogWriter,
)
from app.skills import assemble_skill_prompt
from app.tier_floor import TierFloor, is_refused, resolve_tier_floor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["inference"])


TIER_HEADER: Final[str] = "X-LQ-AI-Routed-Inference-Tier"
"""HTTP response header carrying the routed Inference Tier (1-5).

Documented in ``docs/api/gateway-openapi.yaml``. The body's
``routed_inference_tier`` extension field carries the same value;
the header exists so header-only consumers (HTTP-tracing proxies,
front-end instrumentation) don't have to parse the body."""

PROVIDER_HEADER: Final[str] = "X-LQ-AI-Routed-Provider"
"""HTTP response header carrying the provider name that handled the request."""


# --- Helpers ------------------------------------------------------------------


def _cost_usd_float(cost_estimate: float | None) -> float | None:
    """Return the cost estimate as a Python float suitable for an OTel attribute.

    ``_annotate_response`` already converts the Decimal from ``estimate_cost``
    to ``float`` via ``float(cost)`` before storing it on the response, so the
    value arriving here is already ``float | None``.  The helper exists to make
    the extraction intent explicit and to keep the span-instrumentation site
    readable.
    """

    return cost_estimate


def _not_implemented(
    *,
    message: str,
    next_task: str,
) -> JSONResponse:
    """Build the structured 501 envelope used for unimplemented surface."""

    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={
            "error": {
                "code": "not_implemented",
                "message": message,
                "details": {"next_task": next_task},
            }
        },
    )


def _gateway_error(
    *,
    code: str,
    message: str,
    http_status: int,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build a ``GatewayError``-shaped JSON response."""

    return JSONResponse(
        status_code=http_status,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            }
        },
    )


def _map_provider_error_to_response(exc: ProviderAdapterError) -> JSONResponse:
    """Map a :class:`ProviderAdapterError` to the right HTTP status + envelope.

    Centralizes the mapping so the streaming and non-streaming paths use
    the same rules. Per the gateway-openapi.yaml error enum:

    * Auth errors → ``unauthorized`` / 502 (the gateway is its own auth
      domain; an upstream credential failure is a misconfiguration, not
      the caller's fault).
    * Upstream 429 → ``rate_limit_exceeded`` / 429.
    * Upstream 404 with ``code = "invalid_model"`` (e.g., Ollama
      "model not pulled") → ``invalid_model`` / 400. The caller named
      a model the deployment can't serve — that's a request-side
      mistake, not an upstream outage. Adapters set ``code`` on the
      :class:`ProviderHTTPError` to opt into this mapping.
    * Upstream other 4xx → ``provider_unavailable`` / 502.
    * Upstream 5xx (after fallback exhausted) → ``provider_unavailable`` /
      502.
    * Network / DNS / TLS / timeout → ``provider_unavailable`` / 503.
    * ``ProviderUnsupportedError`` → ``not_implemented`` / 501.
    """

    if isinstance(exc, ProviderUnsupportedError):
        return _gateway_error(
            code=exc.code,
            message=exc.message,
            http_status=status.HTTP_501_NOT_IMPLEMENTED,
            details=exc.details,
        )
    if isinstance(exc, ProviderAuthError):
        logger.warning("provider auth rejected: %s", exc.message)
        return _gateway_error(
            code=exc.code,
            message=exc.message,
            http_status=status.HTTP_502_BAD_GATEWAY,
            details=exc.details,
        )
    if isinstance(exc, ProviderHTTPError):
        upstream = exc.upstream_status
        if upstream == 429:
            gw_status = status.HTTP_429_TOO_MANY_REQUESTS
            gw_code = "rate_limit_exceeded"
        elif upstream == 404 and exc.code == "invalid_model":
            # Adapter signaled "the request named a model the upstream
            # can't serve" (e.g., Ollama's "model not found, try
            # pulling it first"). Surface as 400 invalid_model so
            # callers see the request-side mistake clearly rather
            # than a generic upstream-flake 502.
            gw_status = status.HTTP_400_BAD_REQUEST
            gw_code = "invalid_model"
        else:
            gw_status = status.HTTP_502_BAD_GATEWAY
            gw_code = exc.code
        return _gateway_error(
            code=gw_code,
            message=exc.message,
            http_status=gw_status,
            details=exc.details,
        )
    if isinstance(exc, ProviderNetworkError):
        return _gateway_error(
            code=exc.code,
            message=exc.message,
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            details=exc.details,
        )
    return _gateway_error(
        code=exc.code,
        message=exc.message,
        http_status=status.HTTP_502_BAD_GATEWAY,
        details=exc.details,
    )


def _config(request: Request) -> GatewayConfig:
    """Pull the loaded :class:`GatewayConfig` off ``app.state``.

    D0.5: prefer the live :class:`MutableConfigHolder` snapshot when
    one is installed (lifespan-built apps); fall back to the static
    ``app.state.config`` for tests that bypass the lifespan and stash
    a config directly. The holder's :meth:`current` is a single
    attribute fetch — atomic under CPython's GIL — so an in-flight
    request always sees a single coherent snapshot.
    """

    holder = getattr(request.app.state, "config_holder", None)
    if holder is not None:
        return holder.current()  # type: ignore[no-any-return]
    return request.app.state.config  # type: ignore[no-any-return]


def _backend(request: Request) -> BackendClient:
    """Return the gateway's :class:`BackendClient`.

    The lifespan handler installs ``app.state.backend_client``; tests
    that bypass lifespan get the process-global default.
    """

    pre_built: BackendClient | None = getattr(request.app.state, "backend_client", None)
    if pre_built is not None:
        return pre_built
    return get_backend_client()


def _anonymizer(request: Request) -> Anonymizer:
    """Return the gateway's :class:`Anonymizer` (M2-B3).

    The lifespan installs a process-global :class:`Anonymizer` on
    ``app.state.anonymizer`` whose spaCy backbone loads lazily on the
    first :meth:`Anonymizer.pseudonymize_into` call. Tests that bypass
    lifespan (or want to inject a stub analyzer) can override
    ``app.state.anonymizer`` directly — same pattern as
    ``app.state.routing_log``.
    """

    pre_built: Anonymizer | None = getattr(request.app.state, "anonymizer", None)
    if pre_built is not None:
        return pre_built
    return Anonymizer()


def _inline_ref_to_skill(ref: InlineSkillRef) -> Skill:
    """Wave D.2 Task 3.0 — construct a :class:`Skill` from an inline ref.

    No HTTP, no cache. The backend has already done the
    authorization-equivalent step (the user couldn't have posted an
    inline_body without being authenticated as themselves on
    ``POST /chats/{id}/messages``); the gateway treats the body as
    trusted-from-the-backend and assembles it the same way as a
    catalogue skill.

    The synthesized :class:`Skill` is intentionally minimal: ``name`` +
    ``content_md`` + ``minimum_inference_tier`` is the field set the
    assembler and tier-floor resolver actually consume. ``scope`` is
    set to ``"inline"`` so any downstream introspection can identify
    these without re-parsing the synthesized-name convention.
    """

    return Skill(
        name=ref.name,
        scope="inline",
        title="",
        content_md=ref.body,
        content_yaml="",
        minimum_inference_tier=ref.minimum_inference_tier,
    )


async def _apply_skill_prompt_assembly(
    chat_request: ChatCompletionRequest,
    *,
    backend: BackendClient,
    request_id: str,
) -> list[Skill]:
    """Mutate ``chat_request`` in place to include skill-assembled content.

    Returns the :class:`Skill` objects whose content was actually fetched
    OR built from an inline ref. The route handler reads
    ``[s.name for s in skills]`` for the ``lq_ai_applied_skills``
    response field, and reads ``s.minimum_inference_tier`` for D1
    tier-floor enforcement.

    No-ops when BOTH ``lq_ai_skills`` and ``lq_ai_inline_skills`` are
    empty.

    Order: catalogue skills first (in input order), then inline skills
    (in input order). This is deterministic and matches the documented
    contract on :attr:`ChatCompletionRequest.lq_ai_inline_skills`.

    Inline bodies are NOT logged at INFO or above (PII risk — the body
    may carry user-drafted prompt content). The synthesized name + tier
    are safe to log.

    Raises :class:`LQAIError` subclasses on fetch failure / missing
    required input. The route handler's ``LQAIError`` handler in
    :mod:`app.main` translates them to the canonical envelope.
    """

    if not chat_request.lq_ai_skills and not chat_request.lq_ai_inline_skills:
        return []

    # Fetch each catalogue skill (cache-aware). Fail-fast on the first
    # failure; we don't try to dispatch a request with a partial skill
    # block. ``lq_ai_user_id`` (set by the backend per ADR 0012) drives
    # the user-scope shadow lookup at the internal endpoint — when
    # present, the backend resolves the user's user_skills row first
    # before falling through to the filesystem registry.
    user_id = chat_request.lq_ai_user_id
    skills: list[Skill] = []
    for name in chat_request.lq_ai_skills:
        skill = await backend.get_skill(name, request_id=request_id, user_id=user_id)
        skills.append(skill)

    # Wave D.2 Task 3.0 — append inline-body skills after the
    # catalogue-resolved set. No HTTP; the body is the source of truth.
    # We DO honor per-ref inputs: merge them into the request's
    # skill_inputs map under the synthesized name so the assembler's
    # standard pipeline applies substitution uniformly.
    if chat_request.lq_ai_inline_skills:
        # Defensively copy the inputs map so we don't mutate the
        # caller's dict (the request object is owned by the route
        # handler; we are a hot-path helper called once per request).
        inputs_map: dict[str, dict[str, Any]] = dict(chat_request.lq_ai_skill_inputs or {})
        for inline_ref in chat_request.lq_ai_inline_skills:
            skills.append(_inline_ref_to_skill(inline_ref))
            if inline_ref.inputs:
                # Caller may have already populated skill_inputs[name]
                # via the top-level field; the ref-level inputs take
                # precedence on key collision (most-specific intent).
                merged = dict(inputs_map.get(inline_ref.name, {}))
                merged.update(inline_ref.inputs)
                inputs_map[inline_ref.name] = merged
        chat_request.lq_ai_skill_inputs = inputs_map

    # Fetch the deployment's Organization Profile (D4). Returns None
    # when no Profile is set; the assembler omits Profile rendering
    # in that case. Profile-fetch failure is the same typed error as
    # skill-fetch failure (BackendUnreachable / SkillFetchFailed) and
    # propagates through the LQAIError path so the request fails-fast
    # with a structured envelope rather than dispatching with a
    # partial system prompt.
    organization_profile = await backend.get_organization_profile(
        request_id=request_id,
    )

    # Pull out any existing system message(s). OpenAI permits multiple;
    # we concatenate them with a blank line so the assembler can
    # prepend skill content as one block.
    system_chunks: list[str] = []
    non_system: list[ChatCompletionMessage] = []
    for msg in chat_request.messages:
        if msg.role == "system" and msg.content:
            system_chunks.append(msg.content)
        else:
            non_system.append(msg)
    existing_system = "\n\n".join(s for s in system_chunks if s)

    assembled = assemble_skill_prompt(
        skills,
        skill_inputs=chat_request.lq_ai_skill_inputs or {},
        existing_system_message=existing_system or None,
        organization_profile=organization_profile,
    )

    new_system = ChatCompletionMessage(role="system", content=assembled)
    chat_request.messages = [new_system, *non_system]

    # Audit-log tagging: surface the first attached skill in the
    # B3-era ``skill_name`` field if the caller didn't set it.
    if not chat_request.skill_name and skills:
        chat_request.skill_name = skills[0].name

    return skills


def _adapters(request: Request) -> dict[str, ProviderAdapter]:
    """Pull the adapter registry off ``app.state`` (set by lifespan)."""

    registry: dict[str, ProviderAdapter] = getattr(request.app.state, "adapters", {})
    return registry


def _router(request: Request) -> Router:
    """Pull the :class:`Router` instance off ``app.state``.

    The lifespan constructs the router after config + adapters are
    loaded; if it isn't there (lifespan didn't run, e.g., a test that
    bypassed startup) we fall back to constructing one on the fly.
    """

    pre_built: Router | None = getattr(request.app.state, "router", None)
    if pre_built is not None:
        return pre_built
    return Router(config=_config(request), adapters=_adapters(request))


def _routing_log(request: Request) -> RoutingLogWriter:
    """Pull the :class:`RoutingLogWriter` off ``app.state`` (lifespan-bound)."""

    writer: RoutingLogWriter | None = getattr(request.app.state, "routing_log", None)
    return writer if writer is not None else NullRoutingLogWriter()


def _model_discoverer(request: Request) -> ModelDiscoverer | None:
    """Pull the :class:`ModelDiscoverer` off ``app.state`` if installed.

    Lifespan bound: the gateway's startup constructs one and stashes it
    on ``app.state.model_discoverer`` (D0). Tests that bypass lifespan
    return ``None``; the route handler falls back to the alias-only
    payload in that case.
    """

    return getattr(request.app.state, "model_discoverer", None)


# --- Route handlers -----------------------------------------------------------


@router.post("/chat/completions", response_model=None)
async def chat_completions(request: Request) -> JSONResponse | StreamingResponse:
    """OpenAI-compatible chat completions.

    Body validation is local to this handler (rather than via FastAPI's
    body parser) so we can return a structured ``GatewayError`` envelope
    on validation failure instead of FastAPI's default 422 shape.
    """

    try:
        raw = await request.json()
    except json.JSONDecodeError:
        return _gateway_error(
            code="invalid_request",
            message="Request body is not valid JSON",
            http_status=status.HTTP_400_BAD_REQUEST,
        )
    if not isinstance(raw, dict):
        return _gateway_error(
            code="invalid_request",
            message="Request body must be a JSON object",
            http_status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        chat_request = ChatCompletionRequest.model_validate(raw)
    except ValidationError as exc:
        # ``include_input=False`` strips pydantic's echo of the offending
        # input payload. Without it, a ``string_too_long`` failure on a
        # 64K+1-byte inline-skill ``body`` returns the FULL submitted
        # body verbatim in the response envelope — leaking the
        # user-drafted skill body back over the wire to the caller.
        # ``include_context=False`` / ``include_url=False`` strip
        # non-JSON-serializable exception instances and pydantic doc URLs
        # the caller doesn't need. Regression in
        # ``tests/test_inference_inline_skills.py``.
        return _gateway_error(
            code="invalid_request",
            message="Chat completion request failed schema validation",
            http_status=status.HTTP_400_BAD_REQUEST,
            details={
                "errors": exc.errors(
                    include_context=False,
                    include_url=False,
                    include_input=False,
                )
            },
        )

    config = _config(request)
    gw_router = _router(request)
    log_writer = _routing_log(request)
    request_id = synthesize_request_id(_request_id_header(request))

    # --- Skill prompt assembly (C2) ----------------------------------------
    # Mutates chat_request in place: replaces system message(s) with
    # the assembled skill content (skills first, operator system
    # message after a separator). Errors here are typed LQAIError
    # subclasses (SkillNotFound / SkillFetchFailed / SkillInputMissing);
    # let them propagate to the FastAPI handler so the canonical
    # envelope wraps them.
    applied_skill_objects: list[Skill] = []
    # Wave D.2 Task 3.0 — kick off assembly when EITHER catalogue skills
    # OR inline-body skills are attached. The assembler is a no-op when
    # both lists are empty (preserves pre-D.2 wire shape).
    if chat_request.lq_ai_skills or chat_request.lq_ai_inline_skills:
        backend = _backend(request)
        try:
            applied_skill_objects = await _apply_skill_prompt_assembly(
                chat_request,
                backend=backend,
                request_id=request_id,
            )
        except LQAIError:
            # Re-raise — the global LQAIError handler in app.main
            # serializes the canonical envelope. We don't write a
            # routing-log row here because the request never reached
            # an adapter.
            raise

    applied_skills: list[str] = [skill.name for skill in applied_skill_objects]

    # --- Resolution (no upstream call yet) ----------------------------------
    try:
        candidates = gw_router.resolve(chat_request.model)
    except ModelResolutionError as exc:
        await _write_unresolved(
            log_writer,
            chat_request=chat_request,
            request_id=request_id,
            message=str(exc),
        )
        return _gateway_error(
            code="invalid_model",
            message=str(exc),
            http_status=status.HTTP_400_BAD_REQUEST,
            details={"requested_model": chat_request.model},
        )

    # --- Tier-floor refusal (D1) -------------------------------------------
    # The effective floor is max(request override, project floor, skill
    # floors). Per PRD §4.4, the gateway refuses with 403
    # ``tier_below_minimum`` when the routed tier of the primary
    # candidate falls below that floor. We compare against the *primary*
    # candidate's tier — fallbacks only matter if the primary actually
    # tries and fails. Refusing on the primary's tier mirrors the
    # documented "what tier would this request go to?" semantics.
    floor = resolve_tier_floor(request=chat_request, skills=applied_skill_objects)
    primary = candidates[0]
    if is_refused(resolved_tier=primary.routed_inference_tier, floor=floor):
        # is_refused returns False when floor is None; the assert tells mypy
        # what the runtime invariant guarantees so `floor` narrows to TierFloor.
        assert floor is not None
        await _write_refusal(
            log_writer,
            chat_request=chat_request,
            target=primary,
            request_id=request_id,
            floor=floor,
        )
        return _gateway_error(
            code="tier_below_minimum",
            message=(
                f"Request requires Inference Tier {floor.value} or stronger "
                f"(source: {floor.source}), but the routed model resolves "
                f"to tier {primary.routed_inference_tier}, which is weaker. "
                "Pick a model with an equal or lower-numbered (stronger) tier, "
                "or relax the floor."
            ),
            http_status=status.HTTP_403_FORBIDDEN,
            details={
                "required_tier": floor.value,
                "resolved_tier": primary.routed_inference_tier,
                "source": floor.source,
                "requested_model": chat_request.model,
                "routed_provider": primary.provider.name,
                "routed_model": primary.native_model,
            },
        )

    # --- Anonymization pre-middleware (M2-B3) -------------------------------
    # Sits between Tier Derivation and Provider Adapter per PRD §4.3.
    # Mutates chat_request.messages[*].content + lq_ai_skill_inputs in
    # place. Returns the mapper used for response-path rehydration, or
    # ``None`` when any skip condition fires (master disabled / tier
    # outside apply_at_tiers / privileged chat / per-request opt-out).
    anonymizer = _anonymizer(request)
    anon_mapper: PseudonymMapper | None = pre_anonymize_request(
        chat_request=chat_request,
        config=config.anonymization,
        routed_tier=primary.routed_inference_tier,
        anonymizer=anonymizer,
    )

    # --- Streaming path -----------------------------------------------------
    if chat_request.stream:
        return await _stream_with_fallback(
            request=request,
            chat_request=chat_request,
            candidates=candidates,
            log_writer=log_writer,
            request_id=request_id,
            applied_skills=applied_skills,
            anon_mapper=anon_mapper,
            anonymizer=anonymizer,
        )

    # --- Non-streaming path -------------------------------------------------
    # The span is created here (handler level) rather than inside the router
    # so it can carry ``inference.cost_usd``, which is computed by
    # ``_annotate_response`` on the success path — the router never sees cost.
    # Streaming path is out of scope (deferred).
    tracer = get_tracer()
    with tracer.start_as_current_span("inference.dispatch") as dispatch_span:
        try:
            result = await gw_router.chat_completion(chat_request)
        except RoutedProviderError as wrapped:
            # The router attributes the failure to the actual target that
            # produced the error (rather than the last candidate). Unwrap
            # here, write the routing-log row with that target, and map the
            # underlying error to the right HTTP status.
            record_attributes(
                dispatch_span,
                **{
                    "inference.provider": wrapped.target.provider.name,
                    "inference.model": wrapped.target.native_model,
                    "inference.tier": wrapped.target.routed_inference_tier,
                    "inference.outcome": outcome_label_from_error(wrapped.error),
                },
            )
            await _write_failure(
                log_writer,
                chat_request=chat_request,
                target=wrapped.target,
                request_id=request_id,
                error=wrapped.error,
                latency_ms=wrapped.latency_ms,
                anonymization_applied=anon_mapper is not None,
            )
            return _map_provider_error_to_response(wrapped.error)
        except NoAdapterAvailableError as exc:
            # No model/tier here on purpose: when no adapter could be
            # instantiated the resolved target carries no native model or
            # tier, so only provider + outcome are meaningful.
            record_attributes(
                dispatch_span,
                **{
                    "inference.provider": candidates[0].provider.name,
                    "inference.outcome": "unavailable",
                },
            )
            await _write_unavailable(
                log_writer,
                chat_request=chat_request,
                target=candidates[0],
                request_id=request_id,
                message=exc.message,
                anonymization_applied=anon_mapper is not None,
            )
            return _gateway_error(
                code="provider_unavailable",
                message=exc.message,
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                details={"provider": candidates[0].provider.name},
            )

        # --- Anonymization post-middleware (non-streaming) ----------------------
        # When the pre-middleware fired (mapper is non-None), rehydrate the
        # provider's response content back to the originals. The mapper is
        # then dropped on function exit — never persisted, never logged.
        if anon_mapper is not None:
            post_anonymize_response(
                response=result.response, mapper=anon_mapper, anonymizer=anonymizer
            )

        # --- Success: stamp tier on body, write log, return --------------------
        annotated = _annotate_response(result.response, target=result.target, config=config)
        if applied_skills:
            annotated.lq_ai_applied_skills = list(applied_skills)
        annotated.anonymization_applied = anon_mapper is not None
        usage = result.response.usage
        record_attributes(
            dispatch_span,
            **{
                "inference.provider": result.target.provider.name,
                "inference.model": result.target.native_model,
                "inference.tier": result.target.routed_inference_tier,
                "inference.outcome": "success",
                "inference.tokens_in": usage.prompt_tokens if usage is not None else None,
                "inference.tokens_out": usage.completion_tokens if usage is not None else None,
                "inference.cost_usd": _cost_usd_float(annotated.cost_estimate),
            },
        )
        await _write_success(
            log_writer,
            chat_request=chat_request,
            result=result,
            request_id=request_id,
            cost_estimate=annotated.cost_estimate,
            anonymization_applied=anon_mapper is not None,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=annotated.model_dump(mode="json", exclude_none=True),
            headers={
                TIER_HEADER: str(result.target.routed_inference_tier),
                PROVIDER_HEADER: result.target.provider.name,
            },
        )


@router.post("/embeddings", response_model=None)
async def embeddings(request: Request) -> JSONResponse:
    """OpenAI-compatible embeddings (C6).

    Body: ``{model, input, encoding_format?, dimensions?, user?}`` per
    OpenAI's contract. ``model`` may be either an alias (e.g.,
    ``embedding``) or a provider-native model name; B4's router resolves
    either to a (provider, model) target. The adapter selected by the
    target runs the embeddings call; success returns the OpenAI-shaped
    body annotated with ``routed_inference_tier``.

    The route writes one row to ``inference_routing_log`` per call so
    the audit log captures the embedding workload alongside chat
    completions. Failures translate through the same error envelope as
    chat completions per ADR 0003.
    """

    try:
        raw = await request.json()
    except json.JSONDecodeError:
        return _gateway_error(
            code="invalid_request",
            message="Request body is not valid JSON",
            http_status=status.HTTP_400_BAD_REQUEST,
        )
    if not isinstance(raw, dict):
        return _gateway_error(
            code="invalid_request",
            message="Request body must be a JSON object",
            http_status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        embeddings_request = EmbeddingsRequest.model_validate(raw)
    except ValidationError as exc:
        return _gateway_error(
            code="invalid_request",
            message="Embeddings request failed schema validation",
            http_status=status.HTTP_400_BAD_REQUEST,
            details={"errors": exc.errors()},
        )

    config = _config(request)
    gw_router = _router(request)
    log_writer = _routing_log(request)
    request_id = synthesize_request_id(_request_id_header(request))

    # --- Resolution (no upstream call yet) ---------------------------------
    try:
        candidates = gw_router.resolve(embeddings_request.model)
    except ModelResolutionError as exc:
        await _write_unresolved_embeddings(
            log_writer,
            embeddings_request=embeddings_request,
            request_id=request_id,
            message=str(exc),
        )
        return _gateway_error(
            code="invalid_model",
            message=str(exc),
            http_status=status.HTTP_400_BAD_REQUEST,
            details={"requested_model": embeddings_request.model},
        )

    # --- Adapter dispatch (with the same fallback eligibility as chat) -----
    adapter_registry = _adapters(request)
    last_error: ProviderAdapterError | None = None
    last_error_target: ResolvedTarget | None = None
    last_error_latency_ms = 0
    fallbacks_tried: list[str] = []

    for target in candidates:
        adapter = adapter_registry.get(target.provider.name)
        if adapter is None:
            logger.warning(
                "no adapter for embeddings provider %r (%s); trying next candidate",
                target.provider.name,
                target.role,
            )
            fallbacks_tried.append(target.provider.name)
            continue

        start = time.monotonic()
        try:
            result = await adapter.embeddings(
                embeddings_request,
                model=target.native_model,
            )
        except ProviderAdapterError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "embeddings provider %r failed (%s) after %dms: %s",
                target.provider.name,
                type(exc).__name__,
                latency_ms,
                exc.message,
            )
            last_error = exc
            last_error_target = target
            last_error_latency_ms = latency_ms
            fallbacks_tried.append(target.provider.name)
            # ProviderUnsupportedError on embeddings (e.g., Anthropic) is
            # NOT fallback-eligible per the chat path, but for embeddings
            # it actually IS — the next candidate may be a different
            # provider type that supports embeddings. We override the
            # default chat-side rule here.
            if isinstance(exc, ProviderUnsupportedError):
                continue
            from app.router import is_fallback_eligible

            if is_fallback_eligible(exc):
                continue
            await _write_embeddings_failure(
                log_writer,
                embeddings_request=embeddings_request,
                target=target,
                request_id=request_id,
                error=exc,
                latency_ms=latency_ms,
            )
            return _map_provider_error_to_response(exc)

        # Success: stamp tier on body, write log, return.
        latency_ms = int((time.monotonic() - start) * 1000)
        annotated = _annotate_embeddings_response(result, target=target, config=config)
        await _write_embeddings_success(
            log_writer,
            embeddings_request=embeddings_request,
            target=target,
            request_id=request_id,
            response=annotated,
            latency_ms=latency_ms,
            config=config,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=annotated.model_dump(mode="json", exclude_none=True),
            headers={
                TIER_HEADER: str(target.routed_inference_tier),
                PROVIDER_HEADER: target.provider.name,
            },
        )

    # All candidates failed (no adapter or non-fallback-eligible exhausted).
    if last_error is not None and last_error_target is not None:
        await _write_embeddings_failure(
            log_writer,
            embeddings_request=embeddings_request,
            target=last_error_target,
            request_id=request_id,
            error=last_error,
            latency_ms=last_error_latency_ms,
        )
        return _map_provider_error_to_response(last_error)

    # Nothing was even tried.
    primary = candidates[0]
    await _write_embeddings_unavailable(
        log_writer,
        embeddings_request=embeddings_request,
        target=primary,
        request_id=request_id,
        message="no adapter available",
    )
    return _gateway_error(
        code="provider_unavailable",
        message=(
            f"No adapter available to handle embeddings for model "
            f"{embeddings_request.model!r}; check that the provider's credential "
            "env var is set"
        ),
        http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        details={"provider": primary.provider.name},
    )


@router.get("/models")
async def list_models(request: Request) -> dict[str, Any]:
    """Return aliases + live-discovered provider-native models.

    OpenAI's ``GET /v1/models`` shape is preserved — ``{"object": "list",
    "data": [...]}`` with each entry carrying ``{id, object, created,
    owned_by}``. D0 extends each entry with ``lq_ai_kind`` (``"alias"``
    or ``"provider_native"``) and, where known,
    ``routed_inference_tier`` and ``provider_type`` so the LQ.AI shell's
    model picker can group rows and surface tier badges without a second
    roundtrip.

    Discovery walks every enabled Ollama provider's ``/api/tags`` and
    every Anthropic provider's ``/v1/models``. Each call is best-effort
    behind a short cache (60s for Ollama, 5min for Anthropic). A failed
    source does not abort the merge; the response surfaces whatever
    other sources produced.
    """

    config = _config(request)
    discoverer = _model_discoverer(request)
    if discoverer is None:
        # Lifespan hasn't run (e.g., a test that bypassed startup) — fall
        # back to the alias-only payload so the endpoint stays usable.
        return config.to_models_payload()
    discovered = await discoverer.list_all(config)
    return {
        "object": "list",
        "data": [entry.to_payload() for entry in discovered],
    }


@router.get("/citation-engine/config")
async def citation_engine_config(request: Request) -> dict[str, Any]:
    """Expose the citation_engine block for the api/'s Citation Engine (M2-C1 / M2-D1).

    The api/ runs Stage 3 (LLM paraphrase judge) and Stage 4 (ensemble)
    of the Citation Engine cascade and reads its configuration from
    this endpoint at startup so the operator configures model choices
    in one place (``gateway.yaml``) rather than mirroring them on the
    api/ side.

    Response shape (M2-D1):

    .. code-block:: json

       {
         "judge_model": "fast",
         "ensemble_verification": {
           "default_enabled": false,
           "judge_models": ["fast", "smart"],
           "aggregation_rule": "strict",
           "max_cost_per_message_usd": 0.05,
           "envelope_tier": 3
         }
       }

    ``ensemble_verification.envelope_tier`` is server-computed as
    ``max(routed_inference_tier for each judge_model)`` using the
    primary target of each alias (fallbacks could route weaker at
    runtime, but the primary is the operator's intent; runtime
    weakening is visible via per-call routing_log rows). NULL when
    ``judge_models`` is empty.

    The api/ caches the value for the process lifetime; restarting the
    gateway after an alias change is the deployment story for now.
    Hot-reload of this value lands when M2 needs it; today the alias
    rarely changes outside scheduled maintenance.
    """

    config = _config(request)
    ensemble = config.citation_engine.ensemble_verification

    envelope_tier: int | None = None
    if ensemble.judge_models:
        tiers: list[int] = []
        for judge in ensemble.judge_models:
            try:
                resolved = resolve_alias_chain(requested_model=judge, config=config)
            except ModelResolutionError:
                # Misconfigured judge alias — skip it for envelope
                # computation; the dispatch-time error message will
                # surface the typo when verification actually runs.
                continue
            if resolved:
                tiers.append(resolved[0].routed_inference_tier)
        envelope_tier = max(tiers) if tiers else None

    return {
        "judge_model": config.citation_engine.judge_model,
        "ensemble_verification": {
            "default_enabled": ensemble.default_enabled,
            "judge_models": list(ensemble.judge_models),
            "aggregation_rule": ensemble.aggregation_rule,
            "max_cost_per_message_usd": ensemble.max_cost_per_message_usd,
            "envelope_tier": envelope_tier,
        },
    }


# --- Streaming helpers --------------------------------------------------------


async def _stream_with_fallback(
    *,
    request: Request,
    chat_request: ChatCompletionRequest,
    candidates: list[ResolvedTarget],
    log_writer: RoutingLogWriter,
    request_id: str,
    applied_skills: list[str] | None = None,
    anon_mapper: PseudonymMapper | None = None,
    anonymizer: Anonymizer | None = None,
) -> StreamingResponse:
    """Run the streaming path with primary + fallback chain.

    The router's :meth:`Router.chat_completion` only handles the
    non-streaming case; for streaming we walk candidates here so we can
    inject the tier annotation into each chunk before it goes out the
    wire and write the routing-log row when the stream finishes.

    Streaming surfaces the tier two ways: in the response headers (the
    same :data:`TIER_HEADER` as non-streaming) and inside each
    :class:`ChatCompletionChunk` envelope's
    ``routed_inference_tier`` field. We can't write the routing-log
    row until the stream completes (we need final token usage), so the
    write happens at the end of the iterator.
    """

    adapter_registry = _adapters(request)

    # Pick the first candidate with an adapter as the streaming target.
    # Streaming fallback (start one stream, abort, start another) is
    # operator-hostile — partial output to the client makes the
    # handover ambiguous. For now, streaming uses only the first
    # available candidate; if that fails before producing any output
    # the client sees an SSE error frame. Fallback for streaming is
    # tracked as a follow-up (see deferred items in M1-PROGRESS).
    target: ResolvedTarget | None = None
    adapter: ProviderAdapter | None = None
    for candidate in candidates:
        candidate_adapter = adapter_registry.get(candidate.provider.name)
        if candidate_adapter is not None:
            target = candidate
            adapter = candidate_adapter
            break

    if target is None or adapter is None:
        await _write_unavailable(
            log_writer,
            chat_request=chat_request,
            target=candidates[0],
            request_id=request_id,
            message="no adapter available for streaming",
            anonymization_applied=anon_mapper is not None,
        )
        return StreamingResponse(
            _single_error_sse(
                code="provider_unavailable",
                message=(
                    "No adapter available to handle the request; check that the "
                    "provider's credential env var is set"
                ),
            ),
            media_type="text/event-stream",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={
                TIER_HEADER: str(candidates[0].routed_inference_tier),
                PROVIDER_HEADER: candidates[0].provider.name,
            },
        )

    config = _config(request)

    async def upstream() -> AsyncIterator[ChatCompletionChunk]:
        # Adapter contract: stream=True returns an AsyncIterator[ChatCompletionChunk].
        produced = await adapter.chat_completion(
            chat_request,
            model=target.native_model,
            stream=True,
        )
        if isinstance(produced, ChatCompletionResponse):
            # Defensive — adapters shouldn't do this with stream=True.
            raise RuntimeError("adapter returned a response object for stream=True")
        async for chunk in produced:
            yield chunk

    return StreamingResponse(
        _stream_openai_sse(
            upstream(),
            target=target,
            config=config,
            chat_request=chat_request,
            log_writer=log_writer,
            request_id=request_id,
            applied_skills=applied_skills or [],
            anon_mapper=anon_mapper,
            anonymizer=anonymizer,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            TIER_HEADER: str(target.routed_inference_tier),
            PROVIDER_HEADER: target.provider.name,
        },
    )


async def _stream_openai_sse(
    chunks: AsyncIterator[ChatCompletionChunk],
    *,
    target: ResolvedTarget,
    config: GatewayConfig,
    chat_request: ChatCompletionRequest,
    log_writer: RoutingLogWriter,
    request_id: str,
    applied_skills: list[str] | None = None,
    anon_mapper: PseudonymMapper | None = None,
    anonymizer: Anonymizer | None = None,
) -> AsyncIterator[bytes]:
    """Serialize chunks as OpenAI-format SSE frames; write log on completion.

    M2-B3: when ``anon_mapper`` is non-None, each chunk's
    ``delta.content`` is fed through a per-stream
    :class:`StreamingRehydrator` (Decision B (i)) so the bytes we
    write to the wire contain only rehydrated text, never pseudonyms.
    On stream completion, the rehydrator's buffer is flushed and
    emitted as a synthesized terminal chunk if non-empty.
    """

    last_chunk: ChatCompletionChunk | None = None
    rehydrator: StreamingRehydrator | None = None
    if anon_mapper is not None and anonymizer is not None:
        rehydrator = StreamingRehydrator(mapper=anon_mapper, anonymizer=anonymizer)

    try:
        async for chunk in chunks:
            chunk.routed_provider = target.provider.name
            chunk.routed_inference_tier = target.routed_inference_tier
            if applied_skills:
                chunk.lq_ai_applied_skills = list(applied_skills)
            if rehydrator is not None:
                for choice in chunk.choices:
                    if choice.delta.content is None:
                        continue
                    choice.delta.content = rehydrator.process(choice.delta.content)
            last_chunk = chunk
            payload = chunk.model_dump(mode="json", exclude_none=True)
            yield f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()
    except ProviderAdapterError as exc:
        envelope = {"error": {"code": exc.code, "message": exc.message, "details": exc.details}}
        yield f"data: {json.dumps(envelope, separators=(',', ':'))}\n\n".encode()
        await _write_failure(
            log_writer,
            chat_request=chat_request,
            target=target,
            request_id=request_id,
            error=exc,
            latency_ms=None,
            anonymization_applied=anon_mapper is not None,
        )
        yield b"data: [DONE]\n\n"
        return

    # M2-B3: flush any held tail before [DONE] so the caller doesn't
    # lose the last fragment of a pseudonym that crystallized only at
    # stream end. We attach it to a synthesized terminal chunk with
    # ``choices=[{delta: {content: tail}}]`` if the tail is non-empty,
    # so existing SSE consumers parse it as a normal content delta.
    if rehydrator is not None and last_chunk is not None:
        tail = rehydrator.flush()
        if tail:
            terminal = last_chunk.model_copy(deep=True)
            for choice in terminal.choices:
                choice.delta.content = tail
                choice.delta.role = None
                choice.finish_reason = None
            terminal.lq_ai_applied_skills = None
            payload = terminal.model_dump(mode="json", exclude_none=True)
            yield f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()

    # Persist the routing-log row using the final chunk's usage block.
    # This MUST precede the `[DONE]` yield: the api-side consumer stops
    # iterating on `[DONE]` and closes the stream context, which cancels
    # this generator (throws GeneratorExit at the next suspended `yield`).
    # Anything awaited after the `[DONE]` yield never runs — so every
    # streamed success turn would persist zero routing-log rows. The
    # failure path above writes before its `[DONE]` for the same reason;
    # mirror that here.
    usage = (last_chunk.usage if last_chunk is not None else None) or None
    cost = (
        estimate_cost(
            provider_name=target.provider.name,
            native_model=target.native_model,
            usage=usage,
            rates=config.cost_tracking.rates,
        )
        if usage is not None
        else None
    )
    chat_id, message_id = _correlation_ids(chat_request)
    await log_writer.write(
        InferenceRoutingLogRow(
            requested_model=chat_request.model,
            routed_provider=target.provider.name,
            routed_model=target.native_model,
            routed_inference_tier=target.routed_inference_tier,
            tokens_in=(usage.prompt_tokens if usage is not None else None),
            tokens_out=(usage.completion_tokens if usage is not None else None),
            cost_estimate=cost,
            latency_ms=None,  # streaming latency is wall-time; left null for now
            anonymization_applied=anon_mapper is not None,
            request_id=request_id,
            chat_id=chat_id,
            message_id=message_id,
            purpose=_purpose_from_request(chat_request),
        )
    )

    yield b"data: [DONE]\n\n"


async def _single_error_sse(*, code: str, message: str) -> AsyncIterator[bytes]:
    """Emit a single SSE error frame plus ``[DONE]``."""

    envelope = {"error": {"code": code, "message": message, "details": {}}}
    yield f"data: {json.dumps(envelope, separators=(',', ':'))}\n\n".encode()
    yield b"data: [DONE]\n\n"


# --- Routing-log writers ------------------------------------------------------


def _correlation_ids(
    chat_request: ChatCompletionRequest,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Extract ``(chat_id, message_id)`` from the request envelope (C3).

    The C3 envelope adds ``lq_ai_chat_id`` and ``lq_ai_message_id`` —
    the canonical surface for routing-log correlation. The pre-existing
    ``chat_id`` field (B3-era audit-log tag) is honoured as a fallback
    so older callers (or callers that don't yet plumb the C3 fields)
    still get a chat-id stamp on the routing log.

    Returns ``(None, None)`` for any field that's absent or fails UUID
    parse — defensive: we never let a malformed correlation id break
    the routing-log write.
    """

    def _parse(value: str | None) -> uuid.UUID | None:
        if not value:
            return None
        try:
            return uuid.UUID(value)
        except ValueError:
            return None

    chat_id = _parse(chat_request.lq_ai_chat_id) or _parse(chat_request.chat_id)
    message_id = _parse(chat_request.lq_ai_message_id)
    return chat_id, message_id


# Known values for the ``inference_routing_log.purpose`` column. Values
# outside this set fall back to ``'chat'`` in :func:`_purpose_from_request`
# so an arbitrary caller can't pollute the column with free-form strings.
_KNOWN_PURPOSES = frozenset({"chat", "judge_paraphrase", "embedding"})


def _purpose_from_request(chat_request: ChatCompletionRequest) -> str:
    """Resolve the routing-log ``purpose`` tag from the chat request envelope.

    M2-E2 added ``lq_ai_purpose`` to :class:`ChatCompletionRequest`. The
    Citation Engine sets it to ``'judge_paraphrase'`` on every Stage 3
    / Stage 4 judge call so the api/ cost-calibration query can filter
    routing-log rows down to judge traffic only. Other callers leave
    it unset and the row records ``'chat'``.

    Unknown values fall back to ``'chat'`` defensively — the column is
    ``varchar(32)`` and downstream code expects one of the known
    values.
    """

    raw = chat_request.lq_ai_purpose
    if raw is None:
        return "chat"
    value = raw.strip()
    if value in _KNOWN_PURPOSES:
        return value
    return "chat"


def _annotate_response(
    response: ChatCompletionResponse,
    *,
    target: ResolvedTarget,
    config: GatewayConfig,
) -> ChatCompletionResponse:
    """Stamp the routed-tier and routed-provider fields plus cost estimate."""

    response.routed_provider = target.provider.name
    response.routed_inference_tier = target.routed_inference_tier
    cost = estimate_cost(
        provider_name=target.provider.name,
        native_model=target.native_model,
        usage=response.usage,
        rates=config.cost_tracking.rates,
    )
    if cost is not None:
        response.cost_estimate = float(cost)
    return response


async def _write_success(
    writer: RoutingLogWriter,
    *,
    chat_request: ChatCompletionRequest,
    result: ChatCompletionRoutedResult,
    request_id: str,
    cost_estimate: float | None,
    anonymization_applied: bool = False,
) -> None:
    from decimal import Decimal as _Decimal

    cost: _Decimal | None = None
    if cost_estimate is not None:
        cost = _Decimal(str(cost_estimate))

    chat_id, message_id = _correlation_ids(chat_request)
    await writer.write(
        InferenceRoutingLogRow(
            requested_model=chat_request.model,
            routed_provider=result.target.provider.name,
            routed_model=result.target.native_model,
            routed_inference_tier=result.target.routed_inference_tier,
            tokens_in=result.response.usage.prompt_tokens,
            tokens_out=result.response.usage.completion_tokens,
            cost_estimate=cost,
            latency_ms=result.latency_ms,
            anonymization_applied=anonymization_applied,
            request_id=request_id,
            chat_id=chat_id,
            message_id=message_id,
            purpose=_purpose_from_request(chat_request),
        )
    )


async def _write_failure(
    writer: RoutingLogWriter,
    *,
    chat_request: ChatCompletionRequest,
    target: ResolvedTarget,
    request_id: str,
    error: ProviderAdapterError,
    latency_ms: int | None,
    anonymization_applied: bool = False,
) -> None:
    """Write a routing-log row for a request that reached an adapter and failed.

    The tier is still derived (the choke-point invariant) and the row
    captures the error code in ``refusal_reason`` so operators can grep
    for upstream-induced failures even though ``refused`` is technically
    a tier-floor concept (per D1). We use ``refused = false`` here
    because the tier policy did not refuse the request — the upstream
    failed. ``refusal_reason`` is overloaded as a free-text "why this
    row didn't carry usage data" — the schema's nullability accommodates
    that. D1 will tighten the semantics; we add a follow-up note in
    docs/M1-PROGRESS.md.

    M2-B3: ``anonymization_applied`` records that the middleware fired
    even though the upstream failed. The substitution happened on the
    request path; auditors need to see that the provider received
    pseudonymized content (it just then returned an error).
    """

    chat_id, message_id = _correlation_ids(chat_request)
    await writer.write(
        InferenceRoutingLogRow(
            requested_model=chat_request.model,
            routed_provider=target.provider.name,
            routed_model=target.native_model,
            routed_inference_tier=target.routed_inference_tier,
            latency_ms=latency_ms,
            anonymization_applied=anonymization_applied,
            refused=False,
            refusal_reason=f"upstream_error:{error.code}",
            request_id=request_id,
            chat_id=chat_id,
            message_id=message_id,
            purpose=_purpose_from_request(chat_request),
        )
    )


async def _write_unavailable(
    writer: RoutingLogWriter,
    *,
    chat_request: ChatCompletionRequest,
    target: ResolvedTarget,
    request_id: str,
    message: str,
    anonymization_applied: bool = False,
) -> None:
    """Write a routing-log row when no adapter could handle the request."""

    chat_id, message_id = _correlation_ids(chat_request)
    await writer.write(
        InferenceRoutingLogRow(
            requested_model=chat_request.model,
            routed_provider=target.provider.name,
            routed_model=target.native_model,
            routed_inference_tier=target.routed_inference_tier,
            anonymization_applied=anonymization_applied,
            refused=False,
            refusal_reason=f"adapter_unavailable:{message}",
            request_id=request_id,
            chat_id=chat_id,
            message_id=message_id,
            purpose=_purpose_from_request(chat_request),
        )
    )


async def _write_refusal(
    writer: RoutingLogWriter,
    *,
    chat_request: ChatCompletionRequest,
    target: ResolvedTarget,
    request_id: str,
    floor: TierFloor,
) -> None:
    """Write a routing-log row for a D1 tier-floor refusal.

    The row carries the *primary* candidate's tier (the one we would
    have routed to) so operators auditing the log can see which tier
    the request was about to land on when refusal fired. The
    ``refused`` flag is True (the canonical D1 signal) and the
    ``refusal_reason`` carries the structured ``tier_below_minimum``
    code plus the binding source so the audit trail records *why* the
    refusal happened, not just that it did.
    """

    chat_id, message_id = _correlation_ids(chat_request)
    await writer.write(
        InferenceRoutingLogRow(
            requested_model=chat_request.model,
            routed_provider=target.provider.name,
            routed_model=target.native_model,
            routed_inference_tier=target.routed_inference_tier,
            refused=True,
            refusal_reason=(
                f"tier_below_minimum:required={floor.value}:"
                f"resolved={target.routed_inference_tier}:source={floor.source}"
            ),
            request_id=request_id,
            chat_id=chat_id,
            message_id=message_id,
            purpose=_purpose_from_request(chat_request),
        )
    )


async def _write_unresolved(
    writer: RoutingLogWriter,
    *,
    chat_request: ChatCompletionRequest,
    request_id: str,
    message: str,
) -> None:
    """Write a routing-log row when the request couldn't even resolve.

    The schema requires ``routed_provider``, ``routed_model``, and
    ``routed_inference_tier`` to be NOT NULL; we use the literal
    sentinels ``"<unresolved>"`` and tier ``1`` so the row schema is
    valid and operators can still see the request was received. The
    ``refusal_reason`` carries the diagnostic.

    Tier ``1`` is the safest sentinel — it means "fully local, no data
    leaves the deployment", which is the conservative posture for "we
    don't know where this would have gone".
    """

    chat_id, message_id = _correlation_ids(chat_request)
    await writer.write(
        InferenceRoutingLogRow(
            requested_model=chat_request.model,
            routed_provider="<unresolved>",
            routed_model="<unresolved>",
            routed_inference_tier=1,
            refused=True,
            refusal_reason=f"invalid_model:{message}",
            request_id=request_id,
            chat_id=chat_id,
            message_id=message_id,
            purpose=_purpose_from_request(chat_request),
        )
    )


# --- Misc helpers -------------------------------------------------------------


def _request_id_header(request: Request) -> str | None:
    """Pull the upstream request id if the caller supplied one.

    Backend services typically forward their own request id (X-Request-Id)
    so downstream rows correlate with upstream traces. We accept either
    spelling for tolerance.
    """

    for name in ("x-request-id", "x-correlation-id"):
        header = request.headers.get(name)
        if header:
            return header
    return None


# --- Embeddings helpers (C6) -------------------------------------------------


def _annotate_embeddings_response(
    response: EmbeddingsResponse,
    *,
    target: ResolvedTarget,
    config: GatewayConfig,
) -> EmbeddingsResponse:
    """Stamp tier annotation onto an embeddings response.

    The :class:`EmbeddingsResponse` model has ``extra='allow'``, so
    extension fields round-trip through ``model_dump`` even though
    they aren't first-class attributes. Centralized so the embeddings
    path matches the chat-completions annotation contract.
    """

    # extra="allow" stores unknown attributes in __pydantic_extra__ which
    # model_dump() merges back into the serialized output. Initialize the
    # dict first so we can assign idempotently.
    if response.__pydantic_extra__ is None:
        response.__pydantic_extra__ = {}
    response.__pydantic_extra__["routed_provider"] = target.provider.name
    response.__pydantic_extra__["routed_inference_tier"] = target.routed_inference_tier
    return response


async def _write_embeddings_success(
    writer: RoutingLogWriter,
    *,
    embeddings_request: EmbeddingsRequest,
    target: ResolvedTarget,
    request_id: str,
    response: EmbeddingsResponse,
    latency_ms: int,
    config: GatewayConfig,
) -> None:
    """Write a routing-log row for a successful embeddings call.

    Embeddings have ``tokens_in`` (the prompt tokens) but no
    ``tokens_out`` — embeddings don't generate text. We leave
    ``tokens_out`` as None so the audit row is honest about the shape.

    Cost estimation reuses the same per-(provider, model) rates from
    ``cost_tracking.rates``; for embedding models the ``output_per_mtok``
    rate should be 0 (most providers don't charge for output on
    embeddings) — operators set this in ``gateway.yaml``.
    """

    cost = estimate_cost(
        provider_name=target.provider.name,
        native_model=target.native_model,
        usage=ChatCompletionUsage(
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=0,
            total_tokens=response.usage.total_tokens,
        ),
        rates=config.cost_tracking.rates,
    )
    await writer.write(
        InferenceRoutingLogRow(
            requested_model=embeddings_request.model,
            routed_provider=target.provider.name,
            routed_model=target.native_model,
            routed_inference_tier=target.routed_inference_tier,
            tokens_in=response.usage.prompt_tokens,
            tokens_out=None,
            cost_estimate=cost,
            latency_ms=latency_ms,
            request_id=request_id,
            purpose="embedding",
        )
    )


async def _write_embeddings_failure(
    writer: RoutingLogWriter,
    *,
    embeddings_request: EmbeddingsRequest,
    target: ResolvedTarget,
    request_id: str,
    error: ProviderAdapterError,
    latency_ms: int,
) -> None:
    """Write a routing-log row for an embeddings call that failed at upstream."""

    await writer.write(
        InferenceRoutingLogRow(
            requested_model=embeddings_request.model,
            routed_provider=target.provider.name,
            routed_model=target.native_model,
            routed_inference_tier=target.routed_inference_tier,
            latency_ms=latency_ms,
            refused=False,
            refusal_reason=f"upstream_error:{error.code}",
            request_id=request_id,
            purpose="embedding",
        )
    )


async def _write_embeddings_unavailable(
    writer: RoutingLogWriter,
    *,
    embeddings_request: EmbeddingsRequest,
    target: ResolvedTarget,
    request_id: str,
    message: str,
) -> None:
    """Write a routing-log row when embeddings had no adapter to dispatch to."""

    await writer.write(
        InferenceRoutingLogRow(
            requested_model=embeddings_request.model,
            routed_provider=target.provider.name,
            routed_model=target.native_model,
            routed_inference_tier=target.routed_inference_tier,
            refused=False,
            refusal_reason=f"adapter_unavailable:{message}",
            request_id=request_id,
            purpose="embedding",
        )
    )


async def _write_unresolved_embeddings(
    writer: RoutingLogWriter,
    *,
    embeddings_request: EmbeddingsRequest,
    request_id: str,
    message: str,
) -> None:
    """Write a routing-log row when the embeddings model didn't resolve."""

    await writer.write(
        InferenceRoutingLogRow(
            requested_model=embeddings_request.model,
            routed_provider="<unresolved>",
            routed_model="<unresolved>",
            routed_inference_tier=1,
            refused=True,
            refusal_reason=f"invalid_model:{message}",
            request_id=request_id,
            purpose="embedding",
        )
    )
