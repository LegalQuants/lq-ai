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


@pytest.mark.unit
async def test_verify_citations_shapes_payload(monkeypatch) -> None:
    adapter = _adapter(monkeypatch)
    api_resp = [
        {
            "citation": "576 U.S. 644",
            "normalized_citations": ["576 U.S. 644"],
            "start_index": 0,
            "end_index": 12,
            "status": 200,
            "error_message": "",
            "clusters": [
                {
                    "id": 2812209,
                    "case_name": "Obergefell v. Hodges",
                    "absolute_url": "/opinion/2812209/obergefell-v-hodges/",
                }
            ],
        }
    ]
    with respx.mock:
        route = respx.post(f"{BASE}/citation-lookup/").mock(
            return_value=httpx.Response(200, json=api_resp)
        )
        try:
            result = await adapter.invoke_tool(
                "verify_citations", {"text": "576 U.S. 644"}, request_id="r1"
            )
        finally:
            await adapter.aclose()
    assert route.called
    assert result.skip_anonymization is True
    cites = result.payload["citations"]
    assert cites[0]["citation"] == "576 U.S. 644"
    assert cites[0]["status"] == 200
    assert cites[0]["clusters"][0]["id"] == 2812209
    assert cites[0]["clusters"][0]["case_name"] == "Obergefell v. Hodges"


@pytest.mark.unit
async def test_verify_citations_rejects_empty_text(monkeypatch) -> None:
    adapter = _adapter(monkeypatch)
    try:
        with pytest.raises(ToolProviderInvalidRequestError):
            await adapter.invoke_tool("verify_citations", {"text": "  "}, request_id="r1")
    finally:
        await adapter.aclose()


@pytest.mark.unit
async def test_search_case_law_returns_count_and_results(monkeypatch) -> None:
    adapter = _adapter(monkeypatch)
    api_resp = {
        "count": 2,
        "next": "https://www.courtlistener.com/api/rest/v4/search/?cursor=abc&q=privacy",
        "previous": None,
        "results": [
            {
                "cluster_id": 111,
                "caseName": "Roe v. Wade",
                "court": "Supreme Court",
                "dateFiled": "1973-01-22",
                "citation": ["410 U.S. 113"],
                "absolute_url": "/opinion/111/roe-v-wade/",
                "snippet": "...privacy...",
            }
        ],
    }
    with respx.mock:
        route = respx.get(f"{BASE}/search/").mock(return_value=httpx.Response(200, json=api_resp))
        try:
            result = await adapter.invoke_tool("search_case_law", {"q": "privacy"}, request_id="r1")
        finally:
            await adapter.aclose()
    assert route.calls.last.request.url.params["type"] == "o"
    assert route.calls.last.request.url.params["q"] == "privacy"
    assert result.payload["count"] == 2
    assert result.payload["results"][0]["cluster_id"] == 111
    assert result.payload["results"][0]["case_name"] == "Roe v. Wade"
    assert result.payload["next_cursor"] == "abc"


@pytest.mark.unit
async def test_search_case_law_rejects_empty_query(monkeypatch) -> None:
    adapter = _adapter(monkeypatch)
    try:
        with pytest.raises(ToolProviderInvalidRequestError):
            await adapter.invoke_tool("search_case_law", {"q": ""}, request_id="r1")
    finally:
        await adapter.aclose()
