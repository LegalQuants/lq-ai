"""Tests for the GovInfo tool-provider adapter skeleton (WS-E PR1a, Task 1).

Transport, auth header, type-check, and error-for-unknown-tool.
The two ops (search_authority / get_authority) land in Task 2."""

import httpx
import pytest
import respx

from app.config import ToolProviderConfig
from app.providers.tool.govinfo import GovInfoToolAdapter


def _adapter(monkeypatch):
    monkeypatch.setattr("app.providers.tool.egress._resolve_ips", lambda host: ["93.184.216.34"])
    monkeypatch.setenv("GOVINFO_API_KEY", "test-key")
    cfg = ToolProviderConfig.model_validate(
        {
            "name": "govinfo-prod",
            "type": "govinfo",
            "base_url": "https://api.govinfo.gov",
            "api_key_env": "GOVINFO_API_KEY",
            "egress_tier": 4,
            "allowlist": {"hosts": ["api.govinfo.gov"]},
            "rate_limit": {"requests_per_minute": 60},
        }
    )
    return GovInfoToolAdapter.from_config(cfg)


@pytest.mark.asyncio
async def test_from_config_type_check():
    cfg = ToolProviderConfig.model_validate(
        {
            "name": "x",
            "type": "courtlistener",
            "base_url": "https://www.courtlistener.com",
            "egress_tier": 4,
            "allowlist": {"hosts": ["www.courtlistener.com"]},
            "rate_limit": {"requests_per_minute": 60},
        }
    )
    with pytest.raises(ValueError):
        GovInfoToolAdapter.from_config(cfg)


@pytest.mark.asyncio
async def test_request_sends_x_api_key_header(monkeypatch):
    adapter = _adapter(monkeypatch)
    with respx.mock:
        route = respx.get("https://api.govinfo.gov/collections").mock(
            return_value=httpx.Response(200, json={"collections": []})
        )
        await adapter._request("GET", "/collections")
    assert route.calls.last.request.headers["X-Api-Key"] == "test-key"


@pytest.mark.asyncio
async def test_unknown_tool_raises(monkeypatch):
    from app.providers.tool.base import ToolProviderError

    adapter = _adapter(monkeypatch)
    with pytest.raises(ToolProviderError):
        await adapter.invoke_tool("nope", {}, request_id="r1")
