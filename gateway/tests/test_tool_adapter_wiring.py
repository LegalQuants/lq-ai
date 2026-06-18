"""Unit tests for the ``build_tool_adapter`` factory in ``app.main``.

Verifies:
* echo provider → ``EchoToolAdapter`` instance.
* base_url outside the allowlist → ``EgressRefused`` at build time.
* disabled provider → ``None`` (no adapter built).
* mcp provider → ``MCPToolProviderAdapter`` instance.
"""

import pytest

from app.config import GatewayConfig, ToolProviderConfig
from app.main import build_tool_adapter
from app.providers.tool.echo import EchoToolAdapter
from app.providers.tool.egress import EgressRefused


@pytest.mark.unit
def test_build_tool_adapter_echo(monkeypatch: pytest.MonkeyPatch) -> None:
    # Stub DNS resolution so this unit test works offline / in CI without a
    # live DNS lookup for the synthetic ``example.test`` domain.
    monkeypatch.setattr(
        "app.providers.tool.egress._resolve_ips",
        lambda host: ["93.184.216.34"],
    )
    cfg = GatewayConfig.model_validate(
        {
            "tool_providers": [
                {
                    "name": "echo-test",
                    "type": "echo",
                    "base_url": "https://example.test",
                    "egress_tier": 4,
                    "allowlist": {"hosts": ["example.test"]},
                }
            ]
        }
    )
    adapter = build_tool_adapter(cfg.tool_providers[0])
    assert isinstance(adapter, EchoToolAdapter)


@pytest.mark.unit
def test_build_tool_adapter_rejects_base_url_outside_allowlist() -> None:
    cfg = GatewayConfig.model_validate(
        {
            "tool_providers": [
                {
                    "name": "bad",
                    "type": "echo",
                    "base_url": "https://evil.test",
                    "egress_tier": 4,
                    "allowlist": {"hosts": ["example.test"]},
                }
            ]
        }
    )
    with pytest.raises(EgressRefused):
        build_tool_adapter(cfg.tool_providers[0])


@pytest.mark.unit
def test_build_tool_adapter_disabled_returns_none() -> None:
    cfg = GatewayConfig.model_validate(
        {
            "tool_providers": [
                {
                    "name": "off",
                    "type": "echo",
                    "enabled": False,
                    "base_url": "https://example.test",
                    "egress_tier": 4,
                    "allowlist": {"hosts": ["example.test"]},
                }
            ]
        }
    )
    assert build_tool_adapter(cfg.tool_providers[0]) is None


@pytest.mark.unit
def test_build_tool_adapter_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.tool import egress
    from app.providers.tool.mcp import MCPToolProviderAdapter

    monkeypatch.setattr(egress, "_resolve_ips", lambda host: ["93.184.216.34"])
    cfg = ToolProviderConfig.model_validate(
        {
            "name": "acme-mcp",
            "type": "mcp",
            "base_url": "https://mcp.acme.example/sse",
            "egress_tier": 2,
            "allowlist": {"hosts": ["mcp.acme.example"]},
            "auth": "none",
        }
    )
    adapter = build_tool_adapter(cfg)
    assert isinstance(adapter, MCPToolProviderAdapter)


@pytest.mark.unit
def test_build_tool_adapter_courtlistener(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.tool.courtlistener import CourtListenerToolAdapter

    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token-123")
    monkeypatch.setattr(
        "app.providers.tool.egress._resolve_ips",
        lambda host: ["93.184.216.34"],
    )
    cfg = GatewayConfig.model_validate(
        {
            "tool_providers": [
                {
                    "name": "cl",
                    "type": "courtlistener",
                    "base_url": "https://www.courtlistener.com/api/rest/v4",
                    "api_key_env": "COURTLISTENER_API_TOKEN",
                    "egress_tier": 4,
                    "allowlist": {"hosts": ["www.courtlistener.com"]},
                }
            ]
        }
    )
    adapter = build_tool_adapter(cfg.tool_providers[0])
    assert isinstance(adapter, CourtListenerToolAdapter)
