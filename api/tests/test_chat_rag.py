"""Chat-send RAG step: retrieval + audit + context-prepend (Wave D.1 T7b).

When the chat's project has KBs attached, ``POST /api/v1/chats/{id}/messages``
now runs a RAG step *before* dispatching to the gateway:

1. Load attached KB ids via the T2 ``project_knowledge_bases`` junction.
2. Call ``hybrid_search`` per attached KB and merge by ``hybrid_score``.
3. Write the T7-shape audit row (``action='inference.kb_chunks_retrieved'``,
   ``resource_type='chat'``) so Receipts surfaces 📎 KB retrieval.
4. Prepend the retrieved chunks as a ``system`` message to the gateway
   request payload so the LLM actually sees them.

These tests cover the four contracted shapes:

* attached KB → hybrid_search called + audit row written + gateway sees
  the prepended system message;
* attached KB but empty results → no audit row, no prepend;
* project but no attached KBs → no retrieval attempted;
* no project (standalone chat) → no retrieval attempted.

``hybrid_search`` is patched per the T7 pattern; the retrieval mechanics
themselves are tested in ``test_knowledge_retrieval_unit.py`` against
the real dataclass.
"""

from __future__ import annotations

import json as _json
import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import GatewayClient, set_gateway_client
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.chat import Chat
from app.models.knowledge import KnowledgeBase
from app.models.project import Project
from app.models.project_knowledge_base import ProjectKnowledgeBase
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
    """In-process AsyncClient + a controlled GatewayClient.

    respx intercepts the test-gateway origin. Db session is the per-test
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


@pytest_asyncio.fixture
async def owner_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"rag-{uuid.uuid4().hex[:8]}@example.com",
        display_name="RAG Chat Owner",
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
async def project_for_owner(db_session: AsyncSession, owner_user: User) -> Project:
    project = Project(
        owner_id=owner_user.id,
        name="RAG matter",
        slug=f"rag-matter-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(project)
    await db_session.flush()
    return project


@pytest_asyncio.fixture
async def kb_for_owner(db_session: AsyncSession, owner_user: User) -> KnowledgeBase:
    kb = KnowledgeBase(
        owner_id=owner_user.id,
        name="RAG KB",
        description="Used for T7b chat-RAG tests",
        # FTS-only avoids the embedding round-trip path entirely.
        hybrid_alpha=1.0,
    )
    db_session.add(kb)
    await db_session.flush()
    return kb


@pytest_asyncio.fixture
async def chat_with_kb_attached(
    db_session: AsyncSession,
    owner_user: User,
    project_for_owner: Project,
    kb_for_owner: KnowledgeBase,
) -> Chat:
    """A chat whose project has one KB attached via the T2 junction."""

    junction = ProjectKnowledgeBase(
        project_id=project_for_owner.id,
        knowledge_base_id=kb_for_owner.id,
    )
    db_session.add(junction)
    chat = Chat(
        owner_id=owner_user.id,
        project_id=project_for_owner.id,
        title="rag-chat-test",
    )
    db_session.add(chat)
    await db_session.flush()
    return chat


@pytest_asyncio.fixture
async def chat_in_empty_project(
    db_session: AsyncSession,
    owner_user: User,
    project_for_owner: Project,
) -> Chat:
    """A chat in a project that has NO KBs attached."""

    chat = Chat(
        owner_id=owner_user.id,
        project_id=project_for_owner.id,
        title="rag-empty-project",
    )
    db_session.add(chat)
    await db_session.flush()
    return chat


@pytest_asyncio.fixture
async def chat_no_project(db_session: AsyncSession, owner_user: User) -> Chat:
    """Standalone chat (no project_id)."""

    chat = Chat(owner_id=owner_user.id, title="rag-standalone")
    db_session.add(chat)
    await db_session.flush()
    return chat


def _bearer(user: User) -> str:
    return create_access_token(user.id, user.email, is_admin=user.is_admin)


def _h(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {_bearer(user)}"}


def _success_payload(content: str = "assistant reply") -> dict[str, Any]:
    return {
        "id": "chatcmpl-rag",
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
        "routed_inference_tier": 3,
        "routed_provider": "anthropic-prod",
        "cost_estimate": 0.0001,
    }


def _fake_hybrid_result(
    chunk_id: uuid.UUID,
    *,
    score: float = 0.9,
    content: str = "Retrieved chunk text body.",
    file_name: str = "stub.pdf",
    page_start: int | None = 1,
    page_end: int | None = 1,
) -> Any:
    """Minimal stand-in mirroring :class:`HybridSearchResult` field shape."""

    class _R:
        def __init__(self) -> None:
            self.chunk_id = chunk_id
            self.document_id = uuid.uuid4()
            self.file_id = uuid.uuid4()
            self.file_name = file_name
            self.content = content
            self.page_start = page_start
            self.page_end = page_end
            self.char_offset_start = 0
            self.char_offset_end = len(content)
            self.vector_score = score
            self.fts_score = score
            self.hybrid_score = score

    return _R()


# ---------------------------------------------------------------------------
# 1. attached KB → hybrid_search called + audit row written + system prepend
# ---------------------------------------------------------------------------


@respx.mock
async def test_chat_send_with_attached_kb_writes_audit_and_prepends_context(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    kb_for_owner: KnowledgeBase,
    chat_with_kb_attached: Chat,
) -> None:
    """RAG step fires: hybrid_search called, audit row written, system prepended."""

    chunk_ids = [uuid.uuid4() for _ in range(3)]
    fake_results = [
        _fake_hybrid_result(
            cid,
            score=0.9 - i * 0.1,
            content=f"retrieved chunk #{i + 1}",
            file_name="nda-template.pdf",
            page_start=i + 1,
            page_end=i + 1,
        )
        for i, cid in enumerate(chunk_ids)
    ]

    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload()),
    )

    with patch(
        "app.api.chats.hybrid_search",
        new=AsyncMock(return_value=fake_results),
    ) as mock_search:
        response = await client.post(
            f"/api/v1/chats/{chat_with_kb_attached.id}/messages",
            json={
                "content": "What does the NDA say about non-compete?",
                "model": "smart",
            },
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text
    assert mock_search.called, "hybrid_search must be invoked when KBs are attached"
    assert route.called, "gateway must still be called"

    # Audit row written.
    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "inference.kb_chunks_retrieved",
                    AuditLog.resource_id == str(chat_with_kb_attached.id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1, f"Expected exactly one retrieval audit row, got {len(audits)}"
    row = audits[0]
    assert row.resource_type == "chat"
    assert row.user_id == owner_user.id
    detail = row.details
    assert detail is not None
    assert detail["chunk_count"] == 3
    assert set(detail["chunk_ids"]) == {str(c) for c in chunk_ids}
    assert detail["kb_ids"] == [str(kb_for_owner.id)]
    # "What does the NDA say about non-compete?" → 7 whitespace tokens
    assert detail["query_token_estimate"] == 7

    # Gateway request received a prepended system message with the context.
    sent_body = _json.loads(route.calls[0].request.read())
    messages = sent_body["messages"]
    assert len(messages) == 2, f"Expected system + user, got {messages}"
    assert messages[0]["role"] == "system"
    assert "Retrieved context" in messages[0]["content"]
    # Chunk text shows up verbatim in the context block.
    assert "retrieved chunk #1" in messages[0]["content"]
    assert "retrieved chunk #2" in messages[0]["content"]
    assert "retrieved chunk #3" in messages[0]["content"]
    # File name + page rendered as the chunk header.
    assert "nda-template.pdf" in messages[0]["content"]
    # M2-D2: retrieval-context system message opts out of anonymization
    # so the model sees intact source quotes for citation grounding.
    assert messages[0]["lq_ai_skip_anonymization"] is True
    # User turn unchanged at the end.
    assert messages[1] == {
        "role": "user",
        "content": "What does the NDA say about non-compete?",
        "lq_ai_skip_anonymization": False,
    }


# ---------------------------------------------------------------------------
# 2. attached KB but empty results → no audit row, no prepend
# ---------------------------------------------------------------------------


@respx.mock
async def test_chat_send_with_attached_kb_and_empty_results_writes_no_audit(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    chat_with_kb_attached: Chat,
) -> None:
    """KB attached but hybrid_search returns [] → guard: no audit, no prepend."""

    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload()),
    )

    with patch(
        "app.api.chats.hybrid_search",
        new=AsyncMock(return_value=[]),
    ) as mock_search:
        response = await client.post(
            f"/api/v1/chats/{chat_with_kb_attached.id}/messages",
            json={"content": "needle no haystack", "model": "smart"},
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text
    assert mock_search.called

    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "inference.kb_chunks_retrieved",
                    AuditLog.resource_id == str(chat_with_kb_attached.id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert audits == []

    # Gateway request has only the user turn.
    sent_body = _json.loads(route.calls[0].request.read())
    assert sent_body["messages"] == [
        {"role": "user", "content": "needle no haystack", "lq_ai_skip_anonymization": False}
    ]


# ---------------------------------------------------------------------------
# 3. project but no KBs attached → no retrieval attempted
# ---------------------------------------------------------------------------


@respx.mock
async def test_chat_send_with_project_but_no_kbs_skips_retrieval(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    chat_in_empty_project: Chat,
) -> None:
    """project_id set but no KBs attached → hybrid_search NOT called."""

    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload()),
    )

    with patch(
        "app.api.chats.hybrid_search",
        new=AsyncMock(return_value=[]),
    ) as mock_search:
        response = await client.post(
            f"/api/v1/chats/{chat_in_empty_project.id}/messages",
            json={"content": "hello", "model": "smart"},
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text
    assert not mock_search.called, "hybrid_search must NOT be called when no KBs attached"

    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "inference.kb_chunks_retrieved",
                )
            )
        )
        .scalars()
        .all()
    )
    assert audits == []

    sent_body = _json.loads(route.calls[0].request.read())
    assert sent_body["messages"] == [
        {"role": "user", "content": "hello", "lq_ai_skip_anonymization": False}
    ]


# ---------------------------------------------------------------------------
# 4. no project (standalone chat) → no retrieval attempted
# ---------------------------------------------------------------------------


@respx.mock
async def test_chat_send_standalone_chat_skips_retrieval(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    chat_no_project: Chat,
) -> None:
    """project_id is None → hybrid_search NOT called; no audit row."""

    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload()),
    )

    with patch(
        "app.api.chats.hybrid_search",
        new=AsyncMock(return_value=[]),
    ) as mock_search:
        response = await client.post(
            f"/api/v1/chats/{chat_no_project.id}/messages",
            json={"content": "hello world", "model": "smart"},
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text
    assert not mock_search.called

    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "inference.kb_chunks_retrieved",
                )
            )
        )
        .scalars()
        .all()
    )
    assert audits == []

    sent_body = _json.loads(route.calls[0].request.read())
    assert sent_body["messages"] == [
        {"role": "user", "content": "hello world", "lq_ai_skip_anonymization": False}
    ]
