from unittest.mock import AsyncMock

import pytest

from app.research.adapters import FetchedAuthority, GovInfoAdapter
from app.research.registry import SOURCE_REGISTRY, resolve_available_sources


def test_registry_has_courtlistener_and_govinfo():
    assert "courtlistener" in SOURCE_REGISTRY and "govinfo" in SOURCE_REGISTRY
    assert "search_authority" in SOURCE_REGISTRY["govinfo"].ops


@pytest.mark.asyncio
async def test_resolve_intersects_enabled_and_registered():
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


def test_govinfo_adapter_from_response_get():
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
