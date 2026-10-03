"""Integration tests for the DE-288 bridge quick-ask endpoint.

Covers ``POST /api/v1/integrations/quick-ask``:

* Auth — missing / wrong bridge bearer → 401 (the bearer authenticates
  the bridge, not the user).
* Validation — slack without ``platform_user_id`` / teams without
  ``email`` → 422.
* Fail-closed identity — unknown workspace, unresolvable Slack email,
  unmatched email, unknown tenant → 404 ``user_not_linked`` (uniform;
  the response never says which step failed).
* Account-not-ready — matched user behind the must-change-password
  gate → 403.
* Happy paths (slack + teams) — the turn runs through the normal
  chat-send path: chat + both message rows persisted under the
  resolved user, cost estimate attributed, the configured quick-ask
  skill forwarded to the gateway, the ``bridge.quick_ask`` audit row
  tagged with ``details.source``, and the ``bridge-{platform}-…``
  request id forwarded to the gateway (cost/routing correlation).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import GatewayClient, set_gateway_client
from app.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.chat import Chat, Message
from app.models.slack_workspace import SlackWorkspace
from app.models.teams_tenant import TeamsTenant
from app.models.user import User
from app.security import hash_password
from app.security.encryption import BridgeTokenEncryptor, generate_master_key

BRIDGE_TOKEN = "bridge-token-quick-ask-fixture"
GATEWAY_BASE = "http://test-gateway"
GATEWAY_KEY = "test-gw-key"
QUICK_ASK_SKILL = "nda-review"
WEB_URL = "https://lq.example.test"
BOT_TOKEN_PLAINTEXT = "xoxb-quick-ask-bot-token"


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def configured_settings(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[str]:
    """Bridge env + quick-ask skill + web URL, with a fresh Settings cache."""

    master_key = generate_master_key()
    monkeypatch.setenv("LQ_AI_BRIDGE_TOKEN", BRIDGE_TOKEN)
    monkeypatch.setenv("LQ_AI_BRIDGE_MASTER_KEY", master_key)
    monkeypatch.setenv("LQ_AI_BRIDGE_QUICK_ASK_SKILL", QUICK_ASK_SKILL)
    monkeypatch.setenv("LQ_AI_WEB_PUBLIC_URL", WEB_URL)
    get_settings.cache_clear()
    yield master_key
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession,
    configured_settings: str,
) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    gw = GatewayClient(base_url=GATEWAY_BASE, gateway_key=GATEWAY_KEY)
    set_gateway_client(gw)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    set_gateway_client(None)
    await gw.aclose()
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def linked_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"quickask-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Quick Ask User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def slack_workspace(
    db_session: AsyncSession,
    configured_settings: str,
) -> SlackWorkspace:
    encryptor = BridgeTokenEncryptor(master_key=configured_settings)
    workspace = SlackWorkspace(
        team_id="T0QUICKASK",
        team_name="Quick Ask Legal",
        bot_token_encrypted=encryptor.encrypt(BOT_TOKEN_PLAINTEXT),
        bot_user_id="U0BOT",
        installer_slack_user_id="U0INSTALL",
        scope="commands,chat:write,users:read,users:read.email",
    )
    db_session.add(workspace)
    await db_session.flush()
    return workspace


@pytest_asyncio.fixture
async def teams_tenant(db_session: AsyncSession) -> TeamsTenant:
    tenant = TeamsTenant(
        tenant_id="tid-quickask-0001",
        tenant_name="Quick Ask Org",
        installer_oid="oid-installer",
    )
    db_session.add(tenant)
    await db_session.flush()
    return tenant


def _slack_body(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "platform": "slack",
        "platform_user_id": "U0ASKER",
        "team_ref": "T0QUICKASK",
        "question": "What is an NDA?",
    }
    base.update(overrides)
    return base


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {BRIDGE_TOKEN}"}


def _mock_users_info(email: str | None) -> respx.Route:
    profile: dict[str, object] = {"email": email} if email else {}
    return respx.get("https://slack.com/api/users.info").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True, "user": {"id": "U0ASKER", "profile": profile}},
        )
    )


def _mock_gateway_completion(content: str = "An NDA is a contract.") -> respx.Route:
    return respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-qa",
                "object": "chat.completion",
                "created": 1_700_000_000,
                "model": "claude-sonnet-4-6",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12},
                "routed_inference_tier": 3,
                "routed_provider": "anthropic-prod",
                "cost_estimate": 0.00042,
                "lq_ai_applied_skills": [QUICK_ASK_SKILL],
            },
        )
    )


# ---------------------------------------------------------------------------
# Auth (RBAC — the bearer authenticates the bridge only)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_quick_ask_without_bearer_returns_401(client: AsyncClient) -> None:
    res = await client.post("/api/v1/integrations/quick-ask", json=_slack_body())
    assert res.status_code == 401


@pytest.mark.integration
async def test_quick_ask_with_wrong_bearer_returns_401(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/integrations/quick-ask",
        headers={"Authorization": "Bearer wrong-token"},
        json=_slack_body(),
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_quick_ask_slack_without_platform_user_id_returns_422(
    client: AsyncClient,
) -> None:
    res = await client.post(
        "/api/v1/integrations/quick-ask",
        headers=_auth(),
        json=_slack_body(platform_user_id=None),
    )
    assert res.status_code == 422


@pytest.mark.integration
async def test_quick_ask_teams_without_email_returns_422(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/integrations/quick-ask",
        headers=_auth(),
        json={"platform": "teams", "team_ref": "tid-x", "question": "hi"},
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Fail-closed identity resolution
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_quick_ask_unknown_workspace_returns_user_not_linked(
    client: AsyncClient,
) -> None:
    res = await client.post(
        "/api/v1/integrations/quick-ask",
        headers=_auth(),
        json=_slack_body(team_ref="T0UNKNOWN"),
    )
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "user_not_linked"


@pytest.mark.integration
@respx.mock
async def test_quick_ask_slack_users_info_error_returns_user_not_linked(
    client: AsyncClient,
    slack_workspace: SlackWorkspace,
) -> None:
    # e.g. a pre-DE-288 install whose token lacks users:read.email.
    respx.get("https://slack.com/api/users.info").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "missing_scope"})
    )
    res = await client.post("/api/v1/integrations/quick-ask", headers=_auth(), json=_slack_body())
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "user_not_linked"


@pytest.mark.integration
@respx.mock
async def test_quick_ask_unmatched_email_returns_user_not_linked(
    client: AsyncClient,
    slack_workspace: SlackWorkspace,
) -> None:
    _mock_users_info("nobody-here@example.com")
    res = await client.post("/api/v1/integrations/quick-ask", headers=_auth(), json=_slack_body())
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "user_not_linked"


@pytest.mark.integration
async def test_quick_ask_unknown_tenant_returns_user_not_linked(
    client: AsyncClient,
    linked_user: User,
) -> None:
    res = await client.post(
        "/api/v1/integrations/quick-ask",
        headers=_auth(),
        json={
            "platform": "teams",
            "email": linked_user.email,
            "team_ref": "tid-unknown",
            "question": "hi there",
        },
    )
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "user_not_linked"


@pytest.mark.integration
@respx.mock
async def test_quick_ask_gated_user_returns_403(
    client: AsyncClient,
    db_session: AsyncSession,
    slack_workspace: SlackWorkspace,
) -> None:
    gated = User(
        email=f"gated-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Gated User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=True,
    )
    db_session.add(gated)
    await db_session.flush()
    _mock_users_info(gated.email)

    res = await client.post("/api/v1/integrations/quick-ask", headers=_auth(), json=_slack_body())
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_quick_ask_slack_happy_path(
    client: AsyncClient,
    db_session: AsyncSession,
    linked_user: User,
    slack_workspace: SlackWorkspace,
) -> None:
    users_info = _mock_users_info(linked_user.email)
    gateway_route = _mock_gateway_completion("An NDA is a contract.")

    res = await client.post("/api/v1/integrations/quick-ask", headers=_auth(), json=_slack_body())
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["answer_text"] == "An NDA is a contract."
    assert body["chat_url"] == f"{WEB_URL}/lq-ai/chats?id={body['chat_id']}"

    # users.info was called with the workspace's decrypted bot token.
    assert users_info.called
    info_req = users_info.calls[0].request
    assert info_req.headers["authorization"] == f"Bearer {BOT_TOKEN_PLAINTEXT}"

    # The turn ran through the normal send path: the configured
    # quick-ask skill and the bridge-tagged request id reached the
    # gateway (cost/routing correlation).
    assert gateway_route.called
    import json as _json

    gw_req = _json.loads(gateway_route.calls[0].request.content)
    assert gw_req["lq_ai_skills"] == [QUICK_ASK_SKILL]
    assert gw_req["lq_ai_user_id"] == str(linked_user.id)
    assert gateway_route.calls[0].request.headers["x-request-id"].startswith("bridge-slack-")

    # Chat + both message rows persisted under the resolved user, with
    # the gateway's cost estimate attributed to the assistant row.
    chat_id = uuid.UUID(body["chat_id"])
    chat = (await db_session.execute(select(Chat).where(Chat.id == chat_id))).scalar_one()
    assert chat.owner_id == linked_user.id
    messages = (
        (
            await db_session.execute(
                select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].content == "What is an NDA?"
    assert messages[1].cost_estimate_micros is not None

    # Provenance: the bridge.quick_ask audit row carries the source tag.
    audit = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "bridge.quick_ask",
                    AuditLog.resource_id == str(chat_id),
                )
            )
        )
        .scalars()
        .one()
    )
    assert audit.user_id == linked_user.id
    assert audit.details["source"] == "slack"
    assert audit.details["skill"] == QUICK_ASK_SKILL


@pytest.mark.integration
@respx.mock
async def test_quick_ask_teams_happy_path(
    client: AsyncClient,
    db_session: AsyncSession,
    linked_user: User,
    teams_tenant: TeamsTenant,
) -> None:
    gateway_route = _mock_gateway_completion("Teams answer.")

    res = await client.post(
        "/api/v1/integrations/quick-ask",
        headers=_auth(),
        json={
            "platform": "teams",
            "email": linked_user.email.upper(),  # case-insensitive match
            "team_ref": teams_tenant.tenant_id,
            "question": "What is a DPA?",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["answer_text"] == "Teams answer."

    assert gateway_route.called
    assert gateway_route.calls[0].request.headers["x-request-id"].startswith("bridge-teams-")

    audit = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "bridge.quick_ask",
                    AuditLog.resource_id == body["chat_id"],
                )
            )
        )
        .scalars()
        .one()
    )
    assert audit.details["source"] == "teams"
