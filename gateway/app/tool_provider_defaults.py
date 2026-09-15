"""Gateway-owned egress defaults for runtime-enableable tool providers.

The runtime admin API (`/admin/v1/tool-providers`) lets an operator enable a
registered authority source without hand-editing ``gateway.yaml``. To keep the
api service from ever setting an arbitrary egress target (SSRF, ADR 0014), the
**gateway** owns the base_url / allowlist / tier per type. The api passes only
``{type, api_key?, enabled?}``; this table fills everything else.

Values mirror the shipped ``gateway.yaml.example`` templates. An operator who
needs a different base_url / allowlist / User-Agent pre-adds the entry in
``gateway.yaml`` by hand; the writer then only touches the key fields on it.
"""

from __future__ import annotations

from dataclasses import dataclass

# Generic UA for the keyless sources (SEC fair-access / EUR-Lex both require a
# descriptive User-Agent, no API key). Operator-overridable via gateway.yaml.
_DEFAULT_USER_AGENT = "LQ.AI legal-research (self-hosted; set user_agent in gateway.yaml)"


@dataclass(frozen=True)
class ToolProviderDefault:
    """Immutable egress descriptor for one runtime-enableable tool provider."""

    type: str
    name: str  # canonical tool_providers[].name the writer creates
    base_url: str
    allowlist_hosts: tuple[str, ...]
    egress_tier: int
    rate_limit_rpm: int
    anonymize_outbound: bool
    key_required: bool
    api_key_env: str | None  # documented env var an operator MAY use instead
    user_agent: str | None


TOOL_PROVIDER_DEFAULTS: dict[str, ToolProviderDefault] = {
    "courtlistener": ToolProviderDefault(
        type="courtlistener",
        name="courtlistener-prod",
        base_url="https://www.courtlistener.com/api/rest/v4",
        allowlist_hosts=("www.courtlistener.com",),
        egress_tier=4,
        rate_limit_rpm=60,
        anonymize_outbound=True,
        key_required=True,
        api_key_env="COURTLISTENER_API_TOKEN",
        user_agent=None,
    ),
    "govinfo": ToolProviderDefault(
        type="govinfo",
        name="govinfo-prod",
        base_url="https://api.govinfo.gov",
        allowlist_hosts=("api.govinfo.gov",),
        egress_tier=4,
        rate_limit_rpm=60,
        anonymize_outbound=False,
        key_required=True,
        api_key_env="GOVINFO_API_KEY",
        user_agent=None,
    ),
    "edgar": ToolProviderDefault(
        type="edgar",
        name="edgar-prod",
        base_url="https://efts.sec.gov",
        allowlist_hosts=("efts.sec.gov", "www.sec.gov"),
        egress_tier=4,
        rate_limit_rpm=300,
        anonymize_outbound=False,
        key_required=False,
        api_key_env=None,
        user_agent=_DEFAULT_USER_AGENT,
    ),
    "eurlex": ToolProviderDefault(
        type="eurlex",
        name="eurlex-prod",
        base_url="https://publications.europa.eu",
        allowlist_hosts=("publications.europa.eu",),
        egress_tier=4,
        rate_limit_rpm=60,
        anonymize_outbound=False,
        key_required=False,
        api_key_env=None,
        user_agent=_DEFAULT_USER_AGENT,
    ),
}


__all__ = ["TOOL_PROVIDER_DEFAULTS", "ToolProviderDefault"]
