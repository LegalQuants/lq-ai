import pytest

from app.config import GatewayConfig, ToolProviderConfig


@pytest.mark.unit
def test_tool_provider_config_parses_minimal() -> None:
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
    assert len(cfg.tool_providers) == 1
    tp = cfg.tool_providers[0]
    assert isinstance(tp, ToolProviderConfig)
    assert tp.name == "echo-test"
    assert tp.egress_tier == 4
    assert tp.allowlist.hosts == ["example.test"]
    assert tp.anonymize_outbound is True  # default per ADR 0014 D5


@pytest.mark.unit
def test_tool_provider_rejects_both_key_sources() -> None:
    with pytest.raises(ValueError, match="api_key_env OR"):
        ToolProviderConfig.model_validate(
            {
                "name": "x",
                "type": "echo",
                "base_url": "https://example.test",
                "egress_tier": 4,
                "allowlist": {"hosts": ["example.test"]},
                "api_key_env": "FOO",
                "api_key_encrypted": "gAAAA",
            }
        )


@pytest.mark.unit
def test_tool_provider_requires_nonempty_allowlist() -> None:
    with pytest.raises(ValueError):
        ToolProviderConfig.model_validate(
            {
                "name": "x",
                "type": "echo",
                "base_url": "https://example.test",
                "egress_tier": 4,
                "allowlist": {"hosts": []},
            }
        )


@pytest.mark.unit
def test_tool_provider_by_name_accessor() -> None:
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
    assert cfg.tool_provider_by_name("echo-test") is not None
    assert cfg.tool_provider_by_name("missing") is None
