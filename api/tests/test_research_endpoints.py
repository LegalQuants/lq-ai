"""Integration tests for the /api/v1/research surface (WS3b).

Covers:
- POST /api/v1/research/verify-citations
- POST /api/v1/research/search
- GET  /api/v1/research/clusters/{cluster_id}
- GET  /api/v1/research/opinions/{opinion_id}
- POST /api/v1/research/find-in-case
- Unauthenticated → 401 gate

Gateway calls are mocked with respx; storage is monkeypatched via
the same fake_storage fixture pattern established in test_research_service.py.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.research import service as research_service
from app.security import create_access_token, hash_password

GW = "http://localhost:8001"  # default settings.lq_ai_gateway_url


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _prime_and_reset_provider_cache() -> Iterator[None]:
    """Prime the resolved-provider cache so existing tool-path tests don't
    need to mock GET /admin/v1/config, then reset after to prevent leaks."""
    research_service._resolved_provider = "courtlistener-prod"
    yield
    research_service.reset_provider_cache()


@pytest_asyncio.fixture
async def db_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"research-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Research Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _bearer(user: User) -> str:
    return create_access_token(user.id, user.email, is_admin=user.is_admin)


def _h(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {_bearer(user)}"}


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """In-process AsyncClient with the test DB session wired in."""

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def fake_storage(monkeypatch):
    """Monkeypatch upload_bytes / stream_download in the research service."""
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


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_verify_citations_unauthenticated_returns_401(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/research/verify-citations", json={"text": "Brown v. Board"})
    assert resp.status_code == 401


@pytest.mark.integration
async def test_search_unauthenticated_returns_401(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/research/search", json={"q": "contract law"})
    assert resp.status_code == 401


@pytest.mark.integration
async def test_get_cluster_unauthenticated_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/research/clusters/5")
    assert resp.status_code == 401


@pytest.mark.integration
async def test_read_opinion_unauthenticated_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/research/opinions/9")
    assert resp.status_code == 401


@pytest.mark.integration
async def test_find_in_case_unauthenticated_returns_401(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/research/find-in-case",
        json={"opinion_id": 9, "query": "privacy"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /verify-citations
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_verify_citations_passthrough(client: AsyncClient, db_user: User) -> None:
    gw_resp = {
        "provider": "courtlistener-prod",
        "tool": "verify_citations",
        "tier": 4,
        "payload": {"citations": [{"citation": "347 U.S. 483", "status": 200, "clusters": []}]},
    }
    with respx.mock:
        respx.post(f"{GW}/v1/tools/courtlistener-prod/verify_citations").mock(
            return_value=httpx.Response(200, json=gw_resp)
        )
        resp = await client.post(
            "/api/v1/research/verify-citations",
            json={"text": "347 U.S. 483"},
            headers=_h(db_user),
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "citations" in body
    assert body["citations"][0]["citation"] == "347 U.S. 483"


# ---------------------------------------------------------------------------
# POST /search
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_search_returns_count_and_results(client: AsyncClient, db_user: User) -> None:
    gw_resp = {
        "provider": "courtlistener-prod",
        "tool": "search_case_law",
        "tier": 4,
        "payload": {
            "count": 1,
            "results": [
                {
                    "cluster_id": 42,
                    "case_name": "Roe v. Wade",
                    "court": "scotus",
                    "date_filed": "1973-01-22",
                    "citation": None,
                    "absolute_url": "/opinion/42/",
                    "snippet": "…the right to privacy…",
                }
            ],
            "next_cursor": None,
        },
    }
    with respx.mock:
        respx.post(f"{GW}/v1/tools/courtlistener-prod/search_case_law").mock(
            return_value=httpx.Response(200, json=gw_resp)
        )
        resp = await client.post(
            "/api/v1/research/search",
            json={"q": "right to privacy"},
            headers=_h(db_user),
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert len(body["results"]) == 1
    assert body["results"][0]["case_name"] == "Roe v. Wade"


# ---------------------------------------------------------------------------
# GET /clusters/{cluster_id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_cluster_fetches_and_returns(
    client: AsyncClient, db_user: User, fake_storage
) -> None:
    gw_resp = {
        "provider": "courtlistener-prod",
        "tool": "get_cases",
        "tier": 4,
        "payload": {
            "cluster": {
                "id": 5,
                "case_name": "X v. Y",
                "court": "scotus",
                "date_filed": "2020-01-01",
                "absolute_url": "/opinion/5/",
            },
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
        respx.post(f"{GW}/v1/tools/courtlistener-prod/get_cases").mock(
            return_value=httpx.Response(200, json=gw_resp)
        )
        resp = await client.get(
            "/api/v1/research/clusters/5",
            headers=_h(db_user),
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["cluster"]["cluster_id"] == 5
    assert body["cluster"]["case_name"] == "X v. Y"
    assert len(body["opinions"]) == 1
    assert body["opinions"][0]["opinion_id"] == 9


# ---------------------------------------------------------------------------
# GET /opinions/{opinion_id} — requires cluster already cached
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_read_opinion_404_when_not_cached(
    client: AsyncClient, db_user: User, fake_storage
) -> None:
    """GET /opinions/{id} returns 404 when the cluster was never fetched."""
    resp = await client.get(
        "/api/v1/research/opinions/9999",
        headers=_h(db_user),
    )
    assert resp.status_code == 404


@pytest.mark.integration
async def test_read_opinion_200_after_cluster_cached(
    client: AsyncClient, db_session: AsyncSession, db_user: User, fake_storage
) -> None:
    """Cache the cluster first (via service), then read the opinion via endpoint."""
    from app.models.research import ResearchOpinionMetadata

    fake_storage["courtlistener/opinions/by-cluster/5/9"] = b"Held: it is so."
    db_session.add(
        ResearchOpinionMetadata(
            opinion_id=9,
            cluster_id=5,
            text_field_used="html_with_citations",
            storage_path="courtlistener/opinions/by-cluster/5/9",
            char_length=15,
        )
    )
    await db_session.flush()

    resp = await client.get(
        "/api/v1/research/opinions/9",
        headers=_h(db_user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["opinion_id"] == 9
    assert body["cluster_id"] == 5
    assert "Held: it is so." in body["text"]


# ---------------------------------------------------------------------------
# POST /find-in-case
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_find_in_case_returns_matches(
    client: AsyncClient, db_session: AsyncSession, db_user: User, fake_storage
) -> None:
    from app.models.research import ResearchOpinionMetadata

    text = b"The right to privacy is fundamental. Privacy again here."
    fake_storage["courtlistener/opinions/by-cluster/5/9"] = text
    db_session.add(
        ResearchOpinionMetadata(
            opinion_id=9,
            cluster_id=5,
            text_field_used="html_with_citations",
            storage_path="courtlistener/opinions/by-cluster/5/9",
            char_length=len(text),
        )
    )
    await db_session.flush()

    resp = await client.post(
        "/api/v1/research/find-in-case",
        json={"opinion_id": 9, "query": "privacy", "max_matches": 3},
        headers=_h(db_user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["opinion_id"] == 9
    assert len(body["matches"]) >= 1
    assert "privacy" in body["matches"][0]["snippet"].lower()


@pytest.mark.integration
async def test_find_in_case_404_when_not_cached(
    client: AsyncClient, db_user: User, fake_storage
) -> None:
    resp = await client.post(
        "/api/v1/research/find-in-case",
        json={"opinion_id": 9999, "query": "privacy"},
        headers=_h(db_user),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /capabilities
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_capabilities_unauthenticated_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/research/capabilities")
    assert resp.status_code == 401


@pytest.mark.integration
async def test_capabilities_enabled_when_courtlistener_configured(
    client: AsyncClient, db_user: User, monkeypatch
) -> None:
    from app.research import service

    async def _mock_get_capabilities(**_kwargs):
        return {
            "enabled": True,
            "providers": [{"name": "courtlistener-prod", "type": "courtlistener"}],
        }

    monkeypatch.setattr(service, "get_capabilities", _mock_get_capabilities)
    resp = await client.get("/api/v1/research/capabilities", headers=_h(db_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert len(body["providers"]) == 1
    assert body["providers"][0]["name"] == "courtlistener-prod"


@pytest.mark.integration
async def test_capabilities_disabled_when_not_configured(
    client: AsyncClient, db_user: User, monkeypatch
) -> None:
    from app.research import service

    async def _mock_get_capabilities(**_kwargs):
        return {"enabled": False, "providers": []}

    monkeypatch.setattr(service, "get_capabilities", _mock_get_capabilities)
    resp = await client.get("/api/v1/research/capabilities", headers=_h(db_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["providers"] == []
