import httpx
import pytest
import respx

from app.config import ToolProviderConfig
from app.providers.tool.base import (
    ToolProviderAuthError,
    ToolProviderInvalidRequestError,
)
from app.providers.tool.courtlistener import CourtListenerToolAdapter

BASE = "https://www.courtlistener.com/api/rest/v4"


def _cfg(**over) -> ToolProviderConfig:
    base = {
        "name": "courtlistener-prod",
        "type": "courtlistener",
        "base_url": BASE,
        "api_key_env": "COURTLISTENER_API_TOKEN",
        "egress_tier": 4,
        "allowlist": {"hosts": ["www.courtlistener.com"]},
    }
    base.update(over)
    return ToolProviderConfig.model_validate(base)


def _adapter(monkeypatch) -> CourtListenerToolAdapter:
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token-123")
    monkeypatch.setattr("app.providers.tool.egress._resolve_ips", lambda host: ["93.184.216.34"])
    return CourtListenerToolAdapter.from_config(_cfg())


@pytest.mark.unit
async def test_lists_three_read_tools(monkeypatch) -> None:
    adapter = _adapter(monkeypatch)
    try:
        names = {t.name for t in await adapter.list_tools()}
        assert names == {"verify_citations", "search_case_law", "get_cases"}
        assert all(t.read_only for t in await adapter.list_tools())
    finally:
        await adapter.aclose()


@pytest.mark.unit
async def test_request_sends_token_auth_header(monkeypatch) -> None:
    adapter = _adapter(monkeypatch)
    with respx.mock:
        route = respx.get(f"{BASE}/clusters/1/").mock(
            return_value=httpx.Response(200, json={"id": 1})
        )
        try:
            await adapter._request("GET", "/clusters/1/")
        finally:
            await adapter.aclose()
    assert route.called
    assert route.calls.last.request.headers["Authorization"] == "Token test-token-123"


@pytest.mark.unit
async def test_request_maps_401_to_auth_error(monkeypatch) -> None:
    adapter = _adapter(monkeypatch)
    with respx.mock:
        respx.get(f"{BASE}/clusters/1/").mock(return_value=httpx.Response(401))
        with pytest.raises(ToolProviderAuthError):
            try:
                await adapter._request("GET", "/clusters/1/")
            finally:
                await adapter.aclose()


@pytest.mark.unit
async def test_request_maps_400_to_invalid_request(monkeypatch) -> None:
    adapter = _adapter(monkeypatch)
    with respx.mock:
        respx.get(f"{BASE}/clusters/1/").mock(return_value=httpx.Response(400))
        with pytest.raises(ToolProviderInvalidRequestError):
            try:
                await adapter._request("GET", "/clusters/1/")
            finally:
                await adapter.aclose()


@pytest.mark.unit
async def test_invoke_unknown_tool_raises(monkeypatch) -> None:
    from app.providers.tool.base import ToolProviderError

    adapter = _adapter(monkeypatch)
    try:
        with pytest.raises(ToolProviderError):
            await adapter.invoke_tool("nope", {}, request_id="r1")
    finally:
        await adapter.aclose()
