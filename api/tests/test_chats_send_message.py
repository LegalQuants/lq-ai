"""Integration tests for the chat-message exchange endpoint (B5 + C3).

The endpoint at ``POST /api/v1/chats/{chat_id}/messages`` was wired
through to the gateway in B5 (stateless pass-through) and now persists
both sides of the exchange in C3. These tests cover:

* Auth gate — must be authenticated.
* B2 forced-password-change gate.
* Validation — empty body / non-UUID chat_id / missing content.
* Per-user isolation — cross-user chat 404.
* Happy path (non-streaming) — gateway returns a response, backend
  surfaces tier and routed_provider in body and headers, and
  persists both rows.
* Error translation — gateway 5xx, gateway timeout, gateway 401
  (operator misconfig), gateway 4xx with ``provider_unavailable`` /
  ``invalid_model``, gateway malformed body.
* Streaming — happy path, mid-stream error, pre-frame error.
* No double-write of inference_routing_log — the gateway writes; the
  backend does not.
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
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import GatewayClient, set_gateway_client
from app.db.session import get_db
from app.main import app
from app.models.chat import Chat, Message
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
    """Insert a normal user (must_change_password=False) for chat tests."""

    user = User(
        email=f"chat-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Chat Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def gated_user(db_session: AsyncSession) -> User:
    """User with must_change_password=True — should hit the B2 gate."""

    user = User(
        email=f"gated-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Gated Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def db_chat(db_session: AsyncSession, db_user: User) -> Chat:
    """Create a real chat owned by ``db_user`` so the C3 endpoint has
    something to attach messages to."""

    chat = Chat(owner_id=db_user.id, title="New chat")
    db_session.add(chat)
    await db_session.flush()
    return chat


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """In-process AsyncClient with a controlled GatewayClient injected.

    The GatewayClient is wired against ``http://test-gateway`` and
    respx intercepts that origin. The DB session is the per-test
    SAVEPOINT one from conftest.py.
    """

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


def _success_payload(tier: int = 3, content: str = "hello back") -> dict[str, object]:
    return {
        "id": "chatcmpl-abc",
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
        "usage": {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
        "routed_inference_tier": tier,
        "routed_provider": "anthropic-prod",
        "cost_estimate": 0.00025,
    }


# ---------------------------------------------------------------------------
# Auth + gate
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_send_message_unauthenticated_returns_401(
    client: AsyncClient,
    db_chat: Chat,
) -> None:
    response = await client.post(
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "hello"},
    )

    assert response.status_code == 401


@pytest.mark.integration
async def test_send_message_with_must_change_password_returns_403(
    client: AsyncClient,
    gated_user: User,
    db_chat: Chat,
) -> None:
    token = _bearer_for(gated_user)

    response = await client.post(
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    body = response.json()
    assert body["detail"]["code"] == "password_change_required"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_send_message_with_non_uuid_chat_id_returns_400(
    client: AsyncClient,
    db_user: User,
) -> None:
    token = _bearer_for(db_user)

    response = await client.post(
        "/api/v1/chats/not-a-uuid/messages",
        json={"content": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["detail"]["code"] == "validation_error"


@pytest.mark.integration
async def test_send_message_with_empty_content_returns_400(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
) -> None:
    token = _bearer_for(db_user)

    response = await client.post(
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": ""},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400


@pytest.mark.integration
async def test_send_message_missing_content_field_returns_400(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
) -> None:
    token = _bearer_for(db_user)

    response = await client.post(
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"model": "smart"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400


@pytest.mark.integration
async def test_send_message_with_non_json_body_returns_400(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
) -> None:
    token = _bearer_for(db_user)

    response = await client.post(
        f"/api/v1/chats/{db_chat.id}/messages",
        content=b"not json",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 400


@pytest.mark.integration
async def test_send_message_for_nonexistent_chat_returns_404(
    client: AsyncClient,
    db_user: User,
) -> None:
    """C3: cross-user / nonexistent chat returns 404."""

    token = _bearer_for(db_user)
    other_chat_id = str(uuid.uuid4())

    response = await client.post(
        f"/api/v1/chats/{other_chat_id}/messages",
        json={"content": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# Happy path (non-streaming)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_send_message_non_streaming_happy_path(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
) -> None:
    """Backend → gateway → response with tier surfaced in body and header."""

    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json=_success_payload(tier=3, content="from anthropic"),
            headers={"X-LQ-AI-Routed-Inference-Tier": "3"},
        )
    )
    token = _bearer_for(db_user)

    response = await client.post(
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "hello", "model": "smart"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    assert route.called

    # The gateway saw the X-LQ-AI-Gateway-Key header.
    sent = route.calls[0].request
    assert sent.headers.get("X-LQ-AI-Gateway-Key") == GATEWAY_KEY

    body = response.json()
    assert body["routed_inference_tier"] == 3
    assert body["routed_provider"] == "anthropic-prod"
    assert body["cost_estimate"] == 0.00025
    msg = body["message"]
    assert msg["role"] == "assistant"
    assert msg["content"] == "from anthropic"
    assert msg["routed_inference_tier"] == 3
    # Header surfaces the tier too.
    assert response.headers.get("X-LQ-AI-Routed-Inference-Tier") == "3"
    assert response.headers.get("X-LQ-AI-Routed-Provider") == "anthropic-prod"


@pytest.mark.integration
@respx.mock
async def test_send_message_translates_request_to_single_user_message(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
) -> None:
    """The request's content becomes a single 'user' message; chat_id is forwarded."""
    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )
    token = _bearer_for(db_user)

    await client.post(
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "what is contract law", "model": "fast"},
        headers={"Authorization": f"Bearer {token}"},
    )

    sent_body = _json.loads(route.calls[0].request.read())
    assert sent_body["model"] == "fast"
    assert sent_body["messages"] == [
        {"role": "user", "content": "what is contract law", "lq_ai_skip_anonymization": False}
    ]
    assert sent_body["chat_id"] == str(db_chat.id)
    # C3 — the new envelope fields are populated.
    assert sent_body["lq_ai_chat_id"] == str(db_chat.id)
    # The assistant message id is generated server-side; it must be a
    # well-formed UUID we don't know in advance.
    uuid.UUID(sent_body["lq_ai_message_id"])
    # stream defaults to False.
    assert sent_body["stream"] is False


# ---------------------------------------------------------------------------
# Error translation (non-streaming)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_send_message_gateway_5xx_returns_503_gateway_unreachable(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
) -> None:
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(500, content=b"internal error")
    )
    token = _bearer_for(db_user)

    response = await client.post(
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["detail"]["code"] == "gateway_unreachable"
    # The user-facing message must NOT leak the upstream 500 detail.
    assert "internal error" not in body["detail"]["message"].lower()


@pytest.mark.integration
@respx.mock
async def test_send_message_gateway_401_returns_503_with_no_leak(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
) -> None:
    """The user must not see 'wrong gateway key' — operator misconfig."""

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": {"code": "unauthorized", "message": "x"}})
    )
    token = _bearer_for(db_user)

    response = await client.post(
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["detail"]["code"] == "gateway_unreachable"
    # No reference to keys, auth, etc.
    assert "key" not in body["detail"]["message"].lower()


@pytest.mark.integration
async def test_send_message_gateway_timeout_returns_504(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
) -> None:
    token = _bearer_for(db_user)

    with respx.mock(base_url=GATEWAY_BASE) as router:
        router.post("/v1/chat/completions").mock(side_effect=httpx.ReadTimeout("x"))

        response = await client.post(
            f"/api/v1/chats/{db_chat.id}/messages",
            json={"content": "hello"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 504
    body = response.json()
    assert body["detail"]["code"] == "gateway_timeout"


@pytest.mark.integration
@respx.mock
async def test_send_message_provider_unavailable_returns_502(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
) -> None:
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            502,
            json={
                "error": {
                    "code": "provider_unavailable",
                    "message": "upstream down",
                    "details": {"upstream_status": 503},
                }
            },
        )
    )
    token = _bearer_for(db_user)

    response = await client.post(
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 502
    body = response.json()
    assert body["detail"]["code"] == "provider_unavailable"
    assert body["detail"]["details"]["gateway_code"] == "provider_unavailable"


@pytest.mark.integration
@respx.mock
async def test_send_message_invalid_model_returns_400(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
) -> None:
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            400, json={"error": {"code": "invalid_model", "message": "no such alias"}}
        )
    )
    token = _bearer_for(db_user)

    response = await client.post(
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "hello", "model": "made-up"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["detail"]["code"] == "invalid_model"


@pytest.mark.integration
@respx.mock
async def test_send_message_gateway_invalid_response_body_returns_502(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
) -> None:
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )
    token = _bearer_for(db_user)

    response = await client.post(
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 502
    body = response.json()
    assert body["detail"]["code"] == "gateway_invalid_response"


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


def _stream_chunk(content: str, *, tier: int = 3) -> str:
    """Build one SSE-encoded chat-completion chunk frame."""

    chunk = {
        "id": "chatcmpl-stream",
        "object": "chat.completion.chunk",
        "created": 1_700_000_000,
        "model": "claude-sonnet-4-6",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": content},
                "finish_reason": None,
            }
        ],
        "routed_inference_tier": tier,
        "routed_provider": "anthropic-prod",
    }
    return f"data: {_json.dumps(chunk)}\n\n"


@pytest.mark.integration
@respx.mock
async def test_send_message_streaming_happy_path(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
) -> None:
    body = _stream_chunk("hi ") + _stream_chunk("there") + "data: [DONE]\n\n"
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )
    )
    token = _bearer_for(db_user)

    async with client.stream(
        "POST",
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "hi", "stream": True},
        headers={"Authorization": f"Bearer {token}"},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")
        events: list[dict[str, object]] = []
        async for line in resp.aiter_lines():
            line = line.strip()
            if not line:
                continue
            if line == "data: [DONE]":
                break
            assert line.startswith("data:")
            events.append(_json.loads(line[len("data:") :].strip()))

    delta_events = [e for e in events if e["type"] == "delta"]
    complete_events = [e for e in events if e["type"] == "complete"]
    assert "".join(e["delta"] for e in delta_events) == "hi there"
    assert len(complete_events) == 1
    final = complete_events[0]
    assert final["message"]["routed_inference_tier"] == 3
    assert final["message"]["content"] == "hi there"


@pytest.mark.integration
@respx.mock
async def test_send_message_streaming_mid_stream_error_emits_error_frame(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
) -> None:
    body = (
        _stream_chunk("partial ")
        + 'data: {"error": {"code": "provider_unavailable", "message": "down"}}\n\n'
        + "data: [DONE]\n\n"
    )
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )
    )
    token = _bearer_for(db_user)

    async with client.stream(
        "POST",
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "hi", "stream": True},
        headers={"Authorization": f"Bearer {token}"},
    ) as resp:
        assert resp.status_code == 200
        events: list[dict[str, object]] = []
        async for line in resp.aiter_lines():
            line = line.strip()
            if not line:
                continue
            if line == "data: [DONE]":
                break
            events.append(_json.loads(line[len("data:") :].strip()))

    # Find the partial-delta event and the error envelope.
    delta_events = [e for e in events if e.get("type") == "delta"]
    assert len(delta_events) == 1
    assert delta_events[0]["delta"] == "partial "
    error_events = [e for e in events if "detail" in e]
    assert len(error_events) == 1
    assert error_events[0]["detail"]["code"] == "provider_unavailable"


@pytest.mark.integration
@respx.mock
async def test_send_message_streaming_pre_frame_error_emits_error_frame(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
) -> None:
    """Status-code error before any data frame: SSE response with an error frame.

    Once the StreamingResponse has been returned to FastAPI we can no
    longer change the HTTP status — the response headers have been
    sent. The pre-frame error therefore comes through as a single SSE
    frame carrying the canonical Error envelope, terminated by [DONE].
    The HTTP status stays 200 (SSE convention: errors are in-band).
    """
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(400, json={"error": {"code": "invalid_model", "message": "no"}})
    )
    token = _bearer_for(db_user)

    async with client.stream(
        "POST",
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "hi", "stream": True},
        headers={"Authorization": f"Bearer {token}"},
    ) as resp:
        # SSE response has 200 status; error is in-band.
        assert resp.status_code == 200
        events: list[dict[str, object]] = []
        async for line in resp.aiter_lines():
            line = line.strip()
            if not line:
                continue
            if line == "data: [DONE]":
                break
            events.append(_json.loads(line[len("data:") :].strip()))

    error_events = [e for e in events if "detail" in e]
    assert len(error_events) == 1
    assert error_events[0]["detail"]["code"] == "invalid_model"


# ---------------------------------------------------------------------------
# Backend does NOT double-write inference_routing_log
# ---------------------------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_send_message_does_not_write_inference_routing_log_on_backend(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
    db_session: AsyncSession,
) -> None:
    """Per B4: the gateway is the canonical writer of inference_routing_log.

    The backend must not double-write. This test ensures the
    inference_routing_log table is not touched during a chat call (the
    test fixture's transaction would otherwise capture the row).
    """

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )
    token = _bearer_for(db_user)

    # Snapshot row count before.
    rows_before = await db_session.execute(text("SELECT count(*) FROM inference_routing_log"))
    count_before = rows_before.scalar_one()

    response = await client.post(
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    rows_after = await db_session.execute(text("SELECT count(*) FROM inference_routing_log"))
    count_after = rows_after.scalar_one()
    assert count_after == count_before, (
        "C3 must not write to inference_routing_log — the gateway does (B4)."
    )


# Ensure the count_before query has access to the table — if not, the test
# DB doesn't have inference_routing_log and the test should be skipped.
@pytest.fixture(autouse=True)
async def _ensure_inference_routing_log_table_exists(db_session: AsyncSession) -> None:
    try:
        await db_session.execute(text("SELECT 1 FROM inference_routing_log LIMIT 1"))
    except Exception:
        pytest.skip("inference_routing_log table not present in test DB")


# ---------------------------------------------------------------------------
# requested_model persistence (ADR 0011 follow-on)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_send_message_persists_requested_model_non_streaming(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
    db_session: AsyncSession,
) -> None:
    """The alias the user picked is stored alongside the routed pair.

    ADR 0011 makes alias resolution visible: ``routed_model`` records
    what actually ran, ``requested_model`` records what the user asked
    for. When an alias is used, the two differ; the TierDetailsPanel
    needs both to render "Requested: smart → routed to claude-sonnet-4-6".
    """

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload(content="ok"))
    )
    token = _bearer_for(db_user)

    response = await client.post(
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "hello", "model": "smart"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    msg = body["message"]
    assert msg["requested_model"] == "smart"
    assert msg["routed_model"] == "claude-sonnet-4-6"

    rows = await db_session.execute(
        select(Message)
        .where(Message.chat_id == db_chat.id, Message.role == "assistant")
        .order_by(Message.created_at)
    )
    assistant_rows = list(rows.scalars().all())
    assert len(assistant_rows) == 1
    assert assistant_rows[0].requested_model == "smart"
    assert assistant_rows[0].routed_model == "claude-sonnet-4-6"


@pytest.mark.integration
@respx.mock
async def test_send_message_persists_requested_model_streaming(
    client: AsyncClient,
    db_user: User,
    db_chat: Chat,
    db_session: AsyncSession,
) -> None:
    """Streaming path also persists ``requested_model`` (B5/C3 + ADR 0011).

    The streaming handler accumulates chunks and writes the assistant
    row at end-of-stream. The originally-requested alias must travel
    through the gateway request envelope onto that row, same as the
    non-streaming path.
    """

    body = _stream_chunk("hi ") + _stream_chunk("there") + "data: [DONE]\n\n"
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )
    )
    token = _bearer_for(db_user)

    async with client.stream(
        "POST",
        f"/api/v1/chats/{db_chat.id}/messages",
        json={"content": "hi", "stream": True, "model": "fast"},
        headers={"Authorization": f"Bearer {token}"},
    ) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.strip() == "data: [DONE]":
                break

    rows = await db_session.execute(
        select(Message)
        .where(Message.chat_id == db_chat.id, Message.role == "assistant")
        .order_by(Message.created_at)
    )
    assistant_rows = list(rows.scalars().all())
    assert len(assistant_rows) == 1
    assert assistant_rows[0].requested_model == "fast"
    assert assistant_rows[0].routed_model == "claude-sonnet-4-6"
