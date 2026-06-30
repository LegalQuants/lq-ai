"""Tests for the GovInfo tool-provider adapter (WS-E PR1a).

Task 1: transport, auth header, type-check, and error-for-unknown-tool.
Task 2: search_authority + get_authority ops, validation, and Router audit."""

import httpx
import pytest
import respx

from app.config import GatewayConfig, ToolProviderConfig
from app.providers.tool.govinfo import GovInfoToolAdapter

_CFG_DICT = {
    "name": "govinfo-prod",
    "type": "govinfo",
    "base_url": "https://api.govinfo.gov",
    "api_key_env": "GOVINFO_API_KEY",
    "egress_tier": 4,
    "allowlist": {"hosts": ["api.govinfo.gov"]},
    "rate_limit": {"requests_per_minute": 60},
}


def _cfg() -> ToolProviderConfig:
    return ToolProviderConfig.model_validate(_CFG_DICT)


def _adapter(monkeypatch) -> GovInfoToolAdapter:
    monkeypatch.setattr("app.providers.tool.egress._resolve_ips", lambda host: ["93.184.216.34"])
    monkeypatch.setenv("GOVINFO_API_KEY", "test-key")
    return GovInfoToolAdapter.from_config(_cfg())


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


# ---------------------------------------------------------------------------
# Task 2 — search_authority normalization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_authority_normalizes_results(monkeypatch) -> None:
    adapter = _adapter(monkeypatch)
    with respx.mock:
        respx.route(method__in=["GET", "POST"], host="api.govinfo.gov").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "packageId": "USCODE-2022-title15",
                            "title": "Title 15",
                            "collectionCode": "USCODE",
                            "dateIssued": "2022-01-01",
                        }
                    ],
                    "count": 1,
                },
            )
        )
        out = await adapter.invoke_tool(
            "search_authority",
            {"collection": "USCODE", "query": "antitrust"},
            request_id="r1",
        )
    assert out.payload["count"] == 1
    assert out.payload["results"][0]["package_id"] == "USCODE-2022-title15"
    assert out.payload["results"][0]["collection"] == "USCODE"


@pytest.mark.asyncio
async def test_search_authority_invalid_collection_raises(monkeypatch) -> None:
    """Unsupported collection code → ToolProviderInvalidRequestError."""
    from app.providers.tool.base import ToolProviderInvalidRequestError

    adapter = _adapter(monkeypatch)
    with pytest.raises(ToolProviderInvalidRequestError):
        await adapter.invoke_tool(
            "search_authority",
            {"collection": "BILLS", "query": "something"},
            request_id="r2",
        )


@pytest.mark.asyncio
async def test_search_authority_empty_query_raises(monkeypatch) -> None:
    """Empty query string → ToolProviderInvalidRequestError."""
    from app.providers.tool.base import ToolProviderInvalidRequestError

    adapter = _adapter(monkeypatch)
    with pytest.raises(ToolProviderInvalidRequestError):
        await adapter.invoke_tool(
            "search_authority",
            {"collection": "CFR", "query": ""},
            request_id="r3",
        )


# ---------------------------------------------------------------------------
# Task 2 — get_authority normalization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_authority_returns_text(monkeypatch) -> None:
    """get_authority fetches package summary then follows txtLink for content."""
    adapter = _adapter(monkeypatch)
    summary_json = {
        "packageId": "USCODE-2022-title15",
        "title": "Title 15 § 1",
        "download": {"txtLink": "https://api.govinfo.gov/packages/USCODE-2022-title15/htm"},
    }
    with respx.mock:
        # Both the summary GET and the text GET are intercepted by this route
        respx.route(method__in=["GET"], host="api.govinfo.gov").mock(
            return_value=httpx.Response(200, json=summary_json)
        )
        out = await adapter.invoke_tool(
            "get_authority",
            {"package_id": "USCODE-2022-title15"},
            request_id="r1",
        )
    assert "text" in out.payload
    assert out.payload["package_id"] == "USCODE-2022-title15"


@pytest.mark.asyncio
async def test_get_authority_empty_id_raises(monkeypatch) -> None:
    """Missing / blank package_id → ToolProviderInvalidRequestError."""
    from app.providers.tool.base import ToolProviderInvalidRequestError

    adapter = _adapter(monkeypatch)
    with pytest.raises(ToolProviderInvalidRequestError):
        await adapter.invoke_tool(
            "get_authority",
            {"package_id": ""},
            request_id="r4",
        )


# ---------------------------------------------------------------------------
# Task 2 — Router integration: egress-log row is written with refused=False
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_govinfo_through_router_writes_audit(monkeypatch) -> None:
    """route_tool_call("govinfo-prod","search_authority",...) writes refused=False."""
    from app.router import Router
    from app.tool_egress_log import RecordingToolEgressLogWriter

    monkeypatch.setattr("app.providers.tool.egress._resolve_ips", lambda host: ["93.184.216.34"])
    monkeypatch.setenv("GOVINFO_API_KEY", "test-key")
    cfg = GatewayConfig.model_validate({"tool_providers": [_CFG_DICT]})
    adapter = GovInfoToolAdapter.from_config(cfg.tool_providers[0])
    writer = RecordingToolEgressLogWriter()
    router = Router(
        config=cfg,
        adapters={},
        tool_adapters={"govinfo-prod": adapter},
        tool_egress_log=writer,
    )
    with respx.mock:
        respx.route(method__in=["GET", "POST"], host="api.govinfo.gov").mock(
            return_value=httpx.Response(
                200,
                json={"results": [], "count": 0},
            )
        )
        try:
            res = await router.route_tool_call(
                "govinfo-prod",
                "search_authority",
                {"collection": "USCODE", "query": "antitrust"},
                request_id="r1",
                max_allowed_tier=4,
            )
        finally:
            await adapter.aclose()
    assert res.payload["count"] == 0
    assert writer.rows[-1].refused is False
    assert writer.rows[-1].bytes_in is not None
