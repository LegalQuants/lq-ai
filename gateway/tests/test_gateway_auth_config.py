"""Tests for the gateway-auth startup/reload configuration gate.

Pen-test 2026-09-25 finding gateway#F5: with gateway_auth.enabled but no key
configured, the request-path gate accepted every request (fail-open). The
gateway now refuses to start (lifespan) and refuses to hot-reload
(reload_from_disk) in that state, via check_gateway_auth_configured.
"""

from __future__ import annotations

import pytest

from app.config import GatewayConfig, check_gateway_auth_configured


@pytest.mark.unit
def test_enabled_without_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LQ_AI_GATEWAY_KEY", raising=False)
    config = GatewayConfig.model_validate({"gateway_auth": {"enabled": True}})
    msg = check_gateway_auth_configured(config)
    assert msg is not None
    assert "LQ_AI_GATEWAY_KEY" in msg


@pytest.mark.unit
def test_enabled_with_key_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LQ_AI_GATEWAY_KEY", "a-real-key")
    config = GatewayConfig.model_validate({"gateway_auth": {"enabled": True}})
    assert check_gateway_auth_configured(config) is None


@pytest.mark.unit
def test_disabled_is_accepted_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LQ_AI_GATEWAY_KEY", raising=False)
    config = GatewayConfig.model_validate({"gateway_auth": {"enabled": False}})
    assert check_gateway_auth_configured(config) is None


@pytest.mark.unit
def test_custom_env_name_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LQ_AI_GATEWAY_KEY", raising=False)
    monkeypatch.delenv("CUSTOM_GW_KEY", raising=False)
    config = GatewayConfig.model_validate(
        {"gateway_auth": {"enabled": True, "api_key_env": "CUSTOM_GW_KEY"}}
    )
    msg = check_gateway_auth_configured(config)
    assert msg is not None and "CUSTOM_GW_KEY" in msg
    monkeypatch.setenv("CUSTOM_GW_KEY", "set-now")
    assert check_gateway_auth_configured(config) is None
