"""Integration tests for ``GET /api/v1/models`` (Task D0).

The endpoint is a thin proxy over the gateway's merged-discovery
``GET /v1/models``. We mock the gateway with respx and assert:

* Auth: 401 without a bearer token; 200 with one.
* Happy path: the gateway's payload is forwarded verbatim.
* Gateway 401 (operator misconfig) → 503 ``gateway_unreachable``; the
  user must NOT see the underlying detail.
* Gateway 5xx → 503 ``gateway_unreachable``.
* Gateway timeout → 504 ``gateway_timeout``.

These are integration-style tests that bring up the FastAPI app with
the database fixture but don't rely on the gateway being live.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import GatewayClient, set_gateway_client
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.security import create_access_token, hash_password

GATEWAY_BASE = "http://test-gateway"
GATEWAY_KEY = "test-gw-key"


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def db_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"models-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Models Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


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


_GATEWAY_PAYLOAD: dict[str, object] = {
    "object": "list",
    "data": [
        {
            "id": "smart",
            "object": "model",
            "created": 0,
            "owned_by": "lq-ai-gateway",
            "lq_ai_kind": "alias",
        },
        {
            "id": "anthropic-prod/claude-haiku-4-5",
            "object": "model",
            "created": 0,
            "owned_by": "anthropic-prod",
            "lq_ai_kind": "provider_native",
            "routed_inference_tier": 4,
            "provider_type": "anthropic",
        },
        {
            "id": "ollama-local/llama3.1:8b",
            "object": "model",
            "created": 0,
            "owned_by": "ollama-local",
            "lq_ai_kind": "provider_native",
            "routed_inference_tier": 1,
            "provider_type": "ollama",
        },
    ],
}


@pytest.mark.integration
async def test_list_models_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/models")
    assert response.status_code == 401


@pytest.mark.integration
@respx.mock
async def test_list_models_forwards_gateway_payload_verbatim(
    client: AsyncClient,
    db_user: User,
) -> None:
    respx.get(f"{GATEWAY_BASE}/v1/models").mock(
        return_value=httpx.Response(200, json=_GATEWAY_PAYLOAD)
    )

    response = await client.get(
        "/api/v1/models",
        headers={"Authorization": f"Bearer {_bearer_for(db_user)}"},
    )

    assert response.status_code == 200
    assert response.json() == _GATEWAY_PAYLOAD


@pytest.mark.integration
@respx.mock
async def test_list_models_gateway_5xx_returns_503(
    client: AsyncClient,
    db_user: User,
) -> None:
    respx.get(f"{GATEWAY_BASE}/v1/models").mock(return_value=httpx.Response(503, text="oops"))

    response = await client.get(
        "/api/v1/models",
        headers={"Authorization": f"Bearer {_bearer_for(db_user)}"},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["detail"]["code"] == "gateway_unreachable"


@pytest.mark.integration
@respx.mock
async def test_list_models_gateway_401_returns_503_not_401(
    client: AsyncClient,
    db_user: User,
) -> None:
    """The user must not see "wrong gateway key" — operator misconfig surfaces as 503."""

    respx.get(f"{GATEWAY_BASE}/v1/models").mock(
        return_value=httpx.Response(
            401, json={"error": {"code": "unauthorized", "message": "bad key"}}
        )
    )

    response = await client.get(
        "/api/v1/models",
        headers={"Authorization": f"Bearer {_bearer_for(db_user)}"},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["detail"]["code"] == "gateway_unreachable"
    # The "bad key" detail must NOT leak through.
    assert "bad key" not in body["detail"]["message"].lower()


@pytest.mark.integration
@respx.mock
async def test_list_models_gateway_timeout_returns_504(
    client: AsyncClient,
    db_user: User,
) -> None:
    respx.get(f"{GATEWAY_BASE}/v1/models").mock(side_effect=httpx.TimeoutException("slow"))

    response = await client.get(
        "/api/v1/models",
        headers={"Authorization": f"Bearer {_bearer_for(db_user)}"},
    )

    assert response.status_code == 504
    body = response.json()
    assert body["detail"]["code"] == "gateway_timeout"


@pytest.mark.integration
@respx.mock
async def test_send_message_round_trips_raw_provider_model(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """Posting a raw ``anthropic-prod/claude-haiku-4-5`` model name to
    ``POST /chats/{id}/messages`` round-trips through the gateway and
    persists the resolved model on the assistant message row."""

    from sqlalchemy import select

    from app.models.chat import Chat, Message

    chat = Chat(owner_id=db_user.id, title="New chat")
    db_session.add(chat)
    await db_session.flush()
    chat_id = chat.id

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-d0",
                "object": "chat.completion",
                "created": 1_700_000_000,
                "model": "claude-haiku-4-5",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hi back"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
                "routed_inference_tier": 4,
                "routed_provider": "anthropic-prod",
            },
        )
    )

    response = await client.post(
        f"/api/v1/chats/{chat_id}/messages",
        headers={"Authorization": f"Bearer {_bearer_for(db_user)}"},
        json={
            "content": "hi",
            "model": "anthropic-prod/claude-haiku-4-5",
            "stream": False,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["routed_inference_tier"] == 4
    assert body["routed_provider"] == "anthropic-prod"

    # Persisted message row carries the upstream-reported model name.
    rows = (
        (
            await db_session.execute(
                select(Message).where(Message.chat_id == chat_id, Message.role == "assistant")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].routed_model == "claude-haiku-4-5"
    assert rows[0].routed_provider == "anthropic-prod"
