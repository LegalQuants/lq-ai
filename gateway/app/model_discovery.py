"""Live model discovery for ``GET /v1/models`` (D0).

The base ``GET /v1/models`` payload that A3/B4 ship is built from the
configured ``model_aliases`` only — six aliases out of
``gateway.yaml.example``. Lots of capability never reaches the picker:
operators with a real Anthropic key have access to every model in the
catalog (Opus, Sonnet, Haiku, …), and operators running Ollama locally
typically pull a handful of models that are completely invisible to the
backend.

D0 augments the endpoint to merge three sources:

1. **Configured aliases** (current behaviour).
2. **Ollama tags** — ``GET <ollama_url>/api/tags`` lists the models that
   are actually pulled on the operator's machine.
3. **Anthropic catalog** — ``GET <anthropic_url>/v1/models`` lists every
   model the operator's API key can address.

Discovery results are cached behind a small TTL so the picker doesn't hit
upstream every keystroke. The Anthropic catalog moves slowly so we cache
for 5 minutes; Ollama tags can change every time the operator runs
``ollama pull`` so we cache for 60s (matching the pattern C2's
:class:`~app.clients.backend.SkillCache` uses).

Failure posture
---------------

A discovery call is best-effort. If Ollama isn't running, or the operator's
Anthropic key is invalid, or the upstream is having a bad day, we log
``WARNING`` and return an empty list for that source. **Never raise** —
``/v1/models`` must keep working when half the providers are down.

Security posture
----------------

The discoverers call upstream APIs with the operator's credentials. We
never echo the key value, the response headers, or the raw error body
into log messages or response envelopes. Errors are logged at WARNING
with the *type* of the failure (a string like
``"upstream returned HTTP 401"``) — operator-actionable without leaking
secrets.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

import httpx

from app.config import GatewayConfig, ProviderConfig
from app.router import derive_routed_inference_tier
from app.secrets import ProviderKeyResolver

logger = logging.getLogger(__name__)

# --- Cache TTLs --------------------------------------------------------------
# These match the pattern used by SkillCache in app.clients.backend (C2).

OLLAMA_CACHE_TTL_SECONDS: Final[float] = 60.0
"""TTL for the Ollama tags cache. Operators run ``ollama pull`` ad-hoc;
60s is short enough that newly-pulled models surface quickly while still
buffering bursts of UI traffic."""

ANTHROPIC_CACHE_TTL_SECONDS: Final[float] = 300.0
"""TTL for the Anthropic catalog cache. The hosted catalog moves on the
order of weeks; 5 minutes is plenty fresh while keeping the cost of a
``GET /v1/models`` request load close to zero."""

DISCOVERY_TIMEOUT_SECONDS: Final[float] = 5.0
"""Per-upstream timeout. Discovery is on the picker's hot path; a slow
upstream must not block the response. We pin a tight value so a
misbehaving upstream surfaces as "not available right now" rather than
delaying the picker for tens of seconds."""

ANTHROPIC_API_VERSION: Final[str] = "2023-06-01"
"""Pinned ``anthropic-version`` header. Same value the AnthropicAdapter
uses; centralized here so D0 doesn't import the adapter just to read a
constant."""


# --- Public model entry shape -----------------------------------------------


@dataclass
class DiscoveredModel:
    """One entry in the merged ``GET /v1/models`` response.

    Extends the OpenAI-compatible ``{id, object, created, owned_by}``
    shape with a single LQ.AI extension: ``lq_ai_kind`` differentiates
    configured aliases from provider-native model names so the picker
    can group them sensibly. ``routed_inference_tier`` is also
    surfaced when known so the UI can render a tier badge without a
    second roundtrip.
    """

    id: str
    """Either an alias name (``smart``) or a ``provider/model`` form
    (``anthropic-prod/claude-haiku-4-5``, ``ollama-local/llama3.1:8b``)."""

    owned_by: str
    """For aliases: ``"lq-ai-gateway"``. For provider-native rows: the
    configured provider name (``"anthropic-prod"``, ``"ollama-local"``)."""

    lq_ai_kind: str
    """``"alias"`` for configured aliases; ``"provider_native"`` for live
    discoveries."""

    routed_inference_tier: int | None = None
    """Derived tier the request would land at if dispatched. ``None`` for
    aliases (the tier depends on which fallback step actually runs)."""

    provider_type: str | None = None
    """For provider-native rows: the configured ``ProviderType``
    (``anthropic``, ``ollama``, …). Lets the UI group rows under
    user-friendly section headers without re-deriving."""

    resolves_to: str | None = None
    """ADR 0011: for ``lq_ai_kind == "alias"`` entries, the
    ``<provider_name>/<model>`` form that the alias's primary target
    resolves to today. Surfaces in the picker so users see
    ``smart → anthropic-prod/claude-opus-4-7`` rather than an opaque
    ``smart`` label. ``None`` for provider-native rows (which already
    carry their concrete ``provider/model`` in ``id``)."""

    fallback_count: int = 0
    """For aliases: how many entries are in the fallback chain after
    the primary. Lets the picker show ``(+2 fallbacks)`` without
    sending the full chain on every model-list request. ``0`` for
    provider-native rows."""

    created: int = 0
    """OpenAI-compatible field; we always emit ``0`` (the gateway has no
    provider-relative creation timestamp). Present for client
    compatibility, not as a real value."""

    def to_payload(self) -> dict[str, object]:
        """Serialize for the merged ``/v1/models`` response."""

        out: dict[str, object] = {
            "id": self.id,
            "object": "model",
            "created": self.created,
            "owned_by": self.owned_by,
            "lq_ai_kind": self.lq_ai_kind,
        }
        if self.routed_inference_tier is not None:
            out["routed_inference_tier"] = self.routed_inference_tier
        if self.provider_type is not None:
            out["provider_type"] = self.provider_type
        if self.resolves_to is not None:
            out["lq_ai_resolves_to"] = self.resolves_to
        if self.fallback_count > 0:
            out["lq_ai_fallback_count"] = self.fallback_count
        return out


# --- TTL cache --------------------------------------------------------------


@dataclass
class _CacheEntry:
    models: list[DiscoveredModel]
    fetched_at: float


class _DiscoveryCache:
    """Process-local TTL cache for discovery results.

    Keyed by ``(source, provider_name)`` so two providers of the same
    type (a prod and a staging Anthropic key, say) cache independently.
    The cache uses the monotonic clock so wall-clock adjustments don't
    invalidate entries spuriously; tests inject a fake clock.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._clock: Callable[[], float] = clock if clock is not None else time.monotonic
        self._entries: dict[tuple[str, str], _CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(
        self,
        *,
        source: str,
        provider_name: str,
        ttl_seconds: float,
    ) -> list[DiscoveredModel] | None:
        async with self._lock:
            entry = self._entries.get((source, provider_name))
            if entry is None:
                return None
            if self._clock() - entry.fetched_at > ttl_seconds:
                del self._entries[(source, provider_name)]
                return None
            # Return a defensive copy so caller mutations don't poison the cache.
            return list(entry.models)

    async def put(
        self,
        *,
        source: str,
        provider_name: str,
        models: list[DiscoveredModel],
    ) -> None:
        async with self._lock:
            self._entries[(source, provider_name)] = _CacheEntry(
                models=list(models),
                fetched_at=self._clock(),
            )

    async def clear(self) -> None:
        async with self._lock:
            self._entries.clear()


# --- Discoverer --------------------------------------------------------------


@dataclass
class ModelDiscoverer:
    """Live-discovery layer behind ``/v1/models`` (D0).

    Holds a cache + a single shared :class:`httpx.AsyncClient` so
    discovery RPCs reuse one connection pool. The lifespan handler
    constructs one of these and stashes it on ``app.state.model_discoverer``;
    tests can pass an alternate ``client`` (typically respx-mocked).

    Construction is intentionally not config-aware: the discoverer takes
    the config + provider list per call so a future ``POST /admin/v1/config/reload``
    can re-run discovery against the new config without rebuilding the
    discoverer itself.
    """

    cache: _DiscoveryCache = field(default_factory=_DiscoveryCache)
    client: httpx.AsyncClient | None = None
    timeout_seconds: float = DISCOVERY_TIMEOUT_SECONDS
    env: dict[str, str] | None = None
    """Override for environment lookups (used by tests). Defaults to
    :data:`os.environ` when ``None``."""

    key_resolver: ProviderKeyResolver | None = None
    """ADR 0011: when set, used to resolve provider keys (handles both
    ``api_key_env`` and ``api_key_encrypted`` paths). When ``None``, a
    default resolver is built lazily from :data:`os.environ` so existing
    tests that only override ``env`` keep working unchanged."""

    _owns_client: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=self.timeout_seconds)
            self._owns_client = True

    async def aclose(self) -> None:
        if self._owns_client and self.client is not None:
            await self.client.aclose()

    def _env(self) -> dict[str, str]:
        return self.env if self.env is not None else dict(os.environ)

    def _resolver(self) -> ProviderKeyResolver:
        """Lazy-build the key resolver from this discoverer's env override."""
        if self.key_resolver is not None:
            return self.key_resolver
        env = self._env()
        return ProviderKeyResolver(master_key=env.get("LQ_AI_GATEWAY_MASTER_KEY") or None, env=env)

    # --- Per-source discovery -------------------------------------------------

    async def discover_ollama(self, provider: ProviderConfig) -> list[DiscoveredModel]:
        """Call ``GET <base_url>/api/tags``; surface each tag as one entry.

        Results cache for :data:`OLLAMA_CACHE_TTL_SECONDS`. On any
        upstream failure (network, non-200), we log WARNING and return
        ``[]`` — the merged endpoint surfaces whatever other sources
        produced.
        """

        cached = await self.cache.get(
            source="ollama",
            provider_name=provider.name,
            ttl_seconds=OLLAMA_CACHE_TTL_SECONDS,
        )
        if cached is not None:
            return cached

        models = await self._fetch_ollama_uncached(provider)
        await self.cache.put(source="ollama", provider_name=provider.name, models=models)
        return models

    async def _fetch_ollama_uncached(
        self,
        provider: ProviderConfig,
    ) -> list[DiscoveredModel]:
        if self.client is None:  # pragma: no cover - __post_init__ ensures
            return []
        base_url = (provider.base_url or "").rstrip("/")
        if not base_url:
            return []
        try:
            response = await self.client.get(
                f"{base_url}/api/tags",
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "ollama discovery failed for provider %r: %s",
                provider.name,
                type(exc).__name__,
            )
            return []
        if response.status_code != 200:
            logger.warning(
                "ollama discovery for provider %r returned HTTP %d",
                provider.name,
                response.status_code,
            )
            return []
        try:
            payload = response.json()
        except ValueError:
            logger.warning(
                "ollama discovery for provider %r returned non-JSON body",
                provider.name,
            )
            return []
        models_raw = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models_raw, list):
            return []
        out: list[DiscoveredModel] = []
        for entry in models_raw:
            if not isinstance(entry, dict):
                continue
            tag = entry.get("name")
            if not isinstance(tag, str) or not tag:
                continue
            out.append(
                DiscoveredModel(
                    id=f"{provider.name}/{tag}",
                    owned_by=provider.name,
                    lq_ai_kind="provider_native",
                    provider_type=provider.type,
                )
            )
        return out

    async def discover_anthropic(self, provider: ProviderConfig) -> list[DiscoveredModel]:
        """Call ``GET <base_url>/v1/models``; surface each model id as one entry.

        Anthropic's catalog endpoint takes the same ``x-api-key`` and
        ``anthropic-version`` headers as Messages. We never log the key
        value or the response body (which can include catalog metadata
        we'd rather not relay through gateway logs); only the upstream
        status / exception type lands in the WARNING line on failure.
        """

        cached = await self.cache.get(
            source="anthropic",
            provider_name=provider.name,
            ttl_seconds=ANTHROPIC_CACHE_TTL_SECONDS,
        )
        if cached is not None:
            return cached

        models = await self._fetch_anthropic_uncached(provider)
        await self.cache.put(source="anthropic", provider_name=provider.name, models=models)
        return models

    async def _fetch_anthropic_uncached(
        self,
        provider: ProviderConfig,
    ) -> list[DiscoveredModel]:
        if self.client is None:  # pragma: no cover - __post_init__ ensures
            return []
        # ADR 0011: resolve via ProviderKeyResolver so api_key_encrypted
        # works the same as api_key_env. Default env-name when neither
        # source is set on the provider entry.
        effective_env = provider.api_key_env or (
            None if provider.api_key_encrypted else "ANTHROPIC_API_KEY"
        )
        try:
            api_key = self._resolver().resolve(
                provider_name=provider.name,
                api_key_env=effective_env,
                api_key_encrypted=provider.api_key_encrypted,
            )
        except Exception as exc:
            # Decryption / master-key errors are operator-actionable but
            # must not break /v1/models. Log and treat as "no key".
            logger.warning(
                "anthropic discovery key-resolution failed for provider %r: %s",
                provider.name,
                type(exc).__name__,
            )
            return []
        if not api_key:
            logger.info(
                "anthropic discovery skipped for provider %r: no key configured",
                provider.name,
            )
            return []
        base_url = (provider.base_url or "").rstrip("/")
        if not base_url:
            return []
        try:
            response = await self.client.get(
                f"{base_url}/v1/models",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": ANTHROPIC_API_VERSION,
                },
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "anthropic discovery failed for provider %r: %s",
                provider.name,
                type(exc).__name__,
            )
            return []
        if response.status_code != 200:
            # Don't echo the body — it may carry catalog metadata or
            # operator-account hints. Status alone is enough to act on.
            logger.warning(
                "anthropic discovery for provider %r returned HTTP %d",
                provider.name,
                response.status_code,
            )
            return []
        try:
            payload = response.json()
        except ValueError:
            logger.warning(
                "anthropic discovery for provider %r returned non-JSON body",
                provider.name,
            )
            return []
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return []
        out: list[DiscoveredModel] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            model_id = entry.get("id")
            if not isinstance(model_id, str) or not model_id:
                continue
            out.append(
                DiscoveredModel(
                    id=f"{provider.name}/{model_id}",
                    owned_by=provider.name,
                    lq_ai_kind="provider_native",
                    provider_type=provider.type,
                )
            )
        return out

    async def discover_openai(self, provider: ProviderConfig) -> list[DiscoveredModel]:
        """Call ``GET <base_url>/models``; surface each model id as one entry.

        OpenAI's catalog endpoint takes the same ``Authorization: Bearer``
        header as chat completions. Like the Anthropic discoverer we
        never log the key value or the response body. Cached for the
        same TTL as Anthropic — OpenAI's public catalog moves on the
        order of weeks too.

        Provider-type ``openai_compatible`` (vLLM, llama-cpp servers) is
        also supported here: the catalog endpoint is the same shape and
        most local servers expose it. Local servers without a key are
        called with no Authorization header, matching the OpenAIAdapter
        behavior. An entry that names a key source which does not resolve
        is skipped, also matching the adapter: it has no live adapter, so
        its catalog must not be offered (or the service contacted keyless).
        """

        cached = await self.cache.get(
            source="openai",
            provider_name=provider.name,
            ttl_seconds=ANTHROPIC_CACHE_TTL_SECONDS,
        )
        if cached is not None:
            return cached

        models = await self._fetch_openai_uncached(provider)
        await self.cache.put(source="openai", provider_name=provider.name, models=models)
        return models

    async def _fetch_openai_uncached(
        self,
        provider: ProviderConfig,
    ) -> list[DiscoveredModel]:
        if self.client is None:  # pragma: no cover - __post_init__ ensures
            return []
        # OpenAI's default env name is OPENAI_API_KEY but openai_compatible
        # local servers may legitimately have no key.
        effective_env = provider.api_key_env or (
            None
            if (provider.api_key_encrypted or provider.type == "openai_compatible")
            else "OPENAI_API_KEY"
        )
        try:
            api_key = self._resolver().resolve(
                provider_name=provider.name,
                api_key_env=effective_env,
                api_key_encrypted=provider.api_key_encrypted,
            )
        except Exception as exc:
            logger.warning(
                "openai discovery key-resolution failed for provider %r: %s",
                provider.name,
                type(exc).__name__,
            )
            return []
        key_declared = bool(provider.api_key_env or provider.api_key_encrypted)
        if not api_key and (provider.type == "openai" or key_declared):
            logger.info(
                "openai discovery skipped for provider %r: no key configured",
                provider.name,
            )
            return []
        base_url = (provider.base_url or "").rstrip("/")
        if not base_url:
            return []
        headers: dict[str, str] = {}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        try:
            response = await self.client.get(
                f"{base_url}/models",
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "openai discovery failed for provider %r: %s",
                provider.name,
                type(exc).__name__,
            )
            return []
        if response.status_code != 200:
            logger.warning(
                "openai discovery for provider %r returned HTTP %d",
                provider.name,
                response.status_code,
            )
            return []
        try:
            payload = response.json()
        except ValueError:
            logger.warning(
                "openai discovery for provider %r returned non-JSON body",
                provider.name,
            )
            return []
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return []
        out: list[DiscoveredModel] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            model_id = entry.get("id")
            if not isinstance(model_id, str) or not model_id:
                continue
            out.append(
                DiscoveredModel(
                    id=f"{provider.name}/{model_id}",
                    owned_by=provider.name,
                    lq_ai_kind="provider_native",
                    provider_type=provider.type,
                )
            )
        return out

    # --- Aggregator -----------------------------------------------------------

    async def list_all(self, config: GatewayConfig) -> list[DiscoveredModel]:
        """Return aliases + every reachable provider-native model.

        Called by ``GET /v1/models``. Discovery RPCs run concurrently
        (one per provider per source) so the slowest upstream only gates
        the response, not the sum. Each per-provider call is wrapped in
        the same "log + return []" envelope so one failed source can't
        abort the merge.

        Tier annotation is computed for provider-native rows by
        :func:`derive_routed_inference_tier` so the picker can render
        a tier badge without a second round-trip. For aliases the tier
        is left ``None`` (the alias may resolve to different providers
        through fallback; the picker shows tier on the response after
        the first dispatch).
        """

        out: list[DiscoveredModel] = []

        # 1. Configured aliases.
        # D0.5 fix: aliases resolve to a specific (provider, model)
        # pair at config-load time, so the tier IS knowable. D0
        # accidentally left this off (it only stamped the tier on
        # ``provider_native`` rows); the picker therefore couldn't
        # render a tier badge for the alias options. Compute the
        # primary-target tier per alias here so the UI surface is
        # consistent.
        for alias_name, alias in config.model_aliases.items():
            primary_provider = config.provider_by_name(alias.primary.provider)
            tier: int | None = None
            if primary_provider is not None and alias.primary.model:
                # Walk a single level: if the alias's primary.model is
                # itself another alias (multi-level chains), the
                # config-load validator already proved the chain
                # terminates. We don't recurse here because the
                # listing is best-effort metadata, not the dispatch
                # path; a one-level lookup is the right precision
                # for a UI badge.
                tier = derive_routed_inference_tier(
                    provider=primary_provider,
                    native_model=alias.primary.model,
                    inference_tiers=config.inference_tiers,
                )
            # ADR 0011: surface the alias's resolved primary target so
            # the picker can render "smart → anthropic-prod/claude-opus-4-7"
            # rather than an opaque label. Aliases stay convenience
            # *and* visible — "honest defaults," not opacity.
            resolves_to: str | None = None
            if alias.primary.provider and alias.primary.model:
                resolves_to = f"{alias.primary.provider}/{alias.primary.model}"
            out.append(
                DiscoveredModel(
                    id=alias_name,
                    owned_by="lq-ai-gateway",
                    lq_ai_kind="alias",
                    routed_inference_tier=tier,
                    resolves_to=resolves_to,
                    fallback_count=len(alias.fallback),
                )
            )

        # 2. Live discovery — one task per (provider, source) pair.
        tasks: list[asyncio.Task[list[DiscoveredModel]]] = []
        annotators: list[ProviderConfig] = []
        for provider in config.providers:
            if not provider.enabled:
                continue
            if provider.type == "ollama":
                tasks.append(asyncio.create_task(self.discover_ollama(provider)))
                annotators.append(provider)
            elif provider.type == "anthropic":
                tasks.append(asyncio.create_task(self.discover_anthropic(provider)))
                annotators.append(provider)
            elif provider.type in ("openai", "openai_compatible"):
                # ADR 0011 wave-3: discover OpenAI / OpenAI-compatible
                # catalogs so the picker can show real model ids
                # (gpt-4o, gpt-4o-mini, …) as direct-selection
                # options alongside aliases.
                tasks.append(asyncio.create_task(self.discover_openai(provider)))
                annotators.append(provider)
            # Vertex / Bedrock discovery still deferred — both have
            # provider-specific catalog APIs (boto3 list_foundation_models,
            # GCP discovery client) that would pull large dependency
            # surfaces. Operators wanting Vertex/Bedrock-native model
            # names address them via aliases until those discoverers
            # land.

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for provider, result in zip(annotators, results, strict=True):
                if isinstance(result, BaseException):
                    # Defense-in-depth: per-method handlers catch their
                    # own httpx errors, but a stray exception (e.g., a
                    # bug we haven't anticipated) must not break the
                    # merge.
                    logger.warning(
                        "discovery for provider %r raised %s",
                        provider.name,
                        type(result).__name__,
                    )
                    continue
                # Annotate each row with its derived tier so the picker
                # can render a badge without re-deriving client-side.
                for row in result:
                    native_model = row.id.split("/", 1)[1] if "/" in row.id else row.id
                    row.routed_inference_tier = derive_routed_inference_tier(
                        provider=provider,
                        native_model=native_model,
                        inference_tiers=config.inference_tiers,
                    )
                    out.append(row)

        return out


__all__ = [
    "ANTHROPIC_CACHE_TTL_SECONDS",
    "DISCOVERY_TIMEOUT_SECONDS",
    "OLLAMA_CACHE_TTL_SECONDS",
    "DiscoveredModel",
    "ModelDiscoverer",
]
