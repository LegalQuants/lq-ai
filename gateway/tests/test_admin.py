"""Tests for the admin endpoints under ``/admin/v1``.

A3 ships a real ``GET /admin/v1/tier-config`` (returns the loaded
``tier_policy`` block) and 501 stubs for everything else.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.unit
async def test_tier_config_returns_loaded_policy(client: AsyncClient) -> None:
    """Loaded ``tier_policy`` block is exposed verbatim under /admin/v1."""

    response = await client.get("/admin/v1/tier-config")

    assert response.status_code == 200
    body = response.json()
    tier_policy = body["tier_policy"]

    # Values from gateway.yaml.example
    assert tier_policy["allowed_tiers_global"] == [1, 2, 3, 4]
    assert tier_policy["default_minimum_tier"] == 4
    assert tier_policy["privileged_minimum_tier"] == 3


@pytest.mark.unit
async def test_providers_health_returns_501(client: AsyncClient) -> None:
    response = await client.get("/admin/v1/providers/health")
    assert response.status_code == 501
    body = response.json()
    assert body["error"]["code"] == "not_implemented"


@pytest.mark.unit
async def test_usage_returns_501(client: AsyncClient) -> None:
    response = await client.get("/admin/v1/usage")
    assert response.status_code == 501
    body = response.json()
    assert body["error"]["code"] == "not_implemented"


@pytest.mark.unit
async def test_anonymization_config_returns_loaded_block(client: AsyncClient) -> None:
    """Loaded ``anonymization`` block is exposed verbatim under /admin/v1.

    The M2 middleware shipped and runs; this read surface reflects the
    live config rather than the old 501 stub.
    """

    response = await client.get("/admin/v1/anonymization-config")

    assert response.status_code == 200
    body = response.json()
    anonymization = body["anonymization"]

    # Values from gateway.yaml.example
    assert anonymization["enabled"] is False
    assert anonymization["apply_at_tiers"] == [3, 4, 5]
    # Passthrough keys (AnonymizationConfig has extra="allow") survive round-trip.
    assert "person_name" in anonymization["entity_types"]
