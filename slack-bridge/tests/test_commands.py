"""Signed slash commands only disclose association URLs in private replies."""

import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx
import pytest
from fastapi.testclient import TestClient
from pytest_httpx import HTTPXMock

from app.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    settings = Settings(
        slack_client_id="app",
        slack_client_secret="secret",
        slack_signing_secret="signing",
        lq_ai_backend_url="https://api.test",
        lq_ai_bridge_token="installation",
        lq_ai_bridge_public_url="https://bridge.test",
        lq_ai_slack_command_token="command",
    )
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def send(
    client: TestClient, text: str = "help", *, timestamp: int | None = None, extra: str = ""
) -> httpx.Response:
    raw = (
        urlencode(
            {
                "command": "/lq",
                "text": text,
                "team_id": "T0123",
                "user_id": "U111",
                "response_url": "https://attacker.test/secret",
            }
        )
        + extra
    )
    ts = str(int(time.time()) if timestamp is None else timestamp)
    signature = "v0=" + hmac.new(b"signing", f"v0:{ts}:{raw}".encode(), hashlib.sha256).hexdigest()
    return client.post(
        "/slack/commands",
        content=raw,
        headers={
            "X-Slack-Signature": signature,
            "X-Slack-Request-Timestamp": ts,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )


def test_verified_help_forwards_only_platform_ids_and_returns_private_link(
    client: TestClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://api.test/api/v1/integrations/slack/link-requests",
        status_code=201,
        json={"url": "https://web.test/lq-ai/slack/link#token=private"},
    )
    result = send(client)
    assert result.status_code == 200
    assert result.json()["response_type"] == "ephemeral"
    assert "#token=private" in result.json()["text"]
    calls = httpx_mock.get_requests()
    assert len(calls) == 1
    assert calls[0].headers["authorization"] == "Bearer command"
    assert calls[0].content == b'{"team_id":"T0123","slack_user_id":"U111"}'
    assert len(calls) == 1  # No profile lookup or response_url egress.


def test_unsigned_stale_tampered_and_ambiguous_requests_never_reach_backend(
    client: TestClient, httpx_mock: HTTPXMock
) -> None:
    assert client.post("/slack/commands", content="team_id=T0123&user_id=U111").status_code == 401
    assert send(client, timestamp=int(time.time()) - 301).status_code == 401
    tampered = client.post(
        "/slack/commands",
        content="team_id=TOTHER&user_id=U111",
        headers={
            "X-Slack-Request-Timestamp": str(int(time.time())),
            "X-Slack-Signature": "v0=" + "0" * 64,
        },
    )
    assert tampered.status_code == 401
    assert send(client, extra="&user_id=UOTHER").status_code == 400
    assert len(httpx_mock.get_requests()) == 0


def test_ask_does_not_issue_link_or_inference(client: TestClient, httpx_mock: HTTPXMock) -> None:
    result = send(client, text="ask confidential prompt")
    assert result.json()["response_type"] == "ephemeral"
    assert "not available yet" in result.json()["text"]
    assert "confidential" not in result.text
    assert not httpx_mock.get_requests()


@pytest.mark.parametrize("failure", [401, 404, 500])
def test_backend_failures_are_private_and_do_not_echo_details(
    client: TestClient, failure: int, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://api.test/api/v1/integrations/slack/link-requests",
        status_code=failure,
        text="secret-internal-diagnostics",
    )
    result = send(client)
    assert result.json()["response_type"] == "ephemeral"
    assert "Unable" in result.json()["text"]
    assert "secret-internal" not in result.text


def test_backend_timeout_is_private(client: TestClient, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_exception(httpx.ReadTimeout("secret"))
    result = send(client)
    assert "Unable" in result.json()["text"]
    assert "secret" not in result.text
