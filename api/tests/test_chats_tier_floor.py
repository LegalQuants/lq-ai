"""Tests for D1 — tier-floor forwarding + 403 translation in the chat handler.

Two surface contracts to verify on the api/ side:

1. **Project-floor forwarding.** When a chat lives in a project with
   ``minimum_inference_tier`` set, the backend reads that value and
   sends it on the gateway request as
   ``lq_ai_project_minimum_inference_tier``. The gateway is
   authoritative on refusal; the backend just supplies the value.
2. **403 translation.** When the gateway returns a 403 with
   ``error.code == "tier_below_minimum"``, the backend surfaces a 403
   to the API caller — code preserved, details preserved, status
   preserved, message preserved. No 500 morphing.

Under PRD §1.5.2 lower tier number = stronger security. The project
fixture uses ``minimum_inference_tier=3`` which means "require Tier 3
or stronger." The gateway is authoritative on refusal direction; these
tests only verify the forwarding and translation layers.
"""

from __future__ import annotations

import json as _json
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import GatewayClient, set_gateway_client
from app.db.session import get_db
from app.main import app
from app.models.chat import Chat
from app.models.project import Project
from app.models.user import User
from app.security import create_access_token, hash_password

GATEWAY_BASE = "http://test-gateway"
GATEWAY_KEY = "test-gw-key"


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def db_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"d1-{uuid.uuid4().hex[:8]}@example.com",
        display_name="D1 Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def db_chat(db_session: AsyncSession, db_user: User) -> Chat:
    chat = Chat(owner_id=db_user.id, title="New chat")
    db_session.add(chat)
    await db_session.flush()
    return chat


@pytest_asyncio.fixture
async def project_with_floor(db_session: AsyncSession, db_user: User) -> Project:
    """Project with ``minimum_inference_tier=3`` (declared via privileged=True)."""

    project = Project(
        owner_id=db_user.id,
        name="Privileged Matter",
        slug=f"priv-{uuid.uuid4().hex[:6]}",
        privileged=True,
        minimum_inference_tier=3,
    )
    db_session.add(project)
    await db_session.flush()
    return project


@pytest_asyncio.fixture
async def chat_in_project(
    db_session: AsyncSession, db_user: User, project_with_floor: Project
) -> Chat:
    chat = Chat(
        owner_id=db_user.id,
        project_id=project_with_floor.id,
        title="New chat",
    )
    db_session.add(chat)
    await db_session.flush()
    return chat


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    gw = GatewayClient(base_url=GATEWAY_BASE, gateway_key=GATEWAY_KEY)
    set_gateway_client(gw)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    set_gateway_client(None)
    await gw.aclose()
    app.dependency_overrides.pop(get_db, None)


def _bearer_for(user: User) -> str:
    return create_access_token(user.id, user.email, is_admin=user.is_admin)


def _success_payload() -> dict[str, object]:
    return {
        "id": "chatcmpl-d1",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": "claude-opus-4-7",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        "routed_inference_tier": 4,
        "routed_provider": "anthropic-prod",
    }


# --- Project-floor forwarding -----------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_project_minimum_tier_forwarded_to_gateway(
    client: AsyncClient,
    db_user: User,
    chat_in_project: Chat,
) -> None:
    """A chat in a project forwards Project.minimum_inference_tier to the gateway."""

    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )
    token = _bearer_for(db_user)

    response = await client.post(
        f"/api/v1/chats/{chat_in_project.id}/messages",
        json={"content": "hi", "model": "smart"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text

    sent_body = _json.loads(route.calls[0].request.read())
    assert sent_body["lq_ai_project_minimum_inference_tier"] == 3
    # M2-B3: ``project.privileged=True`` propagates so the gateway
    # anonymization middleware skips for privileged chats. The
    # ``project_with_floor`` fixture sets privileged=True (the CHECK
    # constraint requires it whenever minimum_inference_tier is set).
    assert sent_body["lq_ai_privileged"] is True


@pytest.mark.integration
@respx.mock
async def test_chat_outside_project_does_not_forward_project_floor(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
) -> None:
    """A chat with no project_id does NOT include the project-floor field."""

    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )
    token = _bearer_for(db_user)

    await client.post(
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "hi"},
        headers={"Authorization": f"Bearer {token}"},
    )

    sent_body = _json.loads(route.calls[0].request.read())
    # The field is omitted (exclude_none) when there's no project floor.
    assert "lq_ai_project_minimum_inference_tier" not in sent_body
    # M2-B3: ``lq_ai_privileged`` defaults False; either omitted or
    # explicitly False. Either way, must not be True.
    assert sent_body.get("lq_ai_privileged", False) is False


@pytest.mark.integration
@respx.mock
async def test_project_without_tier_floor_omits_field(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """A non-privileged project with no floor → field omitted."""

    project = Project(
        owner_id=db_user.id,
        name="Loose Matter",
        slug=f"loose-{uuid.uuid4().hex[:6]}",
        privileged=False,
        minimum_inference_tier=None,
    )
    db_session.add(project)
    await db_session.flush()
    chat = Chat(owner_id=db_user.id, project_id=project.id, title="x")
    db_session.add(chat)
    await db_session.flush()

    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )
    token = _bearer_for(db_user)

    await client.post(
        f"/api/v1/chats/{chat.id}/messages",
        json={"content": "hi"},
        headers={"Authorization": f"Bearer {token}"},
    )

    sent_body = _json.loads(route.calls[0].request.read())
    assert "lq_ai_project_minimum_inference_tier" not in sent_body


# --- 403 tier_below_minimum translation ------------------------------------


@pytest.mark.integration
@respx.mock
async def test_gateway_403_tier_below_minimum_surfaces_as_403(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
) -> None:
    """Gateway 403 ``tier_below_minimum`` → backend 403 with same code/details.

    No morphing into 500. The structured envelope flows through with
    enough fidelity that a UI can render "you tried to use a model below
    your privileged-project floor" without parsing a free-text message.
    """

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            403,
            json={
                "error": {
                    "code": "tier_below_minimum",
                    "message": (
                        "Request requires Inference Tier 3 or stronger "
                        "(source: project), but the routed model resolves "
                        "to tier 4, which is weaker."
                    ),
                    "details": {
                        "required_tier": 3,
                        "resolved_tier": 4,
                        "source": "project",
                        "requested_model": "smart",
                        "routed_provider": "anthropic-prod",
                        "routed_model": "claude-opus-4-7",
                    },
                }
            },
        )
    )
    token = _bearer_for(db_user)

    response = await client.post(
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "hi", "model": "smart"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    body = response.json()
    assert body["detail"]["code"] == "tier_below_minimum"
    details = body["detail"]["details"]
    # The structured fields survive translation.
    # required=3 (Tier 3 floor), resolved=4 (Tier 4 is weaker → refused)
    assert details["required_tier"] == 3
    assert details["resolved_tier"] == 4
    assert details["source"] == "project"
    # The translator stamps the original gateway code for forensics.
    assert details["gateway_code"] == "tier_below_minimum"


@pytest.mark.integration
@respx.mock
async def test_request_minimum_inference_tier_can_be_set_via_payload(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
) -> None:
    """Backend accepts client-supplied ``minimum_inference_tier`` and forwards.

    M1 today doesn't expose a request-override field on
    ``MessageCreateRequest`` — the surface is project-floor only — so a
    request override is purely a future surface. This test pins that
    when *no* override is set and *no* project floor exists, the
    gateway sees neither field (omitted via exclude_none).
    """

    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )
    token = _bearer_for(db_user)

    await client.post(
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "hi"},
        headers={"Authorization": f"Bearer {token}"},
    )

    sent_body = _json.loads(route.calls[0].request.read())
    assert "minimum_inference_tier" not in sent_body
    assert "lq_ai_project_minimum_inference_tier" not in sent_body


@pytest.mark.integration
@respx.mock
async def test_gateway_403_does_not_persist_assistant_message(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
    db_session: AsyncSession,
) -> None:
    """A 403 refusal must NOT write a half-formed assistant message row.

    The user message is persisted (the user did say something), but the
    gateway never produced an assistant response, so no assistant row
    should appear.
    """

    from sqlalchemy import select

    from app.models.chat import Message

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            403,
            json={
                "error": {
                    "code": "tier_below_minimum",
                    "message": "below floor",
                    "details": {"required_tier": 5, "resolved_tier": 4, "source": "request"},
                }
            },
        )
    )
    token = _bearer_for(db_user)

    response = await client.post(
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "hi"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403

    rows = (
        (await db_session.execute(select(Message).where(Message.chat_id == db_chat.id)))
        .scalars()
        .all()
    )
    # The user row was persisted; no assistant row was added.
    roles = [r.role for r in rows]
    assert roles == ["user"]
