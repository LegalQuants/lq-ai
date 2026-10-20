"""Service layer: status rows + hot-apply for tool providers."""

from app.config import GatewayConfig
from app.tool_provider_keys import list_tool_provider_status


def _config_with(tool_providers: list[dict]) -> GatewayConfig:
    return GatewayConfig.model_validate(
        {
            "providers": [
                {
                    "name": "anthropic",
                    "type": "anthropic",
                    "base_url": "https://x",
                    "api_key_env": "ANTHROPIC_API_KEY",
                    "tier": 3,
                    "models": ["claude"],
                }
            ],
            "model_aliases": {
                "fast": {"primary": {"provider": "anthropic", "model": "claude"}, "fallback": []}
            },
            "gateway_auth": {"enabled": False},
            "tool_providers": tool_providers,
        }
    )


def test_status_lists_all_four_types_even_when_none_configured() -> None:
    rows = list_tool_provider_status(_config_with([]), {})
    assert {r["type"] for r in rows} == {"courtlistener", "govinfo", "edgar", "eurlex"}
    assert all(r["enabled"] is False for r in rows)
    assert all(r["has_key"] is False for r in rows)
    # key_required flag comes from the gateway default registry
    by_type = {r["type"]: r for r in rows}
    assert by_type["courtlistener"]["key_required"] is True
    assert by_type["edgar"]["key_required"] is False


def test_status_enabled_reflects_live_adapter_presence() -> None:
    cfg = _config_with(
        [
            {
                "name": "edgar-prod",
                "type": "edgar",
                "base_url": "https://efts.sec.gov",
                "egress_tier": 4,
                "allowlist": {"hosts": ["efts.sec.gov", "www.sec.gov"]},
                "user_agent": "x",
            }
        ]
    )
    # Adapter live in the registry (keyed by name) -> enabled True.
    rows = list_tool_provider_status(cfg, {"edgar-prod": object()})
    assert next(r for r in rows if r["type"] == "edgar")["enabled"] is True
    # Config present but no live adapter -> enabled False.
    rows2 = list_tool_provider_status(cfg, {})
    assert next(r for r in rows2 if r["type"] == "edgar")["enabled"] is False


def test_status_has_key_true_for_runtime_keyed_entry() -> None:
    cfg = _config_with(
        [
            {
                "name": "courtlistener-prod",
                "type": "courtlistener",
                "base_url": "https://www.courtlistener.com/api/rest/v4",
                "egress_tier": 4,
                "allowlist": {"hosts": ["www.courtlistener.com"]},
                "api_key_encrypted": "gAAAAAB-x",
            }
        ]
    )
    row = next(
        r
        for r in list_tool_provider_status(cfg, {"courtlistener-prod": object()})
        if r["type"] == "courtlistener"
    )
    assert row["has_key"] is True
    assert row["source"] == "runtime"


def test_status_never_contains_the_ciphertext() -> None:
    cfg = _config_with(
        [
            {
                "name": "courtlistener-prod",
                "type": "courtlistener",
                "base_url": "https://www.courtlistener.com/api/rest/v4",
                "egress_tier": 4,
                "allowlist": {"hosts": ["www.courtlistener.com"]},
                "api_key_encrypted": "gAAAAAB-secret-ciphertext",
            }
        ]
    )
    text = repr(list_tool_provider_status(cfg, {}))
    for forbidden in ("api_key_encrypted", "gAAAAAB", "api_key"):
        assert forbidden not in text
