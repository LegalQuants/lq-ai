"""Direct inference routes and conservative, explicitly priced accounting.

This is an accounted estimate, not a tokenizer or provider-invoice guarantee.
No alias/fallback resolution is reproduced here. Gateway configuration revision
enforcement remains a deployment gate, as it does for authority-source bindings.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from decimal import ROUND_CEILING, Decimal
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field, SerializerFunctionWrapHandler, field_serializer, model_serializer

from app.autonomous.orchestration.contracts import (
    Digest,
    ExecutionScope,
    InferenceTier,
    Money,
    PreparedPlan,
    ShortText,
    Snapshot,
)
from app.autonomous.orchestration.planning import PlanningSnapshot
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


MAX_TOOL_CALLS = 8
_LEGACY_IDENTITY_BYTES = 131072
_CALL_ID = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
# One call's arguments, and all of a turn's together. A working note is at most
# 16,384 characters, so a legitimate call fits the first with room for framing.
_CALL_ARGUMENT_BYTES = 49_152
_TURN_ARGUMENT_BYTES = 65_536


class InputLimitExceeded(Forbidden):
    """The request no longer fits the route's approved input limit. Nothing was sent."""


def _invalid() -> ValidationError:
    return ValidationError(message="Bound inference requires pinned system and user messages")


def _call_shape(call: object) -> bool:
    if not isinstance(call, dict) or set(call) != {"id", "type", "function"}:
        return False
    function = call["function"]
    return (
        isinstance(call["id"], str)
        and call["type"] == "function"
        and isinstance(function, dict)
        and set(function) == {"name", "arguments"}
        and isinstance(function["name"], str)
        and isinstance(function["arguments"], str)
    )


def conversation_identity(
    messages: object, tools: object = None, *, max_bytes: int = _LEGACY_IDENTITY_BYTES
) -> tuple[str, int]:
    """Identify one bound request: pinned system prompt, bounded user data, and
    for an approved child the run's own tool turns and offered schemas.

    Two messages without tools keep the encoding 0.8.0 used, so a retained
    effect's identity is unchanged. Anything else binds messages and tools
    together. The shapes are closed: a message cannot smuggle an extra field.
    """
    if not isinstance(messages, list) or len(messages) < 2:
        raise _invalid()
    offered = [] if tools is None else tools
    if not isinstance(offered, list) or any(not isinstance(t, dict) for t in offered):
        raise _invalid()
    input_bytes = 0
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise _invalid()
        role = message.get("role")
        expected = {0: "system", 1: "user"}.get(index)
        if expected is not None and role != expected:
            raise _invalid()
        # Exactly one system prompt, the pinned skill, and it is first. A later
        # user message is the engine's own notice that tool use has ended.
        if (role == "system" and index == 0) or (role == "user" and index >= 1):
            ok = set(message) == {"role", "content"} and isinstance(message["content"], str)
        elif role == "assistant" and index >= 2:
            calls = message.get("tool_calls")
            ok = (
                set(message) <= {"role", "content", "tool_calls"}
                and isinstance(message.get("content", ""), str)
                and (
                    calls is None
                    or (
                        isinstance(calls, list)
                        and 1 <= len(calls) <= MAX_TOOL_CALLS
                        and all(_call_shape(c) for c in calls)
                    )
                )
            )
            if ok and calls:
                input_bytes += len(json.dumps(calls, ensure_ascii=False).encode())
        elif role == "tool" and index >= 2:
            ok = (
                set(message) == {"role", "content", "tool_call_id"}
                and isinstance(message["content"], str)
                and isinstance(message["tool_call_id"], str)
            )
        else:
            ok = False
        if not ok:
            raise _invalid()
        input_bytes += len(str(message.get("content") or "").encode())
    payload: object = (
        messages if len(messages) == 2 and not offered else {"messages": messages, "tools": offered}
    )
    try:
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    except (TypeError, ValueError, RecursionError):
        raise _invalid() from None
    if len(encoded) > max_bytes:
        raise ValidationError(message="Inference messages exceed bounded request size")
    # UTF-8 bytes plus fixed message framing is an explicit conservative
    # accounting convention. It does not promise a universal token upper bound.
    if offered:
        input_bytes += len(json.dumps(offered, ensure_ascii=False).encode())
    return hashlib.sha256(encoded).hexdigest(), input_bytes


def message_identity(messages: object) -> tuple[str, int]:
    """Only the adapter's pinned system prompt and bounded user data are supported."""
    if not isinstance(messages, list) or len(messages) != 2:
        raise _invalid()
    return conversation_identity(messages)


def identity_limit(policy: InferencePolicy) -> int:
    """Encoded-request ceiling for a route: JSON framing over its input limit."""
    return max(_LEGACY_IDENTITY_BYTES, policy.max_input_bytes * 2)


class InferenceBinding(Snapshot):
    policy_version: ShortText
    policy: InferencePolicy
    routed_tier: InferenceTier
    rates: TokenRates
    messages_digest: Digest
    estimated_prompt_tokens: Annotated[int, Field(ge=0, le=4_194_304)]
    reservation_usd: Money
    config_digest: Digest
    gateway_revision: Digest
    anonymization_expected: bool
    # ADR 0038 D4: whether function schemas were offered on this request. A
    # response may carry tool calls only when they were.
    tools_offered: bool = False

    @field_serializer("reservation_usd")
    def serialize_reservation(self, value: Decimal) -> str:
        return format(value, ".4f")

    @model_serializer(mode="wrap")
    def serialize_binding(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        value = handler(self)
        if not self.tools_offered:
            # Keep the 0.8.0 form for a request without tools: this dump is
            # part of the effect's identity.
            value.pop("tools_offered", None)
        return value

    def matches(self, params: dict[str, Any]) -> bool:
        tools = params.get("tools")
        digest, _ = conversation_identity(
            params.get("messages"), tools, max_bytes=identity_limit(self.policy)
        )
        return (
            params.get("model") == self.policy.model_key
            and params.get("max_tokens") == self.policy.max_output_tokens
            and params.get("reasoning_effort") == self.policy.reasoning_effort
            and digest == self.messages_digest
            and bool(tools) is self.tools_offered
        )


class InferenceRoutes:
    def __init__(self, *, gateway: Any, operator: Callable[[], OperatorPolicy | None]) -> None:
        self.gateway, self.operator = gateway, operator

    async def bind(
        self,
        plan: PreparedPlan | PlanningSnapshot,
        scope: ExecutionScope,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> InferenceBinding:
        operator = self.operator()
        if (
            operator is None
            or operator.version() != plan.policy_version
            or operator.inference is None
        ):
            raise Forbidden(message="Orchestration inference policy is disabled or changed")
        policy = operator.inference
        digest, input_bytes = conversation_identity(
            messages, tools, max_bytes=identity_limit(policy)
        )
        if input_bytes > policy.max_input_bytes:
            raise InputLimitExceeded(message="Inference input exceeds approved byte limit")
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
            # requests deliberately skip rewriting. ``wanted`` is what the run
            # asks for; ``available`` is what the operator's gateway setting
            # does at this route's tier.
            wanted = scope.anonymize and not scope.privileged
            available = anon.get("enabled") is True and tier in anon["apply_at_tiers"]
            if wanted and not available and operator.require_anonymization:
                # A policy that requires it cannot be silently skipped by config.
                raise ValueError("required anonymization is unavailable")
            # Where the policy does not require it, the run follows the
            # operator's setting (ADR 0038 D5). Either way the response must
            # report exactly this, or the call is refused as untrusted, and the
            # gateway revision pinned at intake stops a setting changed mid-run.
            expected = wanted and available
            estimated = input_bytes + 48 * len(messages)  # per-message plus completion framing
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
                tools_offered=bool(tools),
            )
        except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError):
            raise Forbidden(
                message="Inference route, protection or pricing is unavailable"
            ) from None
        current = self.operator()
        if current is None or current.version() != binding.policy_version:
            raise Forbidden(message="Orchestration inference policy is disabled or changed")
        return binding


def _tool_calls(message: Any) -> list[dict[str, str]]:
    """Normalize a model's requested calls into bounded data, never authority.

    A malformed entry is kept with an empty name or arguments, so the loop
    refuses it and tells the model, rather than making the run uncertain for
    what is only a badly formed request. Calls past the cap are dropped.

    Arguments are bounded in bytes, per call and across the turn. This reply is
    retained as its effect's result, which the store bounds; oversized
    arguments are emptied here so they are refused, not left to make that
    record unwritable.
    """
    raw = getattr(message, "tool_calls", None)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("unsupported tool call list")
    calls: list[dict[str, str]] = []
    seen: set[str] = set()
    remaining = _TURN_ARGUMENT_BYTES
    for index, item in enumerate(raw[:MAX_TOOL_CALLS]):
        entry = item if isinstance(item, dict) else getattr(item, "__dict__", {})
        function = entry.get("function") if isinstance(entry, dict) else None
        if not isinstance(function, dict):
            function = getattr(function, "__dict__", {}) or {}
        call_id, name, arguments = entry.get("id"), function.get("name"), function.get("arguments")
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        # The id is echoed back to the provider beside the result, so it must be
        # a plain token and unique within the turn.
        if not isinstance(call_id, str) or _CALL_ID.fullmatch(call_id) is None or call_id in seen:
            call_id = f"call_{index}"
        seen.add(call_id)
        size = len(arguments.encode("utf-8", "replace")) if isinstance(arguments, str) else 0
        if not isinstance(arguments, str) or size > min(_CALL_ARGUMENT_BYTES, remaining):
            arguments = ""
        else:
            remaining -= size
        calls.append(
            {
                "id": call_id,
                "name": name if isinstance(name, str) and len(name) <= 128 else "",
                "arguments": arguments,
            }
        )
    return calls


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
        ):
            raise ValueError("response differs from binding")
        message = response.choices[0].message
        calls = _tool_calls(message)
        finish = response.choices[0].finish_reason
        if calls and not binding.tools_offered:
            # No schema was offered, so no call can run. The provider outcome
            # is known; the reply is simply not an answer. Keep the truthful
            # reason and drop the calls: callers accept only ``stop``.
            calls, finish = [], "tool_calls"
        if calls:
            # Adapters differ on the reason they report beside tool calls.
            finish = "tool_calls"
        content = message.content
        if finish == "tool_calls" and content is None:
            content = ""
        if not isinstance(content, str):
            raise ValueError("response has no text")
        usage = response.usage
        counts = (usage.prompt_tokens, usage.completion_tokens)
        if any(type(c) is not int or not 0 <= c <= 1_000_000_000 for c in counts):
            raise ValueError("invalid usage observation")
        observed = binding.rates.cost(*counts)
        if finish not in {"stop", "length", "content_filter", "tool_calls"}:
            raise ValueError("unsupported completion outcome")
    except (AttributeError, TypeError, ValueError, ArithmeticError):
        raise ValidationError(
            message="Inference response is untrusted; reconciliation is required"
        ) from None
    charged = max(binding.reservation_usd, observed)
    data: dict[str, Any] = {
        "intent": intent,
        "content": content,
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
            "tier": binding.routed_tier,
            "anonymization_applied": binding.anonymization_expected,
            "config_digest": binding.config_digest,
            # What was sent, as a digest: the system message, the opening
            # message, any tool turns and the offered schemas. The owner's
            # read of how a run was set up rebuilds the request and compares.
            "messages_digest": binding.messages_digest,
        },
    }
    if calls:
        data["tool_calls"] = calls
    return ToolResult(cost_usd=charged, data=data)
