"""Citation Engine edge cases — M2-D4 sweep.

Per docs/M2-IMPLEMENTATION-PLAN.md §M2-D4, this file pins regression
tests for the citation-engine-side edge cases the M2 plan calls out:

* **Chunk boundary citations** — citation source slice spans the boundary
  between two adjacent chunks. The verifier reads from
  ``documents.normalized_content`` (un-chunked), so chunk boundaries
  are not directly visible to the verifier — but a citation whose
  source_text was assembled by concatenating across-chunk text must
  still verify cleanly against the underlying document slice.
* **Empty source documents** — a document with an empty
  ``normalized_content`` and a citation with offsets pointing into it
  must fall through to MISS gracefully (no crash, no row written).
* **Cross-document citations** — a message that cites multiple source
  documents must verify each independently and persist one row per
  successfully-verified citation.
* **Failed retrieval / deleted source_file_id** — a citation whose
  source_file_id no longer exists at verification time must be
  handled defensively (no crash; no row persists — the M2-C2 UI
  renders the absence as "unverified"; the M2-C2 Decision H deferred
  state-5 system-error rendering to a future task tracked in DE-275).

The integration test (``test_chat_send_*`` variants) drives the full
chat-send pipeline; pure-cascade tests live alongside
:mod:`tests.citation.test_verify_cascade` and exercise
:func:`app.citation.verification.verify` directly with stubs.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.verification import (
    VerificationResult,
    verify,
    verify_exact_match,
)
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

GATEWAY_BASE = "http://test-gateway"
GATEWAY_KEY = "test-gw-key"


# ---------------------------------------------------------------------------
# Unit-level stubs (mirror test_paraphrase_judge.py shape)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _StubDocument:
    id: uuid.UUID
    normalized_content: str
    was_ocrd: bool = False


@dataclass(slots=True)
class _StubCandidate:
    source_file_id: uuid.UUID
    source_document_id: uuid.UUID
    source_offset_start: int
    source_offset_end: int
    source_page: int | None
    source_text: str


# ---------------------------------------------------------------------------
# Unit tests — verify() against the cascade with edge-case inputs
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_verify_exact_match_against_empty_normalized_content() -> None:
    """Stage 1 on a document with empty ``normalized_content`` returns MISS.

    Defensive: the ``_slice_in_range`` guard catches any positive
    offset against a zero-length document and short-circuits. Without
    this guard, ``content[start:end]`` on an empty string would return
    ``""`` and the equality check against a non-empty ``source_text``
    would fail naturally — but we still want explicit MISS rather than
    relying on the equality coincidence.
    """

    doc = _StubDocument(id=uuid.uuid4(), normalized_content="")
    cand = _StubCandidate(
        source_file_id=uuid.uuid4(),
        source_document_id=doc.id,
        source_offset_start=0,
        source_offset_end=10,
        source_page=None,
        source_text="something",
    )

    result = verify_exact_match(cand, doc)

    assert result.verified is False
    assert result.method is None


@pytest.mark.unit
async def test_verify_cascade_against_empty_normalized_content_no_crash() -> None:
    """Full cascade against an empty document falls through to MISS cleanly.

    Stages 1 + 2 short-circuit on the range guard; Stage 3 / 4 are
    not reached because ``gateway=None`` short-circuits past them.
    The contract is "no crash on degenerate document"; the assertion
    is just that we get a MISS result back.
    """

    doc = _StubDocument(id=uuid.uuid4(), normalized_content="")
    cand = _StubCandidate(
        source_file_id=uuid.uuid4(),
        source_document_id=doc.id,
        source_offset_start=0,
        source_offset_end=5,
        source_page=None,
        source_text="hello",
    )

    result = await verify(cand, doc, gateway=None)

    assert result == VerificationResult(
        verified=False, method=None, confidence=None, partial=False, tier_envelope=None
    )


@pytest.mark.unit
def test_verify_exact_match_offsets_span_chunk_boundary_within_document() -> None:
    """A citation whose offsets straddle a (logical) chunk boundary verifies.

    The verifier reads from ``documents.normalized_content`` directly,
    not from chunks — chunks are only used by retrieval. So a citation
    whose source span happens to cross the boundary between two
    retrieved chunks still verifies cleanly as long as the underlying
    document text at those offsets matches the ``source_text``.

    This test simulates the scenario: a 100-char document split into
    two chunks at offset 50; the citation spans offsets [40, 70]
    crossing the boundary. The verifier reads ``content[40:70]`` and
    compares against the candidate's ``source_text``.
    """

    content = "A" * 50 + "B" * 50  # 100-char document
    doc = _StubDocument(id=uuid.uuid4(), normalized_content=content)
    # Citation spans [40, 70] — straddles the 50-char "boundary"
    cand = _StubCandidate(
        source_file_id=uuid.uuid4(),
        source_document_id=doc.id,
        source_offset_start=40,
        source_offset_end=70,
        source_page=None,
        source_text="A" * 10 + "B" * 20,
    )

    result = verify_exact_match(cand, doc)

    assert result.verified is True
    assert result.method == "exact_match"


# ---------------------------------------------------------------------------
# Integration tests — full chat-send pipeline with edge-case fixtures
# ---------------------------------------------------------------------------


pytestmark = pytest.mark.integration


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
        email=f"edge-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Edge Cases Owner",
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
        name="Edge cases matter",
        slug=f"edge-matter-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(project)
    await db_session.flush()
    return project


@pytest_asyncio.fixture
async def kb_for_owner(db_session: AsyncSession, owner_user: User) -> KnowledgeBase:
    kb = KnowledgeBase(
        owner_id=owner_user.id,
        name="Edge KB",
        description="Edge-case integration tests",
        hybrid_alpha=1.0,
    )
    db_session.add(kb)
    await db_session.flush()
    return kb


@pytest_asyncio.fixture
async def chat_with_kb(
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
        title="edge-cases-test",
    )
    db_session.add(chat)
    await db_session.flush()
    return chat


async def _make_file_doc_chunk(
    db_session: AsyncSession,
    *,
    owner: User,
    content: str,
    filename: str,
) -> tuple[FileModel, Document, DocumentChunk]:
    f = FileModel(
        owner_id=owner.id,
        filename=filename,
        mime_type="application/pdf",
        size_bytes=1024,
        hash_sha256="b" * 64,
        storage_path=f"edge-fixture/{uuid.uuid4()}",
        ingestion_status="ready",
    )
    db_session.add(f)
    await db_session.flush()

    doc = Document(
        file_id=f.id,
        parser="pymupdf-only",
        parser_version="pymupdf=1.27",
        page_count=1,
        character_count=len(content),
        normalized_content=content,
        was_ocrd=False,
    )
    db_session.add(doc)
    await db_session.flush()

    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content=content,
        page_start=1,
        page_end=1,
        char_offset_start=0,
        char_offset_end=len(content),
    )
    db_session.add(chunk)
    await db_session.flush()
    return f, doc, chunk


def _hybrid_result_for(
    chunk: DocumentChunk,
    document: Document,
    file: FileModel,
    *,
    score: float = 0.9,
) -> Any:
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


def _bearer(user: User) -> str:
    return create_access_token(user.id, user.email, is_admin=user.is_admin)


def _h(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {_bearer(user)}"}


def _success_payload(content: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-edge",
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


@respx.mock
async def test_cross_document_citations_persist_one_row_per_verified_citation(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    chat_with_kb: Chat,
) -> None:
    """Citations from N different source documents persist N independent rows.

    The persist_citations loop batch-loads all referenced documents
    in one SELECT then verifies each candidate against its own
    document. This test confirms cross-document independence: a
    message that cites two distinct files lands two citation rows,
    each pointing at the right ``source_file_id``.
    """

    content_a = "Document A contains the alpha clause."
    content_b = "Document B contains the beta clause."

    file_a, doc_a, chunk_a = await _make_file_doc_chunk(
        db_session, owner=owner_user, content=content_a, filename="doc-a.pdf"
    )
    file_b, doc_b, chunk_b = await _make_file_doc_chunk(
        db_session, owner=owner_user, content=content_b, filename="doc-b.pdf"
    )

    quote_a = "the alpha clause"
    quote_b = "the beta clause"
    assistant_text = f'Per doc A: "{quote_a}" (Source: [1]). Per doc B: "{quote_b}" (Source: [2]).'

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload(assistant_text))
    )

    with patch(
        "app.api.chats.hybrid_search",
        new=AsyncMock(
            return_value=[
                _hybrid_result_for(chunk_a, doc_a, file_a),
                _hybrid_result_for(chunk_b, doc_b, file_b),
            ]
        ),
    ):
        response = await client.post(
            f"/api/v1/chats/{chat_with_kb.id}/messages",
            json={"content": "Quote both clauses.", "model": "smart"},
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text

    rows = (
        (
            await db_session.execute(
                select(MessageCitation).where(
                    MessageCitation.source_file_id.in_([file_a.id, file_b.id])
                )
            )
        )
        .scalars()
        .all()
    )

    assert len(rows) == 2, f"expected one row per document, got {len(rows)}"
    by_file = {row.source_file_id: row for row in rows}
    assert by_file[file_a.id].source_text == quote_a
    assert by_file[file_a.id].verification_method == "exact_match"
    assert by_file[file_b.id].source_text == quote_b
    assert by_file[file_b.id].verification_method == "exact_match"


@respx.mock
async def test_chunk_boundary_spanning_citation_verifies_via_full_doc_scan(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    chat_with_kb: Chat,
) -> None:
    """M3-0.2 / DE-277: spanning quotes verify via the full-document fallback.

    Until DE-277 landed, the Citation Engine's extractor located each
    quote inside the cited chunk's content via
    :func:`app.citation.extraction._locate_in_chunk`. A quote spanning
    the boundary between two retrieved chunks — present in
    ``documents.normalized_content`` but in neither chunk individually —
    dropped silently and rendered as "unverified" in the UI.

    DE-277 extends the extractor: when the chunk-local locator misses,
    it retries against the chunk's parent document's
    ``normalized_content`` (M2-A1 surface) and emits the candidate
    with document-absolute offsets. The downstream verifier already
    reads against ``normalized_content`` so the spanning candidate
    verifies cleanly via the same Stage 1 / Stage 2 logic.

    This test pins the new behavior end-to-end: the spanning quote
    persists with ``verification_method='exact_match'`` and the
    persisted offsets are document-absolute.
    """

    full_content = (
        "Section 1: The non-compete clause provides for "
        "a two-year restriction on competing business."
    )
    file_, doc, _whole_chunk = await _make_file_doc_chunk(
        db_session, owner=owner_user, content=full_content, filename="span.pdf"
    )

    # Two adjacent half-chunks at indices 1 and 2 — together they
    # cover the full document, but neither alone contains the
    # spanning quote below.
    chunk_a = DocumentChunk(
        document_id=doc.id,
        chunk_index=1,
        content=full_content[:47],
        page_start=1,
        page_end=1,
        char_offset_start=0,
        char_offset_end=47,
    )
    chunk_b = DocumentChunk(
        document_id=doc.id,
        chunk_index=2,
        content=full_content[47:],
        page_start=1,
        page_end=1,
        char_offset_start=47,
        char_offset_end=len(full_content),
    )
    db_session.add_all([chunk_a, chunk_b])
    await db_session.flush()

    # Quote spans the chunk boundary at offset 47 — present in the
    # full document but in neither chunk alone.
    spanning_quote = full_content[30:60]
    assert spanning_quote not in chunk_a.content
    assert spanning_quote not in chunk_b.content
    assert spanning_quote in full_content

    assistant_text = f'The agreement says "{spanning_quote}" (Source: [1]).'

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload(assistant_text))
    )

    with patch(
        "app.api.chats.hybrid_search",
        new=AsyncMock(
            return_value=[
                _hybrid_result_for(chunk_a, doc, file_),
                _hybrid_result_for(chunk_b, doc, file_),
            ]
        ),
    ):
        response = await client.post(
            f"/api/v1/chats/{chat_with_kb.id}/messages",
            json={"content": "Quote a passage that spans chunks.", "model": "smart"},
            headers=_h(owner_user),
        )

    assert response.status_code == 200, response.text

    # DE-277 behavior: extractor falls back to the document-level scan,
    # the candidate verifies with byte-for-byte equality against
    # ``documents.normalized_content``, and one row persists with
    # document-absolute offsets and ``verification_method='exact_match'``.
    rows = (
        (
            await db_session.execute(
                select(MessageCitation).where(MessageCitation.source_file_id == file_.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, (
        f"Expected exactly one row from the DE-277 spanning fallback; got {len(rows)}."
    )
    row = rows[0]
    assert row.verification_method == "exact_match"
    assert row.verified is True
    assert row.source_offset_start == 30
    assert row.source_offset_end == 60
    assert row.source_text == spanning_quote


@respx.mock
async def test_deleted_source_file_handled_gracefully_no_row_written(
    client: AsyncClient,
    db_session: AsyncSession,
    owner_user: User,
    chat_with_kb: Chat,
) -> None:
    """Citation referencing a deleted document falls through with no crash.

    M2-C2 Decision H deferred the dedicated state-5 system-error UI
    rendering to a future task — the current behavior is "no row
    persisted, M2-C2 UI shows unverified red." This test pins that
    current behavior so a future implementation of state-5 has a
    failing test to flip.

    Scenario: hybrid_search returns a chunk pointing at a document
    that gets deleted before persist_citations runs. The verifier's
    batch-load returns no document for that id; the defensive guard
    at chats.py skips the candidate. The chat-send still returns 200
    (the assistant response is independent of citation persistence
    failures).
    """

    content = "The deleted document said something important."
    file_, doc, chunk = await _make_file_doc_chunk(
        db_session, owner=owner_user, content=content, filename="will-delete.pdf"
    )

    quote = "something important"
    assistant_text = f'The doc said "{quote}" (Source: [1]).'

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload(assistant_text))
    )

    # Stash references then delete the document right before the chat
    # send dispatches. The hybrid_search mock returns the now-stale
    # chunk reference; persist_citations will batch-load the document
    # and find nothing.
    deleted_doc_id = doc.id
    captured_chunk_data = _hybrid_result_for(chunk, doc, file_)

    async def _delete_doc_before_persist(*args: Any, **kwargs: Any) -> list[Any]:
        # Mimic the race: doc gets deleted between retrieval and
        # citation persistence.
        await db_session.execute(
            DocumentChunk.__table__.delete().where(DocumentChunk.document_id == deleted_doc_id)
        )
        await db_session.execute(Document.__table__.delete().where(Document.id == deleted_doc_id))
        await db_session.flush()
        return [captured_chunk_data]

    with patch("app.api.chats.hybrid_search", new=_delete_doc_before_persist):
        response = await client.post(
            f"/api/v1/chats/{chat_with_kb.id}/messages",
            json={"content": "Quote the deleted doc.", "model": "smart"},
            headers=_h(owner_user),
        )

    # Chat send still succeeds — citation persistence is best-effort.
    assert response.status_code == 200, response.text

    # No citation row persisted (defensive skip in persist_citations
    # because the referenced document no longer exists).
    rows = (await db_session.execute(select(MessageCitation))).scalars().all()
    assert rows == [], (
        f"Expected no rows for a deleted-document citation; got {len(rows)}. "
        "The M2-C2 UI renders the absence as the 'unverified' red state; "
        "M2-C2 Decision H deferred state-5 system-error rendering to a "
        "future task."
    )
