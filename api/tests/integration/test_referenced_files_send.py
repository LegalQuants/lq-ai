"""Task 3 (referenced-files) — ``_validate_referenced_file_ids`` direct-call tests.

Exercises the handler-side validator that Task 4 wires into
``send_message`` for caller-referenced file-scoped retrieval:

* KB-only MVP scope: a referenced id must be (1) a well-formed UUID,
  (2) a caller-owned, non-deleted, ``ingestion_status='ready'`` file,
  (3) attached to a Knowledge Base that is itself attached to the
  chat's ``project_id``.
* Any failing referenced id, or a projectless chat, raises
  :class:`NotFound` (404) with the same id-probing-safe message shape
  used by :func:`_validate_owned_file_ids` — a foreign/nonexistent/
  malformed/not-ready/not-in-matter-KB id is indistinguishable.
* Success returns ``(validated_ids, alpha_by_id)`` — deduped,
  order-preserving ids, and each file's retrieval alpha (MIN
  ``hybrid_alpha`` across all containing, project-attached KBs).

These are direct calls against ``_validate_referenced_file_ids`` (no
HTTP client) — Task 4 will append endpoint-level tests exercising the
wired-in ``send_message`` path.
"""

from __future__ import annotations

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

from app.api.chats import _validate_referenced_file_ids
from app.clients.gateway import GatewayClient, set_gateway_client
from app.db.session import get_db
from app.errors import NotFound
from app.main import app
from app.models.audit import AuditLog
from app.models.chat import Chat
from app.models.document import Document, DocumentChunk
from app.models.file import File
from app.models.knowledge import KnowledgeBase, KnowledgeBaseFile
from app.models.project import Project
from app.models.project_knowledge_base import ProjectKnowledgeBase
from app.models.user import User
from app.security import create_access_token, hash_password

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

GATEWAY_BASE = "http://test-gateway"
GATEWAY_KEY = "test-gw-key"


def _make_user() -> User:
    return User(
        email=f"ref-files-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Referenced Files Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )


def _make_project(owner_id: uuid.UUID) -> Project:
    return Project(
        owner_id=owner_id,
        name="Referenced Files Matter",
        slug=f"ref-files-matter-{uuid.uuid4().hex[:8]}",
    )


def _make_kb(owner_id: uuid.UUID, hybrid_alpha: float = 0.7) -> KnowledgeBase:
    return KnowledgeBase(
        owner_id=owner_id,
        name="Referenced Files KB",
        description="Task 3 direct-call tests",
        hybrid_alpha=hybrid_alpha,
    )


def _make_ready_file(owner_id: uuid.UUID, ingestion_status: str = "ready") -> File:
    return File(
        owner_id=owner_id,
        filename="doc.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        hash_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        storage_path=str(uuid.uuid4()),
        ingestion_status=ingestion_status,
    )


def _make_document(file_id: uuid.UUID) -> Document:
    return Document(
        file_id=file_id,
        parser="pymupdf",
        parser_version="1.0",
        normalized_content="referenced file content",
    )


async def _seed_attached_ready_file(
    db_session: AsyncSession,
    *,
    hybrid_alpha: float = 0.7,
    ingestion_status: str = "ready",
) -> tuple[User, Project, File]:
    """Seed user + project + KB (attached to project) + ready file (in KB)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    project = _make_project(user.id)
    db_session.add(project)
    await db_session.flush()

    kb = _make_kb(user.id, hybrid_alpha=hybrid_alpha)
    db_session.add(kb)
    await db_session.flush()

    db_session.add(ProjectKnowledgeBase(project_id=project.id, knowledge_base_id=kb.id))

    file_row = _make_ready_file(user.id, ingestion_status=ingestion_status)
    db_session.add(file_row)
    await db_session.flush()

    db_session.add(KnowledgeBaseFile(kb_id=kb.id, file_id=file_row.id))
    db_session.add(_make_document(file_row.id))
    await db_session.flush()

    return user, project, file_row


async def test_valid_file_returns_ids_and_alpha(db_session: AsyncSession) -> None:
    user, project, file_row = await _seed_attached_ready_file(db_session, hybrid_alpha=0.7)

    result = await _validate_referenced_file_ids(
        db_session,
        [str(file_row.id)],
        owner_id=user.id,
        project_id=project.id,
    )

    assert result == ([str(file_row.id)], {str(file_row.id): 0.7})


async def test_empty_input_returns_empty_without_db_call(db_session: AsyncSession) -> None:
    result = await _validate_referenced_file_ids(
        db_session,
        [],
        owner_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
    )

    assert result == ([], {})


async def test_projectless_chat_raises_not_found(db_session: AsyncSession) -> None:
    user, _project, file_row = await _seed_attached_ready_file(db_session)

    with pytest.raises(NotFound):
        await _validate_referenced_file_ids(
            db_session,
            [str(file_row.id)],
            owner_id=user.id,
            project_id=None,
        )


async def test_foreign_uuid_raises_not_found(db_session: AsyncSession) -> None:
    user, project, _file_row = await _seed_attached_ready_file(db_session)

    with pytest.raises(NotFound):
        await _validate_referenced_file_ids(
            db_session,
            [str(uuid.uuid4())],
            owner_id=user.id,
            project_id=project.id,
        )


async def test_kb_not_attached_to_project_raises_not_found(db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    project = _make_project(user.id)
    db_session.add(project)
    await db_session.flush()

    # KB exists and holds a ready file, but is never attached to `project`
    # via ProjectKnowledgeBase — not referenceable from this chat's matter.
    kb = _make_kb(user.id, hybrid_alpha=0.7)
    db_session.add(kb)
    await db_session.flush()

    file_row = _make_ready_file(user.id)
    db_session.add(file_row)
    await db_session.flush()

    db_session.add(KnowledgeBaseFile(kb_id=kb.id, file_id=file_row.id))
    db_session.add(_make_document(file_row.id))
    await db_session.flush()

    with pytest.raises(NotFound):
        await _validate_referenced_file_ids(
            db_session,
            [str(file_row.id)],
            owner_id=user.id,
            project_id=project.id,
        )


async def test_processing_status_file_raises_not_found(db_session: AsyncSession) -> None:
    user, project, file_row = await _seed_attached_ready_file(
        db_session, ingestion_status="processing"
    )

    with pytest.raises(NotFound):
        await _validate_referenced_file_ids(
            db_session,
            [str(file_row.id)],
            owner_id=user.id,
            project_id=project.id,
        )


async def test_malformed_id_raises_not_found(db_session: AsyncSession) -> None:
    user, project, _file_row = await _seed_attached_ready_file(db_session)

    with pytest.raises(NotFound):
        await _validate_referenced_file_ids(
            db_session,
            ["not-a-uuid"],
            owner_id=user.id,
            project_id=project.id,
        )


async def test_duplicate_ids_deduped_order_preserving(db_session: AsyncSession) -> None:
    user, project, file_row = await _seed_attached_ready_file(db_session, hybrid_alpha=0.7)

    result = await _validate_referenced_file_ids(
        db_session,
        [str(file_row.id), str(file_row.id)],
        owner_id=user.id,
        project_id=project.id,
    )

    assert result == ([str(file_row.id)], {str(file_row.id): 0.7})


# ---------------------------------------------------------------------------
# Task 4 — endpoint-level: send_message wires referenced-file retrieval,
# citation grounding, echo, and audit. The KB pass is stubbed empty and
# the referenced-file primitive (``hybrid_search_files``) is patched to
# point at real seeded rows, isolating the referenced-files wiring under test (the
# real primitive is covered against the DB by Task 2's tests).
# ---------------------------------------------------------------------------

# A chunk body whose verbatim slice the model will quote back. QUOTE is a
# substring so Stage-1 exact-match verification persists a citation row.
CHUNK_BODY = "The parties agree to a mutual two-year non-compete covering the defined territory."
QUOTE = "a mutual two-year non-compete"


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """In-process AsyncClient with a gateway stub, mirroring the Task-3
    integration siblings (ASGI transport + get_db override)."""

    app.dependency_overrides[get_db] = _override_get_db(db_session)
    gw = GatewayClient(base_url=GATEWAY_BASE, gateway_key=GATEWAY_KEY)
    set_gateway_client(gw)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    set_gateway_client(None)
    await gw.aclose()
    app.dependency_overrides.pop(get_db, None)


def _h(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


def _success_payload(content: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-ref",
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
        "usage": {"prompt_tokens": 5, "completion_tokens": 12, "total_tokens": 17},
        "routed_inference_tier": 3,
        "routed_provider": "anthropic-prod",
        "cost_estimate": 0.0001,
    }


def _hybrid_result_for(chunk: DocumentChunk, document: Document, file: File) -> Any:
    """HybridSearchResult-shaped stand-in pointing at real fixture rows."""

    class _R:
        def __init__(self) -> None:
            self.chunk_id = chunk.id
            self.document_id = document.id
            self.file_id = file.id
            self.file_name = file.filename
            self.content = chunk.content
            self.page_start = chunk.page_start
            self.page_end = chunk.page_end
            self.char_offset_start = chunk.char_offset_start
            self.char_offset_end = chunk.char_offset_end
            self.vector_score = 0.9
            self.fts_score = 0.9
            self.hybrid_score = 0.9

    return _R()


async def _seed_chat_with_referenced_file(
    db_session: AsyncSession,
) -> tuple[User, Chat, File, Document, DocumentChunk]:
    """Seed user + project + KB(attached) + ready file(in KB) + Document +
    DocumentChunk + a project-scoped Chat. The Document's
    ``normalized_content`` carries CHUNK_BODY so the Stage-1 verifier can
    slice the quoted passage byte-for-byte."""

    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    project = _make_project(user.id)
    db_session.add(project)
    await db_session.flush()

    # hybrid_alpha=1.0 keeps the (stubbed) KB pass from ever needing an
    # embed call; the referenced primitive is patched regardless.
    kb = _make_kb(user.id, hybrid_alpha=1.0)
    db_session.add(kb)
    await db_session.flush()

    db_session.add(ProjectKnowledgeBase(project_id=project.id, knowledge_base_id=kb.id))

    file_row = _make_ready_file(user.id)
    db_session.add(file_row)
    await db_session.flush()

    db_session.add(KnowledgeBaseFile(kb_id=kb.id, file_id=file_row.id))

    document = Document(
        file_id=file_row.id,
        parser="pymupdf",
        parser_version="1.0",
        normalized_content=CHUNK_BODY,
    )
    db_session.add(document)
    await db_session.flush()

    chunk = DocumentChunk(
        document_id=document.id,
        chunk_index=0,
        content=CHUNK_BODY,
        page_start=1,
        page_end=1,
        char_offset_start=0,
        char_offset_end=len(CHUNK_BODY),
    )
    db_session.add(chunk)

    chat = Chat(owner_id=user.id, project_id=project.id, title="ref-files-send")
    db_session.add(chat)
    await db_session.flush()

    return user, chat, file_row, document, chunk


@respx.mock
async def test_send_with_referenced_file_grounds_and_cites(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST send with a referenced file → 200; the response echoes
    ``applied_referenced_file_ids``, and the GET citations endpoint
    surfaces a verified citation whose source file is the referenced
    file (Stage-1 exact-match against the referenced chunk)."""

    user, chat, file_row, _document, _chunk = await _seed_chat_with_referenced_file(db_session)
    assistant_text = f'"{QUOTE}" (Source: [1])'

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload(assistant_text)),
    )

    with (
        patch(
            "app.api.chats._retrieve_kb_context_for_chat",
            new=AsyncMock(return_value=([], [], None)),
        ),
        patch(
            "app.api.chats.hybrid_search_files",
            new=AsyncMock(return_value=[_hybrid_result_for(_chunk, _document, file_row)]),
        ),
    ):
        resp = await client.post(
            f"/api/v1/chats/{chat.id}/messages",
            headers=_h(user),
            json={
                "content": "Quote the non-compete clause.",
                "model": "smart",
                "referenced_file_ids": [str(file_row.id)],
            },
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied_referenced_file_ids"] == [str(file_row.id)]

    assistant_msg_id = body["message"]["id"]
    cites_resp = await client.get(
        f"/api/v1/chats/{chat.id}/messages/{assistant_msg_id}/citations",
        headers=_h(user),
    )
    assert cites_resp.status_code == 200, cites_resp.text
    cites = cites_resp.json()
    assert any(c["source_file_id"] == str(file_row.id) and c["verified"] for c in cites), cites


@respx.mock
async def test_send_with_referenced_file_writes_audit_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """After the e2e send, exactly one ``inference.message_referenced_files``
    audit row exists carrying ids/counts only — and NO content/query keys."""

    user, chat, file_row, _document, _chunk = await _seed_chat_with_referenced_file(db_session)

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload(f'"{QUOTE}" (Source: [1])')),
    )

    with (
        patch(
            "app.api.chats._retrieve_kb_context_for_chat",
            new=AsyncMock(return_value=([], [], None)),
        ),
        patch(
            "app.api.chats.hybrid_search_files",
            new=AsyncMock(return_value=[_hybrid_result_for(_chunk, _document, file_row)]),
        ),
    ):
        resp = await client.post(
            f"/api/v1/chats/{chat.id}/messages",
            headers=_h(user),
            json={
                "content": "Quote the non-compete clause.",
                "model": "smart",
                "referenced_file_ids": [str(file_row.id)],
            },
        )
    assert resp.status_code == 200, resp.text

    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "inference.message_referenced_files")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, f"expected exactly one referenced-files audit row, got {len(rows)}"
    details = rows[0].details or {}
    assert details["file_ids"] == [str(file_row.id)]
    assert details["referenced_count"] == 1
    assert details["chunk_count"] == 1
    assert len(details["chunk_ids"]) == 1
    # P3 — counts/ids only; no message content or query text may leak.
    assert "content" not in details
    assert "query" not in details
    assert "query_token_estimate" not in details


@respx.mock
async def test_send_foreign_referenced_id_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A referenced id the caller doesn't own (random uuid) → 404,
    id-probing-safe, and the gateway is never called."""

    user, chat, _file_row, _document, _chunk = await _seed_chat_with_referenced_file(db_session)

    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload("unused")),
    )

    resp = await client.post(
        f"/api/v1/chats/{chat.id}/messages",
        headers=_h(user),
        json={
            "content": "hi",
            "model": "smart",
            "referenced_file_ids": [str(uuid.uuid4())],
        },
    )
    assert resp.status_code == 404, resp.text
    assert not route.called


@respx.mock
async def test_send_projectless_chat_with_referenced_id_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A referenced id on a chat with no ``project_id`` → 404 (no matter
    KB to reference into)."""

    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, project_id=None, title="projectless")
    db_session.add(chat)
    await db_session.flush()

    resp = await client.post(
        f"/api/v1/chats/{chat.id}/messages",
        headers=_h(user),
        json={
            "content": "hi",
            "model": "smart",
            "referenced_file_ids": [str(uuid.uuid4())],
        },
    )
    assert resp.status_code == 404, resp.text


@respx.mock
async def test_send_without_referenced_ids_is_backcompat_noop(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST without ``referenced_file_ids`` → 200,
    ``applied_referenced_file_ids == []``, and NO
    ``inference.message_referenced_files`` audit row."""

    user, chat, _file_row, _document, _chunk = await _seed_chat_with_referenced_file(db_session)

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload("plain reply")),
    )

    with patch(
        "app.api.chats._retrieve_kb_context_for_chat",
        new=AsyncMock(return_value=([], [], None)),
    ):
        resp = await client.post(
            f"/api/v1/chats/{chat.id}/messages",
            headers=_h(user),
            json={"content": "hello", "model": "smart"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["applied_referenced_file_ids"] == []

    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "inference.message_referenced_files")
            )
        )
        .scalars()
        .all()
    )
    assert rows == []
