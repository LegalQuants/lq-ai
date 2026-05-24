"""Gateway request router (B4).

The router is the single choke point through which every chat-completion
request flows. It pulls together the four B4 responsibilities:

1. **Alias resolution** — translate the request's ``model`` field through
   ``gateway.yaml``'s ``model_aliases`` map. Multi-level aliases are
   supported (an alias whose ``primary.model`` is itself another alias);
   cycles are rejected at config-load time by
   :func:`app.config.GatewayConfig._aliases_have_no_cycles`.

2. **Tier derivation** — annotate every routed request with its
   ``routed_inference_tier`` (1-5) per PRD §1.5.2 / §3.13. Lookup order:
   ``inference_tiers.overrides[provider/model]`` →
   ``inference_tiers.overrides[provider]`` →
   ``inference_tiers.defaults[provider_type]`` → the provider entry's
   own ``tier:`` field.

3. **Adapter dispatch** — hand the resolved (provider, native model) pair
   to the right :class:`~app.providers.ProviderAdapter`. Adapters live in
   a name-keyed registry (``app.state.adapters``). New adapters in B6
   register without modifying the dispatch logic.

4. **Fallback chain** — when the primary provider fails (timeout,
   network, or 5xx upstream), iterate through the alias's configured
   ``fallback`` list and try the next adapter. The skeleton is in place
   in B4; real activation happens in B6 once additional adapters land
   (only Anthropic is shipped today). Unit tests with mocked adapters
   exercise the fallback path so the structure is verified now.

What B4 *does not* do
---------------------

* **Tier-floor enforcement / refusal.** Per PRD §4.4 / D1 the gateway
  refuses requests below a declared minimum with HTTP 403 and
  ``tier_below_minimum``. B4 only annotates; D1 is the refusal task.
  The error code is reserved in ``docs/api/gateway-openapi.yaml``.
* **Anonymization.** M2 feature; flagged in the data model but not
  applied here.
* **Rate limiting.** Phase E task; the configuration loads but the
  enforcement middleware lands later.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from app.config import (
    MAX_ALIAS_DEPTH,
    CostRateEntry,
    GatewayConfig,
    InferenceTiersConfig,
    ProviderConfig,
)
from app.observability import INFERENCE_REQUESTS_TOTAL
from app.providers import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
    ProviderAdapter,
    ProviderAdapterError,
    ProviderHTTPError,
    ProviderNetworkError,
)

logger = logging.getLogger(__name__)


def outcome_label_from_error(exc: ProviderAdapterError) -> str:
    """Pick a stable outcome label for the inference-dispatch metric.

    Keeps cardinality bounded — three buckets cover the operator
    questions the metric answers: "did the provider service the call",
    "did it fail at the network layer", "did it return a non-success
    HTTP status".
    """

    if isinstance(exc, ProviderNetworkError):
        return "network_error"
    if isinstance(exc, ProviderHTTPError):
        return "provider_error"
    return "provider_error"


def _record_inference_outcome(*, target: ResolvedTarget, outcome: str) -> None:
    """Increment the inference-dispatch counter for one routed request.

    Called from the dispatch loop on both success and error paths. The
    ``target`` is the candidate the router actually tried (primary or
    fallback); ``outcome`` is one of the four stable label values
    documented on :data:`INFERENCE_REQUESTS_TOTAL`.
    """

    INFERENCE_REQUESTS_TOTAL.labels(
        provider=target.provider.name,
        tier=str(target.routed_inference_tier),
        outcome=outcome,
    ).inc()


# --- Exceptions ---------------------------------------------------------------


class ModelResolutionError(Exception):
    """The request's ``model`` field doesn't resolve to any known target.

    Translated to a ``GatewayError`` with ``code = "invalid_model"`` and
    HTTP 400 by the route handler. Distinct from ``ProviderAdapterError``
    because it's a *gateway* problem, not an upstream one.
    """


class NoAdapterAvailableError(Exception):
    """Every candidate provider (primary + fallback) lacked an adapter.

    Common cause: the configured ``api_key_env`` for each candidate is
    unset, so adapter construction was skipped at startup. Translated to
    a ``GatewayError`` with ``code = "provider_unavailable"`` and HTTP 503.
    Carries the most-recent ``ProviderAdapterError`` (if any) for context.
    """

    def __init__(self, message: str, *, last_error: ProviderAdapterError | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.last_error = last_error


# --- Resolution data --------------------------------------------------------


@dataclass(frozen=True)
class ResolvedTarget:
    """One concrete (provider, native model) the router will try.

    The router builds an ordered list — primary first, then fallback in
    declaration order — and walks it until one adapter succeeds or all
    have failed.
    """

    provider: ProviderConfig
    """The configured provider entry that will handle the request."""

    native_model: str
    """The provider-native model string (alias resolution complete)."""

    routed_inference_tier: int
    """The derived tier (1-5) for this (provider, model) pair."""

    role: str
    """``"primary"`` or ``"fallback"`` — used for telemetry / logging."""


class RoutedProviderError(Exception):
    """Wraps a :class:`ProviderAdapterError` with the target that raised it.

    The route handler unwraps this so the ``inference_routing_log`` row
    can attribute the failure to the actual upstream that produced the
    error — not to the last candidate in the fallback chain (which may
    not have been attempted at all because its adapter wasn't
    instantiated).

    Carrying the target out of the router decouples the handler from
    the candidate-list bookkeeping: the router knows which adapter
    produced the error, the handler doesn't have to guess.
    """

    def __init__(
        self,
        *,
        target: ResolvedTarget,
        error: ProviderAdapterError,
        latency_ms: int,
        fallbacks_tried: list[str],
    ) -> None:
        super().__init__(error.message)
        self.target = target
        self.error = error
        self.latency_ms = latency_ms
        self.fallbacks_tried = fallbacks_tried


# --- Tier derivation ---------------------------------------------------------


def derive_routed_inference_tier(
    *,
    provider: ProviderConfig,
    native_model: str,
    inference_tiers: InferenceTiersConfig,
) -> int:
    """Derive the Inference Tier (1-5) for a resolved (provider, model) pair.

    Resolution order, first match wins:

    1. ``inference_tiers.overrides["<provider_name>/<native_model>"]`` —
       most specific.
    2. ``inference_tiers.overrides["<provider_name>"]`` — provider-wide
       override.
    3. ``inference_tiers.defaults["<provider_type>"]`` — per-type default
       (anthropic, openai, vertex, ...).
    4. ``provider.tier`` — the simple posture documented in
       ``gateway.yaml.example``.

    The Pydantic schema constrains every tier value to ``{1..5}``, so the
    return is always a valid tier integer.
    """

    pair_key = f"{provider.name}/{native_model}"
    if pair_key in inference_tiers.overrides:
        return int(inference_tiers.overrides[pair_key])
    if provider.name in inference_tiers.overrides:
        return int(inference_tiers.overrides[provider.name])
    if provider.type in inference_tiers.defaults:
        return int(inference_tiers.defaults[provider.type])
    return int(provider.tier)


# --- Alias resolution -------------------------------------------------------


def resolve_alias_chain(
    *,
    requested_model: str,
    config: GatewayConfig,
) -> list[ResolvedTarget]:
    """Resolve ``requested_model`` to an ordered list of candidate targets.

    Returns the primary target first, followed by every configured fallback.
    The list never contains the same (provider, model) pair twice; if a
    fallback duplicates the primary it is silently skipped.

    The ``requested_model`` may be:

    * A configured alias (``smart``) — fully resolved through any
      multi-level chain via the ``primary`` target's ``model`` field, then
      checked for fallbacks at the *outermost* alias only. (Inner aliases'
      fallback lists are intentionally ignored — they describe how those
      aliases would resolve if requested directly, not what to try after
      this request fails. Mixing the two would surprise operators.)
    * A **raw** ``provider/model`` form (``anthropic-prod/claude-haiku-4-5``,
      ``ollama-local/qwen2.5:7b``) — D0. Split on the *first* slash; the
      prefix names a configured provider, the suffix is the provider-native
      model string. Skips alias resolution; builds a single
      :class:`ResolvedTarget` directly. Cycle detection does not apply
      (it's a one-shot lookup with no fallback). The provider must
      exist in :attr:`GatewayConfig.providers`; an unknown provider
      raises :class:`ModelResolutionError` with a message naming the
      configured set so the operator can see the typo.
    * A provider-native model name without a slash (``claude-sonnet-4-6``) —
      resolved to the first provider whose ``models`` list contains it.
      Fallbacks come from no alias because no alias was named.

    Cycles are pre-validated at config load
    (:func:`GatewayConfig._aliases_have_no_cycles`); this function trusts
    that and uses :data:`MAX_ALIAS_DEPTH` only as a defense-in-depth bound.

    Raises :class:`ModelResolutionError` if no resolution exists.
    """

    candidates: list[ResolvedTarget] = []

    # D0: raw ``provider/model`` passthrough. Aliases never contain a
    # slash (Pydantic doesn't constrain this, but every alias in
    # ``gateway.yaml.example`` is a single word), so a slash is the
    # signal to skip alias resolution. We still check the alias map
    # first below so operators who name an alias with a slash (an
    # unusual choice) keep working. The order of the checks is:
    #
    #   1. Alias name match (exact) — even if the alias has a slash.
    #   2. Slash-form passthrough — ``provider/model``.
    #   3. Provider-native model name (no slash, scan provider lists).
    #
    # The slash-form passthrough never falls back through the alias's
    # fallback chain because no alias was named.
    if requested_model not in config.model_aliases and "/" in requested_model:
        provider_name, native_model = requested_model.split("/", 1)
        provider = config.provider_by_name(provider_name)
        if provider is None:
            configured = sorted(p.name for p in config.providers)
            raise ModelResolutionError(
                f"raw model {requested_model!r} names provider {provider_name!r} "
                f"which is not configured; configured providers: {configured}"
            )
        if not native_model:
            raise ModelResolutionError(
                f"raw model {requested_model!r} has an empty model component "
                "(format: 'provider/model')"
            )
        tier = derive_routed_inference_tier(
            provider=provider,
            native_model=native_model,
            inference_tiers=config.inference_tiers,
        )
        return [
            ResolvedTarget(
                provider=provider,
                native_model=native_model,
                routed_inference_tier=tier,
                role="primary",
            )
        ]

    if requested_model in config.model_aliases:
        # Outer alias — walk to a provider-native model.
        outer_alias = config.model_aliases[requested_model]
        provider_name, native_model = _walk_alias_chain(
            start=requested_model,
            config=config,
        )
        provider = config.provider_by_name(provider_name)
        if provider is None:
            raise ModelResolutionError(
                f"alias {requested_model!r} resolves to unknown provider "
                f"{provider_name!r} (config-load validation should have "
                "caught this)"
            )
        primary_tier = derive_routed_inference_tier(
            provider=provider,
            native_model=native_model,
            inference_tiers=config.inference_tiers,
        )
        candidates.append(
            ResolvedTarget(
                provider=provider,
                native_model=native_model,
                routed_inference_tier=primary_tier,
                role="primary",
            )
        )

        # Fallback list from the outermost alias only — see docstring.
        for fb in outer_alias.fallback:
            fb_provider = config.provider_by_name(fb.provider)
            if fb_provider is None:
                # Validated at config load; defensive skip if it ever happens.
                continue
            # Fallbacks may themselves point at an alias name. Resolve.
            fb_native_model = _walk_model_to_native(
                model=fb.model,
                config=config,
            )
            fb_tier = derive_routed_inference_tier(
                provider=fb_provider,
                native_model=fb_native_model,
                inference_tiers=config.inference_tiers,
            )
            target = ResolvedTarget(
                provider=fb_provider,
                native_model=fb_native_model,
                routed_inference_tier=fb_tier,
                role="fallback",
            )
            if not _is_duplicate(target, candidates):
                candidates.append(target)
        return candidates

    # Provider-native model: take the first provider that lists it.
    for provider in config.providers:
        if requested_model in provider.models:
            tier = derive_routed_inference_tier(
                provider=provider,
                native_model=requested_model,
                inference_tiers=config.inference_tiers,
            )
            return [
                ResolvedTarget(
                    provider=provider,
                    native_model=requested_model,
                    routed_inference_tier=tier,
                    role="primary",
                )
            ]

    raise ModelResolutionError(
        f"model {requested_model!r} does not resolve to any configured alias "
        "or provider-native model name"
    )


def _walk_alias_chain(
    *,
    start: str,
    config: GatewayConfig,
) -> tuple[str, str]:
    """Walk an alias chain starting at ``start`` until a provider-native model.

    Returns ``(provider_name, native_model_string)``. The chain is
    pre-validated to be acyclic and bounded by :data:`MAX_ALIAS_DEPTH` at
    config load; this function trusts that and uses the depth bound as a
    defensive guard.

    The chain starts at the outer alias's ``primary.provider``/
    ``primary.model``. If ``primary.model`` is itself the name of another
    alias, we descend; the provider name is replaced at each step by
    that alias's ``primary.provider``. (The intermediate provider names
    don't have semantic meaning; only the terminal one does.)
    """

    current_alias_name = start
    for _ in range(MAX_ALIAS_DEPTH + 1):
        alias_def = config.model_aliases.get(current_alias_name)
        if alias_def is None:
            raise ModelResolutionError(
                f"alias {current_alias_name!r} not found while walking chain "
                f"that started at {start!r}"
            )
        target_model = alias_def.primary.model
        if target_model not in config.model_aliases:
            return alias_def.primary.provider, target_model
        current_alias_name = target_model
    # Should be unreachable thanks to config-load validation.
    raise ModelResolutionError(
        f"alias chain starting at {start!r} exceeded depth {MAX_ALIAS_DEPTH}"
    )


def _walk_model_to_native(*, model: str, config: GatewayConfig) -> str:
    """If ``model`` is itself an alias, resolve to the chain's terminal model."""

    if model not in config.model_aliases:
        return model
    _, native = _walk_alias_chain(start=model, config=config)
    return native


def _is_duplicate(target: ResolvedTarget, existing: list[ResolvedTarget]) -> bool:
    return any(
        t.provider.name == target.provider.name and t.native_model == target.native_model
        for t in existing
    )


# --- Cost computation -------------------------------------------------------


def estimate_cost(
    *,
    provider_name: str,
    native_model: str,
    usage: ChatCompletionUsage,
    rates: dict[str, CostRateEntry],
) -> Decimal | None:
    """Compute USD cost from token usage and per-million-token rates.

    Returns ``None`` if no rate entry is configured for the resolved
    ``provider/model`` pair — per CLAUDE.md, we don't invent prices. The
    column accepts NULL; downstream consumers know NULL means "unpriced",
    not zero.

    Rates are USD per *million* tokens (matching ``gateway.yaml.example``
    and provider pricing pages). The result is quantized to 4 decimal
    places to fit the ``NUMERIC(10, 4)`` column in
    ``inference_routing_log.cost_estimate``.
    """

    rate = rates.get(f"{provider_name}/{native_model}")
    if rate is None:
        return None
    cost = (
        Decimal(str(rate.input_per_mtok)) * Decimal(usage.prompt_tokens)
        + Decimal(str(rate.output_per_mtok)) * Decimal(usage.completion_tokens)
    ) / Decimal(1_000_000)
    return cost.quantize(Decimal("0.0001"))


# --- Fallback policy --------------------------------------------------------


# Errors that are eligible for fallback. Auth errors (401/403 from upstream)
# do *not* trigger fallback because the failure is a misconfiguration, not
# a transient provider issue — falling back would just wear out the next
# provider's credentials too. ``ProviderHTTPError`` with upstream 5xx is
# fallback-eligible; 4xx other than auth is not (the request itself is
# bad). The classification lives here so unit tests can pin it.
def is_fallback_eligible(error: ProviderAdapterError) -> bool:
    """Decide whether a provider error should trigger fallback.

    Eligible:

    * :class:`ProviderNetworkError` — DNS/TCP/TLS/timeout. Always retry.
    * :class:`ProviderHTTPError` with 5xx ``upstream_status`` — upstream
      service degraded, transient. Retry on a different provider.
    * :class:`ProviderHTTPError` with 429 — rate limited. The router
      doesn't retry the *same* provider on a tighter loop; it falls
      through to the configured backup if any.

    Not eligible:

    * :class:`ProviderAuthError` — credential rejection. No amount of
      retrying will fix it.
    * :class:`ProviderHTTPError` with 4xx (non-429) — the request body
      is bad. The next provider will reject it just as quickly.
    * :class:`ProviderUnsupportedError` — the operation isn't supported
      (e.g., embeddings against Anthropic). Surface to the caller.
    """

    if isinstance(error, ProviderNetworkError):
        return True
    if isinstance(error, ProviderHTTPError):
        upstream = error.upstream_status
        return upstream >= 500 or upstream == 429
    return False


# --- Router -----------------------------------------------------------------


@dataclass
class ChatCompletionRoutedResult:
    """The router's return value for a non-streaming request.

    ``response`` carries the OpenAI-shaped result; ``target`` carries the
    target the router actually used (may be a fallback). The route handler
    serializes ``response`` and writes ``target`` (along with usage and
    latency) to ``inference_routing_log``.
    """

    response: ChatCompletionResponse
    target: ResolvedTarget
    latency_ms: int
    fallbacks_tried: list[str]
    """Provider names that were attempted (and either failed or had no
    instantiated adapter) **before** ``target`` succeeded. Empty when
    the primary succeeded on the first try; the list captures the
    fallback walk for telemetry / log correlation."""


# Type alias for the streaming wrapper signature so adapters can plug in
# without circular imports.
StreamFactory = Callable[
    [ChatCompletionRequest, ResolvedTarget, ProviderAdapter],
    AsyncIterator[ChatCompletionChunk],
]


_DEFAULT_FALLBACKS_TRIED: Final[list[str]] = []


class Router:
    """The B4 router: alias resolution + tier derivation + dispatch + fallback.

    The router is constructed once at startup against the loaded
    :class:`GatewayConfig` and the adapter registry built by the lifespan.
    Per-request methods are pure async functions; the router itself holds
    no per-request state.

    The router does not own the database session or the
    ``inference_routing_log`` write — that's the route handler's job. The
    router's job is to produce a :class:`ChatCompletionRoutedResult` (or
    raise) that the handler can persist.
    """

    def __init__(
        self,
        *,
        config: GatewayConfig,
        adapters: dict[str, ProviderAdapter],
        config_provider: Callable[[], GatewayConfig] | None = None,
    ) -> None:
        self._config = config
        self._adapters = adapters
        # D0.5: when ``config_provider`` is supplied, every per-request
        # call resolves against the live snapshot returned by the
        # callable rather than the constructor-time config. The
        # gateway lifespan wires this to ``MutableConfigHolder.current``
        # so admin alias edits take effect on the very next request
        # without rebuilding the Router. Tests that don't wire the
        # holder still work — the static ``config`` is the fallback.
        self._config_provider = config_provider

    @property
    def config(self) -> GatewayConfig:
        if self._config_provider is not None:
            return self._config_provider()
        return self._config

    @property
    def adapters(self) -> dict[str, ProviderAdapter]:
        return self._adapters

    def resolve(self, requested_model: str) -> list[ResolvedTarget]:
        """Resolve ``requested_model`` to an ordered list of candidate targets."""

        return resolve_alias_chain(requested_model=requested_model, config=self.config)

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
    ) -> ChatCompletionRoutedResult:
        """Run a non-streaming chat completion through the router.

        Walks the candidate list (primary + fallbacks). Each candidate's
        adapter is invoked; on a fallback-eligible error, the next
        candidate is tried. The first success returns. If every candidate
        fails, the last error is re-raised wrapped (so the route handler
        sees both the final error and the chain that led there).
        """

        candidates = self.resolve(request.model)
        last_error: ProviderAdapterError | None = None
        last_error_target: ResolvedTarget | None = None
        last_error_latency_ms = 0
        fallbacks_tried: list[str] = []

        for target in candidates:
            adapter = self._adapters.get(target.provider.name)
            if adapter is None:
                logger.warning(
                    "no adapter for provider %r (%s); trying next candidate",
                    target.provider.name,
                    target.role,
                )
                fallbacks_tried.append(target.provider.name)
                continue

            start = time.monotonic()
            try:
                result = await adapter.chat_completion(
                    request,
                    model=target.native_model,
                    stream=False,
                )
            except ProviderAdapterError as exc:
                latency_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    "provider %r failed (%s) after %dms: %s",
                    target.provider.name,
                    type(exc).__name__,
                    latency_ms,
                    exc.message,
                )
                last_error = exc
                last_error_target = target
                last_error_latency_ms = latency_ms
                fallbacks_tried.append(target.provider.name)
                if not is_fallback_eligible(exc):
                    # Non-retryable; bubble up immediately so the route
                    # handler can map to the right HTTP status. Wrap with
                    # the target so the routing-log row attributes the
                    # failure to the right upstream.
                    _record_inference_outcome(
                        target=target,
                        outcome=outcome_label_from_error(exc),
                    )
                    raise RoutedProviderError(
                        target=target,
                        error=exc,
                        latency_ms=latency_ms,
                        fallbacks_tried=list(fallbacks_tried),
                    ) from exc
                continue

            # Adapter contract guarantees a ChatCompletionResponse here
            # because we asked for stream=False, but assert defensively.
            if not isinstance(result, ChatCompletionResponse):
                raise RuntimeError(
                    f"adapter {target.provider.name!r} returned a non-response "
                    f"object for stream=False: {type(result).__name__}"
                )

            latency_ms = int((time.monotonic() - start) * 1000)
            _record_inference_outcome(target=target, outcome="success")
            return ChatCompletionRoutedResult(
                response=result,
                target=target,
                latency_ms=latency_ms,
                fallbacks_tried=fallbacks_tried,
            )

        # Every candidate failed.
        if last_error is not None and last_error_target is not None:
            _record_inference_outcome(
                target=last_error_target,
                outcome=outcome_label_from_error(last_error),
            )
            raise RoutedProviderError(
                target=last_error_target,
                error=last_error,
                latency_ms=last_error_latency_ms,
                fallbacks_tried=fallbacks_tried,
            )
        raise NoAdapterAvailableError(
            f"no adapter available for model {request.model!r}; tried "
            f"{[t.provider.name for t in candidates]}",
        )


def synthesize_request_id(provided: str | None) -> str:
    """Return a request-id, generating one if the caller didn't supply one.

    Persisted into ``inference_routing_log.request_id`` so the row is
    correlatable with telemetry. Caller-supplied ids (e.g., from the
    backend's per-request middleware) are preserved verbatim; otherwise
    we generate a UUIDv4 — short enough to fit a Text column, opaque
    enough to be safe in logs.
    """

    return provided or f"req_{uuid.uuid4().hex}"
