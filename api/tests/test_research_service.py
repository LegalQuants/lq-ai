from collections.abc import Iterator

import httpx
import pytest
import respx
from sqlalchemy import select

from app.errors import ResearchNotConfigured
from app.models.research import ResearchOpinionMetadata
from app.research import service

GW = "http://localhost:8001"  # default settings.lq_ai_gateway_url

# ---------------------------------------------------------------------------
# Provider-cache isolation — MUST run around every test so a cached name from
# one test cannot leak into another (the cache is a process-level global).
# ---------------------------------------------------------------------------

_CL_CONFIG_RESP = {"tool_providers": [{"name": "courtlistener-prod", "type": "courtlistener"}]}


@pytest.fixture(autouse=True)
def _prime_and_reset_provider_cache() -> Iterator[None]:
    """Prime the resolved-provider cache before each test so existing tests
    that call the tool path work without mocking /admin/v1/config, then reset
    it after so no state leaks between tests."""
    service._resolved_provider = "courtlistener-prod"
    yield
    service.reset_provider_cache()


@pytest.fixture
def fake_storage(monkeypatch):
    store: dict[str, bytes] = {}

    async def _upload(*, storage_path: str, body: bytes, content_type: str) -> None:
        store[storage_path] = body

    class _Reader:
        def __init__(self, data: bytes) -> None:
            self._data = data

        async def __aenter__(self):
            data = self._data

            async def _gen():
                yield data

            return _gen()

        async def __aexit__(self, *a):
            return False

    def _download(*, storage_path: str):
        return _Reader(store[storage_path])

    monkeypatch.setattr("app.research.service.upload_bytes", _upload)
    monkeypatch.setattr("app.research.service.stream_download", _download)
    return store


@pytest.mark.asyncio
async def test_get_cluster_fetches_caches_then_serves_from_cache(db_session, fake_storage) -> None:
    cluster = {
        "id": 5,
        "case_name": "X v. Y",
        "case_name_short": "X",
        "date_filed": "2020-01-01",
        "citations": [],
        "court": "scotus",
        "absolute_url": "/opinion/5/",
    }
    gw_payload = {
        "provider": "courtlistener-prod",
        "tool": "get_cases",
        "tier": 4,
        "payload": {
            "cluster": cluster,
            "opinions": [
                {
                    "id": 9,
                    "text_field_used": "html_with_citations",
                    "text": "<p>Held: it is so.</p>",
                }
            ],
        },
    }
    with respx.mock:
        route = respx.post(f"{GW}/v1/tools/courtlistener-prod/get_cases").mock(
            return_value=httpx.Response(200, json=gw_payload)
        )
        out1 = await service.get_cluster(db_session, cluster_id=5)
        out2 = await service.get_cluster(db_session, cluster_id=5)
    assert out1["cluster"]["case_name"] == "X v. Y"
    assert out1["opinions"][0]["opinion_id"] == 9
    assert out2["opinions"][0]["opinion_id"] == 9
    assert route.call_count == 1  # 2nd call from cache, no gateway hit
    op = (
        await db_session.execute(
            select(ResearchOpinionMetadata).where(ResearchOpinionMetadata.opinion_id == 9)
        )
    ).scalar_one()
    body = fake_storage[op.storage_path].decode()
    assert "Held: it is so." in body
    assert "<p>" not in body


@pytest.mark.asyncio
async def test_read_opinion_404_when_not_fetched(db_session, fake_storage) -> None:
    from app.errors import NotFound

    with pytest.raises(NotFound):
        await service.read_opinion(db_session, opinion_id=999)


@pytest.mark.asyncio
async def test_find_in_case_returns_matches(db_session, fake_storage) -> None:
    fake_storage["k"] = b"The right to privacy is fundamental. Privacy again here."
    db_session.add(
        ResearchOpinionMetadata(
            opinion_id=9, cluster_id=5, text_field_used="x", storage_path="k", char_length=56
        )
    )
    await db_session.flush()
    matches = await service.find_in_case(db_session, opinion_id=9, query="privacy", max_matches=3)
    assert len(matches) >= 1
    assert "privacy" in matches[0]["snippet"].lower()


@pytest.mark.asyncio
async def test_verify_citations_passthrough(db_session) -> None:
    with respx.mock:
        respx.post(f"{GW}/v1/tools/courtlistener-prod/verify_citations").mock(
            return_value=httpx.Response(
                200,
                json={
                    "provider": "courtlistener-prod",
                    "tool": "verify_citations",
                    "tier": 4,
                    "payload": {
                        "citations": [{"citation": "347 U.S. 483", "status": 200, "clusters": []}]
                    },
                },
            )
        )
        out = await service.verify_citations("347 U.S. 483")
    assert out["citations"][0]["citation"] == "347 U.S. 483"


# ---------------------------------------------------------------------------
# get_capabilities tests (always reads fresh from gateway)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_capabilities_enabled_when_courtlistener_configured() -> None:
    service.reset_provider_cache()
    with respx.mock:
        respx.get(f"{GW}/admin/v1/config").mock(
            return_value=httpx.Response(200, json=_CL_CONFIG_RESP)
        )
        caps = await service.get_capabilities()
    assert caps["enabled"] is True
    assert len(caps["providers"]) == 1
    assert caps["providers"][0]["name"] == "courtlistener-prod"
    assert caps["providers"][0]["type"] == "courtlistener"


@pytest.mark.asyncio
async def test_get_capabilities_disabled_when_no_courtlistener_configured() -> None:
    service.reset_provider_cache()
    with respx.mock:
        respx.get(f"{GW}/admin/v1/config").mock(
            return_value=httpx.Response(200, json={"tool_providers": []})
        )
        caps = await service.get_capabilities()
    assert caps["enabled"] is False
    assert caps["providers"] == []


# ---------------------------------------------------------------------------
# _resolve_provider tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_provider_returns_configured_name_and_caches() -> None:
    service.reset_provider_cache()
    with respx.mock:
        route = respx.get(f"{GW}/admin/v1/config").mock(
            return_value=httpx.Response(200, json=_CL_CONFIG_RESP)
        )
        name1 = await service._resolve_provider()
        name2 = await service._resolve_provider()  # second call uses the cache

    assert name1 == "courtlistener-prod"
    assert name2 == "courtlistener-prod"
    # The gateway should only have been called once — second call uses the cache.
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_resolve_provider_raises_when_none_configured() -> None:
    service.reset_provider_cache()
    with respx.mock:
        respx.get(f"{GW}/admin/v1/config").mock(
            return_value=httpx.Response(200, json={"tool_providers": []})
        )
        with pytest.raises(ResearchNotConfigured):
            await service._resolve_provider()
