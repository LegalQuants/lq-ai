"""Matter-only files must reach chat inference without widening file access."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import chats
from app.clients.gateway import GatewayClient, set_gateway_client
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.chat import Chat, Message
from app.models.document import Document
from app.models.file import File
from app.models.project import Project, ProjectFile
from app.models.project_member import ProjectMember
from app.models.user import User
from app.security import create_access_token, hash_password
from tests.test_chats_send_message import _stream_chunk, _success_payload

pytestmark = pytest.mark.integration
GATEWAY = "http://matter-files-gateway"


async def make_user(db: AsyncSession) -> User:
    user = User(
        email=f"matter-{uuid.uuid4().hex}@example.com",
        display_name="Matter Files",
        hashed_password=hash_password("test-password"),
        must_change_password=False,
        is_admin=False,
        mfa_enabled=False,
    )
    db.add(user)
    await db.flush()
    return user


async def make_project(db: AsyncSession, owner: User) -> Project:
    project = Project(owner_id=owner.id, name="Matter", slug=uuid.uuid4().hex)
    db.add(project)
    await db.flush()
    return project


@pytest_asyncio.fixture
async def context(db_session: AsyncSession) -> tuple[User, Project, Chat]:
    user = await make_user(db_session)
    project = await make_project(db_session, user)
    chat = Chat(owner_id=user.id, project_id=project.id, title="New chat")
    db_session.add(chat)
    await db_session.flush()
    return user, project, chat


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = override
    gateway = GatewayClient(base_url=GATEWAY, gateway_key="test")
    set_gateway_client(gateway)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
            yield value
    finally:
        set_gateway_client(None)
        await gateway.aclose()
        app.dependency_overrides.pop(get_db, None)


async def make_file(
    db: AsyncSession,
    owner: User,
    project: Project | None,
    *,
    status: str = "ready",
    text: str | None = "The escrow release date is 23 March.",
    attached_at: datetime | None = None,
) -> File:
    fid = uuid.uuid4()
    file = File(
        id=fid,
        owner_id=owner.id,
        filename=f"{fid}.txt",
        mime_type="text/plain",
        size_bytes=50,
        hash_sha256=fid.hex * 2,
        storage_path=str(fid),
        ingestion_status=status,
    )
    db.add(file)
    await db.flush()
    if text is not None:
        db.add(Document(file_id=fid, parser="text", normalized_content=text))
    if project:
        db.add(
            ProjectFile(
                project_id=project.id, file_id=fid, attached_at=attached_at or datetime.now(UTC)
            )
        )
    await db.flush()
    return file


def gateway_reply(stream: bool) -> httpx.Response:
    if stream:
        return httpx.Response(
            200,
            content=_stream_chunk("answer") + "data: [DONE]\n\n",
            headers={"content-type": "text/event-stream"},
        )
    return httpx.Response(200, json=_success_payload(content="answer"))


async def send(client: AsyncClient, user: User, chat: Chat, **payload: Any) -> httpx.Response:
    return await client.post(
        f"/api/v1/chats/{chat.id}/messages",
        headers={
            "Authorization": f"Bearer {create_access_token(user.id, user.email, is_admin=user.is_admin)}"
        },
        json={"content": "What is the escrow release date?", **payload},
    )


def complete(response: httpx.Response, stream: bool) -> dict[str, Any]:
    if not stream:
        return response.json()
    for line in response.text.splitlines():
        if line.startswith("data:") and line != "data: [DONE]":
            event = json.loads(line[5:])
            if event.get("type") == "complete":
                return event
    raise AssertionError("missing complete frame")


@pytest.mark.parametrize("stream", [False, True])
@respx.mock
async def test_matter_only_file_reaches_model_and_audit(
    client: AsyncClient,
    db_session: AsyncSession,
    context: tuple[User, Project, Chat],
    stream: bool,
) -> None:
    user, project, chat = context
    project.privileged = True
    project.minimum_inference_tier = 2
    file = await make_file(db_session, user, project)
    route = respx.post(f"{GATEWAY}/v1/chat/completions").mock(return_value=gateway_reply(stream))
    response = await send(client, user, chat, stream=stream)
    assert response.status_code == 200, response.text
    body = json.loads(route.calls.last.request.content)
    assert body["lq_ai_file_ids"] == [str(file.id)]
    blocks = [m for m in body["messages"] if "23 March" in m["content"]]
    assert len(blocks) == 1
    assert blocks[0]["lq_ai_skip_anonymization"] is True
    assert body["lq_ai_project_minimum_inference_tier"] == 2
    assert body["lq_ai_privileged"] is True
    assert complete(response, stream)["applied_file_ids"] == [str(file.id)]
    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "inference.message_files_attached",
                AuditLog.resource_id == str(chat.id),
            )
        )
    ).scalar_one()
    assert audit.details is not None
    assert audit.details["file_ids"] == [str(file.id)]
    assert "23 March" not in json.dumps(audit.details)


@respx.mock
async def test_explicit_first_dedup_and_stable_matter_order(
    client: AsyncClient,
    db_session: AsyncSession,
    context: tuple[User, Project, Chat],
) -> None:
    user, project, chat = context
    start = datetime(2026, 1, 1, tzinfo=UTC)
    first = await make_file(db_session, user, project, attached_at=start)
    second = await make_file(db_session, user, project, attached_at=start + timedelta(seconds=1))
    explicit = await make_file(db_session, user, None)
    route = respx.post(f"{GATEWAY}/v1/chat/completions").mock(return_value=gateway_reply(False))
    response = await send(
        client, user, chat, file_ids=[str(second.id), str(explicit.id), str(second.id)]
    )
    assert response.status_code == 200, response.text
    assert json.loads(route.calls.last.request.content)["lq_ai_file_ids"] == [
        str(second.id),
        str(explicit.id),
        str(first.id),
    ]


@pytest.mark.parametrize("count,expected", [(16, 200), (17, 400)])
@respx.mock
async def test_combined_cap_before_message_persistence(
    client: AsyncClient,
    db_session: AsyncSession,
    context: tuple[User, Project, Chat],
    count: int,
    expected: int,
) -> None:
    user, project, chat = context
    for _ in range(count - 1):
        await make_file(db_session, user, project)
    explicit = await make_file(db_session, user, None)
    route = None
    if expected == 200:
        route = respx.post(f"{GATEWAY}/v1/chat/completions").mock(return_value=gateway_reply(False))
    response = await send(client, user, chat, file_ids=[str(explicit.id)])
    assert response.status_code == expected, response.text
    if expected == 400:
        assert not respx.calls
        assert (
            await db_session.scalar(
                select(func.count()).select_from(Message).where(Message.chat_id == chat.id)
            )
        ) == 0
        await db_session.refresh(chat)
        assert chat.title == "New chat"
    else:
        assert route is not None
        assert len(json.loads(route.calls.last.request.content)["lq_ai_file_ids"]) == 16


@pytest.mark.parametrize(
    "excluded", ["pending", "processing", "failed", "deleted", "foreign", "other_matter"]
)
@respx.mock
async def test_ineligible_matter_files_are_not_inherited(
    client: AsyncClient,
    db_session: AsyncSession,
    context: tuple[User, Project, Chat],
    excluded: str,
) -> None:
    user, project, chat = context
    allowed = await make_file(db_session, user, project)
    owner = await make_user(db_session) if excluded == "foreign" else user
    target = await make_project(db_session, user) if excluded == "other_matter" else project
    blocked = await make_file(
        db_session,
        owner,
        target,
        text="DO NOT SEND THIS",
        status=excluded if excluded in {"pending", "processing", "failed"} else "ready",
    )
    if excluded == "deleted":
        blocked.deleted_at = datetime.now(UTC)
        await db_session.flush()
    route = respx.post(f"{GATEWAY}/v1/chat/completions").mock(return_value=gateway_reply(False))
    response = await send(client, user, chat)
    assert response.status_code == 200, response.text
    sent = json.loads(route.calls.last.request.content)
    assert sent["lq_ai_file_ids"] == [str(allowed.id)]
    assert "DO NOT SEND THIS" not in route.calls.last.request.content.decode()


@pytest.mark.parametrize(
    "restriction", ["unreadable_direct", "screened_direct", "screened_attachment"]
)
@respx.mock
async def test_direct_scope_and_other_attachment_screens_follow_file(
    client: AsyncClient,
    db_session: AsyncSession,
    context: tuple[User, Project, Chat],
    restriction: str,
) -> None:
    user, project, chat = context
    other = await make_project(db_session, await make_user(db_session))
    file = await make_file(db_session, user, project, text="SCREENED CONTENT")
    if restriction == "screened_attachment":
        db_session.add(ProjectFile(project_id=other.id, file_id=file.id))
    else:
        file.project_id = other.id
    if restriction.startswith("screened"):
        db_session.add(ProjectMember(project_id=other.id, user_id=user.id, role="blocked"))
    await db_session.flush()
    route = respx.post(f"{GATEWAY}/v1/chat/completions").mock(return_value=gateway_reply(False))
    response = await send(client, user, chat)
    assert response.status_code == 200, response.text
    assert json.loads(route.calls.last.request.content)["lq_ai_file_ids"] == []
    assert "SCREENED CONTENT" not in route.calls.last.request.content.decode()


@respx.mock
async def test_foreign_explicit_attachment_still_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    context: tuple[User, Project, Chat],
) -> None:
    user, project, chat = context
    foreign = await make_file(db_session, await make_user(db_session), project)
    response = await send(client, user, chat, file_ids=[str(foreign.id)])
    assert response.status_code == 404
    assert not respx.calls


@pytest.mark.parametrize("change", ["unready", "deleted", "screened", "chat_moved"])
@respx.mock
async def test_inherited_context_rechecked_after_initial_selection(
    client: AsyncClient,
    db_session: AsyncSession,
    context: tuple[User, Project, Chat],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    user, project, chat = context
    file = await make_file(db_session, user, project, text="OLD MATTER SECRET")
    original = chats._load_matter_file_ids
    changed = False

    async def select_then_change(*args: Any, **kwargs: Any) -> list[str]:
        nonlocal changed
        result = await original(*args, **kwargs)
        if not changed:
            changed = True
            if change == "unready":
                file.ingestion_status = "processing"
            elif change == "deleted":
                file.deleted_at = datetime.now(UTC)
            elif change == "screened":
                other = await make_project(db_session, user)
                db_session.add(ProjectFile(project_id=other.id, file_id=file.id))
                db_session.add(ProjectMember(project_id=other.id, user_id=user.id, role="blocked"))
            else:
                chat.project_id = (await make_project(db_session, user)).id
            await db_session.flush()
        return result

    monkeypatch.setattr(chats, "_load_matter_file_ids", select_then_change)
    route = respx.post(f"{GATEWAY}/v1/chat/completions").mock(return_value=gateway_reply(False))
    response = await send(client, user, chat)
    assert response.status_code == 200, response.text
    assert "OLD MATTER SECRET" not in route.calls.last.request.content.decode()


@respx.mock
async def test_no_matter_preserves_explicit_attachment_behavior(
    client: AsyncClient,
    db_session: AsyncSession,
    context: tuple[User, Project, Chat],
) -> None:
    user, project, chat = context
    await make_file(db_session, user, project, text="NOT IN THIS CHAT")
    explicit = await make_file(db_session, user, None, status="processing", text="EXPLICIT")
    chat.project_id = None
    await db_session.flush()
    route = respx.post(f"{GATEWAY}/v1/chat/completions").mock(return_value=gateway_reply(False))
    response = await send(client, user, chat, file_ids=[str(explicit.id)])
    assert response.status_code == 200, response.text
    sent = route.calls.last.request.content.decode()
    assert json.loads(sent)["lq_ai_file_ids"] == [str(explicit.id)]
    assert "EXPLICIT" in sent
    assert "NOT IN THIS CHAT" not in sent


@pytest.mark.parametrize("text", [None, "", "   "])
@respx.mock
async def test_ready_file_without_extractable_text_does_not_inject_block(
    client: AsyncClient,
    db_session: AsyncSession,
    context: tuple[User, Project, Chat],
    text: str | None,
) -> None:
    user, project, chat = context
    file = await make_file(db_session, user, project, text=text)
    route = respx.post(f"{GATEWAY}/v1/chat/completions").mock(return_value=gateway_reply(False))
    response = await send(client, user, chat)
    assert response.status_code == 200, response.text
    sent = json.loads(route.calls.last.request.content)
    assert sent["lq_ai_file_ids"] == [str(file.id)]
    assert not any("## Attached documents" in m["content"] for m in sent["messages"])


@respx.mock
async def test_readable_direct_scope_is_not_needlessly_excluded(
    client: AsyncClient,
    db_session: AsyncSession,
    context: tuple[User, Project, Chat],
) -> None:
    user, project, chat = context
    other = await make_project(db_session, await make_user(db_session))
    other.share_scope = "org"
    file = await make_file(db_session, user, project)
    file.project_id = other.id
    await db_session.flush()
    route = respx.post(f"{GATEWAY}/v1/chat/completions").mock(return_value=gateway_reply(False))
    response = await send(client, user, chat)
    assert response.status_code == 200, response.text
    assert json.loads(route.calls.last.request.content)["lq_ai_file_ids"] == [str(file.id)]


@pytest.mark.parametrize("change", ["unready", "detached", "direct_access_revoked"])
@respx.mock
async def test_inherited_content_query_rechecks_latest_scope(
    client: AsyncClient,
    db_session: AsyncSession,
    context: tuple[User, Project, Chat],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    user, project, chat = context
    file = await make_file(db_session, user, project, text="MUST NOT LEAVE DATABASE")
    other = await make_project(db_session, await make_user(db_session))
    other.share_scope = "org"
    file.project_id = other.id
    await db_session.flush()
    original = chats._load_attached_file_contexts

    async def mutate_then_load(*args: Any, **kwargs: Any) -> list[tuple[str, str]]:
        # Mutate at the last read boundary, after both ID-selection queries.
        if change == "unready":
            file.ingestion_status = "processing"
        elif change == "detached":
            link = await db_session.get(ProjectFile, (project.id, file.id))
            assert link is not None
            await db_session.delete(link)
        else:
            other.share_scope = "personal"
        await db_session.flush()
        return await original(*args, **kwargs)

    monkeypatch.setattr(chats, "_load_attached_file_contexts", mutate_then_load)
    route = respx.post(f"{GATEWAY}/v1/chat/completions").mock(return_value=gateway_reply(False))
    response = await send(client, user, chat)
    assert response.status_code == 200, response.text
    assert "MUST NOT LEAVE DATABASE" not in route.calls.last.request.content.decode()
