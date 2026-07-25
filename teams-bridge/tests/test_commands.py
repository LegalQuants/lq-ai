"""``/lq`` Teams command surface tests — DE-288.

Covers:

* Activity dispatch — missing bearer → 401; non-message/non-update
  types acknowledged and ignored; disallowed ``serviceUrl`` dropped
  with no outbound calls; non-``/lq`` messages ignored (no silent
  listening).
* Parse — mention stripping, help/unknown → usage, smart quotes and
  HTML entities normalized, quoted questions.
* Happy path — token fetch + member-info email resolution + api
  quick-ask + ONE reply activity with answer + link.
* Fail-closed identity — api 404 → "isn't linked" reply; member
  record without an email → "isn't linked" reply without calling the
  api at all.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pytest_httpx import HTTPXMock

from app.commands import (
    CONNECTOR_TOKEN_URL,
    USAGE_TEXT,
    ParsedCommand,
    parse_lq_text,
    service_url_allowed,
)
from app.config import Settings, get_settings
from app.main import create_app

BACKEND = "http://api.test"
SERVICE_URL = "https://smba.trafficmanager.net/amer"
CONVERSATION_ID = "19:conv-fixture"
SENDER_ID = "29:sender-fixture"
TENANT_ID = "tid-fixture-0001"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        microsoft_app_id="app-id-fixture",
        microsoft_app_password="app-secret-fixture",
        lq_ai_backend_url=BACKEND,
        lq_ai_bridge_token="bridge-token-fixture",
        lq_ai_teams_bridge_public_url="https://teams-bridge.test",
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def _activity(
    *,
    activity_type: str = "message",
    text: str = "/lq help",
    service_url: str = SERVICE_URL,
    **overrides: object,
) -> dict[str, object]:
    base: dict[str, object] = {
        "type": activity_type,
        "id": "activity-1",
        "text": text,
        "serviceUrl": service_url,
        "channelId": "msteams",
        "from": {"id": SENDER_ID, "aadObjectId": "oid-sender"},
        "recipient": {"id": "28:bot-fixture", "name": "LQ.AI"},
        "conversation": {"id": CONVERSATION_ID, "tenantId": TENANT_ID},
    }
    base.update(overrides)
    return base


AUTH = {"Authorization": "Bearer some-connector-jwt"}


def _mock_token(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url=CONNECTOR_TOKEN_URL,
        json={"access_token": "connector-token-fixture", "expires_in": 3600},
    )


def _mock_member(httpx_mock: HTTPXMock, *, email: str | None) -> None:
    member: dict[str, object] = {"id": SENDER_ID, "name": "Sender"}
    if email is not None:
        member["email"] = email
    httpx_mock.add_response(
        method="GET",
        url=f"{SERVICE_URL}/v3/conversations/{CONVERSATION_ID}/members/{SENDER_ID}",
        json=member,
    )


def _mock_reply(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{SERVICE_URL}/v3/conversations/{CONVERSATION_ID}/activities",
        json={"id": "reply-1"},
    )


def _reply_calls(httpx_mock: HTTPXMock) -> list[httpx.Request]:
    return [
        r
        for r in httpx_mock.get_requests()
        if str(r.url).endswith(f"/v3/conversations/{CONVERSATION_ID}/activities")
    ]


def _api_calls(httpx_mock: HTTPXMock) -> list[httpx.Request]:
    return [r for r in httpx_mock.get_requests() if str(r.url).startswith(BACKEND)]


# ---------------------------------------------------------------------------
# Parse (pure function)
# ---------------------------------------------------------------------------


def test_parse_ignores_non_lq_text() -> None:
    assert parse_lq_text("hello bot") is None


def test_parse_strips_bot_mention() -> None:
    assert parse_lq_text("<at>LQ.AI</at> /lq ask what is a DPA") == ParsedCommand(
        action="ask", question="what is a DPA"
    )


@pytest.mark.parametrize("text", ["/lq", "/lq help", "/lq bogus stuff", "/lq ask"])
def test_parse_help_variants(text: str) -> None:
    assert parse_lq_text(text) == ParsedCommand(action="help")


def test_parse_smart_quotes_and_entities() -> None:
    assert parse_lq_text("/lq ask “A &amp; B”") == ParsedCommand(action="ask", question="A & B")


def test_parse_unterminated_quote_falls_back_to_help() -> None:
    assert parse_lq_text('/lq ask "oops') == ParsedCommand(action="help")


# ---------------------------------------------------------------------------
# serviceUrl allowlist (pure function)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,allowed",
    [
        ("https://smba.trafficmanager.net/amer", True),
        ("https://europe.smba.trafficmanager.net/emea/", True),
        ("https://api.botframework.com", True),
        ("http://smba.trafficmanager.net/amer", False),  # not https
        ("https://evil.example.com/", False),
        ("https://smba.trafficmanager.net.evil.example/", False),
        ("not a url", False),
        ("", False),
    ],
)
def test_service_url_allowlist(url: str, allowed: bool) -> None:
    assert service_url_allowed(url) is allowed


def test_service_url_rejects_registered_trafficmanager_sibling() -> None:
    # `trafficmanager.net` is a shared Azure namespace: any customer can
    # register `<name>.trafficmanager.net`. Only the Microsoft-operated
    # Connector host `smba.trafficmanager.net` may pass.
    assert service_url_allowed("https://lqai-evil.trafficmanager.net") is False


def test_service_url_accepts_exact_connector_host() -> None:
    # Regression guard against over-tightening: the real Teams
    # serviceUrl uses the exact host `smba.trafficmanager.net`, which
    # does not end with the `.smba.trafficmanager.net` suffix. Passes
    # both before and after the allowlist tightening.
    assert service_url_allowed("https://smba.trafficmanager.net/amer/") is True


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_missing_bearer_returns_401(client: TestClient) -> None:
    res = client.post("/teams/messages", json=_activity())
    assert res.status_code == 401


def test_unrecognized_activity_type_is_acknowledged(
    client: TestClient, httpx_mock: HTTPXMock
) -> None:
    res = client.post(
        "/teams/messages",
        json=_activity(activity_type="typing"),
        headers=AUTH,
    )
    assert res.status_code == 200
    assert httpx_mock.get_requests() == []


def test_disallowed_service_url_is_dropped(client: TestClient, httpx_mock: HTTPXMock) -> None:
    res = client.post(
        "/teams/messages",
        json=_activity(service_url="https://evil.example.com/"),
        headers=AUTH,
    )
    assert res.status_code == 200
    assert httpx_mock.get_requests() == []


def test_non_lq_message_is_ignored(client: TestClient, httpx_mock: HTTPXMock) -> None:
    res = client.post(
        "/teams/messages",
        json=_activity(text="just chatting"),
        headers=AUTH,
    )
    assert res.status_code == 200
    assert httpx_mock.get_requests() == []


def test_help_replies_with_usage(client: TestClient, httpx_mock: HTTPXMock) -> None:
    _mock_token(httpx_mock)
    _mock_reply(httpx_mock)

    res = client.post("/teams/messages", json=_activity(text="/lq help"), headers=AUTH)
    assert res.status_code == 200

    replies = _reply_calls(httpx_mock)
    assert len(replies) == 1
    reply = json.loads(replies[0].content)
    assert reply["type"] == "message"
    assert reply["text"] == USAGE_TEXT
    assert reply["recipient"]["id"] == SENDER_ID


def test_welcome_on_conversation_update(client: TestClient, httpx_mock: HTTPXMock) -> None:
    _mock_token(httpx_mock)
    _mock_reply(httpx_mock)

    res = client.post(
        "/teams/messages",
        json=_activity(
            activity_type="conversationUpdate",
            text="",
            membersAdded=[{"id": SENDER_ID}],
        ),
        headers=AUTH,
    )
    assert res.status_code == 200
    replies = _reply_calls(httpx_mock)
    assert len(replies) == 1
    assert json.loads(replies[0].content)["text"] == USAGE_TEXT


def test_bot_only_conversation_update_is_ignored(client: TestClient, httpx_mock: HTTPXMock) -> None:
    res = client.post(
        "/teams/messages",
        json=_activity(
            activity_type="conversationUpdate",
            text="",
            membersAdded=[{"id": "28:bot-fixture"}],
        ),
        headers=AUTH,
    )
    assert res.status_code == 200
    assert httpx_mock.get_requests() == []


# ---------------------------------------------------------------------------
# /lq ask flows
# ---------------------------------------------------------------------------


def test_ask_happy_path(client: TestClient, httpx_mock: HTTPXMock) -> None:
    _mock_token(httpx_mock)
    _mock_member(httpx_mock, email="lawyer@acme.example")
    httpx_mock.add_response(
        method="POST",
        url=f"{BACKEND}/api/v1/integrations/quick-ask",
        json={
            "answer_text": "A DPA is a data processing agreement.",
            "chat_id": "22222222-2222-2222-2222-222222222222",
            "chat_url": "https://lq.test/lq-ai/chats?id=2222",
        },
    )
    _mock_reply(httpx_mock)

    res = client.post(
        "/teams/messages",
        json=_activity(text='<at>LQ.AI</at> /lq ask "What is a DPA?"'),
        headers=AUTH,
    )
    assert res.status_code == 200

    # The api saw the bridge bearer + the member-record email + tenant.
    api_calls = _api_calls(httpx_mock)
    assert len(api_calls) == 1
    assert api_calls[0].headers["authorization"] == "Bearer bridge-token-fixture"
    sent = json.loads(api_calls[0].content)
    assert sent == {
        "platform": "teams",
        "email": "lawyer@acme.example",
        "team_ref": TENANT_ID,
        "question": "What is a DPA?",
    }

    # Exactly ONE reply, carrying answer + link.
    replies = _reply_calls(httpx_mock)
    assert len(replies) == 1
    text = json.loads(replies[0].content)["text"]
    assert "A DPA is a data processing agreement." in text
    assert "https://lq.test/lq-ai/chats?id=2222" in text


def test_ask_unlinked_user_gets_refusal_reply(client: TestClient, httpx_mock: HTTPXMock) -> None:
    _mock_token(httpx_mock)
    _mock_member(httpx_mock, email="stranger@acme.example")
    httpx_mock.add_response(
        method="POST",
        url=f"{BACKEND}/api/v1/integrations/quick-ask",
        status_code=404,
        json={"detail": {"code": "user_not_linked", "message": "not linked"}},
    )
    _mock_reply(httpx_mock)

    res = client.post("/teams/messages", json=_activity(text="/lq ask anything"), headers=AUTH)
    assert res.status_code == 200

    replies = _reply_calls(httpx_mock)
    assert len(replies) == 1
    assert "isn't linked" in json.loads(replies[0].content)["text"]


def test_ask_member_without_email_fails_closed_without_api_call(
    client: TestClient, httpx_mock: HTTPXMock
) -> None:
    _mock_token(httpx_mock)
    _mock_member(httpx_mock, email=None)
    _mock_reply(httpx_mock)

    res = client.post("/teams/messages", json=_activity(text="/lq ask anything"), headers=AUTH)
    assert res.status_code == 200

    # No api call was made — identity failed before authority.
    assert _api_calls(httpx_mock) == []
    replies = _reply_calls(httpx_mock)
    assert len(replies) == 1
    assert "couldn't be linked" in json.loads(replies[0].content)["text"]


def test_ask_api_error_gets_generic_reply(client: TestClient, httpx_mock: HTTPXMock) -> None:
    _mock_token(httpx_mock)
    _mock_member(httpx_mock, email="lawyer@acme.example")
    httpx_mock.add_response(
        method="POST",
        url=f"{BACKEND}/api/v1/integrations/quick-ask",
        status_code=500,
        json={"detail": {"code": "internal_error", "message": "secret internals"}},
    )
    _mock_reply(httpx_mock)

    res = client.post("/teams/messages", json=_activity(text="/lq ask anything"), headers=AUTH)
    assert res.status_code == 200

    replies = _reply_calls(httpx_mock)
    assert len(replies) == 1
    text = json.loads(replies[0].content)["text"]
    assert "something went wrong" in text.lower()
    assert "secret internals" not in text
