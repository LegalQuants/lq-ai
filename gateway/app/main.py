"""LQ.AI Inference Gateway entrypoint.

The gateway loads ``gateway.yaml`` on startup, validates it via Pydantic,
and instantiates a :class:`~app.providers.ProviderAdapter` for every
configured provider whose credentials are present. A3 landed config
loading; B3 added the Anthropic adapter and the chat-completion data
path; B4 added the real router (alias resolution + tier derivation +
fallback skeleton) and the ``inference_routing_log`` writer.

If the config is missing or malformed the lifespan raises
:class:`~app.config_loader.ConfigLoadError` and the process exits
non-zero — the gateway is the security boundary, and silently coming
up with an empty config would mask operator misconfiguration. Adapter
construction failures (missing env vars) are *not* fatal; the affected
providers are skipped with a warning so the gateway still serves the
endpoints that don't need them. Likewise the ``DATABASE_URL`` is
optional — without it the gateway runs in ``NullRoutingLogWriter`` mode
(audit rows discarded). Operators see a startup warning so the gap is
visible.

Endpoint posture (current):

* ``GET  /health``                — 200 (liveness; independent of config).
* ``GET  /ready``                 — 200 once config has loaded; 503 otherwise.
* ``POST /v1/chat/completions``   — routes through :class:`app.router.Router`.
* ``POST /v1/embeddings``         — 501 (lands with B6 OpenAI adapter).
* ``GET  /v1/models``             — returns configured aliases.
* ``GET  /admin/v1/tier-config``  — returns loaded tier policy.
* Other ``/admin/v1/*`` endpoints — 501.

Configuration path resolution
-----------------------------

The lifespan reads the path from ``GATEWAY_CONFIG_PATH``. Defaults:

* If ``GATEWAY_CONFIG_PATH`` is set, use it (typical in containers; e.g.,
  ``/etc/gateway.yaml`` mounted from the operator's file).
* Otherwise fall back to ``./gateway.yaml`` relative to the process cwd
  (the repo-root file used during local ``uvicorn app.main:app`` runs).
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app import __version__
from app.anonymization.engine import Anonymizer
from app.api import admin_router, inference_router
from app.clients.backend import (
    BackendClient,
    close_backend_client,
    configure_backend_client,
)
from app.config import GatewayConfig
from app.config_holder import MutableConfigHolder, install_sighup_reload
from app.config_loader import ConfigLoadError, load_config
from app.db import engine_or_none
from app.errors import LQAIError
from app.model_discovery import ModelDiscoverer
from app.providers import (
    AnthropicAdapter,
    AzureOpenAIAdapter,
    OllamaAdapter,
    OpenAIAdapter,
    ProviderAdapter,
)
from app.router import Router
from app.routing_log import NullRoutingLogWriter, RoutingLogWriter, SQLRoutingLogWriter

logger = logging.getLogger(__name__)

SERVICE_NAME = "lq-ai-gateway"

DEFAULT_CONFIG_PATH = Path("gateway.yaml")
"""Default path the gateway looks for its config when ``GATEWAY_CONFIG_PATH``
is unset. Resolved relative to the process cwd."""


def _resolve_config_path() -> Path:
    """Return the effective config path for this process."""

    override = os.environ.get("GATEWAY_CONFIG_PATH")
    if override:
        return Path(override)
    return DEFAULT_CONFIG_PATH


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load and validate ``gateway.yaml`` on startup.

    On success: stash the parsed :class:`GatewayConfig` on ``app.state.config``
    and serve. On failure: log and re-raise — uvicorn exits non-zero.
    """

    config_path = _resolve_config_path()
    logger.info("loading gateway config from %s", config_path)
    try:
        config = load_config(config_path)
    except ConfigLoadError:
        logger.exception("gateway config load failed; refusing to start")
        raise

    # D0.5: wrap the loaded config in a mutable holder so admin endpoints
    # can hot-reload after writing the YAML file. The router and admin
    # handlers read through the holder; in-flight requests hold their
    # own snapshot via :meth:`MutableConfigHolder.current`.
    config_holder = MutableConfigHolder(config, config_path=config_path)
    app.state.config_holder = config_holder
    # Backwards-compat: the existing routes read ``app.state.config``
    # for the *initial* snapshot. Per-request handlers that need the
    # live snapshot read through ``app.state.config_holder.current()``.
    app.state.config = config
    install_sighup_reload(config_holder)
    logger.info(
        "gateway config loaded: %d providers, %d aliases",
        len(config.providers),
        len(config.model_aliases),
    )

    # B3: instantiate adapters for any provider whose credentials are
    # actually present. Adapters with missing env vars are skipped (with
    # a warning, not a fatal error) so the gateway still serves /health,
    # /ready, /v1/models, and the configured providers that are usable.
    # The chat-completions handler returns a structured 503 if a request
    # routes to a provider with no adapter.
    adapters: dict[str, ProviderAdapter] = {}
    for provider in config.providers:
        if not provider.enabled:
            continue
        if provider.type == "anthropic":
            try:
                adapters[provider.name] = AnthropicAdapter.from_config(provider)
                logger.info("instantiated Anthropic adapter for provider %r", provider.name)
            except ValueError as exc:
                logger.warning(
                    "skipping Anthropic provider %r: %s",
                    provider.name,
                    exc,
                )
            continue
        if provider.type in ("openai", "openai_compatible"):
            # C6 + B6: OpenAI adapter services both embeddings and chat
            # completions. The lifespan-time check matches the pattern
            # for Anthropic: a missing key for cloud OpenAI is non-fatal
            # at startup but produces a clean 503 at request time.
            try:
                adapters[provider.name] = OpenAIAdapter.from_config(provider)
                logger.info(
                    "instantiated OpenAI adapter for provider %r (type=%s)",
                    provider.name,
                    provider.type,
                )
            except ValueError as exc:
                logger.warning(
                    "skipping OpenAI provider %r: %s",
                    provider.name,
                    exc,
                )
            continue
        if provider.type == "azure_openai":
            # M2-E1 (DE-267): Azure OpenAI mirrors the OpenAI wire shape
            # with a different URL (deployment-scoped + api-version)
            # and ``api-key`` auth. Missing key or missing api_version
            # surfaces as a startup warning (skip provider) and a clean
            # 503 at request time, matching OpenAI's lifespan posture.
            try:
                adapters[provider.name] = AzureOpenAIAdapter.from_config(provider)
                logger.info(
                    "instantiated Azure OpenAI adapter for provider %r",
                    provider.name,
                )
            except ValueError as exc:
                logger.warning(
                    "skipping Azure OpenAI provider %r: %s",
                    provider.name,
                    exc,
                )
            continue
        if provider.type == "ollama":
            # B6 partial: Ollama is the Mode-2 (air-gapped local
            # inference) backbone per PRD §1.5.1 / §6.1. Chat
            # completions are wired here; embeddings raise
            # ProviderUnsupportedError (the embedding alias still routes
            # through the OpenAI adapter per ADR 0008).
            try:
                adapters[provider.name] = OllamaAdapter.from_config(provider)
                logger.info(
                    "instantiated Ollama adapter for provider %r (base_url=%s)",
                    provider.name,
                    provider.base_url,
                )
            except ValueError as exc:
                logger.warning(
                    "skipping Ollama provider %r: %s",
                    provider.name,
                    exc,
                )
            continue
        # B6 lands the remaining adapters (Vertex, Bedrock).
        logger.debug(
            "no adapter for provider %r (type=%s); awaiting B6",
            provider.name,
            provider.type,
        )
    app.state.adapters = adapters

    # B4: build the request router around the loaded config + adapter
    # registry. Per-request handlers pull this off ``app.state.router``
    # rather than reconstructing it on every call.
    # D0.5: pass the holder's ``current`` so the router reads the live
    # config snapshot on each call. After an admin alias edit lands,
    # the very next request resolves against the new map without
    # restart.
    app.state.router = Router(
        config=config,
        adapters=adapters,
        config_provider=config_holder.current,
    )

    # B4: wire the inference_routing_log writer. ``DATABASE_URL`` is
    # optional — without it the gateway falls back to a no-op writer
    # so the data path keeps working in degraded deployments. The
    # warning makes the gap operator-visible.
    engine = engine_or_none()
    routing_log: RoutingLogWriter
    if engine is None:
        logger.warning(
            "DATABASE_URL is not set; inference_routing_log writes are disabled "
            "(routing still works, but no audit rows are persisted)"
        )
        routing_log = NullRoutingLogWriter()
    else:
        routing_log = SQLRoutingLogWriter(engine)
        logger.info("inference_routing_log writer wired against DATABASE_URL")
    app.state.routing_log = routing_log
    app.state.db_engine = engine  # held so shutdown can dispose

    # C2: backend HTTP client + skill cache. The client reads
    # LQ_AI_API_URL / LQ_AI_GATEWAY_KEY / LQ_AI_SKILL_CACHE_TTL_SECONDS
    # from the environment. The skill assembler in
    # ``app.api.inference`` uses ``app.state.backend_client`` if set,
    # otherwise falls back to the process-global handle. We stash both
    # so tests bypassing lifespan still get a usable handle.
    backend_client: BackendClient = configure_backend_client()
    app.state.backend_client = backend_client
    logger.info("backend client wired against %s", backend_client.base_url)

    # D0: live model discovery for ``GET /v1/models``. The discoverer
    # owns its own httpx client and a TTL cache. Per-source failures
    # never raise — see app.model_discovery.
    model_discoverer = ModelDiscoverer()
    app.state.model_discoverer = model_discoverer
    logger.info("model discoverer wired (Ollama 60s TTL, Anthropic 300s TTL)")

    # M2-B3: anonymization middleware façade. The Anonymizer is
    # lightweight — instance state is just an analyzer reference —
    # and the spaCy load is deferred to first use, so this is a
    # no-cost startup hook even when the config disables the feature.
    # Tests override ``app.state.anonymizer`` to inject a stub analyzer
    # without touching the singleton.
    app.state.anonymizer = Anonymizer()
    logger.info("anonymization middleware wired (lazy analyzer load)")

    try:
        yield
    finally:
        logger.info("gateway shutting down; closing %d adapters", len(adapters))
        for name, adapter in adapters.items():
            try:
                await adapter.aclose()
            except Exception:
                logger.exception("error closing adapter %r", name)
        try:
            await close_backend_client()
        except Exception:
            logger.exception("error closing backend client")
        try:
            await model_discoverer.aclose()
        except Exception:
            logger.exception("error closing model discoverer")
        if engine is not None:
            try:
                await engine.dispose()
            except Exception:
                logger.exception("error disposing DB engine")


app = FastAPI(
    title="LQ.AI Inference Gateway",
    version=__version__,
    description=(
        "OpenAI-compatible inference gateway and security boundary for the "
        "LQ.AI platform. The gateway annotates every routed request with "
        "its derived Inference Tier (1-5) per PRD §3.13 / §1.5.2 and refuses "
        "requests below a declared minimum. M1 implementation lands progressively "
        "per docs/M1-IMPLEMENTATION-ORDER.md; A3 ships the scaffold (config "
        "loading + 501 stubs); B3/B4 land real routing."
    ),
    lifespan=lifespan,
)

app.include_router(inference_router)
app.include_router(admin_router)

# M-Obs.1 — Prometheus /metrics + OpenTelemetry (PRD §5.4). OTel is
# off unless OTEL_EXPORTER_OTLP_ENDPOINT is set; that's the "no
# telemetry by default" guarantee in PRD §5.7. Wired AFTER the routers
# are included so FastAPIInstrumentor walks the full route tree.
from app.observability import install_observability  # noqa: E402

install_observability(app, service_name=SERVICE_NAME, service_version=__version__)


@app.exception_handler(LQAIError)
async def _lqai_error_handler(_request: Request, exc: LQAIError) -> JSONResponse:
    """Translate :class:`LQAIError` to the canonical ``GatewayError`` envelope.

    Renders ``{"error": {"code": ..., "message": ..., "details": ...}}``
    with the exception's effective HTTP status, matching the
    ``GatewayError`` schema in ``docs/api/gateway-openapi.yaml`` and the
    decision in :doc:`docs/adr/0003-error-handling.md`.
    """

    return JSONResponse(
        status_code=exc.effective_http_status,
        content=exc.to_envelope(),
    )


def _config_loaded(app: FastAPI) -> GatewayConfig | None:
    """Return the loaded config if startup succeeded, else ``None``.

    During the small window before lifespan completes (or if startup raised),
    ``app.state.config`` is unset. ``/ready`` uses this to differentiate
    "loaded" from "not yet loaded".
    """

    return getattr(app.state, "config", None)


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness probe — returns 200 as soon as the process is serving requests.

    Per K8s liveness convention: this answers "is the process alive?" and is
    independent of whether the gateway config has loaded. Used by docker
    healthchecks and orchestration platforms.
    """

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "alive",
            "service": SERVICE_NAME,
            "version": __version__,
        },
    )


@app.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness probe — 200 once gateway config is loaded; 503 otherwise.

    Per K8s readiness convention: returns 503 until A3's config load
    completes. (If the config fails to load, the process exits — there is no
    "config failed but server still up" state in A3.)

    Reads config from ``request.app.state`` (not the module-level ``app``)
    so the endpoint is testable when mounted on a fresh ``FastAPI`` instance.

    Provider-reachability checks are layered on top of this in B3+; a future
    revision may downgrade to 503 if every configured provider is failing.
    """

    config = _config_loaded(request.app)
    if config is None:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "not_ready",
                "service": SERVICE_NAME,
                "version": __version__,
                "reason": "config_not_loaded",
            },
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "ready",
            "service": SERVICE_NAME,
            "version": __version__,
            "providers": len(config.providers),
            "aliases": len(config.model_aliases),
        },
    )
