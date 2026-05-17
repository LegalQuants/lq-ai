"""Chat-send → message_citations end-to-end — M2-A2 Stage 1.

Exercises the integration the M2 plan calls out in its M2-A2
verification step: a chat with retrieved-chunk context, an assistant
response that quotes a chunk verbatim followed by ``(Source: [N])``,
and a ``message_citations`` row landing with ``verified=True``,
``verification_method='exact_match'``, ``verification_confidence=1.0``.

The fixture set mirrors ``test_chat_rag.py`` (same gateway-mock +
hybrid_search-patch pattern) but adds real ``Document`` /
``File`` / chunk rows so the citation's FK constraints resolve and
the verifier has real ``normalized_content`` to slice against.

Negative cases:

* The model returns a paraphrase (not byte-for-byte): no row written
  (Stage 1 drops; Stage 2 will catch when M2-B1 ships).
* The model returns prose without any ``(Source: [N])`` marker:
  no row written.
* The model cites an out-of-range chunk index: no row written.
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

from app.clients.gateway import GatewayClient, set_gateway_client
from app.db.session import get_db
from app.main import app
from app.models.chat import Chat, MessageCitation
from app.models.document import Document, DocumentChunk
from app.models.file import File as FileModel
from app.models.knowledge import KnowledgeBase
from app.models.project import Project
from app.models.project_knowledge_base import ProjectKnowledgeBase
from app.models.user import User
from app.security import create_access_token, hash_password

pytestmark = pytest.mark.integration

GATEWAY_BASE = "http://test-gateway"
GATEWAY_KEY = "test-gw-key"


# ---------------------------------------------------------------------------
# Boilerplate fixtures — match test_chat_rag.py's pattern
# ---------------------------------------------------------------------------


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
        email=f"cite-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Citation Test Owner",
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
        name="Citation matter",
        slug=f"cite-matter-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(project)
    await db_session.flush()
    return project


@pytest_asyncio.fixture
async def kb_for_owner(db_session: AsyncSession, owner_user: User) -> KnowledgeBase:
    kb = KnowledgeBase(
        owner_id=owner_user.id,
        name="Citation KB",
        description="Used for M2-A2 chat-citation tests",
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
    junction = ProjectKnowledgeBase(
        project_id=project_for_owner.id,
        knowledge_base_id=kb_for_owner.id,
    )
    db_session.add(junction)
    chat = Chat(
        owner_id=owner_user.id,
        project_id=project_for_owner.id,
        title="cite-chat-test",
    )
    db_session.add(chat)
    await db_session.flush()
    return chat


# ---------------------------------------------------------------------------
# Real File + Document + chunk so FKs resolve and the verifier has text
# ---------------------------------------------------------------------------


CHUNK_BODY = (
    "The non-compete clause provides that the employee shall not engage "
    "in any competing business for a period of two years following "
    "termination of employment."
)


@pytest_asyncio.fixture
async def source_file(db_session: AsyncSession, owner_user: User) -> FileModel:
    f = FileModel(
        owner_id=owner_user.id,
        filename="nda-template.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        hash_sha256="b" * 64,
        storage_path=f"cite-fixture/{uuid.uuid4()}",
        ingestion_status="ready",
    )
    db_session.add(f)
    await db_session.flush()
    return f


@pytest_asyncio.fixture
async def source_document(db_session: AsyncSession, source_file: FileModel) -> Document:
    doc = Document(
        file_id=source_file.id,
        parser="pymupdf-only",
        parser_version="pymupdf=1.27",
        page_count=1,
        character_count=len(CHUNK_BODY),
        normalized_content=CHUNK_BODY,
        was_ocrd=False,
    )
    db_session.add(doc)
    await db_session.flush()
    return doc


@pytest_asyncio.fixture
async def source_chunk(db_session: AsyncSession, source_document: Document) -> DocumentChunk:
    chunk = DocumentChunk(
        document_id=source_document.id,
        chunk_index=0,
        content=CHUNK_BODY,
        page_start=1,
        page_end=1,
        char_offset_start=0,
        char_offset_end=len(CHUNK_BODY),
    )
    db_session.add(chunk)
    await db_session.flush()
    return chunk


def _bearer(user: User) -> str:
    return create_access_token(user.id, user.email, is_admin=user.is_admin)


def _h(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {_bearer(user)}"}


def _success_payload(content: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-cite",
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


def _hybrid_result_for(
    chunk: DocumentChunk,
    document: Document,
    file: FileModel,
    *,
    score: float = 0.9,
) -> Any:
    """Build a HybridSearchResult-shaped stand-in pointing at the real fixture rows."""

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
            self.vector_score = score
            self.fts_score = score
            self.hybrid_score = score

    return _R()


# ---------------------------------------------------------------------------
# 1. Verbatim quote with (Source: [1]) → message_citations row, verified=True
# ---------------------------------------------------------------------------


@respx.mock
async def test_chat_send_persists_verified_citation_from_verbatim_quote(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    chat_with_kb_attached: Chat,
    source_file: FileModel,
    source_document: Document,
    source_chunk: DocumentChunk,
) -> None:
    """An assistant response with a verbatim quote + (Source: [1]) writes
    a verified citation row pointing at the right file / offsets / page."""

    quote = "the employee shall not engage in any competing business"
    # Sanity: the quote is a real substring of the chunk we'll feed back.
    assert quote in source_chunk.content

    assistant_text = (
        f'The agreement states "{quote}" (Source: [1]). This is a two-year non-compete.'
    )

    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload(assistant_text)),
    )

    with patch(
        "app.api.chats.hybrid_search",
        new=AsyncMock(
            return_value=[_hybrid_result_for(source_chunk, source_document, source_file)]
        ),
    ):
        response = await client.post(
            f"/api/v1/chats/{chat_with_kb_attached.id}/messages",
            json={"content": "Quote the non-compete clause.", "model": "smart"},
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text
    assert route.called

    rows = (
        (
            await db_session.execute(
                select(MessageCitation).where(MessageCitation.source_file_id == source_file.id)
            )
        )
        .scalars()
        .all()
    )

    assert len(rows) == 1, f"expected exactly one citation, got {len(rows)}"
    cite = rows[0]
    assert cite.verified is True
    assert cite.verification_method == "exact_match"
    assert cite.verification_confidence is not None
    assert float(cite.verification_confidence) == 1.0
    assert cite.source_text == quote
    assert cite.source_page == 1
    # Offsets correspond to the position inside the chunk + the chunk's
    # char_offset_start (which is 0 in this fixture).
    expected_start = CHUNK_BODY.find(quote)
    assert cite.source_offset_start == expected_start
    assert cite.source_offset_end == expected_start + len(quote)


# ---------------------------------------------------------------------------
# M2-B1 — Stage 2 (tolerant-match) covers smart quotes + whitespace drift
# ---------------------------------------------------------------------------


@respx.mock
async def test_chat_send_whitespace_drift_quote_passes_tolerant_match(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    chat_with_kb_attached: Chat,
) -> None:
    """A model quote with whitespace drift passes Stage 2 (tolerant-match).

    Source chunk has double spaces; model normalizes them to single
    spaces when quoting. Stage 1 fails (byte-precise slice carries the
    double space; model's source_text has the single-space version);
    extraction's rapidfuzz alignment fallback still locates the span,
    so Stage 2 runs and the normalized fuzz ratio passes.
    """

    body = "the employee  shall not  engage in any competing  business for two years."
    drifted_quote = "the employee shall not engage in any competing business for two years."

    # Fresh fixtures so the chunk content has the whitespace-drift body
    # (avoids changing CHUNK_BODY used by other tests).
    file_row = FileModel(
        owner_id=owner_user.id,
        filename="nda-template-double-space.pdf",
        mime_type="application/pdf",
        size_bytes=2048,
        hash_sha256="c" * 64,
        storage_path=f"cite-fixture/{uuid.uuid4()}",
        ingestion_status="ready",
    )
    db_session.add(file_row)
    await db_session.flush()

    doc = Document(
        file_id=file_row.id,
        parser="pymupdf-only",
        parser_version="pymupdf=1.27",
        page_count=1,
        character_count=len(body),
        normalized_content=body,
        was_ocrd=False,
    )
    db_session.add(doc)
    await db_session.flush()

    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content=body,
        page_start=1,
        page_end=1,
        char_offset_start=0,
        char_offset_end=len(body),
    )
    db_session.add(chunk)
    await db_session.flush()

    assistant_text = f'The agreement states "{drifted_quote}" (Source: [1]).'

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload(assistant_text)),
    )

    with patch(
        "app.api.chats.hybrid_search",
        new=AsyncMock(return_value=[_hybrid_result_for(chunk, doc, file_row)]),
    ):
        response = await client.post(
            f"/api/v1/chats/{chat_with_kb_attached.id}/messages",
            json={"content": "Quote the non-compete clause.", "model": "smart"},
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text

    rows = (
        (
            await db_session.execute(
                select(MessageCitation).where(MessageCitation.source_file_id == file_row.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    cite = rows[0]
    assert cite.verified is True
    assert cite.verification_method == "tolerant_match"
    assert cite.verification_confidence is not None
    assert float(cite.verification_confidence) >= 0.95


# ---------------------------------------------------------------------------
# 2. Paraphrased quote → no citation row (Stages 1+2 reject; Stage 3 will catch)
# ---------------------------------------------------------------------------


@respx.mock
async def test_chat_send_paraphrased_quote_writes_no_citation(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    chat_with_kb_attached: Chat,
    source_file: FileModel,
    source_document: Document,
    source_chunk: DocumentChunk,
) -> None:
    """A paraphrased quote (not byte-for-byte) is dropped by Stage 1."""

    # Note: the chunk body says "shall not engage" — this paraphrase
    # changes it to "may not engage", so the byte-for-byte search fails.
    paraphrase = "the employee may not engage in any competing business"
    assert paraphrase not in source_chunk.content

    assistant_text = f'The agreement says "{paraphrase}" (Source: [1]).'

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload(assistant_text)),
    )

    with patch(
        "app.api.chats.hybrid_search",
        new=AsyncMock(
            return_value=[_hybrid_result_for(source_chunk, source_document, source_file)]
        ),
    ):
        response = await client.post(
            f"/api/v1/chats/{chat_with_kb_attached.id}/messages",
            json={"content": "Quote the non-compete clause.", "model": "smart"},
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text

    rows = (await db_session.execute(select(MessageCitation))).scalars().all()
    assert rows == []


# ---------------------------------------------------------------------------
# 3. No (Source: [N]) marker → no citation row
# ---------------------------------------------------------------------------


@respx.mock
async def test_chat_send_unmarked_quote_writes_no_citation(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    chat_with_kb_attached: Chat,
    source_file: FileModel,
    source_document: Document,
    source_chunk: DocumentChunk,
) -> None:
    """A quote without `(Source: [N])` is not a citation."""

    quote = "the employee shall not engage in any competing business"
    assistant_text = f'The agreement says "{quote}", but I cited nothing.'

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload(assistant_text)),
    )

    with patch(
        "app.api.chats.hybrid_search",
        new=AsyncMock(
            return_value=[_hybrid_result_for(source_chunk, source_document, source_file)]
        ),
    ):
        response = await client.post(
            f"/api/v1/chats/{chat_with_kb_attached.id}/messages",
            json={"content": "Quote the non-compete clause.", "model": "smart"},
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text

    rows = (await db_session.execute(select(MessageCitation))).scalars().all()
    assert rows == []


# ---------------------------------------------------------------------------
# 4. Out-of-range source index → no citation row
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_citations_endpoint_returns_persisted_rows(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    chat_with_kb_attached: Chat,
    source_file: FileModel,
    source_document: Document,
    source_chunk: DocumentChunk,
) -> None:
    """`GET /chats/{id}/messages/{mid}/citations` returns the structured rows."""

    quote = "the employee shall not engage in any competing business"
    assistant_text = f'The agreement states "{quote}" (Source: [1]).'

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload(assistant_text)),
    )

    with patch(
        "app.api.chats.hybrid_search",
        new=AsyncMock(
            return_value=[_hybrid_result_for(source_chunk, source_document, source_file)]
        ),
    ):
        send = await client.post(
            f"/api/v1/chats/{chat_with_kb_attached.id}/messages",
            json={"content": "Quote it.", "model": "smart"},
            headers=_h(owner_user),
        )
    assert send.status_code == 200, send.text

    message_id = send.json()["message"]["id"]

    get_response = await client.get(
        f"/api/v1/chats/{chat_with_kb_attached.id}/messages/{message_id}/citations",
        headers=_h(owner_user),
    )
    assert get_response.status_code == 200, get_response.text
    body = get_response.json()
    assert isinstance(body, list)
    assert len(body) == 1
    cite = body[0]
    assert cite["source_file_id"] == str(source_file.id)
    assert cite["source_text"] == quote
    assert cite["verified"] is True
    assert cite["verification_method"] == "exact_match"
    assert cite["verification_confidence"] == 1.0
    assert cite["partial"] is False
    assert cite["source_page"] == 1
    expected_start = CHUNK_BODY.find(quote)
    assert cite["source_offset_start"] == expected_start
    assert cite["source_offset_end"] == expected_start + len(quote)


@respx.mock
async def test_chat_send_out_of_range_source_writes_no_citation(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    chat_with_kb_attached: Chat,
    source_file: FileModel,
    source_document: Document,
    source_chunk: DocumentChunk,
) -> None:
    """`(Source: [99])` against one retrieved chunk is dropped."""

    quote = "the employee shall not engage"
    assistant_text = f'It says "{quote}" (Source: [99]).'

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload(assistant_text)),
    )

    with patch(
        "app.api.chats.hybrid_search",
        new=AsyncMock(
            return_value=[_hybrid_result_for(source_chunk, source_document, source_file)]
        ),
    ):
        response = await client.post(
            f"/api/v1/chats/{chat_with_kb_attached.id}/messages",
            json={"content": "Quote the non-compete clause.", "model": "smart"},
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text

    rows = (await db_session.execute(select(MessageCitation))).scalars().all()
    assert rows == []


# ---------------------------------------------------------------------------
# M2-C1 — Stage 3 (paraphrase judge) catches paraphrases Stages 1+2 miss
# ---------------------------------------------------------------------------


def _judge_response_payload(*, verdict: str, confidence: str) -> dict[str, Any]:
    """A chat.completion payload whose content is a judge JSON verdict."""

    import json as _json

    judge_content = _json.dumps(
        {
            "verdict": verdict,
            "confidence": confidence,
            "justification": "test justification",
        }
    )
    return _success_payload(judge_content)


@respx.mock
async def test_chat_send_paraphrased_quote_verified_by_stage_3_judge(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    chat_with_kb_attached: Chat,
    source_file: FileModel,
    source_document: Document,
    source_chunk: DocumentChunk,
) -> None:
    """Paraphrased quote misses Stages 1+2; Stage 3 judge says 'yes/high' → verified.

    Wire path: the gateway client makes two calls per message —
    (a) the assistant chat completion, then
    (b) the Stage 3 judge chat completion when Stages 1+2 miss.
    Both hit ``/v1/chat/completions``; we sequence the responses with
    respx ``side_effect``.
    """

    paraphrase = "the employee may not engage in any competing business"
    assert paraphrase not in source_chunk.content  # genuine paraphrase

    assistant_text = f'The agreement says "{paraphrase}" (Source: [1]).'

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(200, json=_success_payload(assistant_text)),
            httpx.Response(200, json=_judge_response_payload(verdict="yes", confidence="high")),
        ]
    )

    with patch(
        "app.api.chats.hybrid_search",
        new=AsyncMock(
            return_value=[_hybrid_result_for(source_chunk, source_document, source_file)]
        ),
    ):
        response = await client.post(
            f"/api/v1/chats/{chat_with_kb_attached.id}/messages",
            json={"content": "Quote the non-compete clause.", "model": "smart"},
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text

    rows = (
        (
            await db_session.execute(
                select(MessageCitation).where(MessageCitation.source_file_id == source_file.id)
            )
        )
        .scalars()
        .all()
    )

    assert len(rows) == 1
    cite = rows[0]
    assert cite.verified is True
    assert cite.verification_method == "paraphrase_judge"
    assert cite.verification_confidence is not None
    assert float(cite.verification_confidence) == pytest.approx(0.90)
    assert cite.partial is False
    assert cite.source_text == paraphrase


@respx.mock
async def test_chat_send_partial_verdict_persists_with_partial_true(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    chat_with_kb_attached: Chat,
    source_file: FileModel,
    source_document: Document,
    source_chunk: DocumentChunk,
) -> None:
    """'partial' verdict persists as verified=True, partial=True (M2-C2 UI flag)."""

    paraphrase = "the employee may not engage in any competing business"
    assistant_text = f'The agreement says "{paraphrase}" (Source: [1]).'

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(200, json=_success_payload(assistant_text)),
            httpx.Response(
                200,
                json=_judge_response_payload(verdict="partial", confidence="medium"),
            ),
        ]
    )

    with patch(
        "app.api.chats.hybrid_search",
        new=AsyncMock(
            return_value=[_hybrid_result_for(source_chunk, source_document, source_file)]
        ),
    ):
        response = await client.post(
            f"/api/v1/chats/{chat_with_kb_attached.id}/messages",
            json={"content": "Quote the non-compete clause.", "model": "smart"},
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text

    rows = (await db_session.execute(select(MessageCitation))).scalars().all()
    assert len(rows) == 1
    cite = rows[0]
    assert cite.verified is True
    assert cite.partial is True
    assert cite.verification_method == "paraphrase_judge"
    assert float(cite.verification_confidence or 0) == pytest.approx(0.70)


@respx.mock
async def test_get_citations_endpoint_exposes_partial_flag(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    chat_with_kb_attached: Chat,
    source_file: FileModel,
    source_document: Document,
    source_chunk: DocumentChunk,
) -> None:
    """`GET /messages/{id}/citations` surfaces `partial=True` for partial verdicts (M2-C2)."""

    paraphrase = "the employee may not engage in any competing business"
    assistant_text = f'The agreement says "{paraphrase}" (Source: [1]).'

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(200, json=_success_payload(assistant_text)),
            httpx.Response(
                200,
                json=_judge_response_payload(verdict="partial", confidence="medium"),
            ),
        ]
    )

    with patch(
        "app.api.chats.hybrid_search",
        new=AsyncMock(
            return_value=[_hybrid_result_for(source_chunk, source_document, source_file)]
        ),
    ):
        send = await client.post(
            f"/api/v1/chats/{chat_with_kb_attached.id}/messages",
            json={"content": "Quote the non-compete clause.", "model": "smart"},
            headers=_h(owner_user),
        )
    assert send.status_code == 200, send.text
    message_id = send.json()["message"]["id"]

    get_response = await client.get(
        f"/api/v1/chats/{chat_with_kb_attached.id}/messages/{message_id}/citations",
        headers=_h(owner_user),
    )
    assert get_response.status_code == 200, get_response.text
    body = get_response.json()
    assert len(body) == 1
    cite = body[0]
    assert cite["verified"] is True
    assert cite["partial"] is True
    assert cite["verification_method"] == "paraphrase_judge"
    assert cite["verification_confidence"] == pytest.approx(0.70)


@respx.mock
async def test_chat_send_judge_says_no_writes_no_citation(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    chat_with_kb_attached: Chat,
    source_file: FileModel,
    source_document: Document,
    source_chunk: DocumentChunk,
) -> None:
    """'no' verdict → no citation row (rendered as unverified by M2-C2)."""

    paraphrase = "the employee may not engage in any competing business"
    assistant_text = f'The agreement says "{paraphrase}" (Source: [1]).'

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(200, json=_success_payload(assistant_text)),
            httpx.Response(200, json=_judge_response_payload(verdict="no", confidence="high")),
        ]
    )

    with patch(
        "app.api.chats.hybrid_search",
        new=AsyncMock(
            return_value=[_hybrid_result_for(source_chunk, source_document, source_file)]
        ),
    ):
        response = await client.post(
            f"/api/v1/chats/{chat_with_kb_attached.id}/messages",
            json={"content": "Quote the non-compete clause.", "model": "smart"},
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text

    rows = (await db_session.execute(select(MessageCitation))).scalars().all()
    assert rows == []


# ---------------------------------------------------------------------------
# M2-D2 — Citation Engine x Anonymization integration
# ---------------------------------------------------------------------------


@respx.mock
async def test_chat_send_marks_retrieval_context_skip_anonymization(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    chat_with_kb_attached: Chat,
    source_file: FileModel,
    source_document: Document,
    source_chunk: DocumentChunk,
) -> None:
    """M2-D2 / Decision M2-1: retrieved source documents are NOT pseudonymized.

    The api/ marks the retrieval-context system message with
    ``lq_ai_skip_anonymization=True`` so the gateway middleware
    leaves the chunk text untouched. The model needs intact source
    quotes for citation grounding; pseudonymizing the retrieval
    would make the model see ``PERSON_0001 agreed to ...`` and
    produce citations the post-rehydrator must repair, polluting
    the audit trail.

    This test pins the api-side contract: the flag is set on the
    retrieval message and ONLY on that message (user turn flag
    stays default-False so the gateway middleware pseudonymizes
    chat content as usual when anonymization is active).
    """

    import json as _stdlib_json

    assistant_text = '"the employee shall not engage in any competing business" (Source: [1])'

    captured_requests: list[dict[str, Any]] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        captured_requests.append(_stdlib_json.loads(request.content))
        return httpx.Response(200, json=_success_payload(assistant_text))

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(side_effect=_capture)

    with patch(
        "app.api.chats.hybrid_search",
        new=AsyncMock(
            return_value=[_hybrid_result_for(source_chunk, source_document, source_file)]
        ),
    ):
        response = await client.post(
            f"/api/v1/chats/{chat_with_kb_attached.id}/messages",
            json={"content": "Quote the non-compete clause.", "model": "smart"},
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text
    assert len(captured_requests) == 1
    sent = captured_requests[0]

    # The api/ injects a system message with the retrieval context as
    # the first messages-array entry. Confirm it carries the skip
    # marker.
    system_msgs = [m for m in sent["messages"] if m.get("role") == "system"]
    assert len(system_msgs) >= 1, "expected at least one system message (retrieval context)"
    retrieval_msg = system_msgs[0]
    assert "Retrieved context" in retrieval_msg.get("content", ""), (
        "first system message should be the retrieval context block"
    )
    assert retrieval_msg.get("lq_ai_skip_anonymization") is True, (
        "retrieval context system message must opt out of anonymization per M2-D2"
    )

    # The user turn must NOT carry the skip flag — its content is
    # subject to anonymization when the middleware is active.
    user_msgs = [m for m in sent["messages"] if m.get("role") == "user"]
    assert len(user_msgs) >= 1
    for msg in user_msgs:
        assert msg.get("lq_ai_skip_anonymization", False) is False, (
            "user turn must not opt out of anonymization"
        )


# ---------------------------------------------------------------------------
# M2-D3 — Privileged-project handling (verification + audit trail)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def privileged_project_for_owner(db_session: AsyncSession, owner_user: User) -> Project:
    """A privileged project — anonymization middleware skips its chats.

    The CHECK ``chk_projects_privileged_implies_tier`` requires a
    non-NULL ``minimum_inference_tier`` when ``privileged=True``;
    Tier 2 is the typical posture for privileged matters per PRD §5.3
    (local Tier 1 preferred where possible; Tier 2 allows enterprise-
    ZDR upstreams when local capacity is insufficient).
    """

    project = Project(
        owner_id=owner_user.id,
        name="Privileged matter (Smith v Acme)",
        slug=f"privileged-{uuid.uuid4().hex[:8]}",
        privileged=True,
        minimum_inference_tier=2,
    )
    db_session.add(project)
    await db_session.flush()
    return project


@pytest_asyncio.fixture
async def privileged_chat_with_kb(
    db_session: AsyncSession,
    owner_user: User,
    privileged_project_for_owner: Project,
    kb_for_owner: KnowledgeBase,
) -> Chat:
    """A chat inside a privileged project, with a KB attached.

    Combines the M2-D3 privileged-handling path with the Citation
    Engine retrieval path so a single end-to-end test can pin both
    behaviors at once.
    """

    junction = ProjectKnowledgeBase(
        project_id=privileged_project_for_owner.id,
        knowledge_base_id=kb_for_owner.id,
    )
    db_session.add(junction)
    chat = Chat(
        owner_id=owner_user.id,
        project_id=privileged_project_for_owner.id,
        title="privileged-chat-test",
    )
    db_session.add(chat)
    await db_session.flush()
    return chat


@respx.mock
async def test_chat_send_privileged_project_full_audit_trail(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    privileged_project_for_owner: Project,
    privileged_chat_with_kb: Chat,
    source_file: FileModel,
    source_document: Document,
    source_chunk: DocumentChunk,
) -> None:
    """M2-D3: a chat in a privileged project produces a clean audit trail.

    Three invariants pinned by this test:

    1. **Gateway request carries the privilege signal.** The api/
       reads ``Project.privileged`` and forwards
       ``lq_ai_privileged=True`` + ``lq_ai_project_minimum_inference_tier=2``
       so the gateway middleware can skip pseudonymization and the
       tier-floor enforcement applies.
    2. **audit_log row marks the action privileged.** The
       ``audit_action`` helper resolves the project's privilege flag
       and writes ``privilege_marked=True`` + ``privilege_basis``
       containing the project name on the ``chat.message_sent`` row.
    3. **Citation Engine operates normally.** No special path for
       privileged projects on the citation verification side; the
       verbatim quote is verified and persisted exactly as for a
       non-privileged chat.

    The gateway-side invariants (middleware skip + provider receives
    un-pseudonymized content + ``routing_log.anonymization_applied=False``)
    are covered by ``gateway/tests/test_inference_anonymization.py::
    test_privileged_request_skips_middleware``; this test pins the
    api-side contract feeding into that gateway behavior.
    """

    import json as _stdlib_json

    quote = "the employee shall not engage in any competing business"
    assert quote in source_chunk.content
    assistant_text = (
        f'Per the agreement, "{quote}" (Source: [1]). This is a privileged matter context.'
    )

    captured_requests: list[dict[str, Any]] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        captured_requests.append(_stdlib_json.loads(request.content))
        return httpx.Response(200, json=_success_payload(assistant_text))

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(side_effect=_capture)

    with patch(
        "app.api.chats.hybrid_search",
        new=AsyncMock(
            return_value=[_hybrid_result_for(source_chunk, source_document, source_file)]
        ),
    ):
        response = await client.post(
            f"/api/v1/chats/{privileged_chat_with_kb.id}/messages",
            json={"content": "What does the non-compete say?", "model": "smart"},
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text
    assert len(captured_requests) == 1
    sent = captured_requests[0]

    # Invariant 1: privilege signal reaches the gateway.
    assert sent.get("lq_ai_privileged") is True, (
        "privileged chats must forward lq_ai_privileged=True so the gateway "
        "middleware can skip pseudonymization"
    )
    assert sent.get("lq_ai_project_minimum_inference_tier") == 2, (
        "privileged projects forward their tier floor so the gateway can enforce it"
    )

    # Invariant 2: audit_log row marks the chat-message-sent action privileged.
    from app.models.audit import AuditLog

    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.user_id == owner_user.id,
                    AuditLog.action == "chat.message_sent",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1, f"expected one chat.message_sent row, got {len(audit_rows)}"
    row = audit_rows[0]
    assert row.privilege_marked is True, "privileged-project actions must be marked"
    assert row.privilege_basis is not None
    assert privileged_project_for_owner.name in row.privilege_basis, (
        f"privilege_basis should name the project; got {row.privilege_basis!r}"
    )
    assert row.routed_inference_tier == 3, (
        "routed_inference_tier should mirror the gateway response's tier"
    )

    # Invariant 3: Citation Engine operates normally — no special path
    # for privileged projects. The verbatim quote verified via Stage 1
    # exactly as for a non-privileged chat.
    citation_rows = (
        (
            await db_session.execute(
                select(MessageCitation).where(MessageCitation.source_file_id == source_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(citation_rows) == 1, (
        f"Citation Engine must operate normally for privileged chats; got {len(citation_rows)} rows"
    )
    cite = citation_rows[0]
    assert cite.verified is True
    assert cite.verification_method == "exact_match"
    assert cite.source_text == quote
