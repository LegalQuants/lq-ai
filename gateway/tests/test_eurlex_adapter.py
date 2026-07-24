"""Tests for the EUR-Lex tool-provider adapter (WS-E PR2b Task 1; search DE-374).

Auth model mirrors EDGAR: a descriptive User-Agent header, no API key
(EU Publications Office Cellar service has no fair-access key scheme).
search_authority (DE-374) queries the Cellar SPARQL endpoint for title
matches and returns CELEX refs with no body; get_authority fetches the
document text by CELEX id. The Cellar ``/resource/celex/{CELEX}`` URL
303-redirects to a concrete manifestation whose ``Location`` is http;
egress is https-only, so the adapter upgrades the redirect target to https
and re-validates every hop against the allowlist before following it
(never lets httpx auto-follow an unvalidated/http hop)."""

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
# list_tools: search_authority + get_authority
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_list_tools_search_and_get_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter(monkeypatch)
    tools = await adapter.list_tools()
    assert [t.name for t in tools] == ["search_authority", "get_authority"]
    assert all(t.read_only for t in tools)


# ---------------------------------------------------------------------------
# search_authority — SPARQL query construction, escaping, parsing (DE-374)
# ---------------------------------------------------------------------------

_SPARQL_URL = "https://publications.europa.eu/webapi/rdf/sparql"


def _sparql_body(*rows: tuple[str, str]) -> dict:
    return {
        "head": {"vars": ["celex", "title"]},
        "results": {
            "bindings": [
                {
                    "celex": {"type": "literal", "value": celex},
                    "title": {"type": "literal", "value": title},
                }
                for celex, title in rows
            ]
        },
    }


@pytest.mark.unit
async def test_search_authority_builds_sparql_and_parses_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter(monkeypatch)
    body = _sparql_body(
        ("32016R0679", "General Data Protection Regulation"),
        ("32011L0083", "Consumer Rights Directive"),
    )
    with respx.mock:
        route = respx.get(_SPARQL_URL).mock(return_value=httpx.Response(200, json=body))
        out = await adapter.invoke_tool(
            "search_authority", {"query": "data protection"}, request_id="r1"
        )
        req = route.calls.last.request
        sparql = req.url.params["query"]
        assert 'CONTAINS(LCASE(STR(?title)), LCASE("data protection"))' in sparql
        assert "cdm:resource_legal_id_celex" in sparql
        assert sparql.endswith("LIMIT 10")
        assert req.headers["accept"] == "application/sparql-results+json"
        assert req.headers["user-agent"] == "LQ.AI test ops@lq.ai"
    assert out.payload["count"] == 2
    r0 = out.payload["results"][0]
    assert r0["external_ref"] == "32016R0679"
    assert r0["title"] == "General Data Protection Regulation"
    assert r0["url"] == "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679"
    assert "text" not in r0  # search results carry NO body (fail-closed contract)
    assert out.skip_anonymization is True


@pytest.mark.unit
async def test_search_authority_escapes_sparql_string_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hostile keyword must be embedded as an escaped literal — it can never
    terminate the string and inject SPARQL syntax into the FILTER clause."""
    adapter = _adapter(monkeypatch)
    hostile = "x\") } LIMIT 1 # \\ 'quote'\nnewline"
    with respx.mock:
        route = respx.get(_SPARQL_URL).mock(return_value=httpx.Response(200, json=_sparql_body()))
        await adapter.invoke_tool("search_authority", {"query": hostile}, request_id="r1")
        sparql = route.calls.last.request.url.params["query"]
    expected_literal = '"x\\") } LIMIT 1 # \\\\ \\\'quote\\\'\\nnewline"'
    assert f"LCASE({expected_literal})" in sparql
    # No raw double-quote inside the literal and no raw newline anywhere in it.
    assert 'LCASE("x") } LIMIT 1' not in sparql


@pytest.mark.unit
async def test_search_authority_respects_page_size(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter(monkeypatch)
    with respx.mock:
        route = respx.get(_SPARQL_URL).mock(return_value=httpx.Response(200, json=_sparql_body()))
        await adapter.invoke_tool(
            "search_authority", {"query": "gdpr", "page_size": 3}, request_id="r1"
        )
        assert route.calls.last.request.url.params["query"].endswith("LIMIT 3")
        # Bad page_size falls back to the default.
        await adapter.invoke_tool(
            "search_authority", {"query": "gdpr", "page_size": True}, request_id="r2"
        )
        assert route.calls.last.request.url.params["query"].endswith("LIMIT 10")


@pytest.mark.unit
async def test_search_authority_empty_results(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter(monkeypatch)
    with respx.mock:
        respx.get(_SPARQL_URL).mock(return_value=httpx.Response(200, json=_sparql_body()))
        out = await adapter.invoke_tool(
            "search_authority", {"query": "no such instrument"}, request_id="r1"
        )
    assert out.payload == {"results": [], "count": 0}


@pytest.mark.unit
async def test_search_authority_empty_query_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.tool.base import ToolProviderInvalidRequestError

    adapter = _adapter(monkeypatch)
    for bad in ("", "   ", None):
        with pytest.raises(ToolProviderInvalidRequestError):
            await adapter.invoke_tool("search_authority", {"query": bad}, request_id="r1")


@pytest.mark.unit
async def test_search_authority_drops_unfetchable_celex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hits whose CELEX get_authority would reject are dropped rather than
    surfaced with an unfetchable external_ref; treaty (12016E/TXT) and
    corrigendum (32016R0679R(01)) shapes are now fetchable (DE-375) and
    SURVIVE."""
    adapter = _adapter(monkeypatch)
    body = _sparql_body(
        ("32016R0679R(01)", "GDPR corrigendum"),  # corrigendum — now fetchable (DE-375)
        ("12016E/TXT", "TFEU"),  # treaty — now fetchable (DE-375)
        ("", "no celex at all"),  # dropped
        ("12016E/../etc", "traversal-shaped"),  # dropped — fails _VALID_CELEX_RE
        ("not a celex", "garbage"),  # dropped — fails _VALID_CELEX_RE
        ("32016R0679", "General Data Protection Regulation"),
    )
    with respx.mock:
        respx.get(_SPARQL_URL).mock(return_value=httpx.Response(200, json=body))
        out = await adapter.invoke_tool("search_authority", {"query": "gdpr"}, request_id="r1")
    assert [r["external_ref"] for r in out.payload["results"]] == [
        "32016R0679R(01)",
        "12016E/TXT",
        "32016R0679",
    ]
    assert out.payload["count"] == 3


@pytest.mark.unit
async def test_search_authority_redirect_hop_outside_allowlist_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A SPARQL-endpoint redirect to a non-allowlisted host must be refused
    before any egress to that host (every hop re-runs validate_egress_target)."""
    from app.providers.tool.egress import EgressRefused

    adapter = _adapter(monkeypatch)
    with respx.mock:
        respx.get(_SPARQL_URL).mock(
            return_value=httpx.Response(303, headers={"location": "http://evil.test/steal"})
        )
        evil = respx.get("https://evil.test/steal").mock(
            return_value=httpx.Response(200, json=_sparql_body())
        )
        with pytest.raises(EgressRefused):
            await adapter.invoke_tool("search_authority", {"query": "gdpr"}, request_id="r1")
        assert not evil.called  # refused before any egress to the rogue host


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
@pytest.mark.parametrize(
    "celex,valid",
    [
        ("32016R0679", True),  # regulation
        ("62014CJ0362", True),  # CJEU judgment (2-letter descriptor)
        ("12016E", True),  # bare treaty id (no number)
        ("12016E101", True),  # treaty article
        ("12016E/TXT", True),  # treaty full text (DE-375)
        ("12012P/TXT", True),  # Charter full text (DE-375)
        ("32016R0679R(01)", True),  # corrigendum (DE-375)
        ("02016R0679-20160504", True),  # consolidated version
        ("", False),
        ("garbage", False),
        ("12016E/PDF", False),  # only /TXT is a valid segment
        ("12016E/TXT/TXT", False),
        ("12016E/../TXT", False),
        ("12016e/txt", False),  # lowercase
        ("32016R0679R(001)", False),  # corrigendum needs exactly two digits
        ("32016R0679R()", False),
        ("32016R0679 ", False),  # whitespace
        ("2016R0679", False),  # missing sector digit
    ],
)
def test_valid_celex_re_shapes(celex: str, valid: bool) -> None:
    from app.providers.tool.eurlex import _VALID_CELEX_RE

    assert bool(_VALID_CELEX_RE.fullmatch(celex)) is valid


@pytest.mark.unit
async def test_get_authority_treaty_celex_url_quoted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A treaty CELEX (12016E/TXT, DE-375) is fetchable; the '/' is URL-quoted
    in the Cellar path while external_ref/url stay raw CELEX."""
    adapter = _adapter(monkeypatch)
    quoted_url = "https://publications.europa.eu/resource/celex/12016E%2FTXT"
    with respx.mock:
        route = respx.get(quoted_url).mock(
            return_value=httpx.Response(200, text="<html><body>Treaty  text</body></html>")
        )
        out = await adapter.invoke_tool(
            "get_authority", {"external_ref": "12016E/TXT"}, request_id="r1"
        )
        assert route.called
        # The '/' must be percent-encoded in the raw request path — never a
        # path segment of its own.
        assert b"12016E%2FTXT" in route.calls.last.request.url.raw_path
    assert out.payload["external_ref"] == "12016E/TXT"  # raw CELEX, user-visible
    assert out.payload["url"] == (
        "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:12016E/TXT"
    )
    assert out.payload["text"] == "Treaty text"
    assert out.payload["content_kind"] == "eu_legislation"  # sector 1 fallback


@pytest.mark.unit
async def test_get_authority_corrigendum_celex_url_quoted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A corrigendum CELEX (32016R0679R(01), DE-375) is fetchable; the parens
    are URL-quoted in the Cellar path while external_ref stays raw CELEX."""
    adapter = _adapter(monkeypatch)
    quoted_url = "https://publications.europa.eu/resource/celex/32016R0679R%2801%29"
    with respx.mock:
        route = respx.get(quoted_url).mock(
            return_value=httpx.Response(200, text="<html><body>Corrigendum</body></html>")
        )
        out = await adapter.invoke_tool(
            "get_authority", {"external_ref": "32016R0679R(01)"}, request_id="r1"
        )
        assert route.called
        assert b"32016R0679R%2801%29" in route.calls.last.request.url.raw_path
    assert out.payload["external_ref"] == "32016R0679R(01)"  # raw CELEX, user-visible
    assert out.payload["text"] == "Corrigendum"
    assert out.payload["content_kind"] == "eu_regulation"  # sector 3, type R


@pytest.mark.unit
async def test_get_authority_rejects_unsafe_celex_before_egress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ids failing full-CELEX validation (traversal, lowercase, stray
    segments, malformed suffixes) are 400ed before any egress (DE-375)."""
    from app.providers.tool.base import ToolProviderInvalidRequestError

    adapter = _adapter(monkeypatch)
    with respx.mock:
        route = respx.get(url__regex=r".*").mock(return_value=httpx.Response(200, text="x"))
        for bad in (
            "../../etc/passwd",  # path traversal
            "12016E/../TXT",  # traversal hidden in a treaty-looking id
            "12016E/PDF",  # only the literal /TXT segment is allowed
            "12016E/TXT/TXT",  # extra segment
            "12016e/txt",  # lowercase
            "32016R0679R(1)",  # corrigendum suffix must be two digits
            "32016R0679R(01",  # unbalanced paren
            "garbage",  # not CELEX-shaped at all
            "32016R0679 ",  # trailing whitespace
        ):
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
