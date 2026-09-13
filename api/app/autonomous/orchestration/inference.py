"""Direct inference routes and conservative, explicitly priced accounting.

This is an accounted estimate, not a tokenizer or provider-invoice guarantee.
No alias/fallback resolution is reproduced here. Gateway configuration revision
enforcement remains a deployment gate, as it does for authority-source bindings.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from decimal import ROUND_CEILING, Decimal
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field, field_serializer

from app.autonomous.orchestration.contracts import (
    Digest,
    ExecutionScope,
    InferenceTier,
    Money,
    PreparedPlan,
    ShortText,
    Snapshot,
)
from app.autonomous.orchestration.policy import InferencePolicy, OperatorPolicy
from app.errors import Forbidden, ValidationError

if TYPE_CHECKING:
    from app.autonomous.guard import ToolResult

type Rate = Annotated[
    Decimal, Field(ge=0, le=1000000, max_digits=15, decimal_places=8, allow_inf_nan=False)
]


class TokenRates(Snapshot):
    input_per_mtok: Rate
    output_per_mtok: Rate

    @field_serializer("*")
    def serialize_rate(self, value: Decimal) -> str:
        return format(value, ".8f")

    def cost(self, prompt_tokens: int, completion_tokens: int) -> Decimal:
        return (
            (self.input_per_mtok * prompt_tokens + self.output_per_mtok * completion_tokens)
            / Decimal(1000000)
        ).quantize(Decimal("0.0001"), rounding=ROUND_CEILING)


def message_identity(messages: object) -> tuple[str, int]:
    """Only the adapter's pinned system prompt and bounded user data are supported."""
    if (
        not isinstance(messages, list)
        or len(messages) != 2
        or any(not isinstance(m, dict) or set(m) != {"role", "content"} for m in messages)
        or [m["role"] for m in messages] != ["system", "user"]
        or any(not isinstance(m["content"], str) for m in messages)
    ):
        raise ValidationError(message="Bound inference requires pinned system and user messages")
    encoded = json.dumps(
        messages, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    if len(encoded) > 131072:
        raise ValidationError(message="Inference messages exceed bounded request size")
    # UTF-8 bytes plus fixed message framing is an explicit conservative
    # accounting convention. It does not promise a universal token upper bound.
    input_bytes = sum(len(m["content"].encode()) for m in messages)
    return hashlib.sha256(encoded).hexdigest(), input_bytes


class InferenceBinding(Snapshot):
    policy_version: ShortText
    policy: InferencePolicy
    routed_tier: InferenceTier
    rates: TokenRates
    messages_digest: Digest
    estimated_prompt_tokens: Annotated[int, Field(ge=0, le=131168)]
    reservation_usd: Money
    config_digest: Digest
    gateway_revision: Digest
    anonymization_expected: bool

    @field_serializer("reservation_usd")
    def serialize_reservation(self, value: Decimal) -> str:
        return format(value, ".4f")

    def matches(self, params: dict[str, Any]) -> bool:
        digest, _ = message_identity(params.get("messages"))
        return (
            params.get("model") == self.policy.model_key
            and params.get("max_tokens") == self.policy.max_output_tokens
            and digest == self.messages_digest
        )


class InferenceRoutes:
    def __init__(self, *, gateway: Any, operator: Callable[[], OperatorPolicy | None]) -> None:
        self.gateway, self.operator = gateway, operator

    async def bind(
        self, plan: PreparedPlan, scope: ExecutionScope, messages: list[dict[str, Any]]
    ) -> InferenceBinding:
        operator = self.operator()
        if (
            operator is None
            or operator.version() != plan.policy_version
            or operator.inference is None
        ):
            raise Forbidden(message="Orchestration inference policy is disabled or changed")
        policy = operator.inference
        digest, input_bytes = message_identity(messages)
        if input_bytes > policy.max_input_bytes:
            raise Forbidden(message="Inference input exceeds approved byte limit")
        config = await self.gateway.get_admin_config()
        try:
            # Slash-named aliases take precedence even over direct routes in the
            # gateway. Refuse collisions rather than inherit their fallback chain.
            if policy.model_key in config["model_aliases"]:
                raise ValueError("direct model is shadowed by an alias")
            providers = config["providers"]
            if not isinstance(providers, list):
                raise ValueError("invalid provider catalog")
            matches = [
                p for p in providers if isinstance(p, dict) and p.get("name") == policy.provider
            ]
            if len(matches) != 1:
                raise ValueError("missing or ambiguous provider")
            provider = matches[0]
            if provider.get("enabled") is not True:
                raise ValueError("disabled provider")
            tiers = config["inference_tiers"]
            overrides, defaults = tiers["overrides"], tiers["defaults"]
            tier = overrides.get(
                policy.model_key,
                overrides.get(policy.provider, defaults.get(provider["type"], provider["tier"])),
            )
            if type(tier) is not int or not 1 <= tier <= 5 or tier > scope.minimum_inference_tier:
                raise ValueError("route weaker than approved inference requirement")
            pricing = config["cost_tracking"]
            if pricing.get("enabled") is not True:
                raise ValueError("pricing disabled")
            raw = pricing["rates"][policy.model_key]
            parsed = {}
            for key in ("input_per_mtok", "output_per_mtok"):
                if type(raw[key]) not in (str, int, float):
                    raise ValueError("invalid explicit token rate")
                parsed[key] = Decimal(str(raw[key]))
            rates = TokenRates(**parsed)
            anon = config["anonymization"]
            # Match the gateway's established privilege semantics: privileged
            # requests deliberately skip rewriting. Otherwise an explicit
            # anonymization requirement cannot be silently skipped by config.
            expected = scope.anonymize and not scope.privileged
            if expected and (anon.get("enabled") is not True or tier not in anon["apply_at_tiers"]):
                raise ValueError("required anonymization is unavailable")
            estimated = input_bytes + 96  # two messages plus completion framing
            routing = {
                "provider": {
                    k: provider.get(k)
                    for k in ("name", "type", "base_url", "enabled", "use_max_completion_tokens")
                },
                "model": policy.native_model,
                "tier": tier,
                "rates": rates.model_dump(mode="json"),
                "anonymization": {k: anon.get(k) for k in ("enabled", "apply_at_tiers")},
                "estimator": "utf8-bytes-plus-framing-v1",
            }
            binding = InferenceBinding(
                policy_version=plan.policy_version,
                policy=policy,
                routed_tier=tier,
                rates=rates,
                messages_digest=digest,
                estimated_prompt_tokens=estimated,
                reservation_usd=rates.cost(estimated, policy.max_output_tokens),
                config_digest=hashlib.sha256(
                    json.dumps(routing, sort_keys=True, allow_nan=False).encode()
                ).hexdigest(),
                gateway_revision=config["configuration_revision"],
                anonymization_expected=expected,
            )
        except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError):
            raise Forbidden(
                message="Inference route, protection or pricing is unavailable"
            ) from None
        current = self.operator()
        if current is None or current.version() != binding.policy_version:
            raise Forbidden(message="Orchestration inference policy is disabled or changed")
        return binding


def bound_result(binding: InferenceBinding, response: Any, *, intent: str) -> ToolResult:
    """Keep the estimate as the charge floor; record usage observations separately.

    Gateway/provider usage may omit hidden or billable work. It cannot establish
    that reserved spend was unused. Reported usage above the estimate still counts
    in full, so the store can stop an observed allocation overrun.
    """
    from app.autonomous.guard import ToolResult

    try:
        if (
            response.routed_provider != binding.policy.provider
            or response.routed_model != binding.policy.native_model
            or type(response.routed_inference_tier) is not int
            or response.routed_inference_tier != binding.routed_tier
            or response.anonymization_applied is not binding.anonymization_expected
            or len(response.choices) != 1
            or not isinstance(response.choices[0].message.content, str)
        ):
            raise ValueError("response differs from binding")
        usage = response.usage
        counts = (usage.prompt_tokens, usage.completion_tokens)
        if any(type(c) is not int or not 0 <= c <= 1_000_000_000 for c in counts):
            raise ValueError("invalid usage observation")
        observed = binding.rates.cost(*counts)
        finish = response.choices[0].finish_reason
        if finish not in {"stop", "length", "content_filter"}:
            raise ValueError("unsupported completion outcome")
    except (AttributeError, TypeError, ValueError, ArithmeticError):
        raise ValidationError(
            message="Inference response is untrusted; reconciliation is required"
        ) from None
    charged = max(binding.reservation_usd, observed)
    return ToolResult(
        cost_usd=charged,
        data={
            "intent": intent,
            "content": response.choices[0].message.content,
            "finish_reason": finish,
            "token_counts": {"prompt_tokens": counts[0], "completion_tokens": counts[1]},
            "accounting": {
                "basis": "conservative-estimate-or-reported-usage-v1",
                "estimated_prompt_tokens": binding.estimated_prompt_tokens,
                "reserved_usd": format(binding.reservation_usd, ".4f"),
                "reported_usage_cost_usd": format(observed, ".4f"),
                "charged_usd": format(charged, ".4f"),
                "provider": binding.policy.provider,
                "model": binding.policy.native_model,
                "config_digest": binding.config_digest,
            },
        },
    )
