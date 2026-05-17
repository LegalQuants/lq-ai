"""Pydantic schema for ``gateway.yaml``.

Mirrors the structure documented in ``gateway.yaml.example`` and PRD §4.4.
A3 originally landed config loading; B4 extends the schema with
``inference_tiers`` (per-provider-type defaults + per-(provider, model)
overrides) and adds alias-cycle detection.

Validation rules enforced here:

* ``Provider.tier`` is in ``{1, 2, 3, 4, 5}``.
* ``TierPolicy.allowed_tiers_global`` is a non-empty subset of
  ``{1, 2, 3, 4, 5}``.
* Every ``ModelAlias.primary.provider`` (and each fallback's ``provider``)
  references a configured provider name.
* B4: ``model_aliases`` are checked for cycles. An alias's ``primary.model``
  may itself be the name of another alias (multi-level aliasing), but the
  resolution chain must terminate. A cycle is rejected at config load,
  not at request time.
* B4: ``inference_tiers.defaults`` keys are validated against the
  ``ProviderType`` enum so a typo (``anthropc``) is caught at startup.

Anything not strictly required is permissive (``extra="allow"``) so future
tasks can keep adding fields without rev-locking the YAML schema.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --- Primitive type aliases ---------------------------------------------------

InferenceTier = Annotated[int, Field(ge=1, le=5)]
"""An Inference Tier (1-5 per PRD §1.5.2)."""

LogLevel = Literal["debug", "info", "warn", "error"]

MAX_ALIAS_DEPTH = 8
"""Maximum length of a multi-level alias chain (``a -> b -> c -> ...``).

Real configurations typically resolve in 1-2 levels; an 8-level depth is
generous enough that legitimate operator setups never hit it but tight
enough that a runaway cycle is caught quickly. Tunable via a future
config field if the assumption ever bites."""


# --- Server / auth ------------------------------------------------------------


class ServerConfig(BaseModel):
    """Top-level ``server:`` block."""

    model_config = ConfigDict(extra="forbid")

    host: str = "0.0.0.0"
    port: int = Field(default=8001, ge=1, le=65535)
    log_level: LogLevel = "info"


class GatewayAuthConfig(BaseModel):
    """``gateway_auth:`` — how the backend authenticates to the gateway."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    api_key_env: str = "LQ_AI_GATEWAY_KEY"


# --- Providers ----------------------------------------------------------------


ProviderType = Literal[
    "anthropic",
    "openai",
    "vertex",
    "cohere",
    "azure_openai",
    "bedrock",
    "ollama",
    "vllm",
    "openai_compatible",
]


class ProviderConfig(BaseModel):
    """One entry under ``providers:``.

    Keeps unknown provider-specific fields (``project_id``, ``region``,
    ``aws_region``, ``api_version``, etc.) by allowing extra fields. The
    per-type adapter (B3+) is responsible for reading what it needs.

    API-key sourcing (per ADR 0011) supports two paths and exactly one
    is used per provider:

    * ``api_key_env: ANTHROPIC_API_KEY`` — read the key from the
      environment at adapter build time. Existing path; deprecated but
      still loadable through M1+M2.
    * ``api_key_encrypted: gAAAAAB...`` — Fernet-wrapped ciphertext;
      decrypted in-memory by ``app.secrets.ProviderKeyResolver`` using
      the master key bound at gateway startup
      (:envvar:`LQ_AI_GATEWAY_MASTER_KEY`).

    Mixing both on a single entry is rejected by the validator.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    type: ProviderType
    base_url: str = Field(min_length=1)
    # Some local providers (e.g., Ollama) legitimately have an empty string
    # here. Accept ``None`` and ``""`` to mean "no key required".
    api_key_env: str | None = None
    api_key_encrypted: str | None = None
    """Fernet token (urlsafe-base64) of the provider key. Decrypted at
    gateway startup. See ``app.secrets`` and ADR 0011."""
    tier: InferenceTier
    models: list[str] = Field(default_factory=list)
    enabled: bool = True

    @model_validator(mode="after")
    def _exactly_one_key_source(self) -> ProviderConfig:
        if self.api_key_env and self.api_key_encrypted:
            raise ValueError(
                f"Provider {self.name!r}: set either api_key_env OR "
                f"api_key_encrypted, not both. Aborting at config-load "
                f"time so a misconfigured provider can't silently fall "
                f"back to a different key source than the operator "
                f"intended."
            )
        return self


# --- Model aliases ------------------------------------------------------------


class ModelTarget(BaseModel):
    """A specific (provider, model) target referenced from an alias."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)


class ModelAliasConfig(BaseModel):
    """One entry under ``model_aliases:``.

    Per PRD §4.4 / ``gateway.yaml.example``, an alias has a ``primary`` target
    and an optional ``fallback`` chain. Skills and the backend reference
    aliases (``smart``, ``fast``, ``budget``, ``local``, ``embedding``) rather
    than concrete provider/model pairs.
    """

    model_config = ConfigDict(extra="forbid")

    primary: ModelTarget
    fallback: list[ModelTarget] = Field(default_factory=list)


# --- Inference-tier derivation (B4) ------------------------------------------


class InferenceTiersConfig(BaseModel):
    """``inference_tiers:`` — operator-controlled tier-derivation overrides.

    Two layers of resolution applied by :func:`derive_routed_inference_tier`:

    1. ``overrides`` — exact ``"<provider_name>/<model>"`` keys win. Used when
       a single (provider, model) pair lands at a non-default tier (e.g., a
       ZDR'd Claude account on Bedrock that should be Tier 2 even though
       Bedrock's default is 3).
    2. ``defaults`` — per ``ProviderType`` (``anthropic``, ``openai``,
       ``vertex``, ...). Used when an operator wants every model under a
       given provider type to land at a non-default tier.

    Both layers are *optional*. If neither matches, the tier falls back to the
    provider entry's own ``tier:`` field (the simple posture documented in
    ``gateway.yaml.example``).

    Per PRD §4.4 / §1.5.2 / §3.13. Tier values are 1-5 inclusive.
    """

    model_config = ConfigDict(extra="allow")

    defaults: dict[ProviderType, InferenceTier] = Field(default_factory=dict)
    """Per-provider-type tier defaults (``anthropic`` → 4, ``openai`` → 4,
    ``ollama`` → 1, ...). Keys are validated against the ``ProviderType``
    enum so a typo is caught at startup, not on the first inference call."""

    overrides: dict[str, InferenceTier] = Field(default_factory=dict)
    """Per-(provider, model) tier overrides keyed as ``"<provider>/<model>"``.

    Example::

        overrides:
          anthropic-prod/claude-opus-4-7: 3   # operator's ZDR addendum

    A bare ``"<provider>"`` key is also honored; it lifts every model on
    that named provider to the override value (rare; per-type ``defaults``
    is usually the cleaner expression of operator intent).
    """


# --- Tier policy --------------------------------------------------------------


class TierPolicyConfig(BaseModel):
    """``tier_policy:`` — operator-level tier policy.

    A3 loads this; D1 enforces ``default_minimum_tier`` /
    ``privileged_minimum_tier`` refusals.
    """

    model_config = ConfigDict(extra="allow")

    allowed_tiers_global: list[InferenceTier] = Field(default_factory=lambda: [1, 2, 3, 4])
    default_minimum_tier: InferenceTier = 4
    privileged_minimum_tier: InferenceTier = 3
    warn_on_tiers: list[InferenceTier] = Field(default_factory=lambda: [4, 5])

    @field_validator("allowed_tiers_global")
    @classmethod
    def _allowed_tiers_must_be_non_empty(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("tier_policy.allowed_tiers_global must be non-empty")
        # Pydantic's ``InferenceTier`` already constrains each element to 1..5.
        # Deduplicate while preserving order for stable downstream behavior.
        seen: set[int] = set()
        deduped: list[int] = []
        for tier in value:
            if tier not in seen:
                seen.add(tier)
                deduped.append(tier)
        return deduped


# --- Rate limits / cost / validation / etc. (loose schemas) ------------------
#
# A3 doesn't enforce these; B6 / cost-tracker tasks tighten them as needed.
# We keep them as ``BaseModel`` with ``extra="allow"`` so the YAML round-trips
# cleanly and so future tasks can read what they need.


class RateLimitsConfig(BaseModel):
    model_config = ConfigDict(extra="allow")


class AnonymizationConfig(BaseModel):
    """``anonymization:`` block. M2 feature.

    Typed fields the M2-B3 middleware reads directly:

    * :attr:`enabled` — master switch. ``False`` short-circuits the
      pre/post middleware to a no-op regardless of per-request
      ``anonymize`` flags or tier gating.
    * :attr:`apply_at_tiers` — tier gate. The middleware fires only
      when the request's routed tier is in this list. Tiers outside
      ``[1, 5]`` raise a config-load error rather than silently
      becoming a no-op.

    Other keys from ``gateway.yaml.example`` (``entity_types`` etc.)
    pass through under ``extra="allow"`` and are documented in
    ``docs/security/anonymization.md``; M2-B3 does not depend on them
    yet.
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    apply_at_tiers: list[int] = Field(default_factory=list)

    @field_validator("apply_at_tiers")
    @classmethod
    def _validate_tier_range(cls, value: list[int]) -> list[int]:
        for tier in value:
            if not 1 <= tier <= 5:
                raise ValueError(
                    f"apply_at_tiers entry {tier} is out of [1, 5] range; "
                    "tiers run 1 (strongest) to 5 (weakest) per PRD §1.5.2."
                )
        return value


class CostRateEntry(BaseModel):
    """One ``cost_tracking.rates`` entry: input/output USD per million tokens.

    The B4 router uses these to populate ``inference_routing_log.cost_estimate``
    for each routed request. If the resolved ``"<provider>/<model>"`` key is
    not in :attr:`CostTrackingConfig.rates`, ``cost_estimate`` is left ``NULL``
    rather than invented (per CLAUDE.md: don't overclaim).
    """

    model_config = ConfigDict(extra="allow")

    input_per_mtok: float = Field(ge=0.0)
    output_per_mtok: float = Field(ge=0.0)


class CostTrackingConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    rates: dict[str, CostRateEntry] = Field(default_factory=dict)
    """Per-(provider, model) USD-per-million-token rates keyed as
    ``"<provider>/<model>"``. See ``gateway.yaml.example`` for the canonical
    shape. The router consults this when computing ``cost_estimate`` for the
    ``inference_routing_log`` row.
    """


class TelemetryConfig(BaseModel):
    model_config = ConfigDict(extra="allow")


class CircuitBreakerConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = True


class RequestValidationConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    max_max_tokens: int = Field(default=16384, ge=1)
    max_messages_per_request: int = Field(default=100, ge=1)
    max_total_request_chars: int = Field(default=1_000_000, ge=1)
    large_context_threshold_tokens: int = Field(default=50_000, ge=1)


class DevModeConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = False


class EnsembleVerificationConfig(BaseModel):
    """``citation_engine.ensemble_verification:`` block — M2-D1.

    Stage 4 of the Citation Engine cascade. When activated (per-skill,
    per-project, or per-deployment), the paraphrase judge runs in
    parallel across :attr:`judge_models` and the verdicts aggregate
    under :attr:`aggregation_rule`.

    Activation is computed by the api/ at chat-send time: ``any()``
    across the skill frontmatter ``ensemble_verification`` flag, the
    project's ``ensemble_verification`` column, and this block's
    :attr:`default_enabled`. The gateway exposes the resolved config
    via ``GET /v1/citation-engine/config``; the api/ caches it for the
    process and reads it on every verify() call.

    :attr:`judge_models` is a list of aliases (or fully-qualified
    ``provider/model``) the gateway's router can resolve. Three is the
    canonical M2-D1 baseline (primary judge + 2 alternates from
    different provider families); operators may choose more or fewer.
    An empty list disables ensemble even when :attr:`default_enabled`
    is True — defense-in-depth against misconfiguration.

    :attr:`aggregation_rule` selects strict (all judges must verdict
    ``"yes"``) or majority (simple majority wins). The persisted
    ``message_citations.verification_method`` is
    ``'ensemble_strict'`` or ``'ensemble_majority'`` accordingly.

    :attr:`max_cost_per_message_usd` is the pre-flight budget cap. The
    api/ estimates ``input_tokens * len(judge_models) * max_judge_rate``
    before dispatch; if the estimate exceeds the cap, verification
    falls back to a single Stage 3 judge call with a warning logged.
    Default ``0.05`` is a conservative ceiling; operators tune per
    their cost posture.
    """

    model_config = ConfigDict(extra="allow")

    default_enabled: bool = False
    judge_models: list[str] = Field(default_factory=list)
    aggregation_rule: Literal["strict", "majority"] = "strict"
    max_cost_per_message_usd: float = Field(default=0.05, ge=0.0)


class CitationEngineConfig(BaseModel):
    """``citation_engine:`` block — M2-C1 / M2-D1.

    The Citation Engine runs in the api/ but reads the *model name* it
    should use for the Stage 3 (paraphrase) judge from the gateway's
    config so the operator has one place to configure model choices.
    The api/ pulls this over ``GET /v1/citation-engine/config`` at
    startup (or on first need) and caches it for the process.

    :attr:`judge_model` accepts any value the gateway's router can
    resolve: an alias from ``model_aliases`` (``fast``, ``smart``,
    ``budget``) or a fully-qualified provider/model form
    (``anthropic-prod/claude-haiku-4-5``). Defaults to ``"fast"`` —
    deliberately a smaller model than the typical citation-generating
    model so the judge cost is bounded.

    :attr:`ensemble_verification` (M2-D1) is the Stage 4 ensemble
    block. See :class:`EnsembleVerificationConfig` for the per-field
    contract. Default-constructed (``default_enabled=False``, empty
    ``judge_models``) means Stage 4 is opt-in per skill or project.
    """

    model_config = ConfigDict(extra="allow")

    judge_model: str = Field(default="fast", min_length=1)
    ensemble_verification: EnsembleVerificationConfig = Field(
        default_factory=EnsembleVerificationConfig
    )


# --- Top-level config ---------------------------------------------------------


class GatewayConfig(BaseModel):
    """Full ``gateway.yaml`` shape.

    Loaded once on startup by :func:`app.config_loader.load_config` and
    attached to ``app.state.config``. Treat as immutable after startup.
    """

    model_config = ConfigDict(extra="allow")

    server: ServerConfig = Field(default_factory=ServerConfig)
    gateway_auth: GatewayAuthConfig = Field(default_factory=GatewayAuthConfig)
    providers: list[ProviderConfig] = Field(default_factory=list)
    model_aliases: dict[str, ModelAliasConfig] = Field(default_factory=dict)
    inference_tiers: InferenceTiersConfig = Field(default_factory=InferenceTiersConfig)
    tier_policy: TierPolicyConfig = Field(default_factory=TierPolicyConfig)
    rate_limits: RateLimitsConfig = Field(default_factory=RateLimitsConfig)
    anonymization: AnonymizationConfig = Field(default_factory=AnonymizationConfig)
    citation_engine: CitationEngineConfig = Field(default_factory=CitationEngineConfig)
    cost_tracking: CostTrackingConfig = Field(default_factory=CostTrackingConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    request_validation: RequestValidationConfig = Field(default_factory=RequestValidationConfig)
    dev_mode: DevModeConfig = Field(default_factory=DevModeConfig)

    @model_validator(mode="after")
    def _aliases_reference_known_providers(self) -> GatewayConfig:
        """Every alias target must point at a configured provider.

        A typo here is the most common kind of misconfiguration ("provider:
        anthropic" when the configured name is "anthropic-prod"); refusing
        to start with a clear message beats failing on first request.
        """

        provider_names = {provider.name for provider in self.providers}
        if not provider_names:
            # Empty providers is allowed for tests / minimal configs, but then
            # there must also be no aliases referencing them.
            if self.model_aliases:
                raise ValueError(
                    "model_aliases configured but providers list is empty; "
                    "every alias must reference a provider"
                )
            return self

        for alias_name, alias in self.model_aliases.items():
            targets: list[tuple[str, ModelTarget]] = [("primary", alias.primary)]
            targets.extend(("fallback", target) for target in alias.fallback)
            for label, target in targets:
                if target.provider not in provider_names:
                    raise ValueError(
                        f"model_aliases.{alias_name}.{label} references unknown "
                        f"provider {target.provider!r}; configured providers: "
                        f"{sorted(provider_names)}"
                    )
        return self

    @model_validator(mode="after")
    def _aliases_have_no_cycles(self) -> GatewayConfig:
        """Reject alias chains that don't terminate.

        Multi-level aliasing (alias whose ``primary.model`` is itself the
        name of another alias) is supported in B4's router, but the chain
        must terminate at a provider-native model. A cycle (``a -> b -> a``)
        or a chain longer than :data:`MAX_ALIAS_DEPTH` is rejected at
        startup so the failure is visible during ``docker compose up``,
        not on the first inference call.

        We resolve from each alias separately because a chain like
        ``a -> b -> c`` should be rejected as soon as we see it; doing
        the full graph SCC analysis would catch the same cases at the
        cost of clarity.
        """

        for alias_name in self.model_aliases:
            seen: list[str] = []
            current = alias_name
            for _ in range(MAX_ALIAS_DEPTH + 1):
                if current in seen:
                    chain = " -> ".join([*seen, current])
                    raise ValueError(
                        f"model_aliases cycle detected: {chain} (each alias "
                        "must terminate at a provider-native model name)"
                    )
                seen.append(current)
                alias_def = self.model_aliases.get(current)
                if alias_def is None:
                    # Reached a provider-native model; chain terminated.
                    break
                current = alias_def.primary.model
            else:
                # Loop exhausted without break — chain too deep.
                chain = " -> ".join(seen)
                raise ValueError(
                    f"model_aliases chain exceeds maximum depth {MAX_ALIAS_DEPTH}: {chain}"
                )
        return self

    # --- Convenience accessors used by routers --------------------------------

    def alias_ids(self) -> list[str]:
        """Return the configured alias names in declaration order.

        Backs ``GET /v1/models``.
        """

        return list(self.model_aliases.keys())

    def provider_by_name(self, name: str) -> ProviderConfig | None:
        """Look up a configured provider by name; ``None`` if not found.

        Used by the B4 router to dispatch to the right adapter and read the
        provider's tier (used as the final fallback in tier derivation).
        """

        for provider in self.providers:
            if provider.name == name:
                return provider
        return None

    def to_models_payload(self) -> dict[str, Any]:
        """OpenAI ``GET /v1/models``-shaped response built from aliases.

        OpenAI's ``/v1/models`` returns ``{"object": "list", "data": [...]}``
        with each entry shaped as ``{"id", "object": "model", "created",
        "owned_by"}``. We use a fixed ``created=0`` because the gateway has
        no provider-relative creation timestamp; the field is included for
        client compatibility, not as a real value.
        """

        # D0.5: surface ``lq_ai_kind`` and ``routed_inference_tier`` on
        # the alias rows so the alias-only fallback (used by tests that
        # bypass the lifespan-built ``ModelDiscoverer``) carries the
        # same shape as the live-discovery merge. Avoids importing
        # the router here (would create a circular dep) by inlining
        # the same lookup chain ``derive_routed_inference_tier`` runs.
        out: list[dict[str, Any]] = []
        for alias_name, alias in self.model_aliases.items():
            tier: int | None = None
            primary = self.provider_by_name(alias.primary.provider)
            if primary is not None and alias.primary.model:
                pair = f"{primary.name}/{alias.primary.model}"
                if pair in self.inference_tiers.overrides:
                    tier = int(self.inference_tiers.overrides[pair])
                elif primary.name in self.inference_tiers.overrides:
                    tier = int(self.inference_tiers.overrides[primary.name])
                elif primary.type in self.inference_tiers.defaults:
                    tier = int(self.inference_tiers.defaults[primary.type])
                else:
                    tier = int(primary.tier)
            entry: dict[str, Any] = {
                "id": alias_name,
                "object": "model",
                "created": 0,
                "owned_by": "lq-ai-gateway",
                "lq_ai_kind": "alias",
            }
            if tier is not None:
                entry["routed_inference_tier"] = tier
            out.append(entry)
        return {"object": "list", "data": out}
