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
* ``GET /teams/oauth/callback`` — ``error=...`` query param (with a valid
  state) renders the static cancellation page without contacting
  Microsoft or the api.
* Output encoding + CSP regression suite (reflected XSS in the callback,
  reported 2026-08): the state check precedes every page-rendering
  branch; ``error`` / ``error_description`` / upstream bodies are never
  reflected; every HTML page carries ``default-src 'none'``.
* Microsoft token endpoint returning non-200 → 502.
* api persistence returning non-2xx → 502.
* Graph display-name lookup failure falls back to tid (does NOT 502).
* Install-only id_token constraints (D-03, #587): iss/aud/exp/nbf/tid/oid
  fail closed, the unverified decode stays confined to this module, claims
  grant nothing beyond the tenant record, and token-bearing upstream bodies
  are redacted in logs.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

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
    now = int(time.time())
    id_token = _make_id_token(
        {
            "tid": tenant_id,
            "oid": installer_oid,
            "iss": f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            "aud": "ms-app-id-fixture",
            "exp": now + 3600,
            "nbf": now - 60,
        }
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
    """A declined consent (valid state, no code) renders the static cancel
    page; ``error`` / ``error_description`` are logged, never echoed."""
    state = _seed_state("stateDenied")
    res = client.get(
        f"/teams/oauth/callback?state={state}&error=access_denied&error_description=admin+declined"
    )
    assert res.status_code == 400
    assert "Install cancelled" in res.text
    assert "access_denied" not in res.text
    assert "admin declined" not in res.text
    assert state not in oauth_module._STATE_STORE


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
    assert "did not pass the install checks" in res.text


# ---------------------------------------------------------------------------
# Output encoding + CSP (reflected-XSS regression, 2026-08 advisory)
# ---------------------------------------------------------------------------
#
# Teams was the easier reported attack: ``code`` and ``state`` were already
# optional here, so ``?error=x&error_description=<script>…`` reached the
# reflecting branch with no other parameter. The state check now runs
# first, and nothing caller- or provider-controlled is rendered.

_SCRIPT_PAYLOAD = "<script>document.title='pwned'</script>"
_IMG_PAYLOAD = '<img src=x onerror="alert(1)">'


def _assert_hardened_html(res: object) -> None:
    headers = res.headers  # type: ignore[attr-defined]
    text = res.text  # type: ignore[attr-defined]
    assert headers["content-type"].startswith("text/html")
    assert headers["content-security-policy"] == oauth_module._CONTENT_SECURITY_POLICY
    assert headers["content-security-policy"].startswith("default-src 'none'")
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["cache-control"] == "no-store"
    # No live tag or attribute survives: only the entity-encoded form may.
    assert "<script" not in text.lower()
    assert "<img" not in text.lower()
    assert 'onerror="' not in text.lower()
    assert "Correlation:" in text


def test_error_branch_is_unreachable_without_valid_state(client: TestClient) -> None:
    """The reported bare-URL reach (no code, no state) is closed."""
    res = client.get(f"/teams/oauth/callback?error=x&error_description={quote(_SCRIPT_PAYLOAD)}")
    assert res.status_code == 400
    assert "invalid or expired state" in res.text.lower()
    assert "<script" not in res.text
    assert res.headers["content-type"].startswith("application/json")


def test_error_and_description_payloads_are_not_reflected(client: TestClient) -> None:
    state = _seed_state("stateXss")
    res = client.get(
        f"/teams/oauth/callback?state={state}&error={quote(_IMG_PAYLOAD)}"
        f"&error_description={quote(_SCRIPT_PAYLOAD)}"
    )
    assert res.status_code == 400
    assert "Install cancelled" in res.text
    assert "pwned" not in res.text
    _assert_hardened_html(res)


def test_missing_code_without_error_returns_400_after_state_check(
    client: TestClient,
) -> None:
    state = _seed_state("stateOnlyState")
    res = client.get(f"/teams/oauth/callback?state={state}")
    assert res.status_code == 400
    assert "missing authorization code" in res.text.lower()


def test_token_endpoint_body_is_not_reflected(
    client: TestClient,
    httpx_mock: HTTPXMock,
) -> None:
    """The raw upstream body used to land in a ``<pre>``; now only the HTTP
    status and a token-shaped error code (if any) are shown."""
    state = _seed_state("stateBody")
    httpx_mock.add_response(
        url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        method="POST",
        status_code=400,
        text=_SCRIPT_PAYLOAD,
    )
    res = client.get(f"/teams/oauth/callback?code=bad&state={state}")
    assert res.status_code == 502
    assert "HTTP 400" in res.text
    assert "error code: unknown" in res.text
    assert "pwned" not in res.text
    _assert_hardened_html(res)


def test_token_endpoint_error_code_rendered_only_when_token_shaped(
    client: TestClient,
    httpx_mock: HTTPXMock,
) -> None:
    state = _seed_state("stateMarkupCode")
    httpx_mock.add_response(
        url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        method="POST",
        status_code=400,
        json={"error": _IMG_PAYLOAD, "error_description": _SCRIPT_PAYLOAD},
    )
    res = client.get(f"/teams/oauth/callback?code=bad&state={state}")
    assert res.status_code == 502
    assert "error code: unknown" in res.text
    _assert_hardened_html(res)


def test_id_token_decode_failure_detail_is_not_reflected(
    client: TestClient,
    httpx_mock: HTTPXMock,
) -> None:
    state = _seed_state("stateBadJwt")
    httpx_mock.add_response(
        url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        method="POST",
        status_code=200,
        json={"id_token": _SCRIPT_PAYLOAD, "access_token": "x"},
    )
    res = client.get(f"/teams/oauth/callback?code=auth-code&state={state}")
    assert res.status_code == 502
    assert "could not be decoded" in res.text
    assert "pwned" not in res.text
    _assert_hardened_html(res)


def test_success_page_escapes_tenant_name(
    client: TestClient,
    settings: Settings,
    httpx_mock: HTTPXMock,
) -> None:
    """The consenting tenant's own Graph display name is still output-encoded."""
    state = _seed_state("stateName")
    _add_token_endpoint_success(httpx_mock)
    _add_graph_org_success(httpx_mock, display_name=_IMG_PAYLOAD)
    httpx_mock.add_response(
        url=f"{settings.lq_ai_backend_url}/api/v1/integrations/teams/tenants",
        method="POST",
        status_code=201,
        json={},
    )
    res = client.get(f"/teams/oauth/callback?code=auth-code&state={state}")
    assert res.status_code == 200, res.text
    assert "Install complete" in res.text
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in res.text
    _assert_hardened_html(res)


def test_api_persist_rejection_body_is_not_reflected(
    client: TestClient,
    settings: Settings,
    httpx_mock: HTTPXMock,
) -> None:
    state = _seed_state("stateApiBody")
    _add_token_endpoint_success(httpx_mock)
    _add_graph_org_success(httpx_mock)
    httpx_mock.add_response(
        url=f"{settings.lq_ai_backend_url}/api/v1/integrations/teams/tenants",
        method="POST",
        status_code=500,
        text=_SCRIPT_PAYLOAD,
    )
    res = client.get(f"/teams/oauth/callback?code=auth-code&state={state}")
    assert res.status_code == 502
    assert "Backend rejected with HTTP 500" in res.text
    _assert_hardened_html(res)


# ---------------------------------------------------------------------------
# Install-only id_token constraints (D-03, #587)
# ---------------------------------------------------------------------------
#
# The bridge never verifies the id_token signature: the token is trusted only
# because it arrives straight from Microsoft's token endpoint over TLS, in
# reply to the bridge's own client_secret-authenticated POST. These tests pin
# the compensating controls: every required claim is checked and fails closed,
# the decode helper stays confined to the install callback, the claims never
# grant anything beyond the three-field tenant record, and no token or full
# token response reaches a log line or a page.

_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"


def _valid_claims(**overrides: Any) -> dict[str, Any]:
    """Claims Microsoft puts in a v2.0 id_token for the install flow."""

    now = int(time.time())
    claims: dict[str, Any] = {
        "tid": "00000000-0000-0000-0000-aaaaaaaaaaaa",
        "oid": "00000000-0000-0000-0000-111111111111",
        "iss": "https://login.microsoftonline.com/00000000-0000-0000-0000-aaaaaaaaaaaa/v2.0",
        "aud": "ms-app-id-fixture",
        "exp": now + 3600,
        "nbf": now - 60,
        "iat": now - 60,
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not _ABSENT}


_ABSENT = object()


def _add_token_endpoint_with_claims(httpx_mock: HTTPXMock, claims: dict[str, Any]) -> None:
    httpx_mock.add_response(
        url=_TOKEN_URL,
        method="POST",
        status_code=200,
        json={
            "token_type": "Bearer",
            "id_token": _make_id_token(claims),
            "access_token": "graph-access-token",
            "refresh_token": "refresh-token-fixture",
        },
    )


@pytest.mark.parametrize(
    ("label", "overrides"),
    [
        ("wrong-issuer", {"iss": "https://evil.example/v2.0"}),
        ("issuer-tenant-mismatch", {"iss": "https://login.microsoftonline.com/other-tid/v2.0"}),
        ("missing-issuer", {"iss": _ABSENT}),
        ("wrong-audience", {"aud": "some-other-app-id"}),
        ("missing-audience", {"aud": _ABSENT}),
        ("expired", {"exp": int(time.time()) - 3600}),
        ("missing-exp", {"exp": _ABSENT}),
        ("exp-not-int", {"exp": "soon"}),
        ("not-yet-valid", {"nbf": int(time.time()) + 3600}),
        ("missing-tid", {"tid": _ABSENT}),
        ("missing-oid", {"oid": _ABSENT}),
        ("empty-oid", {"oid": ""}),
        ("tid-not-string", {"tid": 12345}),
    ],
)
def test_callback_rejects_id_token_with_bad_claims(
    client: TestClient,
    httpx_mock: HTTPXMock,
    caplog: pytest.LogCaptureFixture,
    label: str,
    overrides: dict[str, Any],
) -> None:
    """Every required claim fails closed: 502, state consumed, backend never called,
    and neither the page nor the log carries a claim value or the token."""
    state = _seed_state(f"state-{label}")
    claims = _valid_claims(**overrides)
    _add_token_endpoint_with_claims(httpx_mock, claims)

    with caplog.at_level("WARNING", logger="app.oauth"):
        res = client.get(f"/teams/oauth/callback?code=auth-code&state={state}")

    assert res.status_code == 502, res.text
    assert "did not pass the install checks" in res.text
    _assert_hardened_html(res)
    assert state not in oauth_module._STATE_STORE
    assert [r for r in httpx_mock.get_requests() if r.url.host == "api.test"] == []

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "teams.oauth.id_token_claims_rejected" in logged
    for leaked in ("evil.example", "other-tid", "some-other-app-id", "eyJ"):
        assert leaked not in logged
        assert leaked not in res.text


def test_callback_accepts_valid_claims_and_persists_only_the_tenant_record(
    client: TestClient,
    settings: Settings,
    httpx_mock: HTTPXMock,
) -> None:
    """Claims cannot grant anything: even extra privilege-looking claims produce
    exactly the three-field tenant record and nothing else."""
    state = _seed_state("state-valid")
    claims = _valid_claims(
        roles=["GlobalAdmin"], groups=["lq-ai-admins"], sub="user-sub", email="a@b.test"
    )
    _add_token_endpoint_with_claims(httpx_mock, claims)
    _add_graph_org_success(httpx_mock)
    httpx_mock.add_response(
        url=f"{settings.lq_ai_backend_url}/api/v1/integrations/teams/tenants",
        method="POST",
        status_code=201,
        json={},
    )

    res = client.get(f"/teams/oauth/callback?code=auth-code&state={state}")
    assert res.status_code == 200, res.text

    persist = [r for r in httpx_mock.get_requests() if r.url.host == "api.test"]
    assert len(persist) == 1
    sent = json.loads(persist[0].content)
    assert set(sent) == {"tenant_id", "tenant_name", "installer_oid"}
    assert "roles" not in persist[0].content.decode()
    assert persist[0].headers["authorization"] == f"Bearer {settings.lq_ai_bridge_token}"


def test_validate_install_claims_is_pure_and_fails_closed() -> None:
    """Unit coverage of the validator so the reason strings never carry values."""
    now = 1_700_000_000
    good = _valid_claims(exp=now + 10, nbf=now - 10)
    assert oauth_module._validate_install_claims(good, app_id="ms-app-id-fixture", now=now) == (
        "00000000-0000-0000-0000-aaaaaaaaaaaa",
        "00000000-0000-0000-0000-111111111111",
    )
    with pytest.raises(ValueError, match="aud") as excinfo:
        oauth_module._validate_install_claims(good, app_id="another-app", now=now)
    assert "ms-app-id-fixture" not in str(excinfo.value)
    assert "another-app" not in str(excinfo.value)
    skew = oauth_module._INSTALL_CLAIM_SKEW_SECONDS
    with pytest.raises(ValueError, match="exp"):
        oauth_module._validate_install_claims(good, app_id="ms-app-id-fixture", now=now + 10 + skew)
    # Clock skew allowance: one second past exp is still inside the window.
    oauth_module._validate_install_claims(good, app_id="ms-app-id-fixture", now=now + 10 + 1)
    with pytest.raises(ValueError, match="nbf"):
        oauth_module._validate_install_claims(
            good, app_id="ms-app-id-fixture", now=now - 10 - skew - 1
        )
    with pytest.raises(ValueError, match="exp"):
        oauth_module._validate_install_claims(
            _valid_claims(exp=True), app_id="ms-app-id-fixture", now=now
        )


def test_unverified_decode_is_confined_to_the_install_module() -> None:
    """Regression guard for D-03: the unverified decode helper must not be
    imported or re-exported anywhere else in the bridge."""
    app_dir = Path(oauth_module.__file__).resolve().parent
    offenders = [
        p.name
        for p in app_dir.rglob("*.py")
        if p.name != "oauth.py" and "_decode_id_token_unverified" in p.read_text()
    ]
    assert offenders == []
    assert not hasattr(oauth_module, "decode_id_token_unverified")
    assert "_decode_id_token_unverified" not in getattr(oauth_module, "__all__", [])


def test_token_endpoint_rejection_log_redacts_tokens(
    client: TestClient,
    httpx_mock: HTTPXMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A non-200 token endpoint body is logged redacted, not merely truncated."""
    state = _seed_state("state-redact-token")
    body = {
        "error": "invalid_grant",
        "access_token": "secret-access-value",
        "refresh_token": "secret-refresh-value",
        "id_token": "eyJhbGciOiJSUzI1NiJ9.eyJ0aWQiOiJ4In0.sig",
    }
    httpx_mock.add_response(url=_TOKEN_URL, method="POST", status_code=400, json=body)

    with caplog.at_level("WARNING", logger="app.oauth"):
        res = client.get(f"/teams/oauth/callback?code=bad&state={state}")

    assert res.status_code == 502
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "teams.oauth.token_endpoint_rejected" in logged
    assert "[redacted]" in logged
    for secret in ("secret-access-value", "secret-refresh-value", "eyJhbGci"):
        assert secret not in logged
        assert secret not in res.text


def test_api_persist_rejection_log_redacts_tokens(
    client: TestClient,
    settings: Settings,
    httpx_mock: HTTPXMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = _seed_state("state-redact-persist")
    _add_token_endpoint_with_claims(httpx_mock, _valid_claims())
    _add_graph_org_success(httpx_mock)
    httpx_mock.add_response(
        url=f"{settings.lq_ai_backend_url}/api/v1/integrations/teams/tenants",
        method="POST",
        status_code=500,
        text='{"detail": "boom", "access_token": "secret-echoed-back"}',
    )

    with caplog.at_level("WARNING", logger="app.oauth"):
        res = client.get(f"/teams/oauth/callback?code=auth-code&state={state}")

    assert res.status_code == 502
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "teams.oauth.api_persist_rejected" in logged
    assert "secret-echoed-back" not in logged
    assert "[redacted]" in logged


def test_graph_lookup_rejection_log_redacts_tokens(
    client: TestClient,
    settings: Settings,
    httpx_mock: HTTPXMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = _seed_state("state-redact-graph")
    _add_token_endpoint_with_claims(httpx_mock, _valid_claims())
    httpx_mock.add_response(
        url="https://graph.microsoft.com/v1.0/organization",
        method="GET",
        status_code=401,
        text='{"error": "x", "access_token": "secret-graph-echo"}',
    )
    httpx_mock.add_response(
        url=f"{settings.lq_ai_backend_url}/api/v1/integrations/teams/tenants",
        method="POST",
        status_code=201,
        json={},
    )

    with caplog.at_level("INFO", logger="app.oauth"):
        res = client.get(f"/teams/oauth/callback?code=auth-code&state={state}")

    assert res.status_code == 200
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "teams.oauth.graph_org_lookup_rejected" in logged
    assert "secret-graph-echo" not in logged


@pytest.mark.parametrize(
    ("raw", "must_hide"),
    [
        ('{"access_token": "abc123", "x": 1}', "abc123"),
        ("access_token=abc123&token_type=Bearer", "abc123"),
        ("prefix eyJhbGciOiJSUzI1NiJ9.eyJ0aWQiOiJ4In0.c2ln tail", "eyJhbGci"),
        ('{"refresh_token":"r-secret","id_token":"i-secret"}', "r-secret"),
    ],
)
def test_redact_tokens_covers_json_form_and_jwt_shapes(raw: str, must_hide: str) -> None:
    out = oauth_module._redact_tokens(raw)
    assert must_hide not in out
    assert "[redacted]" in out
    assert len(out) <= oauth_module._LOG_MAX_CHARS + 2  # repr quotes
