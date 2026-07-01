"""Tests for the SEC EDGAR tool-provider adapter (WS-E PR2a Task 1).

Auth model differs from GovInfo/CourtListener: SEC requires a descriptive
User-Agent header and no API key (fair-access policy). Public filing text,
so results are marked ``skip_anonymization=True`` for verbatim citation
grounding (ADR 0014 D5), mirroring the GovInfo/CourtListener adapters."""

import httpx
import pytest
import respx

from app.config import ToolProviderConfig
from app.providers.tool.edgar import EdgarToolAdapter

_CFG_DICT = {
    "name": "edgar-prod",
    "type": "edgar",
    "base_url": "https://efts.sec.gov",
    "egress_tier": 4,
    "allowlist": {"hosts": ["efts.sec.gov", "www.sec.gov"]},
    "user_agent": "LQ.AI test ops@lq.ai",
}


def _cfg(**overrides: object) -> ToolProviderConfig:
    merged = dict(_CFG_DICT)
    merged.update(overrides)
    return ToolProviderConfig.model_validate(merged)


def _adapter(monkeypatch: pytest.MonkeyPatch) -> EdgarToolAdapter:
    monkeypatch.setattr("app.providers.tool.egress._resolve_ips", lambda host: ["93.184.216.34"])
    return EdgarToolAdapter.from_config(_cfg())


# ---------------------------------------------------------------------------
# from_config: no API key, User-Agent required
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_from_config_requires_no_api_key_and_sets_user_agent() -> None:
    adapter = EdgarToolAdapter.from_config(_cfg())
    assert adapter._user_agent == "LQ.AI test ops@lq.ai"


@pytest.mark.unit
def test_from_config_rejects_missing_user_agent() -> None:
    with pytest.raises(ValueError, match="user_agent"):
        EdgarToolAdapter.from_config(_cfg(user_agent=None))


@pytest.mark.unit
def test_from_config_type_check() -> None:
    cfg = ToolProviderConfig.model_validate(
        {
            "name": "x",
            "type": "govinfo",
            "base_url": "https://api.govinfo.gov",
            "api_key_env": "GOVINFO_API_KEY",
            "egress_tier": 4,
            "allowlist": {"hosts": ["api.govinfo.gov"]},
        }
    )
    with pytest.raises(ValueError):
        EdgarToolAdapter.from_config(cfg)


# ---------------------------------------------------------------------------
# search_authority — normalization + external_ref construction
# ---------------------------------------------------------------------------

_SEARCH_BODY = {
    "hits": {
        "total": {"value": 42, "relation": "eq"},
        "hits": [
            {
                "_id": "0001193125-09-237465:dex992.htm",
                "_source": {
                    "ciks": ["0001005010"],
                    "display_names": ["ARTHROCARE CORP  (CIK 0001005010)"],
                    "form": "10-K",
                    "adsh": "0001193125-09-237465",
                    "file_date": "2009-11-18",
                },
            }
        ],
    }
}


@pytest.mark.unit
async def test_search_authority_normalizes_hits_and_builds_external_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter(monkeypatch)
    with respx.mock:
        respx.get("https://efts.sec.gov/LATEST/search-index").mock(
            return_value=httpx.Response(200, json=_SEARCH_BODY)
        )
        out = await adapter.invoke_tool("search_authority", {"query": "revenue"}, request_id="r1")
    assert out.payload["count"] == 42
    r0 = out.payload["results"][0]
    assert r0["external_ref"] == "1005010_000119312509237465_dex992.htm"
    assert r0["form_type"] == "10-K"
    assert r0["filed_date"] == "2009-11-18"
    assert out.skip_anonymization is True


@pytest.mark.unit
async def test_search_authority_sends_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter(monkeypatch)
    with respx.mock:
        route = respx.get("https://efts.sec.gov/LATEST/search-index").mock(
            return_value=httpx.Response(200, json=_SEARCH_BODY)
        )
        await adapter.invoke_tool("search_authority", {"query": "revenue"}, request_id="r1")
    assert route.calls.last.request.headers["User-Agent"] == "LQ.AI test ops@lq.ai"


@pytest.mark.unit
async def test_search_authority_empty_query_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.tool.base import ToolProviderInvalidRequestError

    adapter = _adapter(monkeypatch)
    with pytest.raises(ToolProviderInvalidRequestError):
        await adapter.invoke_tool("search_authority", {"query": ""}, request_id="r2")


# ---------------------------------------------------------------------------
# get_authority — archives URL construction + HTML stripping
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_get_authority_builds_archives_url_and_strips_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter(monkeypatch)
    with respx.mock:
        route = respx.get(
            "https://www.sec.gov/Archives/edgar/data/1005010/000119312509237465/dex992.htm"
        ).mock(return_value=httpx.Response(200, text="<html><body>Hello  world</body></html>"))
        out = await adapter.invoke_tool(
            "get_authority",
            {"external_ref": "1005010_000119312509237465_dex992.htm"},
            request_id="r1",
        )
    assert out.payload["url"] == (
        "https://www.sec.gov/Archives/edgar/data/1005010/000119312509237465/dex992.htm"
    )
    assert out.payload["text"] == "Hello world"
    assert out.payload["content_kind"] == "sec_filing"
    assert out.payload["external_ref"] == "1005010_000119312509237465_dex992.htm"
    assert out.skip_anonymization is True
    assert route.calls.last.request.headers["User-Agent"] == "LQ.AI test ops@lq.ai"


@pytest.mark.unit
async def test_get_authority_rejects_malformed_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.tool.base import ToolProviderInvalidRequestError

    adapter = _adapter(monkeypatch)
    with pytest.raises(ToolProviderInvalidRequestError):
        await adapter.invoke_tool(
            "get_authority", {"external_ref": "nodelimiters"}, request_id="r3"
        )


# ---------------------------------------------------------------------------
# Unknown tool + error mapping
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_unknown_tool_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.tool.base import ToolProviderError

    adapter = _adapter(monkeypatch)
    with pytest.raises(ToolProviderError):
        await adapter.invoke_tool("nope", {}, request_id="r1")


@pytest.mark.unit
async def test_rate_limited_raises_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.tool.base import ToolProviderHTTPError

    adapter = _adapter(monkeypatch)
    with respx.mock:
        respx.get("https://efts.sec.gov/LATEST/search-index").mock(return_value=httpx.Response(429))
        with pytest.raises(ToolProviderHTTPError):
            await adapter.invoke_tool("search_authority", {"query": "revenue"}, request_id="r1")


# ---------------------------------------------------------------------------
# Base-url validation (SSRF)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_validate_base_url_rejects_host_outside_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.providers.tool.egress import EgressRefused

    monkeypatch.setattr("app.providers.tool.egress._resolve_ips", lambda host: ["93.184.216.34"])
    adapter = EdgarToolAdapter.from_config(_cfg(base_url="https://evil.test"))
    with pytest.raises(EgressRefused):
        adapter.validate_base_url()
