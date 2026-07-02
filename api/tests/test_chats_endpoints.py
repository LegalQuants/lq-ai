"""Integration tests for the chats CRUD + persistence flow (Task C3).

The B5/C2 tests in ``test_chats_send_message.py`` cover the gateway
plumbing (auth, error translation, streaming chunks). This module
covers the C3-specific surface: actual chat persistence, the auto-
rename, message listing with cursor pagination, per-user isolation,
the lq_ai_message_id correlation flow, and CASCADE delete behaviour
on the underlying tables.
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
    user = User(
        email=f"chats-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Chats Test User",
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
        display_name="Other Test User",
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


def _success_payload(*, content: str = "hi") -> dict[str, object]:
    return {
        "id": "chatcmpl-c3",
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
        "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        "routed_inference_tier": 3,
        "routed_provider": "anthropic-prod",
        "cost_estimate": 0.000123,
        "lq_ai_applied_skills": ["nda-review"],
    }


def _stream_chunk(content: str, *, tier: int = 3) -> str:
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
        "lq_ai_applied_skills": ["msa-review-saas"],
    }
    return f"data: {_json.dumps(chunk)}\n\n"


# ---------------------------------------------------------------------------
# CRUD round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_chat_201_with_default_title(
    client: AsyncClient,
    db_user: User,
) -> None:
    token = _bearer_for(db_user)

    response = await client.post(
        "/api/v1/chats",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "New chat"
    assert body["owner_id"] == str(db_user.id)
    assert body["project_id"] is None
    assert body["message_count"] == 0
    uuid.UUID(body["id"])  # well-formed


@pytest.mark.integration
async def test_create_chat_with_explicit_title_and_project_id(
    client: AsyncClient,
    db_user: User,
) -> None:
    token = _bearer_for(db_user)
    project_id = str(uuid.uuid4())  # FK is SET NULL — invalid id is fine here

    response = await client.post(
        "/api/v1/chats",
        json={"title": "Custom Title"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Custom Title"
    # project_id was not supplied so it stays null.
    assert body["project_id"] is None
    # Confirm we can omit project_id without 422.
    _ = project_id


@pytest.mark.integration
async def test_get_chat_returns_persisted_row(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    chat = Chat(owner_id=db_user.id, title="My Chat")
    db_session.add(chat)
    await db_session.flush()
    token = _bearer_for(db_user)

    response = await client.get(
        f"/api/v1/chats/{chat.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(chat.id)
    assert body["title"] == "My Chat"


@pytest.mark.integration
async def test_get_chat_cross_user_returns_404(
    client: AsyncClient,
    db_user: User,
    other_user: User,
    db_session: AsyncSession,
) -> None:
    """Per-user isolation: another user's chat is invisible (404)."""

    chat = Chat(owner_id=other_user.id, title="Their Chat")
    db_session.add(chat)
    await db_session.flush()
    token = _bearer_for(db_user)

    response = await client.get(
        f"/api/v1/chats/{chat.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["code"] == "not_found"


@pytest.mark.integration
async def test_patch_chat_title(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    chat = Chat(owner_id=db_user.id, title="Old")
    db_session.add(chat)
    await db_session.flush()
    token = _bearer_for(db_user)

    response = await client.patch(
        f"/api/v1/chats/{chat.id}",
        json={"title": "New"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "New"


@pytest.mark.integration
async def test_patch_chat_archive_unarchive(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    chat = Chat(owner_id=db_user.id, title="X")
    db_session.add(chat)
    await db_session.flush()
    token = _bearer_for(db_user)

    archived = await client.patch(
        f"/api/v1/chats/{chat.id}",
        json={"archived": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None

    unarchived = await client.patch(
        f"/api/v1/chats/{chat.id}",
        json={"archived": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert unarchived.status_code == 200
    assert unarchived.json()["archived_at"] is None


@pytest.mark.integration
async def test_delete_chat_soft_deletes(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    chat = Chat(owner_id=db_user.id, title="Y")
    db_session.add(chat)
    await db_session.flush()
    chat_id = chat.id
    token = _bearer_for(db_user)

    response = await client.delete(
        f"/api/v1/chats/{chat_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204

    # Idempotent: a second delete (chat is now archived) returns 404.
    response2 = await client.delete(
        f"/api/v1/chats/{chat_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response2.status_code == 404


@pytest.mark.integration
async def test_list_chats_default_excludes_archived(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    from datetime import UTC, datetime

    active = Chat(owner_id=db_user.id, title="Active")
    archived = Chat(owner_id=db_user.id, title="Archived", archived_at=datetime.now(tz=UTC))
    db_session.add_all([active, archived])
    await db_session.flush()
    token = _bearer_for(db_user)

    response = await client.get(
        "/api/v1/chats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    titles = {item["title"] for item in response.json()["items"]}
    assert "Active" in titles
    assert "Archived" not in titles


@pytest.mark.integration
async def test_list_chats_archived_true_returns_archived_only(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    from datetime import UTC, datetime

    active = Chat(owner_id=db_user.id, title="Active")
    archived = Chat(owner_id=db_user.id, title="Archived", archived_at=datetime.now(tz=UTC))
    db_session.add_all([active, archived])
    await db_session.flush()
    token = _bearer_for(db_user)

    response = await client.get(
        "/api/v1/chats?archived=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    titles = {item["title"] for item in response.json()["items"]}
    assert titles == {"Archived"}


@pytest.mark.integration
async def test_list_chats_pagination_with_cursor(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """Pagination: limit=2 returns 2 items + a next_cursor; the next
    page advances past those two."""

    for i in range(5):
        db_session.add(Chat(owner_id=db_user.id, title=f"Chat {i}"))
    await db_session.flush()
    token = _bearer_for(db_user)

    page1 = await client.get(
        "/api/v1/chats?limit=2",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert page1.status_code == 200
    body1 = page1.json()
    assert len(body1["items"]) == 2
    assert body1["next_cursor"] is not None

    page2 = await client.get(
        f"/api/v1/chats?limit=2&cursor={body1['next_cursor']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert page2.status_code == 200
    body2 = page2.json()
    assert len(body2["items"]) == 2

    # The two pages must be disjoint.
    page1_ids = {item["id"] for item in body1["items"]}
    page2_ids = {item["id"] for item in body2["items"]}
    assert page1_ids.isdisjoint(page2_ids)


@pytest.mark.integration
async def test_list_chats_cross_user_isolation(
    client: AsyncClient,
    db_user: User,
    other_user: User,
    db_session: AsyncSession,
) -> None:
    db_session.add(Chat(owner_id=db_user.id, title="Mine"))
    db_session.add(Chat(owner_id=other_user.id, title="Theirs"))
    await db_session.flush()
    token = _bearer_for(db_user)

    response = await client.get(
        "/api/v1/chats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    titles = {item["title"] for item in response.json()["items"]}
    assert titles == {"Mine"}


@pytest.mark.integration
async def test_list_chats_filter_by_project_id(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """Project-scoped listing: ``project_id=`` filters correctly."""

    # We need a real project row because the FK is constrained.
    from app.models.project import Project

    project = Project(
        owner_id=db_user.id, name="P1", slug=f"p1-{uuid.uuid4().hex[:6]}", privileged=False
    )
    db_session.add(project)
    await db_session.flush()
    in_project = Chat(owner_id=db_user.id, title="In", project_id=project.id)
    out_project = Chat(owner_id=db_user.id, title="Out")
    db_session.add_all([in_project, out_project])
    await db_session.flush()
    token = _bearer_for(db_user)

    response = await client.get(
        f"/api/v1/chats?project_id={project.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    titles = {item["title"] for item in response.json()["items"]}
    assert titles == {"In"}


@pytest.mark.integration
async def test_list_chats_malformed_cursor_returns_400(
    client: AsyncClient,
    db_user: User,
) -> None:
    token = _bearer_for(db_user)
    response = await client.get(
        "/api/v1/chats?cursor=not-a-real-cursor",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "validation_error"


# ---------------------------------------------------------------------------
# Auto-rename + message persistence
# ---------------------------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_post_message_persists_user_and_assistant_rows(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """C3: a single POST writes one user message and one assistant
    message row, and the chat is auto-renamed."""

    chat = Chat(owner_id=db_user.id, title="New chat")
    db_session.add(chat)
    await db_session.flush()
    token = _bearer_for(db_user)

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload(content="back"))
    )

    response = await client.post(
        f"/api/v1/chats/{chat.id}/messages",
        json={"content": "What does NDA Section 4.2 mean?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text

    # Verify two messages persisted.
    rows = await db_session.execute(
        select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at)
    )
    messages = list(rows.scalars().all())
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "What does NDA Section 4.2 mean?"
    assert messages[1].role == "assistant"
    assert messages[1].content == "back"
    assert messages[1].routed_inference_tier == 3
    assert messages[1].routed_provider == "anthropic-prod"
    # Cost was 0.000123 USD = 123 micros.
    assert messages[1].cost_estimate_micros == 123
    # Skills surfaced from the gateway.
    assert messages[1].applied_skills == ["nda-review"]

    # Auto-rename happened.
    await db_session.refresh(chat)
    assert chat.title == "What does NDA Section 4.2 mean?"


@pytest.mark.integration
@respx.mock
async def test_post_message_does_not_overwrite_user_set_title(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """C3: a chat with a non-default title is NOT auto-renamed."""

    chat = Chat(owner_id=db_user.id, title="Important Discussion")
    db_session.add(chat)
    await db_session.flush()
    token = _bearer_for(db_user)

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )

    response = await client.post(
        f"/api/v1/chats/{chat.id}/messages",
        json={"content": "first message"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    await db_session.refresh(chat)
    assert chat.title == "Important Discussion"


@pytest.mark.integration
@respx.mock
async def test_post_message_second_call_does_not_rename_again(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """C3: only the first POST renames; subsequent ones leave the title alone."""

    chat = Chat(owner_id=db_user.id, title="New chat")
    db_session.add(chat)
    await db_session.flush()
    token = _bearer_for(db_user)

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )

    await client.post(
        f"/api/v1/chats/{chat.id}/messages",
        json={"content": "First!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    await db_session.refresh(chat)
    assert chat.title == "First!"

    # Second message: title must NOT change.
    await client.post(
        f"/api/v1/chats/{chat.id}/messages",
        json={"content": "Second!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    await db_session.refresh(chat)
    assert chat.title == "First!"


# ---------------------------------------------------------------------------
# lq_ai_message_id correlation
# ---------------------------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_post_message_forwards_lq_ai_message_id_to_gateway(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """C3: the backend generates the assistant message id pre-dispatch
    and forwards it as ``lq_ai_message_id`` so the gateway's routing
    log can correlate."""

    chat = Chat(owner_id=db_user.id, title="x")
    db_session.add(chat)
    await db_session.flush()
    token = _bearer_for(db_user)

    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )

    response = await client.post(
        f"/api/v1/chats/{chat.id}/messages",
        json={"content": "hi"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    sent = _json.loads(route.calls[0].request.read())
    forwarded_id = sent["lq_ai_message_id"]
    forwarded_chat_id = sent["lq_ai_chat_id"]
    assert forwarded_chat_id == str(chat.id)
    parsed = uuid.UUID(forwarded_id)

    # The persisted assistant row's id matches the forwarded id.
    rows = await db_session.execute(
        select(Message).where(Message.chat_id == chat.id, Message.role == "assistant")
    )
    asst = rows.scalar_one()
    assert asst.id == parsed


# ---------------------------------------------------------------------------
# Streaming persistence
# ---------------------------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_streaming_persists_assistant_at_end_of_stream(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """C3: streaming writes the assistant row exactly once at end of stream."""

    chat = Chat(owner_id=db_user.id, title="New chat")
    db_session.add(chat)
    await db_session.flush()
    token = _bearer_for(db_user)

    body = _stream_chunk("hi ") + _stream_chunk("there") + "data: [DONE]\n\n"
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )
    )

    async with client.stream(
        "POST",
        f"/api/v1/chats/{chat.id}/messages",
        json={"content": "hi", "stream": True},
        headers={"Authorization": f"Bearer {token}"},
    ) as resp:
        assert resp.status_code == 200
        # Drain the stream.
        async for _ in resp.aiter_lines():
            pass

    # User + assistant rows persisted.
    rows = await db_session.execute(
        select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at)
    )
    messages = list(rows.scalars().all())
    assert len(messages) == 2
    assert messages[1].role == "assistant"
    assert messages[1].content == "hi there"
    assert messages[1].routed_inference_tier == 3
    assert messages[1].applied_skills == ["msa-review-saas"]
    assert messages[1].error_code is None


@pytest.mark.integration
@respx.mock
async def test_streaming_mid_stream_failure_persists_partial_row_with_error_code(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """C3 — the canonical streaming-failure test.

    A mid-stream error from the gateway must result in:

    1. The user message row persisted (already committed before dispatch).
    2. A partial assistant row persisted with whatever content the
       client already saw, and ``error_code`` populated.
    3. The HTTP response status remains 200 (SSE convention) and the
       stream emits an error envelope as a final SSE frame.
    """

    chat = Chat(owner_id=db_user.id, title="x")
    db_session.add(chat)
    await db_session.flush()
    token = _bearer_for(db_user)

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

    async with client.stream(
        "POST",
        f"/api/v1/chats/{chat.id}/messages",
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

    # Verify a partial assistant row landed with error_code populated.
    rows = await db_session.execute(
        select(Message).where(Message.chat_id == chat.id, Message.role == "assistant")
    )
    asst = rows.scalar_one()
    assert asst.content == "partial "  # the content received before the error
    assert asst.error_code == "provider_unavailable"

    # And the SSE error envelope is on the wire.
    error_events = [e for e in events if "detail" in e]
    assert len(error_events) == 1
    assert error_events[0]["detail"]["code"] == "provider_unavailable"


# ---------------------------------------------------------------------------
# Non-streaming gateway failure: no assistant row
# ---------------------------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_non_streaming_gateway_failure_persists_user_only(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """C3: when the gateway fails before producing any response, the
    user row is persisted (audit trail) but no assistant row is."""

    chat = Chat(owner_id=db_user.id, title="x")
    db_session.add(chat)
    await db_session.flush()
    token = _bearer_for(db_user)

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            502,
            json={"error": {"code": "provider_unavailable", "message": "down"}},
        )
    )

    response = await client.post(
        f"/api/v1/chats/{chat.id}/messages",
        json={"content": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 502

    rows = await db_session.execute(
        select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at)
    )
    messages = list(rows.scalars().all())
    assert len(messages) == 1
    assert messages[0].role == "user"


# ---------------------------------------------------------------------------
# List messages
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_messages_returns_persisted_rows_oldest_first(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    chat = Chat(owner_id=db_user.id, title="x")
    db_session.add(chat)
    await db_session.flush()

    # Stagger created_at so the handler's secondary sort (Message.id ASC,
    # a random UUID) doesn't drive the ordering. The handler sorts by
    # (created_at ASC, id ASC); without explicit timestamps three rows in
    # the same flush share now() and tie-break on UUID.
    from datetime import UTC, datetime, timedelta

    base = datetime.now(tz=UTC)
    db_session.add_all(
        [
            Message(chat_id=chat.id, role="user", content="first", created_at=base),
            Message(
                chat_id=chat.id,
                role="assistant",
                content="second",
                created_at=base + timedelta(seconds=1),
            ),
            Message(
                chat_id=chat.id,
                role="user",
                content="third",
                created_at=base + timedelta(seconds=2),
            ),
        ]
    )
    await db_session.flush()
    token = _bearer_for(db_user)

    response = await client.get(
        f"/api/v1/chats/{chat.id}/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    contents = [item["content"] for item in items]
    assert contents == ["first", "second", "third"]


# ---------------------------------------------------------------------------
# Skill attachment captured on user message
# ---------------------------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_skill_attachment_captured_on_user_message(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """C3 / ADR 0007: the request's ``skills`` list is captured on the
    persisted user message's ``applied_skills`` column."""

    chat = Chat(owner_id=db_user.id, title="x")
    db_session.add(chat)
    await db_session.flush()
    token = _bearer_for(db_user)

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )

    await client.post(
        f"/api/v1/chats/{chat.id}/messages",
        json={"content": "review", "skills": ["nda-review", "msa-review-saas"]},
        headers={"Authorization": f"Bearer {token}"},
    )

    rows = await db_session.execute(
        select(Message).where(Message.chat_id == chat.id, Message.role == "user")
    )
    user_msg = rows.scalar_one()
    assert user_msg.applied_skills == ["nda-review", "msa-review-saas"]


# ---------------------------------------------------------------------------
# Cascade delete
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_chat_cascade_delete_removes_messages(
    db_session: AsyncSession,
    db_user: User,
) -> None:
    """The migration's ``ON DELETE CASCADE`` on ``messages.chat_id``
    means a hard-delete on the chat row removes its messages."""

    chat = Chat(owner_id=db_user.id, title="x")
    db_session.add(chat)
    await db_session.flush()
    db_session.add_all(
        [
            Message(chat_id=chat.id, role="user", content="a"),
            Message(chat_id=chat.id, role="assistant", content="b"),
        ]
    )
    await db_session.flush()
    chat_id = chat.id

    # Hard-delete via raw SQL (the API does soft-delete; this test
    # documents the underlying constraint behavior).
    await db_session.execute(text("DELETE FROM chats WHERE id = :cid"), {"cid": chat_id})
    await db_session.flush()

    rows = await db_session.execute(
        text("SELECT count(*) FROM messages WHERE chat_id = :cid"), {"cid": chat_id}
    )
    assert rows.scalar_one() == 0


# ---------------------------------------------------------------------------
# Hidden session-owned chats (WS-D PR2)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def owner_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"owner-chats-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Owner Chats User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.mark.integration
async def test_session_owned_chat_excluded_from_list(
    db_session: AsyncSession, client: AsyncClient, owner_user: User
) -> None:
    from app.models.autonomous import AutonomousSession
    from app.models.chat import Chat

    sess = AutonomousSession(user_id=owner_user.id, trigger_kind="manual", params={})
    db_session.add(sess)
    await db_session.flush()
    visible = Chat(owner_id=owner_user.id, title="Visible")
    hidden = Chat(owner_id=owner_user.id, title="Session", autonomous_session_id=sess.id)
    db_session.add_all([visible, hidden])
    await db_session.commit()

    resp = await client.get(
        "/api/v1/chats", headers={"Authorization": f"Bearer {_bearer_for(owner_user)}"}
    )
    assert resp.status_code == 200
    titles = {c["title"] for c in resp.json()["items"]}
    assert "Visible" in titles
    assert "Session" not in titles  # session-owned chat is hidden from the list
