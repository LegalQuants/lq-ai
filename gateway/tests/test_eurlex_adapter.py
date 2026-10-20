"""Tests for the EUR-Lex tool-provider adapter (WS-E PR2b Task 1).

Auth model mirrors EDGAR: a descriptive User-Agent header, no API key
(EU Publications Office Cellar service has no fair-access key scheme).
get_authority only (search lands as DE-374). The Cellar
``/resource/celex/{CELEX}`` URL 303-redirects to a concrete manifestation
whose ``Location`` is http; egress is https-only, so the adapter upgrades
the redirect target to https and re-validates every hop against the
allowlist before following it (never lets httpx auto-follow an
unvalidated/http hop)."""

import httpx
import pytest
import respx

from app.config import ToolProviderConfig
from app.providers.tool.eurlex import EurLexToolAdapter, _content_kind_from_celex

_CFG_DICT = {
    "name": "eurlex-prod",
    "type": "eurlex",
    "base_url": "https://publications.europa.eu",
    "egress_tier": 4,
    "allowlist": {"hosts": ["publications.europa.eu"]},
    "user_agent": "LQ.AI test ops@lq.ai",
}


def _cfg(**overrides: object) -> ToolProviderConfig:
    merged = dict(_CFG_DICT)
    merged.update(overrides)
    return ToolProviderConfig.model_validate(merged)


def _adapter(monkeypatch: pytest.MonkeyPatch) -> EurLexToolAdapter:
    monkeypatch.setattr("app.providers.tool.egress._resolve_ips", lambda host: ["93.184.216.34"])
    return EurLexToolAdapter.from_config(_cfg())


# ---------------------------------------------------------------------------
# from_config: no API key, User-Agent required
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_from_config_requires_user_agent_no_key() -> None:
    with pytest.raises(ValueError, match="user_agent"):
        EurLexToolAdapter.from_config(_cfg(user_agent=None))


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
        EurLexToolAdapter.from_config(cfg)


# ---------------------------------------------------------------------------
# content_kind derivation from CELEX
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "celex,kind",
    [
        ("32016R0679", "eu_regulation"),
        ("32011L0083", "eu_directive"),
        ("32014D0123", "eu_decision"),
        ("62014CJ0362", "eu_caselaw"),
        ("12016E", "eu_legislation"),  # sector 1 treaty-ish -> fallback
        ("garbage", "eu_legislation"),  # unparseable -> fallback
    ],
)
def test_content_kind_from_celex(celex: str, kind: str) -> None:
    assert _content_kind_from_celex(celex) == kind


# ---------------------------------------------------------------------------
# list_tools: get_authority only
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_list_tools_only_get_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter(monkeypatch)
    tools = await adapter.list_tools()
    assert [t.name for t in tools] == ["get_authority"]
    assert all(t.read_only for t in tools)


# ---------------------------------------------------------------------------
# get_authority — redirect-follow, https-upgrade, HTML stripping
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_get_authority_follows_redirect_upgrades_https_strips_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter(monkeypatch)
    celex_url = "https://publications.europa.eu/resource/celex/32016R0679"
    doc_http = "http://publications.europa.eu/resource/cellar/abc/DOC_1"  # 303 target is http
    doc_https = "https://publications.europa.eu/resource/cellar/abc/DOC_1"
    with respx.mock:
        celex_route = respx.get(celex_url).mock(
            return_value=httpx.Response(303, headers={"location": doc_http})
        )
        doc_route = respx.get(doc_https).mock(
            return_value=httpx.Response(200, text="<html><body>Article 6  lawful</body></html>")
        )
        out = await adapter.invoke_tool(
            "get_authority", {"external_ref": "32016R0679"}, request_id="r1"
        )
        # Accept-Language + User-Agent sent on the first request
        req = celex_route.calls.last.request
        assert req.headers["accept-language"] == "eng"
        assert req.headers["user-agent"] == "LQ.AI test ops@lq.ai"
    assert doc_route.called  # fetched the HTTPS-upgraded manifestation
    assert out.payload["text"] == "Article 6 lawful"  # tag-stripped, whitespace-collapsed
    assert out.payload["content_kind"] == "eu_regulation"
    assert out.payload["external_ref"] == "32016R0679"
    assert out.skip_anonymization is True


@pytest.mark.unit
async def test_get_authority_rejects_unsafe_celex_before_egress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.providers.tool.base import ToolProviderInvalidRequestError

    adapter = _adapter(monkeypatch)
    with respx.mock:
        route = respx.get(url__regex=r".*").mock(return_value=httpx.Response(200, text="x"))
        for bad in ("12016E/TXT", "32016R0679R(01)"):
            with pytest.raises(ToolProviderInvalidRequestError):
                await adapter.invoke_tool("get_authority", {"external_ref": bad}, request_id="r1")
        assert not route.called  # rejected before any egress


@pytest.mark.unit
async def test_get_authority_missing_celex_404_maps_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.providers.tool.base import ToolProviderInvalidRequestError

    adapter = _adapter(monkeypatch)
    url = "https://publications.europa.eu/resource/celex/99999X9999"
    with respx.mock:
        respx.get(url).mock(return_value=httpx.Response(404))
        with pytest.raises(ToolProviderInvalidRequestError):
            await adapter.invoke_tool(
                "get_authority", {"external_ref": "99999X9999"}, request_id="r1"
            )


@pytest.mark.unit
async def test_get_authority_empty_ref_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.tool.base import ToolProviderInvalidRequestError

    adapter = _adapter(monkeypatch)
    with pytest.raises(ToolProviderInvalidRequestError):
        await adapter.invoke_tool("get_authority", {"external_ref": ""}, request_id="r1")


# ---------------------------------------------------------------------------
# Unknown tool + base-url validation (SSRF)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_unknown_tool_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.tool.base import ToolProviderError

    adapter = _adapter(monkeypatch)
    with pytest.raises(ToolProviderError):
        await adapter.invoke_tool("nope", {}, request_id="r1")


@pytest.mark.unit
def test_validate_base_url_rejects_host_outside_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.providers.tool.egress import EgressRefused

    monkeypatch.setattr("app.providers.tool.egress._resolve_ips", lambda host: ["93.184.216.34"])
    adapter = EurLexToolAdapter.from_config(_cfg(base_url="https://evil.test"))
    with pytest.raises(EgressRefused):
        adapter.validate_base_url()
