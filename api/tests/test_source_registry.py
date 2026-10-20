from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest

from app.research.adapters import (
    EdgarAdapter,
    EurLexAdapter,
    FetchedAuthority,
    GovInfoAdapter,
    _content_kind_from_id,
)
from app.research.registry import SOURCE_REGISTRY, resolve_available_sources
from app.tools.governance import _reset_provider_tier_cache_for_tests

# ---------------------------------------------------------------------------
# Cache isolation — reset the process-level governance tier cache around every
# test so egress_tier lookups don't bleed across tests.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_tier_cache() -> Iterator[None]:
    _reset_provider_tier_cache_for_tests()
    yield
    _reset_provider_tier_cache_for_tests()


# ---------------------------------------------------------------------------
# Registry structure
# ---------------------------------------------------------------------------


def test_registry_has_courtlistener_and_govinfo() -> None:
    assert "courtlistener" in SOURCE_REGISTRY and "govinfo" in SOURCE_REGISTRY
    assert "search_authority" in SOURCE_REGISTRY["govinfo"].ops


def test_edgar_registered_with_sec_filing_kind() -> None:
    spec = SOURCE_REGISTRY["edgar"]
    assert spec.type == "edgar"
    assert spec.content_kinds == ("sec_filing",)
    assert spec.ops == ("search_authority", "get_authority")
    assert spec.adapter is not None


# ---------------------------------------------------------------------------
# resolve_available_sources — join logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_intersects_enabled_and_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Patch governance get_gateway_client so the tier-cache load returns an
    # empty tool_providers list (all providers default to _MAX_TIER).  This
    # keeps the test isolated from the real gateway and avoids a noisy HTTP
    # call being swallowed by _load_provider_tier_cache's exception handler.
    async def _fake_get_admin_config(*, request_id: str | None = None) -> dict:
        return {"tool_providers": []}

    class _FakeGW:
        get_admin_config = staticmethod(_fake_get_admin_config)

    monkeypatch.setattr("app.tools.governance.get_gateway_client", lambda: _FakeGW())

    gw = AsyncMock()
    gw.list_tool_providers.return_value = [
        {"name": "govinfo-prod", "type": "govinfo"},
        {"name": "mystery", "type": "not_in_registry"},  # excluded
    ]
    out = await resolve_available_sources(gw)
    by_type = {s.type: s for s in out}
    assert by_type["govinfo"].name == "govinfo-prod" and by_type["govinfo"].enabled is True
    assert "not_in_registry" not in by_type
    # a registry type with no configured provider is reported unavailable
    assert by_type["courtlistener"].enabled is False
    # disabled source has no provider → egress_tier must be None
    assert by_type["courtlistener"].egress_tier is None


@pytest.mark.asyncio
async def test_resolve_egress_tier_from_governance_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """egress_tier is resolved from the admin-config governance cache, not from
    the list_tool_providers payload (which only carries {name, type} in prod).
    Asserts that a CONFIGURED tier actually surfaces on the enabled source."""

    async def _fake_get_admin_config(*, request_id: str | None = None) -> dict:
        return {
            "tool_providers": [
                {"name": "govinfo-prod", "type": "govinfo", "egress_tier": 4},
            ]
        }

    class _FakeGW:
        get_admin_config = staticmethod(_fake_get_admin_config)

    monkeypatch.setattr("app.tools.governance.get_gateway_client", lambda: _FakeGW())

    gw = AsyncMock()
    # list_tool_providers returns {name, type} ONLY — matching the real
    # GatewayClient projection.  No egress_tier here (that would be the bug).
    gw.list_tool_providers.return_value = [
        {"name": "govinfo-prod", "type": "govinfo"},
    ]
    out = await resolve_available_sources(gw)
    by_type = {s.type: s for s in out}

    assert by_type["govinfo"].enabled is True
    assert by_type["govinfo"].egress_tier == 4, (
        "egress_tier must be resolved from the governance admin-config cache, "
        "not from the list_tool_providers payload"
    )


# ---------------------------------------------------------------------------
# GovInfoAdapter
# ---------------------------------------------------------------------------


def test_govinfo_adapter_from_response_get() -> None:
    fa = GovInfoAdapter().from_response(
        "get_authority",
        {
            "package_id": "USCODE-2022-title15",
            "title": "15 U.S.C. § 1",
            "citation": "15 U.S.C. § 1",
            "url": "https://www.govinfo.gov/...",
            "text": "Every contract ... in restraint of trade ... is declared to be illegal.",
        },
    )
    assert isinstance(fa, FetchedAuthority)
    assert fa.external_ref == "USCODE-2022-title15"
    assert "restraint of trade" in fa.citable_text
    assert fa.content_kind in {"statute", "regulation"}


# ---------------------------------------------------------------------------
# _content_kind_from_id — honest catch-all
# ---------------------------------------------------------------------------


def test_content_kind_from_id_uscode_returns_statute() -> None:
    assert _content_kind_from_id("USCODE-2022-title15") == "statute"


def test_content_kind_from_id_cfr_returns_regulation() -> None:
    assert _content_kind_from_id("CFR-2023-title12-vol1") == "regulation"


def test_content_kind_from_id_unknown_returns_unknown() -> None:
    """A non-USCODE/CFR package_id must return 'unknown', not 'statute'.

    Returning 'statute' for an unrecognised id would be a confident mislabel
    (anti-overclaiming posture, PRD §1.3 transparency principle).
    """
    assert _content_kind_from_id("BILLS-2022-s1234") == "unknown"
    assert _content_kind_from_id("CREC-2023-pt1") == "unknown"
    assert _content_kind_from_id("") == "unknown"


# ---------------------------------------------------------------------------
# EdgarAdapter
# ---------------------------------------------------------------------------


def test_edgar_get_authority_maps_to_fetched_authority() -> None:
    payload = {
        "external_ref": "1005010_000119312509237465_dex992.htm",
        "title": "dex992.htm",
        "url": "https://www.sec.gov/Archives/edgar/data/1005010/000119312509237465/dex992.htm",
        "text": "Revenue recognition policy ...",
        "content_kind": "sec_filing",
    }
    fa = EdgarAdapter().from_response("get_authority", payload)
    assert isinstance(fa, FetchedAuthority)
    assert fa.content_kind == "sec_filing"
    assert fa.external_ref == "1005010_000119312509237465_dex992.htm"
    assert fa.citable_text == "Revenue recognition policy ..."
    assert fa.url.endswith("dex992.htm")


def test_edgar_search_authority_is_title_only_body() -> None:
    payload = {
        "results": [
            {
                "external_ref": "1005010_000119312509237465_dex992.htm",
                "form_type": "10-K",
                "company": "ARTHROCARE CORP",
                "filed_date": "2009-11-18",
                "title": "ARTHROCARE CORP — 10-K (2009-11-18)",
            }
        ],
        "count": 1,
    }
    fa = EdgarAdapter().from_response("search_authority", payload)
    assert fa.content_kind == "sec_filing"
    # search bodies are NOT quotable full text — citable_text is the title/label only
    assert "ARTHROCARE" in fa.citable_text


# ---------------------------------------------------------------------------
# EurLexAdapter
# ---------------------------------------------------------------------------


def test_eurlex_get_authority_maps_to_fetched_authority() -> None:
    payload = {
        "external_ref": "32016R0679",
        "title": "32016R0679",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679",
        "text": "Article 6 lawfulness of processing ...",
        "content_kind": "eu_regulation",
    }
    fa = EurLexAdapter().from_response("get_authority", payload)
    assert fa.content_kind == "eu_regulation"
    assert fa.external_ref == "32016R0679"
    assert fa.citable_text.startswith("Article 6")
    assert "CELEX:32016R0679" in fa.url


def test_eurlex_unsupported_op_raises() -> None:
    with pytest.raises(ValueError):
        EurLexAdapter().from_response("search_authority", {})


# ---------------------------------------------------------------------------
# eurlex registry entry
# ---------------------------------------------------------------------------


def test_eurlex_registered_get_only() -> None:
    spec = SOURCE_REGISTRY["eurlex"]
    assert spec.type == "eurlex"
    assert spec.ops == ("get_authority",)
    assert "eu_regulation" in spec.content_kinds
    assert spec.adapter is not None
