"""Tests for autonomous-related defaults on the backend Settings object.

Task M4-D2 (real-executor-work) §5 introduces a global fallback cap on
per-session cost for autonomous sessions whose spawning trigger (watch
or schedule) did not specify ``max_cost_usd``. The default mirrors the
gateway.yaml default ($5.00). Operators can override via
``LQ_AI_AUTONOMOUS_DEFAULT_MAX_COST_USD``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.config import get_settings


def test_autonomous_default_max_cost_usd_present_with_sane_default() -> None:
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.autonomous_default_max_cost_usd == Decimal("5.00")
    finally:
        get_settings.cache_clear()


def test_autonomous_default_max_cost_usd_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LQ_AI_AUTONOMOUS_DEFAULT_MAX_COST_USD", "1.25")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.autonomous_default_max_cost_usd == Decimal("1.25")
    finally:
        get_settings.cache_clear()
