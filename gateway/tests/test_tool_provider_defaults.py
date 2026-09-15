"""TOOL_PROVIDER_DEFAULTS is the gateway-owned egress truth (ADR 0014)."""

from app.config import ToolProviderConfig
from app.tool_provider_defaults import TOOL_PROVIDER_DEFAULTS, ToolProviderDefault  # noqa: F401


def test_registry_covers_exactly_the_four_authority_types() -> None:
    assert set(TOOL_PROVIDER_DEFAULTS) == {"courtlistener", "govinfo", "edgar", "eurlex"}


def test_key_required_matches_source_semantics() -> None:
    assert TOOL_PROVIDER_DEFAULTS["courtlistener"].key_required is True
    assert TOOL_PROVIDER_DEFAULTS["govinfo"].key_required is True
    assert TOOL_PROVIDER_DEFAULTS["edgar"].key_required is False
    assert TOOL_PROVIDER_DEFAULTS["eurlex"].key_required is False


def test_keyless_sources_carry_a_default_user_agent() -> None:
    assert TOOL_PROVIDER_DEFAULTS["edgar"].user_agent
    assert TOOL_PROVIDER_DEFAULTS["eurlex"].user_agent


def test_every_default_builds_a_valid_tool_provider_config() -> None:
    # A default + a fake encrypted key (or keyless) must validate against
    # the real ToolProviderConfig model — proves the writer emits valid YAML.
    for d in TOOL_PROVIDER_DEFAULTS.values():
        entry: dict = {
            "name": d.name,
            "type": d.type,
            "base_url": d.base_url,
            "egress_tier": d.egress_tier,
            "allowlist": {"hosts": list(d.allowlist_hosts)},
            "rate_limit": {"requests_per_minute": d.rate_limit_rpm},
            "anonymize_outbound": d.anonymize_outbound,
        }
        if d.user_agent:
            entry["user_agent"] = d.user_agent
        if d.key_required:
            entry["api_key_encrypted"] = "gAAAAAB-fake"
        ToolProviderConfig.model_validate(entry)  # raises on malformation
