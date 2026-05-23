"""OAuth admin-consent + callback handler tests for the teams-bridge (M3-D3).

Covers:

* ``GET /teams/oauth/install`` — generates a fresh state token, stores
  it in the bridge's in-memory store, and redirects to the Microsoft
  identity platform multi-tenant authorize endpoint with the right
  ``client_id`` / ``scope`` / ``redirect_uri`` / ``state`` /
  ``prompt=admin_consent`` query params.
* ``GET /teams/oauth/callback`` — happy path: valid state → mocked
  token exchange → mocked Graph display-name lookup → POST tenant
  record to the api over the shared bridge token → success page.
* ``GET /teams/oauth/callback`` — bad state → 400.
* ``GET /teams/oauth/callback`` — ``error=...`` query param renders
  the cancellation page without contacting Microsoft or the api.
* Microsoft token endpoint returning non-200 → 502.
* api persistence returning non-2xx → 502.
* Graph display-name lookup failure falls back to tid (does NOT 502).
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from pytest_httpx import HTTPXMock

from app import oauth as oauth_module
from app.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        microsoft_app_id="ms-app-id-fixture",
        microsoft_app_password="ms-app-password-fixture",
        lq_ai_backend_url="http://api.test",
        lq_ai_bridge_token="bridge-token-fixture",
        lq_ai_teams_bridge_public_url="https://teams-bridge.test",
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app, follow_redirects=False)


@pytest.fixture(autouse=True)
def _reset_state_store() -> None:
    oauth_module._STATE_STORE.clear()
    yield
    oauth_module._STATE_STORE.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_state(state: str = "stateA") -> str:
    oauth_module._STATE_STORE[state] = time.time()
    return state


def _b64url(data: bytes) -> str:
    """Base64-url-encode without padding (JWT convention)."""

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_id_token(claims: dict[str, Any]) -> str:
    """Construct a JWT-shaped id_token for tests (signature ignored)."""

    header = _b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps(claims).encode())
    signature = _b64url(b"signature-not-checked")
    return f"{header}.{payload}.{signature}"


# ---------------------------------------------------------------------------
# /teams/oauth/install
# ---------------------------------------------------------------------------


def test_install_redirects_to_microsoft_consent_with_required_params(
    client: TestClient,
    settings: Settings,
) -> None:
    res = client.get("/teams/oauth/install")
    assert res.status_code == 302
    location = res.headers["location"]

    parsed = urlparse(location)
    assert parsed.scheme == "https"
    assert parsed.netloc == "login.microsoftonline.com"
    assert parsed.path == "/common/oauth2/v2.0/authorize"

    params = parse_qs(parsed.query)
    assert params["client_id"] == [settings.microsoft_app_id]
    assert params["response_type"] == ["code"]
    assert params["redirect_uri"] == [
        f"{settings.lq_ai_teams_bridge_public_url.rstrip('/')}/teams/oauth/callback"
    ]
    assert params["response_mode"] == ["query"]
    assert params["prompt"] == ["admin_consent"]
    scope_value = params["scope"][0]
    assert "openid" in scope_value
    assert "User.Read" in scope_value
    state = params["state"][0]
    assert state  # non-empty CSRF token
    assert state in oauth_module._STATE_STORE


def test_install_emits_distinct_state_tokens(client: TestClient) -> None:
    states = set()
    for _ in range(3):
        res = client.get("/teams/oauth/install")
        states.add(parse_qs(urlparse(res.headers["location"]).query)["state"][0])
    assert len(states) == 3


# ---------------------------------------------------------------------------
# /teams/oauth/callback — happy path
# ---------------------------------------------------------------------------


def _add_token_endpoint_success(
    httpx_mock: HTTPXMock,
    *,
    tenant_id: str = "00000000-0000-0000-0000-aaaaaaaaaaaa",
    installer_oid: str = "00000000-0000-0000-0000-111111111111",
    access_token: str = "graph-access-token",
) -> None:
    id_token = _make_id_token(
        {"tid": tenant_id, "oid": installer_oid, "iss": "https://login.microsoftonline.com/x/v2.0"}
    )
    httpx_mock.add_response(
        url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        method="POST",
        status_code=200,
        json={
            "token_type": "Bearer",
            "id_token": id_token,
            "access_token": access_token,
            "refresh_token": "refresh-token-fixture",
            "expires_in": 3599,
        },
    )


def _add_graph_org_success(
    httpx_mock: HTTPXMock,
    *,
    display_name: str = "Acme Legal LLP",
) -> None:
    httpx_mock.add_response(
        url="https://graph.microsoft.com/v1.0/organization",
        method="GET",
        status_code=200,
        json={"value": [{"displayName": display_name}]},
    )


def test_callback_happy_path_persists_to_api_and_returns_success(
    client: TestClient,
    settings: Settings,
    httpx_mock: HTTPXMock,
) -> None:
    state = _seed_state()
    _add_token_endpoint_success(httpx_mock)
    _add_graph_org_success(httpx_mock)
    httpx_mock.add_response(
        url=f"{settings.lq_ai_backend_url}/api/v1/integrations/teams/tenants",
        method="POST",
        status_code=201,
        json={
            "id": "00000000-0000-0000-0000-000000000999",
            "tenant_id": "00000000-0000-0000-0000-aaaaaaaaaaaa",
            "tenant_name": "Acme Legal LLP",
            "installer_oid": "00000000-0000-0000-0000-111111111111",
            "installed_at": "2026-05-22T12:00:00Z",
        },
    )

    res = client.get(f"/teams/oauth/callback?code=auth-code&state={state}")
    assert res.status_code == 200, res.text
    assert "Install complete" in res.text
    assert "Acme Legal LLP" in res.text

    assert state not in oauth_module._STATE_STORE

    sent_requests = httpx_mock.get_requests()
    persist = [r for r in sent_requests if r.url.host == "api.test"]
    assert len(persist) == 1
    assert persist[0].headers["authorization"] == f"Bearer {settings.lq_ai_bridge_token}"
    assert json.loads(persist[0].content) == {
        "tenant_id": "00000000-0000-0000-0000-aaaaaaaaaaaa",
        "tenant_name": "Acme Legal LLP",
        "installer_oid": "00000000-0000-0000-0000-111111111111",
    }


def test_callback_falls_back_to_tid_when_graph_lookup_fails(
    client: TestClient,
    settings: Settings,
    httpx_mock: HTTPXMock,
) -> None:
    """Graph hiccup must NOT fail the whole install — fall back to tid."""
    state = _seed_state("stateFallback")
    _add_token_endpoint_success(httpx_mock)
    httpx_mock.add_response(
        url="https://graph.microsoft.com/v1.0/organization",
        method="GET",
        status_code=503,
        text="Graph is having a moment",
    )
    httpx_mock.add_response(
        url=f"{settings.lq_ai_backend_url}/api/v1/integrations/teams/tenants",
        method="POST",
        status_code=201,
        json={
            "id": "00000000-0000-0000-0000-000000000999",
            "tenant_id": "00000000-0000-0000-0000-aaaaaaaaaaaa",
            "tenant_name": "00000000-0000-0000-0000-aaaaaaaaaaaa",
            "installer_oid": "00000000-0000-0000-0000-111111111111",
            "installed_at": "2026-05-22T12:00:00Z",
        },
    )

    res = client.get(f"/teams/oauth/callback?code=auth-code&state={state}")
    assert res.status_code == 200, res.text

    sent_requests = httpx_mock.get_requests()
    persist = [r for r in sent_requests if r.url.host == "api.test"]
    body = json.loads(persist[0].content)
    # Graph fallback: tenant_name = tenant_id
    assert body["tenant_name"] == body["tenant_id"]


# ---------------------------------------------------------------------------
# /teams/oauth/callback — failure paths
# ---------------------------------------------------------------------------


def test_callback_with_bad_state_returns_400(client: TestClient) -> None:
    res = client.get("/teams/oauth/callback?code=anything&state=not-a-real-state")
    assert res.status_code == 400
    assert "invalid or expired state" in res.text.lower()


def test_callback_with_error_query_param_renders_cancellation_page(
    client: TestClient,
) -> None:
    res = client.get(
        "/teams/oauth/callback?code=ignored&state=ignored"
        "&error=access_denied&error_description=admin+declined"
    )
    assert res.status_code == 400
    assert "Install cancelled" in res.text
    assert "access_denied" in res.text


def test_callback_with_token_endpoint_failure_returns_502(
    client: TestClient,
    httpx_mock: HTTPXMock,
) -> None:
    state = _seed_state("stateTokenFail")
    httpx_mock.add_response(
        url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        method="POST",
        status_code=400,
        json={"error": "invalid_grant", "error_description": "code expired"},
    )
    res = client.get(f"/teams/oauth/callback?code=bad&state={state}")
    assert res.status_code == 502
    assert "invalid_grant" in res.text


def test_callback_with_api_persist_failure_returns_502(
    client: TestClient,
    settings: Settings,
    httpx_mock: HTTPXMock,
) -> None:
    state = _seed_state("stateApiFail")
    _add_token_endpoint_success(httpx_mock)
    _add_graph_org_success(httpx_mock)
    httpx_mock.add_response(
        url=f"{settings.lq_ai_backend_url}/api/v1/integrations/teams/tenants",
        method="POST",
        status_code=500,
        text="boom",
    )
    res = client.get(f"/teams/oauth/callback?code=auth-code&state={state}")
    assert res.status_code == 502
    assert "HTTP 500" in res.text


def test_callback_with_id_token_missing_claims_returns_502(
    client: TestClient,
    httpx_mock: HTTPXMock,
) -> None:
    """An id_token without tid/oid claims is a malformed Microsoft response."""
    state = _seed_state("stateNoClaims")
    id_token = _make_id_token({"sub": "irrelevant"})  # no tid, no oid
    httpx_mock.add_response(
        url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        method="POST",
        status_code=200,
        json={
            "token_type": "Bearer",
            "id_token": id_token,
            "access_token": "x",
        },
    )
    res = client.get(f"/teams/oauth/callback?code=auth-code&state={state}")
    assert res.status_code == 502
    assert "tid + oid" in res.text
