"""``/lq`` slash-command surface tests — DE-288.

Covers:

* Signature gate — missing/invalid signature and stale timestamp → 401
  with no detail about which check failed.
* Parse — help/empty/unknown subcommand render usage; ``ask`` accepts
  bare words, ASCII quotes, smart quotes, and HTML-entity-escaped
  text; unterminated quotes fall back to usage.
* Fail-closed identity — api 404 → ephemeral "account isn't linked"
  refusal via response_url.
* Account-not-ready — api 403 → ephemeral "finish setup" refusal.
* Generic failure — api 5xx / unreachable → generic ephemeral with a
  correlation reference; handled failures never surface non-200 to
  Slack.
* Happy path — immediate ephemeral ack; ONE final response_url POST
  carrying the answer + chat link.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import httpx
import pytest
from fastapi.testclient import TestClient
from pytest_httpx import HTTPXMock

from app.commands import USAGE_TEXT, ParsedCommand, parse_command
from app.config import Settings, get_settings
from app.main import create_app

SIGNING_SECRET = "test-signing-secret-for-commands"
BACKEND = "http://api.test"
RESPONSE_URL = "https://hooks.slack.test/commands/T1/123/abc"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        slack_client_id="A123CLIENT",
        slack_client_secret="A123SECRET",
        slack_signing_secret=SIGNING_SECRET,
        lq_ai_backend_url=BACKEND,
        lq_ai_bridge_token="bridge-token-fixture",
        lq_ai_bridge_public_url="https://bridge.test",
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def _signed_headers(body: bytes, *, timestamp: int | None = None) -> dict[str, str]:
    ts = timestamp if timestamp is not None else int(time.time())
    base = f"v0:{ts}:".encode() + body
    digest = hmac.new(SIGNING_SECRET.encode(), base, hashlib.sha256).hexdigest()
    return {
        "X-Slack-Request-Timestamp": str(ts),
        "X-Slack-Signature": f"v0={digest}",
        "Content-Type": "application/x-www-form-urlencoded",
    }


def _command_body(text: str) -> bytes:
    return urlencode(
        {
            "command": "/lq",
            "text": text,
            "user_id": "U0USER",
            "team_id": "T0TEAM",
            "response_url": RESPONSE_URL,
            "channel_id": "C0CHAN",
        }
    ).encode()


# ---------------------------------------------------------------------------
# Signature gate
# ---------------------------------------------------------------------------


def test_missing_signature_returns_401(client: TestClient) -> None:
    res = client.post("/slack/commands", content=_command_body("help"))
    assert res.status_code == 401


def test_tampered_body_returns_401(client: TestClient) -> None:
    body = _command_body("help")
    headers = _signed_headers(body)
    res = client.post("/slack/commands", content=body + b"&extra=1", headers=headers)
    assert res.status_code == 401


def test_stale_timestamp_returns_401(client: TestClient) -> None:
    body = _command_body("help")
    stale = int(time.time()) - 6 * 60  # outside the 5-minute window
    headers = _signed_headers(body, timestamp=stale)
    res = client.post("/slack/commands", content=body, headers=headers)
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Parse (pure function)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   ", "help", "HELP", "bogus subcommand", "ask", 'ask ""'])
def test_parse_help_and_unknown_and_empty_ask(text: str) -> None:
    assert parse_command(text) == ParsedCommand(action="help")


def test_parse_ask_bare_words() -> None:
    assert parse_command("ask what is an NDA") == ParsedCommand(
        action="ask", question="what is an NDA"
    )


def test_parse_ask_ascii_quoted() -> None:
    assert parse_command('ask "what is an NDA?"') == ParsedCommand(
        action="ask", question="what is an NDA?"
    )


def test_parse_ask_smart_quoted() -> None:
    # Clients curly-quote the user's typed quotes; the parser must
    # normalize U+201C/U+201D before the shlex split.
    assert parse_command("ask “what is an NDA?”") == ParsedCommand(
        action="ask", question="what is an NDA?"
    )


def test_parse_ask_html_entities_unescaped() -> None:
    # Slack escapes & < > in the command text.
    assert parse_command("ask is A &amp; B &lt; C") == ParsedCommand(
        action="ask", question="is A & B < C"
    )


def test_parse_unterminated_quote_falls_back_to_help() -> None:
    assert parse_command('ask "unterminated') == ParsedCommand(action="help")


# ---------------------------------------------------------------------------
# Endpoint behavior
# ---------------------------------------------------------------------------


def test_help_returns_immediate_ephemeral_usage(client: TestClient) -> None:
    body = _command_body("help")
    res = client.post("/slack/commands", content=body, headers=_signed_headers(body))
    assert res.status_code == 200
    payload = res.json()
    assert payload["response_type"] == "ephemeral"
    assert payload["text"] == USAGE_TEXT


def test_unknown_subcommand_returns_usage(client: TestClient) -> None:
    body = _command_body("frobnicate now")
    res = client.post("/slack/commands", content=body, headers=_signed_headers(body))
    assert res.status_code == 200
    assert res.json()["text"] == USAGE_TEXT


def _quick_ask_calls(httpx_mock: HTTPXMock) -> list[httpx.Request]:
    return [r for r in httpx_mock.get_requests() if str(r.url).startswith(f"{BACKEND}/api/v1/")]


def _response_url_calls(httpx_mock: HTTPXMock) -> list[httpx.Request]:
    return [r for r in httpx_mock.get_requests() if str(r.url) == RESPONSE_URL]


def test_ask_happy_path_acks_then_posts_answer(client: TestClient, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{BACKEND}/api/v1/integrations/quick-ask",
        json={
            "answer_text": "An NDA is a nondisclosure agreement.",
            "chat_id": "11111111-1111-1111-1111-111111111111",
            "chat_url": "https://lq.test/c/1111",
        },
    )
    httpx_mock.add_response(method="POST", url=RESPONSE_URL, json={"ok": True})

    body = _command_body('ask "what is an NDA?"')
    res = client.post("/slack/commands", content=body, headers=_signed_headers(body))

    # Immediate ack (inside Slack's 3 s window) is ephemeral.
    assert res.status_code == 200
    ack = res.json()
    assert ack["response_type"] == "ephemeral"
    assert "Working on it" in ack["text"]

    # The deferred worker called the api with bridge bearer + identity.
    api_calls = _quick_ask_calls(httpx_mock)
    assert len(api_calls) == 1
    assert api_calls[0].headers["authorization"] == "Bearer bridge-token-fixture"
    sent = json.loads(api_calls[0].content)
    assert sent == {
        "platform": "slack",
        "platform_user_id": "U0USER",
        "team_ref": "T0TEAM",
        "question": "what is an NDA?",
    }

    # Exactly ONE final response_url post, ephemeral, answer + link.
    finals = _response_url_calls(httpx_mock)
    assert len(finals) == 1
    final = json.loads(finals[0].content)
    assert final["response_type"] == "ephemeral"
    assert "An NDA is a nondisclosure agreement." in final["text"]
    assert "https://lq.test/c/1111" in final["text"]


def test_ask_unlinked_user_gets_ephemeral_refusal(
    client: TestClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{BACKEND}/api/v1/integrations/quick-ask",
        status_code=404,
        json={"error": {"code": "not_found", "message": "user not linked"}},
    )
    httpx_mock.add_response(method="POST", url=RESPONSE_URL, json={"ok": True})

    body = _command_body("ask what is an NDA")
    res = client.post("/slack/commands", content=body, headers=_signed_headers(body))
    assert res.status_code == 200

    finals = _response_url_calls(httpx_mock)
    assert len(finals) == 1
    final = json.loads(finals[0].content)
    assert final["response_type"] == "ephemeral"
    assert "isn't linked" in final["text"]


def test_ask_account_not_ready_gets_ephemeral_refusal(
    client: TestClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{BACKEND}/api/v1/integrations/quick-ask",
        status_code=403,
        json={"error": {"code": "forbidden", "message": "account not ready"}},
    )
    httpx_mock.add_response(method="POST", url=RESPONSE_URL, json={"ok": True})

    body = _command_body("ask anything")
    res = client.post("/slack/commands", content=body, headers=_signed_headers(body))
    assert res.status_code == 200

    finals = _response_url_calls(httpx_mock)
    assert len(finals) == 1
    assert "isn't ready" in json.loads(finals[0].content)["text"]


def test_ask_api_error_gets_generic_ephemeral(client: TestClient, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{BACKEND}/api/v1/integrations/quick-ask",
        status_code=500,
        json={"error": {"code": "internal_error", "message": "boom secret detail"}},
    )
    httpx_mock.add_response(method="POST", url=RESPONSE_URL, json={"ok": True})

    body = _command_body("ask anything")
    res = client.post("/slack/commands", content=body, headers=_signed_headers(body))
    assert res.status_code == 200

    finals = _response_url_calls(httpx_mock)
    assert len(finals) == 1
    text = json.loads(finals[0].content)["text"]
    # Generic message + correlation ref; never internal detail.
    assert "something went wrong" in text.lower()
    assert "ref:" in text
    assert "boom secret detail" not in text


def test_ask_api_unreachable_gets_generic_ephemeral(
    client: TestClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_exception(
        httpx.ConnectError("connection refused"),
        method="POST",
        url=f"{BACKEND}/api/v1/integrations/quick-ask",
    )
    httpx_mock.add_response(method="POST", url=RESPONSE_URL, json={"ok": True})

    body = _command_body("ask anything")
    res = client.post("/slack/commands", content=body, headers=_signed_headers(body))
    assert res.status_code == 200

    finals = _response_url_calls(httpx_mock)
    assert len(finals) == 1
    assert "something went wrong" in json.loads(finals[0].content)["text"].lower()
