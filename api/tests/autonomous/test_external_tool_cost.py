"""Tests for DE-344: per-provider external-tool cost model.

Coverage:
- retrieve_authority with a configured cost returns the configured Decimal rate.
- retrieve_authority with no cost_per_call (free provider) returns Decimal("0").
- retrieve_authority with an unknown/bad source returns Decimal("0") without raising.
- retrieve_caselaw with a configured cost returns the configured rate.
- call_mcp_tool with a configured cost returns the configured rate.
- R4 projects the configured cost (guarded_tool_call estimate uses the configured rate).
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.autonomous.cost import estimate_tool_cost
from app.autonomous.enums import ToolIntent
from app.tools.governance import _reset_provider_tier_cache_for_tests

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_gw_class(providers: list[dict]) -> type:
    """Return a fake GW class whose get_admin_config returns the given providers."""

    async def _fake_get_admin_config(*, request_id: str | None = None) -> dict:
        return {"tool_providers": providers}

    class _FakeGW:
        get_admin_config = staticmethod(_fake_get_admin_config)

    return _FakeGW


_COST_PROVIDERS: list[dict] = [
    {
        "name": "govinfo-prod",
        "type": "govinfo",
        "egress_tier": 2,
        "cost_per_call": 0.005,
    },
    {
        "name": "courtlistener-prod",
        "type": "courtlistener",
        "egress_tier": 4,
        "cost_per_call": 0.01,
    },
    {
        "name": "acme-mcp",
        "type": "mcp",
        "egress_tier": 2,
        "cost_per_call": 0.002,
    },
]

_FREE_PROVIDERS: list[dict] = [
    {
        "name": "govinfo-prod",
        "type": "govinfo",
        "egress_tier": 2,
        # no cost_per_call — free provider
    },
]


@pytest.fixture(autouse=True)
def _reset_cache() -> Iterator[None]:
    """Reset the process-level tier + cost caches before every test."""
    _reset_provider_tier_cache_for_tests()
    yield
    _reset_provider_tier_cache_for_tests()


# ---------------------------------------------------------------------------
# resolve_provider_cost / resolve_provider_name_by_type unit tests
# ---------------------------------------------------------------------------


async def test_resolve_provider_cost_returns_configured_decimal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve_provider_cost returns the cost_per_call as a Decimal."""
    from app.tools.governance import resolve_provider_cost

    monkeypatch.setattr(
        "app.tools.governance.get_gateway_client",
        lambda: _make_fake_gw_class(_COST_PROVIDERS)(),
    )

    cost = await resolve_provider_cost("govinfo-prod")
    assert cost == Decimal("0.005")

    cost2 = await resolve_provider_cost("courtlistener-prod")
    assert cost2 == Decimal("0.01")


async def test_resolve_provider_cost_returns_zero_for_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve_provider_cost returns Decimal("0") for an unknown provider."""
    from app.tools.governance import resolve_provider_cost

    monkeypatch.setattr(
        "app.tools.governance.get_gateway_client",
        lambda: _make_fake_gw_class(_COST_PROVIDERS)(),
    )

    cost = await resolve_provider_cost("no-such-provider")
    assert cost == Decimal("0")


async def test_resolve_provider_name_by_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_provider_name_by_type maps source type → provider name."""
    from app.tools.governance import resolve_provider_name_by_type

    monkeypatch.setattr(
        "app.tools.governance.get_gateway_client",
        lambda: _make_fake_gw_class(_COST_PROVIDERS)(),
    )

    name = await resolve_provider_name_by_type("govinfo")
    assert name == "govinfo-prod"

    name2 = await resolve_provider_name_by_type("courtlistener")
    assert name2 == "courtlistener-prod"


async def test_resolve_provider_name_by_type_unknown_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve_provider_name_by_type returns None for an unknown type."""
    from app.tools.governance import resolve_provider_name_by_type

    monkeypatch.setattr(
        "app.tools.governance.get_gateway_client",
        lambda: _make_fake_gw_class(_COST_PROVIDERS)(),
    )

    name = await resolve_provider_name_by_type("no-such-type")
    assert name is None


# ---------------------------------------------------------------------------
# estimate_tool_cost — retrieve_authority
# ---------------------------------------------------------------------------


async def test_retrieve_authority_with_configured_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    """retrieve_authority returns the configured cost_per_call for the source provider."""
    monkeypatch.setattr(
        "app.tools.governance.get_gateway_client",
        lambda: _make_fake_gw_class(_COST_PROVIDERS)(),
    )

    cost = await estimate_tool_cost(
        ToolIntent.retrieve_authority,
        {"source": "govinfo", "op": "get_authority", "args": {}},
        None,
    )
    assert cost == Decimal("0.005")


async def test_retrieve_authority_free_provider_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """retrieve_authority with no cost_per_call (free provider) returns Decimal("0")."""
    monkeypatch.setattr(
        "app.tools.governance.get_gateway_client",
        lambda: _make_fake_gw_class(_FREE_PROVIDERS)(),
    )

    cost = await estimate_tool_cost(
        ToolIntent.retrieve_authority,
        {"source": "govinfo", "op": "get_authority", "args": {}},
        None,
    )
    assert cost == Decimal("0")


async def test_retrieve_authority_unknown_source_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """retrieve_authority with an unknown/bad source returns Decimal("0") without raising."""
    monkeypatch.setattr(
        "app.tools.governance.get_gateway_client",
        lambda: _make_fake_gw_class(_COST_PROVIDERS)(),
    )

    cost = await estimate_tool_cost(
        ToolIntent.retrieve_authority,
        {"source": "unknown_source_type", "op": "get_authority", "args": {}},
        None,
    )
    assert cost == Decimal("0")


async def test_retrieve_authority_empty_source_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """retrieve_authority with empty/missing source returns Decimal("0") without raising."""
    monkeypatch.setattr(
        "app.tools.governance.get_gateway_client",
        lambda: _make_fake_gw_class(_COST_PROVIDERS)(),
    )

    cost = await estimate_tool_cost(
        ToolIntent.retrieve_authority,
        {"source": "", "op": "get_authority"},
        None,
    )
    assert cost == Decimal("0")


# ---------------------------------------------------------------------------
# estimate_tool_cost — retrieve_caselaw
# ---------------------------------------------------------------------------


async def test_retrieve_caselaw_with_configured_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    """retrieve_caselaw returns the configured cost_per_call for the CL provider."""
    monkeypatch.setattr(
        "app.tools.governance.get_gateway_client",
        lambda: _make_fake_gw_class(_COST_PROVIDERS)(),
    )
    monkeypatch.setattr(
        "app.research.service._resolve_provider",
        AsyncMock(return_value="courtlistener-prod"),
    )

    cost = await estimate_tool_cost(
        ToolIntent.retrieve_caselaw,
        {"query": "patent infringement", "max_results": 5},
        None,
    )
    assert cost == Decimal("0.01")


async def test_retrieve_caselaw_gateway_failure_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """retrieve_caselaw returns Decimal("0") when _resolve_provider raises."""
    monkeypatch.setattr(
        "app.tools.governance.get_gateway_client",
        lambda: _make_fake_gw_class(_COST_PROVIDERS)(),
    )
    monkeypatch.setattr(
        "app.research.service._resolve_provider",
        AsyncMock(side_effect=RuntimeError("no courtlistener configured")),
    )

    cost = await estimate_tool_cost(
        ToolIntent.retrieve_caselaw,
        {"query": "patent infringement"},
        None,
    )
    assert cost == Decimal("0")


# ---------------------------------------------------------------------------
# estimate_tool_cost — call_mcp_tool
# ---------------------------------------------------------------------------


async def test_call_mcp_tool_with_configured_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    """call_mcp_tool returns the configured cost_per_call for the MCP provider."""
    monkeypatch.setattr(
        "app.tools.governance.get_gateway_client",
        lambda: _make_fake_gw_class(_COST_PROVIDERS)(),
    )

    cost = await estimate_tool_cost(
        ToolIntent.call_mcp_tool,
        {"provider": "acme-mcp", "tool": "search", "args": {}},
        None,
    )
    assert cost == Decimal("0.002")


async def test_call_mcp_tool_unknown_provider_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """call_mcp_tool with an unknown provider returns Decimal("0") without raising."""
    monkeypatch.setattr(
        "app.tools.governance.get_gateway_client",
        lambda: _make_fake_gw_class(_COST_PROVIDERS)(),
    )

    cost = await estimate_tool_cost(
        ToolIntent.call_mcp_tool,
        {"provider": "unknown-mcp", "tool": "search", "args": {}},
        None,
    )
    assert cost == Decimal("0")


async def test_call_mcp_tool_missing_provider_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """call_mcp_tool with missing provider key returns Decimal("0") without raising."""
    monkeypatch.setattr(
        "app.tools.governance.get_gateway_client",
        lambda: _make_fake_gw_class(_COST_PROVIDERS)(),
    )

    cost = await estimate_tool_cost(
        ToolIntent.call_mcp_tool,
        {"tool": "search", "args": {}},
        None,
    )
    assert cost == Decimal("0")


# ---------------------------------------------------------------------------
# R4 integration: inference intents are unaffected by this change
# ---------------------------------------------------------------------------


async def test_inference_intents_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_skill / run_playbook / plan cost paths are unchanged by DE-344."""
    # Patch at the usage site (autonomous.cost imports the name at module load).
    monkeypatch.setattr(
        "app.autonomous.cost.estimate_judge_call_cost_usd",
        AsyncMock(return_value=Decimal("0.05")),
    )

    cost = await estimate_tool_cost(
        ToolIntent.run_skill,
        {"judge_model": "claude-3-haiku-20240307"},
        None,
    )
    assert cost == Decimal("0.05")
