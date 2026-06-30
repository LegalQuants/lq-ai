"""Content-source registry for the autonomous legal-matter loop (WS-E).

The registry maps provider *types* (e.g. ``"govinfo"``) to their static
metadata — jurisdiction, coverage, available ops, and the response adapter.
At runtime ``resolve_available_sources`` joins the registry against the
gateway's live provider list to produce the set of sources the matter loop
may call.

Design constraints (ADR 0021 D5, P3 / ADR 0016):
- Metadata includes name/type/jurisdiction/coverage/content_kinds/ops only.
  NEVER auth keys, cost fields, or secret values.
- A registered type with no configured provider is reported ``enabled=False``
  (unavailable-with-reason).  It is never silently omitted.
- A provider whose type is not in the registry is excluded entirely — the
  loop only calls sources it has an adapter + spec for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.research.adapters import GovInfoAdapter, SourceAdapter

# ---------------------------------------------------------------------------
# SourceSpec — static registry entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceSpec:
    """Static descriptor for one authority-source type.

    :attr type:          Provider type key (matches ``gateway.yaml`` ``type:``).
    :attr jurisdiction:  Jurisdictional scope string.
    :attr coverage:      Human-readable description of what this source covers.
    :attr content_kinds: Tuple of content-kind strings this source produces.
    :attr ops:           Tuple of gateway tool-op names the source supports.
    :attr adapter:       Response adapter (``None`` for passthrough sources).
    """

    type: str
    jurisdiction: str
    coverage: str
    content_kinds: tuple[str, ...]
    ops: tuple[str, ...]
    adapter: SourceAdapter | None


# ---------------------------------------------------------------------------
# SOURCE_REGISTRY
# ---------------------------------------------------------------------------

SOURCE_REGISTRY: dict[str, SourceSpec] = {
    "courtlistener": SourceSpec(
        type="courtlistener",
        jurisdiction="us-federal",
        coverage="U.S. federal & state appellate caselaw (operator CourtListener key)",
        content_kinds=("caselaw",),
        # Tool ops as called via gateway.call_tool (service.py names):
        ops=("verify_citations", "search_case_law", "get_citing_opinions", "get_cases"),
        # Caselaw payloads are used directly; no normalisation adapter needed.
        adapter=None,
    ),
    "govinfo": SourceSpec(
        type="govinfo",
        jurisdiction="us-federal",
        coverage="U.S. Code + Code of Federal Regulations",
        content_kinds=("statute", "regulation"),
        ops=("search_authority", "get_authority"),
        adapter=GovInfoAdapter(),
    ),
}

# ---------------------------------------------------------------------------
# AvailableSource — runtime join of registry + gateway live config
# ---------------------------------------------------------------------------


@dataclass
class AvailableSource:
    """A source entry after joining the registry against live gateway config.

    :attr name:          Provider name from gateway.yaml (``None`` if unavailable).
    :attr type:          Provider type key.
    :attr jurisdiction:  From the registry spec.
    :attr coverage:      From the registry spec.
    :attr content_kinds: From the registry spec.
    :attr enabled:       ``True`` iff a matching provider is configured in the gateway.
    :attr egress_tier:   Egress tier from the provider config, if present; else ``None``.
    """

    name: str | None
    type: str
    jurisdiction: str
    coverage: str
    content_kinds: tuple[str, ...]
    enabled: bool
    egress_tier: int | None


# ---------------------------------------------------------------------------
# resolve_available_sources
# ---------------------------------------------------------------------------


async def resolve_available_sources(gateway: Any) -> list[AvailableSource]:
    """Join the SOURCE_REGISTRY against the gateway's live provider list.

    Calls ``gateway.list_tool_providers()`` (returns ``[{name, type, ...}]``)
    and intersects with ``SOURCE_REGISTRY``:

    - Registry type with a matching configured provider → ``enabled=True``.
    - Registry type with no configured provider → ``enabled=False``.
    - Configured provider whose type is NOT in the registry → excluded.

    The output list follows ``SOURCE_REGISTRY`` insertion order.
    No secrets or cost fields are ever included (P3 / ADR 0016).

    :param gateway: A ``GatewayClient`` (or compatible mock) with an async
                    ``list_tool_providers()`` method.
    :returns: One ``AvailableSource`` per registry entry.
    """
    raw_providers: list[dict[str, Any]] = await gateway.list_tool_providers()

    # Build a map of type → first provider with that type.
    # We only need one provider per type; multiple entries of the same type
    # are unusual in practice (gateway.yaml is operator-authored) and the
    # first wins.
    provider_by_type: dict[str, dict[str, Any]] = {}
    for p in raw_providers:
        ptype: str = p.get("type") or ""
        if ptype and ptype not in provider_by_type:
            provider_by_type[ptype] = p

    result: list[AvailableSource] = []
    for _key, spec in SOURCE_REGISTRY.items():
        provider = provider_by_type.get(spec.type)
        if provider is not None:
            egress_raw = provider.get("egress_tier")
            egress_tier: int | None = int(egress_raw) if egress_raw is not None else None
            result.append(
                AvailableSource(
                    name=provider.get("name"),
                    type=spec.type,
                    jurisdiction=spec.jurisdiction,
                    coverage=spec.coverage,
                    content_kinds=spec.content_kinds,
                    enabled=True,
                    egress_tier=egress_tier,
                )
            )
        else:
            # Registered type with no configured provider — report unavailable.
            result.append(
                AvailableSource(
                    name=None,
                    type=spec.type,
                    jurisdiction=spec.jurisdiction,
                    coverage=spec.coverage,
                    content_kinds=spec.content_kinds,
                    enabled=False,
                    egress_tier=None,
                )
            )

    return result
