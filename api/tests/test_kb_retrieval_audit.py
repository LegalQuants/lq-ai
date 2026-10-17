"""KB retrieval writes an audit row so Receipts can render '📎 KB retrieval'.

Wave D.1 T7. Verifies that ``POST /api/v1/knowledge-bases/{kb_id}/query``,
when called with a ``chat_id`` in the request body, writes an audit row
with ``action='inference.kb_chunks_retrieved'`` scoped to the chat
(``resource_type='chat'``). Without a ``chat_id``, no audit row is
written (standalone retrieval). With an empty result set, no audit row
is written either (guard).

``hybrid_search`` is patched to synthetic results to keep this focused
on the audit write — the retrieval mechanics themselves are tested in
``test_knowledge_retrieval_unit.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.chat import Chat
from app.models.knowledge import KnowledgeBase
from app.models.user import User
from app.security import create_access_token, hash_password

pytestmark = pytest.mark.integration


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def owner_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"kb-audit-{uuid.uuid4().hex[:8]}@example.com",
        display_name="KB Audit Owner",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        role="member",
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
async def kb(db_session: AsyncSession, owner_user: User) -> KnowledgeBase:
    kb = KnowledgeBase(
        owner_id=owner_user.id,
        name="Audit-trail KB",
        description="Used for T7 retrieval-audit tests",
        hybrid_alpha=0.5,
    )
    db_session.add(kb)
    await db_session.flush()
    return kb


@pytest_asyncio.fixture
async def chat_for_owner(db_session: AsyncSession, owner_user: User) -> Chat:
    chat = Chat(owner_id=owner_user.id, title="kb-audit-test")
    db_session.add(chat)
    await db_session.flush()
    return chat


def _fake_hybrid_result(chunk_id: uuid.UUID, score: float = 0.9) -> Any:
    """Minimal HybridSearchResult stand-in carrying just .chunk_id.

    The handler maps each result via a comprehension that reads many
    fields, so for the audit-row test we only mock far enough that the
    audit-write codepath runs — the response-mapping codepath itself
    is exercised in test_knowledge_retrieval_unit.py against the real
    dataclass.
    """

    class _R:
        def __init__(self) -> None:
            self.chunk_id = chunk_id
            self.document_id = uuid.uuid4()
            self.file_id = uuid.uuid4()
            self.file_name = "stub.pdf"
            self.content = "stub chunk text"
            self.page_start = 1
            self.page_end = 1
            self.char_offset_start = 0
            self.char_offset_end = 16
            self.vector_score = score
            self.fts_score = score
            self.hybrid_score = score

    return _R()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_chat_initiated_query_writes_retrieval_audit_row(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    kb: KnowledgeBase,
    chat_for_owner: Chat,
) -> None:
    """``chat_id`` in body + non-empty results → audit row written."""

    chunk_ids = [uuid.uuid4() for _ in range(3)]
    fake_results = [_fake_hybrid_result(cid) for cid in chunk_ids]

    with (
        patch(
            "app.api.knowledge_bases.hybrid_search",
            new=AsyncMock(return_value=fake_results),
        ),
        patch(
            # alpha=1.0 path skips embedding entirely; safer than mocking
            # the gateway client. We force FTS-only via hybrid_alpha=1.0
            # below, but also patch embed-fetch as a defensive belt: any
            # production-path change to alpha gating won't blow up the test.
            "app.api.knowledge_bases.request_embedding_vector",
            new=AsyncMock(return_value=[0.0] * 1536),
        ),
    ):
        response = await client.post(
            f"/api/v1/knowledge-bases/{kb.id}/query",
            json={
                "query": "What does the NDA say about non-compete?",
                "top_k": 5,
                "hybrid_alpha": 1.0,
                "chat_id": str(chat_for_owner.id),
            },
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text

    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "inference.kb_chunks_retrieved",
                    AuditLog.resource_id == str(chat_for_owner.id),
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
    assert detail["kb_ids"] == [str(kb.id)]
    # query "What does the NDA say about non-compete?" → 7 whitespace-split tokens
    assert detail["query_token_estimate"] == 7


async def test_standalone_query_writes_no_retrieval_audit_row(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    kb: KnowledgeBase,
) -> None:
    """No ``chat_id`` → no audit row, even with non-empty results."""

    fake_results = [_fake_hybrid_result(uuid.uuid4()) for _ in range(2)]

    with (
        patch(
            "app.api.knowledge_bases.hybrid_search",
            new=AsyncMock(return_value=fake_results),
        ),
        patch(
            "app.api.knowledge_bases.request_embedding_vector",
            new=AsyncMock(return_value=[0.0] * 1536),
        ),
    ):
        response = await client.post(
            f"/api/v1/knowledge-bases/{kb.id}/query",
            json={
                "query": "hello",
                "top_k": 5,
                "hybrid_alpha": 1.0,
            },
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text

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


async def test_empty_results_writes_no_retrieval_audit_row(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    kb: KnowledgeBase,
    chat_for_owner: Chat,
) -> None:
    """``chat_id`` set + empty result set → no audit row (guard)."""

    with (
        patch(
            "app.api.knowledge_bases.hybrid_search",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.api.knowledge_bases.request_embedding_vector",
            new=AsyncMock(return_value=[0.0] * 1536),
        ),
    ):
        response = await client.post(
            f"/api/v1/knowledge-bases/{kb.id}/query",
            json={
                "query": "needle that finds no haystack",
                "top_k": 5,
                "hybrid_alpha": 1.0,
                "chat_id": str(chat_for_owner.id),
            },
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text

    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "inference.kb_chunks_retrieved",
                    AuditLog.resource_id == str(chat_for_owner.id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert audits == []
