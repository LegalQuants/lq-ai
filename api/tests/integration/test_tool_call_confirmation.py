"""Integration tests for the PR5b-ii confirmation-gate endpoint.

``POST /api/v1/chats/{chat_id}/tool-calls/{pending_call_id}`` — the approve/deny
resolve path. Exercises the real DB (migration 0054 / ``pending_tool_call``),
owner-checking, single-use + TTL semantics, and the deny-resume stream.
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

from app.chat.pending import create_pending_tool_call
from app.clients.gateway import GatewayClient, set_gateway_client
from app.db.session import get_db
from app.main import app
from app.models.chat import Chat
from app.models.pending_tool_call import PendingToolCall
from app.models.user import User
from app.schemas.gateway import ChatCompletionMessage, ChatCompletionRequest
from app.security import create_access_token, hash_password
from app.security.encryption import MCP_MASTER_KEY_ENV, generate_master_key

GATEWAY_BASE = "http://test-gateway"
GATEWAY_KEY = "test-gw-key"


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest.fixture(autouse=True)
def _mcp_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # The gate encrypts the resume payload; the encryptor needs the MCP key.
    monkeypatch.setenv(MCP_MASTER_KEY_ENV, generate_master_key())


@pytest_asyncio.fixture
async def db_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"gate-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Gate Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Other User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def chat(db_session: AsyncSession, db_user: User) -> Chat:
    row = Chat(owner_id=db_user.id, title="Gate test chat")
    db_session.add(row)
    await db_session.flush()
    return row


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    gw = GatewayClient(base_url=GATEWAY_BASE, gateway_key=GATEWAY_KEY)
    set_gateway_client(gw)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    set_gateway_client(None)
    await gw.aclose()
    app.dependency_overrides.pop(get_db, None)


def _bearer(user: User) -> str:
    return create_access_token(user.id, user.email, is_admin=user.is_admin)


async def _make_pending(db_session: AsyncSession, *, user: User, chat: Chat) -> str:
    resume_request = ChatCompletionRequest(
        model="claude-haiku-4-5",
        messages=[
            ChatCompletionMessage(role="user", content="make a doc"),
            ChatCompletionMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "create_doc", "arguments": "{}"},
                    }
                ],
            ),
        ],
    )
    return await create_pending_tool_call(
        db_session,
        user_id=user.id,
        chat_id=chat.id,
        message_id=uuid.uuid4(),
        provider="office",
        tool="create_doc",
        destructive=True,
        args={"title": "X"},
        tool_call_id="call_1",
        resume_request=resume_request,
        max_allowed_tier=None,
    )


_FINAL = {
    "id": "chatcmpl-final",
    "object": "chat.completion",
    "created": 1_700_000_000,
    "model": "claude-haiku-4-5",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Understood — I won't create it."},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
    "routed_inference_tier": 3,
    "routed_provider": "anthropic-prod",
}


@pytest.mark.integration
async def test_unknown_pending_call_returns_410(
    client: AsyncClient, chat: Chat, db_user: User
) -> None:
    resp = await client.post(
        f"/api/v1/chats/{chat.id}/tool-calls/does-not-exist",
        json={"decision": "approve"},
        headers={"Authorization": f"Bearer {_bearer(db_user)}"},
    )
    assert resp.status_code == 410


@pytest.mark.integration
async def test_nonowner_returns_404(
    client: AsyncClient, db_session: AsyncSession, chat: Chat, db_user: User, other_user: User
) -> None:
    pending_id = await _make_pending(db_session, user=db_user, chat=chat)
    resp = await client.post(
        f"/api/v1/chats/{chat.id}/tool-calls/{pending_id}",
        json={"decision": "deny"},
        headers={"Authorization": f"Bearer {_bearer(other_user)}"},  # not the owner
    )
    assert resp.status_code == 404


@pytest.mark.integration
@respx.mock
async def test_deny_resumes_and_finalizes(
    client: AsyncClient, db_session: AsyncSession, chat: Chat, db_user: User
) -> None:
    # No MCP tool providers configured -> assemble_mcp_tools empty -> deny path
    # finalizes via a single gateway chat_completion.
    respx.get(f"{GATEWAY_BASE}/admin/v1/config").mock(
        return_value=httpx.Response(200, json={"tool_providers": []})
    )
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_FINAL)
    )
    pending_id = await _make_pending(db_session, user=db_user, chat=chat)

    resp = await client.post(
        f"/api/v1/chats/{chat.id}/tool-calls/{pending_id}",
        json={"decision": "deny"},
        headers={"Authorization": f"Bearer {_bearer(db_user)}"},
    )
    assert resp.status_code == 200
    body = resp.text
    assert '"type":"complete"' in body or '"type": "complete"' in body
    assert "won't create it" in body
    # single-use: the pending row is gone.
    gone = (
        await db_session.execute(
            select(PendingToolCall).where(PendingToolCall.pending_call_id == pending_id)
        )
    ).scalar_one_or_none()
    assert gone is None


@pytest.mark.integration
@respx.mock
async def test_replay_after_resolve_returns_410(
    client: AsyncClient, db_session: AsyncSession, chat: Chat, db_user: User
) -> None:
    respx.get(f"{GATEWAY_BASE}/admin/v1/config").mock(
        return_value=httpx.Response(200, json={"tool_providers": []})
    )
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_FINAL)
    )
    pending_id = await _make_pending(db_session, user=db_user, chat=chat)
    headers = {"Authorization": f"Bearer {_bearer(db_user)}"}
    path = f"/api/v1/chats/{chat.id}/tool-calls/{pending_id}"

    first = await client.post(path, json={"decision": "deny"}, headers=headers)
    assert first.status_code == 200
    replay = await client.post(path, json={"decision": "deny"}, headers=headers)
    assert replay.status_code == 410


@pytest.mark.integration
async def test_gate_does_not_write_placeholder_message(
    db_session: AsyncSession, chat: Chat, db_user: User
) -> None:
    """Regression: the gate must NOT persist a placeholder assistant message.

    It used to write a content="" assistant row at gate time; the resume path's
    re-gate / final-save then tried to INSERT the same message_id again ->
    ``UniqueViolationError messages_pkey`` (surfaced as a null pending_call_id
    + a 410 on the next approve). The resume path owns the single message write.
    """

    from app.api.chats import _persist_pending_tool_call
    from app.chat.tool_loop import ToolConfirmationRequired
    from app.models.chat import Message

    assistant_message_id = uuid.uuid4()
    request = ChatCompletionRequest(
        model="claude-haiku-4-5",
        messages=[ChatCompletionMessage(role="user", content="hi")],
    )
    exc = ToolConfirmationRequired(
        provider="deepwiki",
        tool="ask_question",
        args={"q": "x"},
        tool_call_id="call_1",
        destructive=False,
        messages_so_far=[ChatCompletionMessage(role="user", content="hi")],
    )

    info = await _persist_pending_tool_call(
        db_session,
        user=db_user,
        request=request,
        confirm_exc=exc,
        chat=chat,
        assistant_message_id=assistant_message_id,
    )

    assert info["pending_call_id"]  # a real handle, not None
    # No placeholder assistant message row — the resume path writes it once.
    msg = (
        await db_session.execute(select(Message).where(Message.id == assistant_message_id))
    ).scalar_one_or_none()
    assert msg is None
    # The pending row IS persisted.
    pending = (
        await db_session.execute(
            select(PendingToolCall).where(
                PendingToolCall.pending_call_id == info["pending_call_id"]
            )
        )
    ).scalar_one_or_none()
    assert pending is not None
