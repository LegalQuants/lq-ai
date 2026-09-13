"""Exact authority-source bindings from current gateway and operator policy.

Fetch configuration before opening the guard's transaction. No legacy process
cache, type-based provider selection, implicit free rate or model-owned binding.
Gateway configuration revisions are not yet conditional on dispatch; deployment
must still provide coordinated policy/configuration updates before enablement.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from pydantic import field_serializer

from app.autonomous.orchestration.contracts import (
    Digest,
    ExecutionScope,
    Money,
    PreparedPlan,
    ShortText,
    Snapshot,
)
from app.autonomous.orchestration.policy import OperatorPolicy, SourcePolicy
from app.errors import Forbidden
from app.research.registry import SOURCE_REGISTRY


class SourceBinding(Snapshot):
    policy_version: ShortText
    source: SourcePolicy
    operation: ShortText
    cost_usd: Money
    config_digest: Digest
    gateway_revision: Digest

    @field_serializer("cost_usd")
    def serialize_cost(self, value: Decimal) -> str:
        return format(value, ".4f")


class AuthoritySources:
    def __init__(self, *, gateway: Any, operator: Callable[[], OperatorPolicy | None]) -> None:
        self.gateway, self.operator = gateway, operator

    async def bind(
        self,
        plan: PreparedPlan,
        scope: ExecutionScope,
        *,
        source_name: str,
        operation: str,
    ) -> SourceBinding:
        policy = self.operator()
        if policy is None or policy.version() != plan.policy_version:
            raise Forbidden(message="Orchestration operator policy is disabled or changed")
        source = next((s for s in policy.sources if s.name == source_name), None)
        if (
            source is None
            or source_name not in scope.resources.source_names
            or operation not in source.operations
            or source.egress_tier > scope.maximum_egress_tier
            or SOURCE_REGISTRY[source.source_type].adapter is None
        ):
            raise Forbidden(message="Authority source operation is outside approved scope")
        # Tool dispatch does not yet implement the configured anonymization
        # transform. Never silently send raw arguments for an anonymized scope.
        if scope.anonymize:
            raise Forbidden(message="Authority-source anonymization is not implemented")

        config = await self.gateway.get_admin_config()
        try:
            entries = config["tool_providers"]
            if not isinstance(entries, list):
                raise ValueError("invalid catalog")
            matches = [p for p in entries if isinstance(p, dict) and p.get("name") == source.name]
            if len(matches) != 1:
                raise ValueError("ambiguous or missing provider")
            entry = matches[0]
            if (
                entry.get("enabled") is not True
                or entry.get("type") != source.source_type
                or type(entry.get("egress_tier")) is not int
                or entry["egress_tier"] != source.egress_tier
            ):
                raise ValueError("provider differs from policy")
            # Gateway JSON/YAML permits numeric extras. Convert their decimal
            # spelling once at this boundary; never do float budget arithmetic.
            raw = entry["cost_per_call"]
            if type(raw) not in (str, int, float):
                raise ValueError("missing or invalid explicit rate")
            price = Decimal(str(raw))
            # Bound magnitude before fixed-point formatting; a malformed rate
            # with an enormous exponent must not allocate an enormous string.
            if not price.is_finite() or not 0 <= price <= Decimal("999999.9999"):
                raise ValueError("rate outside accounting range")
            unit = entry.get("cost_per_unit")
            if unit is not None and (
                type(unit) not in (str, int, float) or Decimal(str(unit)) != 0
            ):
                raise ValueError("variable pricing has no supported meter")
            # Keep only public routing/accounting fields in the fingerprint.
            # Never retain the admin payload or credentials in a receipt.
            routing = {
                key: entry.get(key)
                for key in ("name", "type", "base_url", "egress_tier", "enabled", "allowlist")
            }
            routing["cost_per_call"] = format(price, ".4f")
            binding = SourceBinding(
                policy_version=plan.policy_version,
                source=source,
                operation=operation,
                cost_usd=price,
                config_digest=hashlib.sha256(
                    json.dumps(routing, sort_keys=True, allow_nan=False).encode()
                ).hexdigest(),
                gateway_revision=config["configuration_revision"],
            )
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise Forbidden(
                message="Authority provider configuration or pricing is unavailable"
            ) from None
        # A policy refresh while config I/O was pending cannot produce a binding
        # to the previous policy. Durable admission checks current policy again.
        current = self.operator()
        if current is None or current.version() != binding.policy_version:
            raise Forbidden(message="Orchestration operator policy is disabled or changed")
        return binding
