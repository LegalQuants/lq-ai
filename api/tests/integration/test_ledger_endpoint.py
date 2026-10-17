"""GET /api/v1/chats/{chat_id}/ledger — one-click trace read surface (P1-A3)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.gate import compute_and_record_gate
from app.citation.ledger import assemble_ledger_entries
from app.db.session import get_db
from app.main import app
from app.models.chat import Chat, Message, MessageCitation
from app.models.file import File as FileModel
from app.models.user import User
from app.security import create_access_token, hash_password

pytestmark = pytest.mark.integration


def _override_get_db(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _dep() -> AsyncIterator[AsyncSession]:
        yield session

    return _dep


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> tuple[User, Chat, Message]:
    user = User(
        email=f"led-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        role="member",
    )
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="ledger")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="a")
    db_session.add(msg)
    await db_session.flush()
    f = FileModel(
        owner_id=user.id,
        filename="d.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        hash_sha256="0" * 64,
        storage_path=f"k/{uuid.uuid4().hex}",
    )
    db_session.add(f)
    await db_session.flush()
    db_session.add(
        MessageCitation(
            message_id=msg.id,
            source_file_id=f.id,
            source_offset_start=0,
            source_offset_end=5,
            source_text="hello",
            verified=True,
            verification_method="exact_match",
            verification_confidence=1.0,
        )
    )
    await db_session.flush()
    await assemble_ledger_entries(db_session, message_id=msg.id)
    await db_session.flush()
    return user, chat, msg


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


def _auth(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_ledger_returns_resolved_entries(
    client: AsyncClient, seeded: tuple[User, Chat, Message]
) -> None:
    user, chat, _msg = seeded
    r = await client.get(f"/api/v1/chats/{chat.id}/ledger", headers=_auth(user))
    assert r.status_code == 200
    body = r.json()
    assert body["chat_id"] == str(chat.id)
    assert len(body["entries"]) == 1
    e = body["entries"][0]
    assert e["source"]["kind"] == "kb_document"
    assert e["source"]["passages"][0]["text"] == "hello"
    assert e["verification_status"] == "exact_match"


@pytest.mark.asyncio
async def test_ledger_message_id_filter(
    client: AsyncClient, seeded: tuple[User, Chat, Message]
) -> None:
    user, chat, msg = seeded
    r = await client.get(f"/api/v1/chats/{chat.id}/ledger?message_id={msg.id}", headers=_auth(user))
    assert r.status_code == 200
    assert len(r.json()["entries"]) == 1
    r2 = await client.get(
        f"/api/v1/chats/{chat.id}/ledger?message_id={uuid.uuid4()}", headers=_auth(user)
    )
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_ledger_cross_user_404(
    client: AsyncClient, db_session: AsyncSession, seeded: tuple[User, Chat, Message]
) -> None:
    _, chat, _ = seeded
    other = User(
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        role="member",
    )
    db_session.add(other)
    await db_session.flush()
    r = await client.get(f"/api/v1/chats/{chat.id}/ledger", headers=_auth(other))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_ledger_auditor_can_read_cross_user_and_is_audited(
    client: AsyncClient, db_session: AsyncSession, seeded: tuple[User, Chat, Message]
) -> None:
    owner, chat, _msg = seeded
    auditor = User(
        email=f"aud-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        role="auditor",
    )
    db_session.add(auditor)
    await db_session.flush()

    r = await client.get(f"/api/v1/chats/{chat.id}/ledger", headers=_auth(auditor))
    assert r.status_code == 200
    assert "entries" in r.json()

    from sqlalchemy import select as _select

    from app.models.audit import AuditLog

    row = (
        (
            await db_session.execute(
                _select(AuditLog).where(AuditLog.action == "auditor.ledger_viewed")
            )
        )
        .scalars()
        .one()
    )
    assert row.user_id == auditor.id
    assert row.details is not None
    assert row.details["viewed_user_id"] == str(owner.id)


@pytest.mark.asyncio
async def test_ledger_member_cross_user_still_404_and_not_audited(
    client: AsyncClient, db_session: AsyncSession, seeded: tuple[User, Chat, Message]
) -> None:
    _owner, chat, _msg = seeded
    other = User(
        email=f"other2-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        role="member",
    )
    db_session.add(other)
    await db_session.flush()

    r = await client.get(f"/api/v1/chats/{chat.id}/ledger", headers=_auth(other))
    assert r.status_code == 404

    from sqlalchemy import func, select as _select

    from app.models.audit import AuditLog

    count = (
        await db_session.execute(
            _select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "auditor.ledger_viewed")
        )
    ).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_ledger_owner_read_not_audited(
    client: AsyncClient, db_session: AsyncSession, seeded: tuple[User, Chat, Message]
) -> None:
    owner, chat, _msg = seeded
    r = await client.get(f"/api/v1/chats/{chat.id}/ledger", headers=_auth(owner))
    assert r.status_code == 200

    from sqlalchemy import func, select as _select

    from app.models.audit import AuditLog

    count = (
        await db_session.execute(
            _select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "auditor.ledger_viewed")
        )
    ).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_ledger_non_uuid_400(client: AsyncClient, seeded: tuple[User, Chat, Message]) -> None:
    # _validate_chat_id raises ValidationError (HTTP 400), matching the pattern
    # used by all other chat endpoints (e.g. send_message, get_citations).
    user, _, _ = seeded
    r = await client.get("/api/v1/chats/not-a-uuid/ledger", headers=_auth(user))
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_ledger_includes_gate(
    client: AsyncClient, db_session: AsyncSession, seeded: tuple[User, Chat, Message]
) -> None:
    user, chat, msg = seeded
    await compute_and_record_gate(db_session, message_id=msg.id)
    await db_session.flush()
    r = await client.get(f"/api/v1/chats/{chat.id}/ledger", headers=_auth(user))
    assert r.status_code == 200
    body = r.json()
    assert "gates" in body
    assert len(body["gates"]) == 1
    g = body["gates"][0]
    assert g["message_id"] == str(msg.id)
    # the seeded turn has one exact_match KB citation -> fiduciary_grade
    assert g["gate_status"] == "fiduciary_grade"
    assert g["pass_count"] == 1
