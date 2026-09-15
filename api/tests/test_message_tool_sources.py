from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import GatewayClient, set_gateway_client
from app.db.session import get_db
from app.main import app
from app.models import MessageToolSource
from app.models.chat import Chat, Message
from app.models.user import User
from app.security import create_access_token, hash_password

pytestmark = pytest.mark.integration

GATEWAY_BASE = "http://test-gateway"
GATEWAY_KEY = "test-gw-key"


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


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


@pytest_asyncio.fixture
async def owner_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"src-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Sources Test Owner",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _assistant_message(db_session: AsyncSession, owner: User) -> tuple[Chat, Message]:
    chat = Chat(owner_id=owner.id, project_id=None, title="src-chat")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="answer")
    db_session.add(msg)
    await db_session.flush()
    return chat, msg


@pytest.mark.asyncio
async def test_persist_message_tool_sources_writes_rows(db_session: AsyncSession, owner_user: User):
    from app.api.chats import _persist_message_tool_sources
    from app.chat.tool_loop import ToolSourceRecord

    _chat, msg = await _assistant_message(db_session, owner_user)
    recs = [
        ToolSourceRecord(
            "caselaw",
            "Roe v. Wade",
            "scotus · 1973-01-22",
            "https://www.courtlistener.com/opinion/42/",
            "42",
            "courtlistener",
            "search_case_law",
        ),
    ]
    await _persist_message_tool_sources(db_session, message_id=msg.id, records=recs)
    rows = (
        (
            await db_session.execute(
                select(MessageToolSource).where(MessageToolSource.message_id == msg.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].label == "Roe v. Wade"

    # No-op on empty.
    _chat2, msg2 = await _assistant_message(db_session, owner_user)
    await _persist_message_tool_sources(db_session, message_id=msg2.id, records=[])
    rows2 = (
        (
            await db_session.execute(
                select(MessageToolSource).where(MessageToolSource.message_id == msg2.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows2 == []


@pytest.mark.asyncio
async def test_message_tool_source_roundtrips(db_session: AsyncSession, owner_user: User):
    _chat, msg = await _assistant_message(db_session, owner_user)
    row = MessageToolSource(
        message_id=msg.id,
        source_kind="caselaw",
        label="Roe v. Wade",
        subtitle="scotus · 1973-01-22",
        url="https://www.courtlistener.com/opinion/42/",
        external_ref="42",
        provider="courtlistener",
        tool="search_case_law",
    )
    db_session.add(row)
    await db_session.flush()
    got = (
        await db_session.execute(
            select(MessageToolSource).where(MessageToolSource.message_id == msg.id)
        )
    ).scalar_one()
    assert got.label == "Roe v. Wade"
    assert got.source_kind == "caselaw"
    assert got.external_ref == "42"
    assert got.created_at is not None


@pytest.mark.asyncio
async def test_get_sources_endpoint(
    client: AsyncClient, db_session: AsyncSession, owner_user: User
):
    chat, msg = await _assistant_message(db_session, owner_user)
    db_session.add(
        MessageToolSource(
            message_id=msg.id,
            source_kind="caselaw",
            label="Roe v. Wade",
            subtitle="scotus · 1973-01-22",
            url="https://www.courtlistener.com/opinion/42/",
            external_ref="42",
            provider="courtlistener",
            tool="search_case_law",
        )
    )
    await db_session.flush()

    token = create_access_token(user_id=owner_user.id, email=owner_user.email, is_admin=False)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get(f"/api/v1/chats/{chat.id}/messages/{msg.id}/sources", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["label"] == "Roe v. Wade"
    assert body[0]["url"] == "https://www.courtlistener.com/opinion/42/"
    assert body[0]["source_kind"] == "caselaw"

    # Unknown message → 404.
    resp404 = await client.get(
        f"/api/v1/chats/{chat.id}/messages/{uuid.uuid4()}/sources", headers=headers
    )
    assert resp404.status_code == 404


@pytest.mark.asyncio
async def test_get_sources_auditor_can_read_cross_user_and_is_audited(
    client: AsyncClient, db_session: AsyncSession, owner_user: User
):
    chat, msg = await _assistant_message(db_session, owner_user)
    db_session.add(
        MessageToolSource(
            message_id=msg.id,
            source_kind="caselaw",
            label="Roe v. Wade",
            subtitle="scotus · 1973-01-22",
            url="https://www.courtlistener.com/opinion/42/",
            external_ref="42",
            provider="courtlistener",
            tool="search_case_law",
        )
    )
    await db_session.flush()

    auditor = User(
        email=f"aud-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        role="auditor",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(auditor)
    await db_session.flush()
    token = create_access_token(user_id=auditor.id, email=auditor.email, is_admin=False)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get(f"/api/v1/chats/{chat.id}/messages/{msg.id}/sources", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    from app.models.audit import AuditLog

    row = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "auditor.sources_viewed")
            )
        )
        .scalars()
        .one()
    )
    assert row.user_id == auditor.id
    assert row.details["viewed_user_id"] == str(owner_user.id)


@pytest.mark.asyncio
async def test_get_sources_member_cross_user_still_404_and_not_audited(
    client: AsyncClient, db_session: AsyncSession, owner_user: User
):
    chat, msg = await _assistant_message(db_session, owner_user)
    db_session.add(
        MessageToolSource(
            message_id=msg.id,
            source_kind="caselaw",
            label="Roe v. Wade",
            subtitle="scotus · 1973-01-22",
            url="https://www.courtlistener.com/opinion/42/",
            external_ref="42",
            provider="courtlistener",
            tool="search_case_law",
        )
    )
    await db_session.flush()

    other = User(
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(other)
    await db_session.flush()
    token = create_access_token(user_id=other.id, email=other.email, is_admin=False)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get(f"/api/v1/chats/{chat.id}/messages/{msg.id}/sources", headers=headers)
    assert resp.status_code == 404

    from sqlalchemy import func

    from app.models.audit import AuditLog

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "auditor.sources_viewed")
        )
    ).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_get_sources_owner_read_not_audited(
    client: AsyncClient, db_session: AsyncSession, owner_user: User
):
    chat, msg = await _assistant_message(db_session, owner_user)
    db_session.add(
        MessageToolSource(
            message_id=msg.id,
            source_kind="caselaw",
            label="Roe v. Wade",
            subtitle="scotus · 1973-01-22",
            url="https://www.courtlistener.com/opinion/42/",
            external_ref="42",
            provider="courtlistener",
            tool="search_case_law",
        )
    )
    await db_session.flush()

    token = create_access_token(user_id=owner_user.id, email=owner_user.email, is_admin=False)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get(f"/api/v1/chats/{chat.id}/messages/{msg.id}/sources", headers=headers)
    assert resp.status_code == 200

    from sqlalchemy import func

    from app.models.audit import AuditLog

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "auditor.sources_viewed")
        )
    ).scalar_one()
    assert count == 0
