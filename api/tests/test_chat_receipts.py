"""GET /api/v1/chats/{chat_id}/receipts — replay-at-read event log.

Wave D.1 T5. Verifies the receipts endpoint merges chronological
events from four source tables (messages + applied_skills denorm +
inference_routing_log + audit_log) into one timestamp-ordered
stream, applies the comma-separated ``?event_kinds=...`` filter, and
gates on owner-or-admin.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.chat import Chat, Message
from app.models.inference import InferenceRoutingLog
from app.models.user import User
from app.security import create_access_token, hash_password

pytestmark = pytest.mark.integration


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """In-process AsyncClient bound to the test db_session."""
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def owner_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"owner-receipts-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Receipts Owner",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"other-receipts-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Receipts Stranger",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"admin-receipts-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Receipts Admin",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=True,
        role="admin",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _bearer(user: User) -> str:
    return create_access_token(user.id, user.email, is_admin=user.is_admin)


def _h(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {_bearer(user)}"}


@pytest_asyncio.fixture
async def populated_chat(db_session: AsyncSession, owner_user: User) -> Chat:
    """A chat with 1 user msg + 1 ai msg + 1 inference log + 1 audit row.

    Explicit timestamps keep the chronological ordering deterministic.
    """
    chat = Chat(owner_id=owner_user.id, title="receipts test")
    db_session.add(chat)
    await db_session.flush()

    base = datetime.now(tz=UTC)
    user_msg = Message(
        chat_id=chat.id,
        role="user",
        kind="user",
        content="Hello",
        applied_skills=[],
        created_at=base,
    )
    ai_msg = Message(
        chat_id=chat.id,
        role="assistant",
        kind="ai",
        content="Hi there",
        applied_skills=["nda-review"],
        created_at=base + timedelta(seconds=1),
    )
    db_session.add_all([user_msg, ai_msg])
    await db_session.flush()

    inference = InferenceRoutingLog(
        chat_id=chat.id,
        message_id=ai_msg.id,
        routed_provider="anthropic",
        routed_model="claude-opus-4-7",
        routed_inference_tier=2,
        refused=False,
        timestamp=base + timedelta(seconds=1),
    )
    audit = AuditLog(
        user_id=owner_user.id,
        action="chat.created",
        resource_type="chat",
        resource_id=str(chat.id),
        details={"chat_id": str(chat.id)},
        timestamp=base + timedelta(seconds=2),
    )
    db_session.add_all([inference, audit])
    await db_session.flush()
    return chat


async def test_receipts_merges_all_sources(
    client: AsyncClient, owner_user: User, populated_chat: Chat
) -> None:
    response = await client.get(
        f"/api/v1/chats/{populated_chat.id}/receipts",
        headers=_h(owner_user),
    )
    assert response.status_code == 200, response.text
    events = response.json()
    kinds = {e["kind"] for e in events}
    assert "message" in kinds
    assert "inference" in kinds
    assert "audit" in kinds
    assert "skill" in kinds


async def test_receipts_chronological_ascending(
    client: AsyncClient, owner_user: User, populated_chat: Chat
) -> None:
    response = await client.get(
        f"/api/v1/chats/{populated_chat.id}/receipts",
        headers=_h(owner_user),
    )
    assert response.status_code == 200, response.text
    events = response.json()
    timestamps = [e["ts"] for e in events]
    assert timestamps == sorted(timestamps)


async def test_receipts_filters_by_event_kinds(
    client: AsyncClient, owner_user: User, populated_chat: Chat
) -> None:
    response = await client.get(
        f"/api/v1/chats/{populated_chat.id}/receipts?event_kinds=message,audit",
        headers=_h(owner_user),
    )
    assert response.status_code == 200, response.text
    events = response.json()
    kinds = {e["kind"] for e in events}
    assert kinds <= {"message", "audit"}


async def test_receipts_skill_event_from_applied_skills(
    client: AsyncClient, owner_user: User, populated_chat: Chat
) -> None:
    response = await client.get(
        f"/api/v1/chats/{populated_chat.id}/receipts",
        headers=_h(owner_user),
    )
    assert response.status_code == 200, response.text
    events = response.json()
    skill_events = [e for e in events if e["kind"] == "skill"]
    assert len(skill_events) >= 1
    assert skill_events[0]["detail"]["skill_name"] == "nda-review"


async def test_receipts_non_owner_returns_403_or_404(
    client: AsyncClient, other_user: User, populated_chat: Chat
) -> None:
    response = await client.get(
        f"/api/v1/chats/{populated_chat.id}/receipts",
        headers=_h(other_user),
    )
    assert response.status_code in (403, 404)


async def test_receipts_admin_can_view_any_chat(
    client: AsyncClient, admin_user: User, populated_chat: Chat
) -> None:
    response = await client.get(
        f"/api/v1/chats/{populated_chat.id}/receipts",
        headers=_h(admin_user),
    )
    assert response.status_code == 200, response.text


async def test_receipts_inference_refused_renders_as_error(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
) -> None:
    chat = Chat(owner_id=owner_user.id, title="refused chat")
    db_session.add(chat)
    await db_session.flush()
    log = InferenceRoutingLog(
        chat_id=chat.id,
        routed_provider="anthropic",
        routed_model="claude-opus-4-7",
        routed_inference_tier=2,
        refused=True,
        refusal_reason="tier_mismatch",
        timestamp=datetime.now(tz=UTC),
    )
    db_session.add(log)
    await db_session.flush()
    response = await client.get(
        f"/api/v1/chats/{chat.id}/receipts",
        headers=_h(owner_user),
    )
    assert response.status_code == 200, response.text
    events = response.json()
    error_events = [e for e in events if e["kind"] == "error"]
    assert len(error_events) >= 1
    assert error_events[0]["detail"]["refused"] is True


async def test_receipts_inference_detail_includes_anonymization_and_message_id(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
) -> None:
    """The inference event's detail surfaces ``anonymization_applied`` (the UI
    indicator's source of truth) and the assistant ``message_id`` (so the
    frontend can pin the indicator to the right message bubble)."""
    chat = Chat(owner_id=owner_user.id, title="anon chat")
    db_session.add(chat)
    await db_session.flush()
    ai_msg = Message(
        chat_id=chat.id,
        role="assistant",
        kind="ai",
        content="Hi there",
        applied_skills=[],
        created_at=datetime.now(tz=UTC),
    )
    db_session.add(ai_msg)
    await db_session.flush()
    log = InferenceRoutingLog(
        chat_id=chat.id,
        message_id=ai_msg.id,
        routed_provider="anthropic",
        routed_model="claude-opus-4-7",
        routed_inference_tier=2,
        refused=False,
        anonymization_applied=True,
        timestamp=datetime.now(tz=UTC),
    )
    db_session.add(log)
    await db_session.flush()

    response = await client.get(
        f"/api/v1/chats/{chat.id}/receipts",
        headers=_h(owner_user),
    )
    assert response.status_code == 200, response.text
    events = response.json()
    inference_events = [e for e in events if e["kind"] == "inference"]
    assert len(inference_events) == 1
    detail = inference_events[0]["detail"]
    # anonymization_applied is a real bool (not a string/None) — the indicator
    # reads it directly.
    assert detail["anonymization_applied"] is True
    # message_id pins the indicator to the assistant message bubble.
    assert detail["message_id"] == str(ai_msg.id)


# ----------------------------------------------------------------
# Wave D.1 T6 — JSONL export sibling route
# ----------------------------------------------------------------


async def test_receipts_export_jsonl(
    client: AsyncClient, owner_user: User, populated_chat: Chat
) -> None:
    """JSONL export returns one event per line with correct headers."""
    response = await client.get(
        f"/api/v1/chats/{populated_chat.id}/receipts/export.jsonl",
        headers=_h(owner_user),
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/jsonl")
    assert "attachment" in response.headers["content-disposition"]
    assert f"chat-{populated_chat.id}-receipts.jsonl" in response.headers["content-disposition"]

    import json

    lines = [line for line in response.text.splitlines() if line.strip()]
    assert len(lines) > 0
    for raw in lines:
        parsed = json.loads(raw)
        assert "ts" in parsed
        assert "kind" in parsed
        assert "detail" in parsed


async def test_receipts_export_jsonl_filter_event_kinds(
    client: AsyncClient, owner_user: User, populated_chat: Chat
) -> None:
    """Filter param works on the JSONL export too."""
    response = await client.get(
        f"/api/v1/chats/{populated_chat.id}/receipts/export.jsonl?event_kinds=message",
        headers=_h(owner_user),
    )
    assert response.status_code == 200, response.text
    import json

    lines = [line for line in response.text.splitlines() if line.strip()]
    for raw in lines:
        parsed = json.loads(raw)
        assert parsed["kind"] == "message"


async def test_receipts_export_jsonl_non_owner_returns_403_or_404(
    client: AsyncClient, other_user: User, populated_chat: Chat
) -> None:
    response = await client.get(
        f"/api/v1/chats/{populated_chat.id}/receipts/export.jsonl",
        headers=_h(other_user),
    )
    assert response.status_code in (403, 404)
