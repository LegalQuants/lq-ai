"""Live CourtListener integration test (provider-marked).

Runs only when ``COURTLISTENER_API_TOKEN`` is set in the environment, mirroring
``test_anthropic_provider.py``'s real-provider gating. CI/unit runs skip it.
"""

import os

import pytest

from app.config import ToolProviderConfig
from app.providers.tool.courtlistener import CourtListenerToolAdapter

BASE = "https://www.courtlistener.com/api/rest/v4"


@pytest.mark.provider
async def test_verify_citations_live() -> None:
    """Live CourtListener call — runs only when COURTLISTENER_API_TOKEN is set."""
    if not os.environ.get("COURTLISTENER_API_TOKEN"):
        pytest.skip("COURTLISTENER_API_TOKEN not set; skipping live test")
    cfg = ToolProviderConfig.model_validate(
        {
            "name": "courtlistener-live",
            "type": "courtlistener",
            "base_url": BASE,
            "api_key_env": "COURTLISTENER_API_TOKEN",
            "egress_tier": 4,
            "allowlist": {"hosts": ["www.courtlistener.com"]},
        }
    )
    adapter = CourtListenerToolAdapter.from_config(cfg)
    try:
        # Brown v. Board of Education, 347 U.S. 483 — a stable, famous citation.
        result = await adapter.invoke_tool(
            "verify_citations", {"text": "347 U.S. 483"}, request_id="live-1"
        )
    finally:
        await adapter.aclose()
    cites = result.payload["citations"]
    assert cites, "expected at least one citation result"
    assert cites[0]["status"] == 200
    assert any("Brown" in (c.get("case_name") or "") for c in cites[0]["clusters"])
