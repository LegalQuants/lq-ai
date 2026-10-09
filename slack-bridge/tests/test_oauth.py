"""OAuth install + callback handler tests for the slack-bridge (M3-D1).

Covers:

* ``GET /slack/oauth/install`` — generates a fresh state token, stores
  it in the bridge's in-memory store, and redirects to Slack's consent
  URL with the right ``client_id`` / ``scope`` / ``redirect_uri`` /
  ``state`` query params.
* ``GET /slack/oauth/callback`` — happy path: valid state → mocked
  Slack ``oauth.v2.access`` exchange → POST workspace record to the
  api over an internal bridge token → success page.
* ``GET /slack/oauth/callback`` — bad state → 400.
* ``GET /slack/oauth/callback`` — ``error=...`` query param (with a valid
  state) renders the static cancellation page without contacting Slack
  or the api.
* Output encoding + CSP regression suite (reflected XSS in the callback,
  reported 2026-08): the state check precedes every page-rendering
  branch; attacker- or provider-controlled strings are never reflected;
  every HTML page carries ``Content-Security-Policy: default-src 'none'``.
"""

from __future__ import annotations

import json
import time
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
        slack_client_id="A123CLIENT",
        slack_client_secret="A123SECRET",
        slack_signing_secret="A123SIGNING",
        lq_ai_backend_url="http://api.test",
        lq_ai_bridge_token="bridge-token-fixture",
        lq_ai_bridge_public_url="https://bridge.test",
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    """Test client wired to a fresh app instance using the test Settings.

    Overrides the ``get_settings`` dependency so the oauth router
    sees the test Settings instead of the process-cached one (which
    is derived from the conftest's env-var defaults).
    """

    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app, follow_redirects=False)


@pytest.fixture(autouse=True)
def _reset_state_store() -> None:
    """Module-level _STATE_STORE leaks between tests; clear before each."""

    oauth_module._STATE_STORE.clear()
    yield
    oauth_module._STATE_STORE.clear()


# ---------------------------------------------------------------------------
# /slack/oauth/install
# ---------------------------------------------------------------------------


def test_install_redirects_to_slack_consent_with_required_params(
    client: TestClient,
    settings: Settings,
) -> None:
    res = client.get("/slack/oauth/install")
    assert res.status_code == 302
    location = res.headers["location"]

    parsed = urlparse(location)
    assert parsed.scheme == "https"
    assert parsed.netloc == "slack.com"
    assert parsed.path == "/oauth/v2/authorize"

    params = parse_qs(parsed.query)
    assert params["client_id"] == [settings.slack_client_id]
    assert params["scope"] == ["commands,chat:write,users:read,users:read.email"]
    assert params["redirect_uri"] == [
        f"{settings.lq_ai_bridge_public_url.rstrip('/')}/slack/oauth/callback"
    ]
    state = params["state"][0]
    assert state  # non-empty CSRF token
    assert state in oauth_module._STATE_STORE


def test_install_emits_distinct_state_tokens(client: TestClient) -> None:
    """Each install call mints a fresh CSRF token."""
    states = set()
    for _ in range(3):
        res = client.get("/slack/oauth/install")
        states.add(parse_qs(urlparse(res.headers["location"]).query)["state"][0])
    assert len(states) == 3


# ---------------------------------------------------------------------------
# /slack/oauth/callback — happy path
# ---------------------------------------------------------------------------


class _StubSlackResponse:
    """Stand-in for ``slack_sdk.web.SlackResponse`` for tests."""

    def __init__(self, payload: dict[str, object]) -> None:
        self.data = payload

    def get(self, key: str, default: object | None = None) -> object | None:
        return self.data.get(key, default)


class _StubAsyncWebClient:
    """Replaces ``slack_sdk.web.async_client.AsyncWebClient`` for tests.

    Captures the kwargs ``oauth_v2_access`` was called with so assertions
    can verify the bridge passed ``client_id`` / ``client_secret`` /
    ``code`` / ``redirect_uri`` per Slack's contract.
    """

    last_kwargs: dict[str, object] | None = None

    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self._payload = payload or {
            "ok": True,
            "access_token": "xoxb-fake-bot-token",
            "bot_user_id": "U99BOT",
            "scope": "commands,chat:write,users:read,users:read.email",
            "team": {"id": "T0123456", "name": "Acme Legal"},
            "authed_user": {"id": "U11INSTALLER"},
        }

    async def oauth_v2_access(self, **kwargs: object) -> _StubSlackResponse:
        type(self).last_kwargs = kwargs
        return _StubSlackResponse(self._payload)


def _seed_state(state: str = "stateA") -> str:
    oauth_module._STATE_STORE[state] = time.time()
    return state


def test_callback_happy_path_persists_to_api_and_returns_success(
    client: TestClient,
    settings: Settings,
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _seed_state()
    monkeypatch.setattr(
        "slack_sdk.web.async_client.AsyncWebClient",
        _StubAsyncWebClient,
        raising=True,
    )
    httpx_mock.add_response(
        url=f"{settings.lq_ai_backend_url}/api/v1/integrations/slack/workspaces",
        method="POST",
        status_code=201,
        json={
            "id": "00000000-0000-0000-0000-000000000001",
            "team_id": "T0123456",
            "team_name": "Acme Legal",
            "bot_user_id": "U99BOT",
            "installer_slack_user_id": "U11INSTALLER",
            "scope": "commands,chat:write,users:read,users:read.email",
            "installed_at": "2026-05-22T12:00:00Z",
        },
    )

    res = client.get(f"/slack/oauth/callback?code=auth-code-from-slack&state={state}")
    assert res.status_code == 200, res.text
    assert "Install complete" in res.text
    assert "Acme Legal" in res.text

    # Confirm the bridge consumed the state token (single-use).
    assert state not in oauth_module._STATE_STORE

    # Confirm Slack code exchange was called with the right kwargs.
    assert _StubAsyncWebClient.last_kwargs is not None
    assert _StubAsyncWebClient.last_kwargs["code"] == "auth-code-from-slack"
    assert _StubAsyncWebClient.last_kwargs["client_id"] == settings.slack_client_id
    assert _StubAsyncWebClient.last_kwargs["client_secret"] == settings.slack_client_secret
    assert _StubAsyncWebClient.last_kwargs["redirect_uri"] == (
        f"{settings.lq_ai_bridge_public_url.rstrip('/')}/slack/oauth/callback"
    )

    # Confirm the api POST carried the bridge bearer + the expected body shape.
    sent_requests = httpx_mock.get_requests()
    assert len(sent_requests) == 1
    sent = sent_requests[0]
    assert sent.headers["authorization"] == f"Bearer {settings.lq_ai_bridge_token}"
    assert json.loads(sent.content) == {
        "team_id": "T0123456",
        "team_name": "Acme Legal",
        "bot_token": "xoxb-fake-bot-token",
        "bot_user_id": "U99BOT",
        "installer_slack_user_id": "U11INSTALLER",
        "scope": "commands,chat:write,users:read,users:read.email",
    }


# ---------------------------------------------------------------------------
# /slack/oauth/callback — failure paths
# ---------------------------------------------------------------------------


def test_callback_with_bad_state_returns_400(client: TestClient) -> None:
    """A state token we didn't issue is rejected with 400."""
    res = client.get("/slack/oauth/callback?code=anything&state=not-a-real-state")
    assert res.status_code == 400
    assert "invalid or expired state" in res.text.lower()


def test_callback_with_error_query_param_renders_cancellation_page(
    client: TestClient,
) -> None:
    """``?error=access_denied`` with a valid state short-circuits without
    touching Slack/api. The provider's error string is logged, not echoed."""
    state = _seed_state("stateDenied")
    res = client.get(f"/slack/oauth/callback?state={state}&error=access_denied")
    assert res.status_code == 400
    assert "Install cancelled" in res.text
    assert "access_denied" not in res.text
    # The token was consumed — a cancelled flow cannot be replayed.
    assert state not in oauth_module._STATE_STORE


def test_callback_with_slack_returning_not_ok_returns_502(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If Slack's oauth.v2.access returns ok=false, the bridge surfaces 502."""
    state = _seed_state("stateNotOk")

    class _NotOkClient(_StubAsyncWebClient):
        def __init__(self) -> None:
            super().__init__(payload={"ok": False, "error": "invalid_code"})

    monkeypatch.setattr(
        "slack_sdk.web.async_client.AsyncWebClient",
        _NotOkClient,
        raising=True,
    )
    res = client.get(f"/slack/oauth/callback?code=bad&state={state}")
    assert res.status_code == 502
    assert "invalid_code" in res.text


def test_callback_with_api_persist_failure_returns_502(
    client: TestClient,
    settings: Settings,
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the api rejects the persistence POST, the bridge surfaces 502."""
    state = _seed_state("stateApiFail")
    monkeypatch.setattr(
        "slack_sdk.web.async_client.AsyncWebClient",
        _StubAsyncWebClient,
        raising=True,
    )
    httpx_mock.add_response(
        url=f"{settings.lq_ai_backend_url}/api/v1/integrations/slack/workspaces",
        method="POST",
        status_code=500,
        text="boom",
    )

    res = client.get(f"/slack/oauth/callback?code=auth-code&state={state}")
    assert res.status_code == 502
    assert "Backend rejected with HTTP 500" in res.text


# ---------------------------------------------------------------------------
# Output encoding + CSP (reflected-XSS regression, 2026-08 advisory)
# ---------------------------------------------------------------------------
#
# The pre-fix tests above exercised the vulnerable branch with the
# payload-free token ``access_denied``, which escaping leaves byte-identical
# — they passed before and after the fix. These tests carry live payloads
# and assert on absence of the raw markup, presence of the escaped form,
# and the security headers, so removing the escaping fails the suite.

_SCRIPT_PAYLOAD = "<script>document.title='pwned'</script>"
_IMG_PAYLOAD = '<img src=x onerror="alert(1)">'


def _assert_hardened_html(res: object) -> None:
    """Every HTML page the bridge serves: no live markup, CSP + nosniff set."""
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
    """The reported pre-auth reach: a bare crafted link never renders a page.

    The state check now runs before the user-declined branch, so an
    unauthenticated caller gets the JSON 400 — no HTML, no reflection.
    """
    res = client.get(f"/slack/oauth/callback?error={quote(_SCRIPT_PAYLOAD)}&state=forged&code=x")
    assert res.status_code == 400
    assert "invalid or expired state" in res.text.lower()
    assert "<script" not in res.text
    assert res.headers["content-type"].startswith("application/json")


def test_error_param_payload_is_not_reflected(client: TestClient) -> None:
    """Even with a valid state, ``error`` is never rendered — logged only."""
    state = _seed_state("stateXss")
    res = client.get(f"/slack/oauth/callback?error={quote(_SCRIPT_PAYLOAD)}&state={state}&code=x")
    assert res.status_code == 400
    assert "Install cancelled" in res.text
    assert "pwned" not in res.text
    _assert_hardened_html(res)


def test_cancellation_without_code_is_not_a_422(client: TestClient) -> None:
    """Slack's user-declined redirect carries ``error`` and ``state`` but no
    ``code``; ``code`` must therefore be optional or a real cancellation
    would surface as a validation error instead of the cancel page."""
    state = _seed_state("stateNoCode")
    res = client.get(f"/slack/oauth/callback?error=access_denied&state={state}")
    assert res.status_code == 400
    assert "Install cancelled" in res.text


def test_missing_code_without_error_returns_400_after_state_check(
    client: TestClient,
) -> None:
    state = _seed_state("stateOnlyState")
    res = client.get(f"/slack/oauth/callback?state={state}")
    assert res.status_code == 400
    assert "missing authorization code" in res.text.lower()


def test_slack_error_code_rendered_only_when_token_shaped(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``oauth.v2.access``'s ``error`` field is shown only if it looks like an
    RFC 6749 error code; markup falls back to ``unknown``."""
    state = _seed_state("stateMarkupError")

    class _MarkupErrorClient(_StubAsyncWebClient):
        def __init__(self) -> None:
            super().__init__(payload={"ok": False, "error": _IMG_PAYLOAD})

    monkeypatch.setattr(
        "slack_sdk.web.async_client.AsyncWebClient", _MarkupErrorClient, raising=True
    )
    res = client.get(f"/slack/oauth/callback?code=bad&state={state}")
    assert res.status_code == 502
    assert "error code: unknown" in res.text
    _assert_hardened_html(res)


def test_exchange_exception_detail_is_not_reflected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exception repr (which can carry upstream text) goes to the log, not the page."""
    state = _seed_state("stateExc")

    class _RaisingClient(_StubAsyncWebClient):
        async def oauth_v2_access(self, **kwargs: object) -> _StubSlackResponse:
            raise RuntimeError(_SCRIPT_PAYLOAD)

    monkeypatch.setattr("slack_sdk.web.async_client.AsyncWebClient", _RaisingClient, raising=True)
    res = client.get(f"/slack/oauth/callback?code=x&state={state}")
    assert res.status_code == 502
    assert "Install failed" in res.text
    assert "pwned" not in res.text
    _assert_hardened_html(res)


def test_success_page_escapes_workspace_name(
    client: TestClient,
    settings: Settings,
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The consenting party's own workspace name is still output-encoded."""
    state = _seed_state("stateName")

    class _MarkupNameClient(_StubAsyncWebClient):
        def __init__(self) -> None:
            super().__init__(
                payload={
                    "ok": True,
                    "access_token": "xoxb-fake-bot-token",
                    "bot_user_id": "U99BOT",
                    "scope": "commands,chat:write",
                    "team": {"id": "T0123456", "name": _IMG_PAYLOAD},
                    "authed_user": {"id": "U11INSTALLER"},
                }
            )

    monkeypatch.setattr(
        "slack_sdk.web.async_client.AsyncWebClient", _MarkupNameClient, raising=True
    )
    httpx_mock.add_response(
        url=f"{settings.lq_ai_backend_url}/api/v1/integrations/slack/workspaces",
        method="POST",
        status_code=201,
        json={},
    )
    res = client.get(f"/slack/oauth/callback?code=auth-code&state={state}")
    assert res.status_code == 200, res.text
    assert "Install complete" in res.text
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in res.text
    _assert_hardened_html(res)


def test_api_persist_rejection_body_is_not_reflected(
    client: TestClient,
    settings: Settings,
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _seed_state("stateApiBody")
    monkeypatch.setattr(
        "slack_sdk.web.async_client.AsyncWebClient", _StubAsyncWebClient, raising=True
    )
    httpx_mock.add_response(
        url=f"{settings.lq_ai_backend_url}/api/v1/integrations/slack/workspaces",
        method="POST",
        status_code=500,
        text=_SCRIPT_PAYLOAD,
    )
    res = client.get(f"/slack/oauth/callback?code=auth-code&state={state}")
    assert res.status_code == 502
    assert "Backend rejected with HTTP 500" in res.text
    _assert_hardened_html(res)
