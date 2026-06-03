"""HTTP-level tests for navigable tabular cell citations (Donna).

Exercises ``GET /api/v1/tabular/executions/{id}`` read-time enrichment:
each synthesized cell ``Citation`` (built from the persisted
``cited_chunk_ids``) is enriched with ``source_file_id``
(``documents.file_id``), ``source_page`` (``document_chunks.page_start``),
and ``source_text`` (``document_chunks.content``) so the frontend can open
the cited source in its doc panel.

Key property under test: enrichment happens at serialization time. The
execution rows are inserted directly with the pre-change persisted shape
(``cited_chunk_ids`` only — no navigation fields stored), simulating a
pre-feature execution; the response must still carry the navigation fields
with no migration / backfill / re-run.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.cost import invalidate_cache as invalidate_judge_cache
from app.clients.gateway import EnsembleConfig, get_gateway_client
from app.db.session import get_db
from app.main import app
from app.models.document import Document, DocumentChunk
from app.models.file import File as FileModel
from app.models.tabular import TabularExecution
from app.models.user import User
from app.security import create_access_token, hash_password
from app.tabular import cost as tabular_cost


def _override_get_db(db_session: AsyncSession):
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


async def _make_user(db: AsyncSession) -> User:
    u = User(
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(u)
    await db.flush()
    return u


def _bearer(user: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token(user.id, user.email, is_admin=user.is_admin)}"
        )
    }


async def _make_doc_with_chunk(
    db: AsyncSession,
    *,
    owner: User,
    content: str,
    page_start: int | None,
) -> tuple[Document, DocumentChunk]:
    """Seed a File + Document(file_id) + one DocumentChunk."""

    f = FileModel(
        owner_id=owner.id,
        filename=f"doc-{uuid.uuid4().hex[:6]}.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        hash_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        storage_path=f"tabular-citation-fixture/{uuid.uuid4()}",
        ingestion_status="ready",
    )
    db.add(f)
    await db.flush()
    doc = Document(
        file_id=f.id,
        parser="pymupdf-only",
        parser_version="pymupdf=1.27",
        page_count=3,
        character_count=len(content),
        normalized_content=content,
        was_ocrd=False,
    )
    db.add(doc)
    await db.flush()
    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content=content,
        page_start=page_start,
        page_end=page_start,
        char_offset_start=0,
        char_offset_end=len(content),
    )
    db.add(chunk)
    await db.flush()
    return doc, chunk


async def _insert_execution(
    db: AsyncSession,
    *,
    owner: User,
    document_ids: list[uuid.UUID],
    rows: list[dict[str, Any]],
) -> TabularExecution:
    """Insert a completed execution row directly in the pre-change shape.

    ``results.rows[*].cells[*]`` carry only the persisted keys (notably
    ``cited_chunk_ids``) — no navigation fields — so the test proves
    enrichment happens at read time, not via stored data.
    """

    execution = TabularExecution(
        user_id=owner.id,
        skill_name=None,
        status="completed",
        document_ids=document_ids,
        columns=[{"name": "Term", "query": "What is the term?"}],
        results={"schema_version": "m3-c2-v1", "rows": rows},
    )
    db.add(execution)
    await db.flush()
    return execution


@pytest.mark.integration
async def test_get_execution_enriches_citations_with_navigable_source(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    content = "The term of this Agreement is three (3) years from the Effective Date."
    doc, chunk = await _make_doc_with_chunk(db_session, owner=user, content=content, page_start=2)
    execution = await _insert_execution(
        db_session,
        owner=user,
        document_ids=[doc.id],
        rows=[
            {
                "document_id": str(doc.id),
                "document_name": "nda.pdf",
                "cells": {
                    "Term": {
                        "value": "3 years",
                        "cited_chunk_ids": [str(chunk.id)],
                        "confidence": "high",
                        "tier_used": 2,
                    }
                },
            }
        ],
    )

    resp = await client.get(f"/api/v1/tabular/executions/{execution.id}", headers=_bearer(user))
    assert resp.status_code == 200, resp.text
    cell = resp.json()["results"]["rows"][0]["cells"]["Term"]
    citations = cell["citations"]
    assert len(citations) == 1
    cit = citations[0]

    # Existing display-only fields still present.
    assert cit["document_id"] == str(doc.id)
    assert cit["chunk_id"] == str(chunk.id)
    assert cit["citation_id"]  # synthetic deterministic id

    # Navigation fields resolved at read time.
    assert cit["source_file_id"] == str(doc.file_id)
    assert cit["source_page"] == 2
    assert cit["source_text"] == content

    # The referenced file actually exists.
    file_row = await db_session.get(FileModel, doc.file_id)
    assert file_row is not None


@pytest.mark.integration
async def test_get_execution_empty_cited_chunk_ids_yields_no_citations(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Back-compat: a cell with no cited chunks → empty citations, no error."""

    user = await _make_user(db_session)
    doc, _chunk = await _make_doc_with_chunk(
        db_session, owner=user, content="irrelevant", page_start=1
    )
    execution = await _insert_execution(
        db_session,
        owner=user,
        document_ids=[doc.id],
        rows=[
            {
                "document_id": str(doc.id),
                "document_name": "nda.pdf",
                "cells": {
                    "Term": {
                        "value": None,
                        "cited_chunk_ids": [],
                        "confidence": "failed",
                        "error": "no citation found",
                    }
                },
            }
        ],
    )

    resp = await client.get(f"/api/v1/tabular/executions/{execution.id}", headers=_bearer(user))
    assert resp.status_code == 200, resp.text
    cell = resp.json()["results"]["rows"][0]["cells"]["Term"]
    assert cell["citations"] == []


@pytest.mark.integration
async def test_get_execution_stale_chunk_id_leaves_nav_fields_null(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A cited chunk id with no backing row → nav fields stay null, no crash."""

    user = await _make_user(db_session)
    doc, _chunk = await _make_doc_with_chunk(
        db_session, owner=user, content="present", page_start=1
    )
    stale_chunk_id = uuid.uuid4()  # never inserted
    execution = await _insert_execution(
        db_session,
        owner=user,
        document_ids=[doc.id],
        rows=[
            {
                "document_id": str(doc.id),
                "document_name": "nda.pdf",
                "cells": {
                    "Term": {
                        "value": "x",
                        "cited_chunk_ids": [str(stale_chunk_id)],
                        "confidence": "low",
                    }
                },
            }
        ],
    )

    resp = await client.get(f"/api/v1/tabular/executions/{execution.id}", headers=_bearer(user))
    assert resp.status_code == 200, resp.text
    cit = resp.json()["results"]["rows"][0]["cells"]["Term"]["citations"][0]
    assert cit["chunk_id"] == str(stale_chunk_id)
    assert cit["source_file_id"] is None
    assert cit["source_page"] is None
    assert cit["source_text"] is None


@pytest.mark.integration
async def test_get_execution_batches_across_two_documents(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A cell citing two chunks across two documents resolves each correctly.

    Proves the batched chunk + document IN-queries map each citation to
    the right file / page / text (no cross-contamination).
    """

    user = await _make_user(db_session)
    doc_a, chunk_a = await _make_doc_with_chunk(
        db_session, owner=user, content="alpha source text", page_start=1
    )
    doc_b, chunk_b = await _make_doc_with_chunk(
        db_session, owner=user, content="bravo source text", page_start=5
    )
    # Row is for doc_a; its cell cites a chunk from doc_a AND doc_b.
    execution = await _insert_execution(
        db_session,
        owner=user,
        document_ids=[doc_a.id, doc_b.id],
        rows=[
            {
                "document_id": str(doc_a.id),
                "document_name": "a.pdf",
                "cells": {
                    "Term": {
                        "value": "cross-doc",
                        "cited_chunk_ids": [str(chunk_a.id), str(chunk_b.id)],
                        "confidence": "high",
                    }
                },
            }
        ],
    )

    resp = await client.get(f"/api/v1/tabular/executions/{execution.id}", headers=_bearer(user))
    assert resp.status_code == 200, resp.text
    citations = resp.json()["results"]["rows"][0]["cells"]["Term"]["citations"]
    by_chunk = {c["chunk_id"]: c for c in citations}

    cit_a = by_chunk[str(chunk_a.id)]
    assert cit_a["source_file_id"] == str(doc_a.file_id)
    assert cit_a["source_page"] == 1
    assert cit_a["source_text"] == "alpha source text"

    cit_b = by_chunk[str(chunk_b.id)]
    assert cit_b["source_file_id"] == str(doc_b.file_id)
    assert cit_b["source_page"] == 5
    assert cit_b["source_text"] == "bravo source text"


# --- preview-cost: ensemble premium surface (Donna #6) ----------------------


class _StubGateway:
    """Minimal gateway stub for preview-cost — only the ensemble-config
    accessor the endpoint touches is implemented."""

    def __init__(self, ensemble_config: EnsembleConfig | None) -> None:
        self._ensemble_config = ensemble_config

    async def get_citation_engine_ensemble_config(self) -> EnsembleConfig | None:
        return self._ensemble_config


@pytest.mark.asyncio
async def test_preview_cost_no_ensemble_config_back_compat(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """With no ensemble configured, the new fields are present and zero —
    the back-compat shape the UI relies on when the gateway has no
    ensemble. (The premium math itself is unit-tested in
    tests/tabular/test_cost.py.)"""

    user = await _make_user(db_session)
    app.dependency_overrides[get_gateway_client] = lambda: _StubGateway(None)
    tabular_cost.invalidate_cache()
    invalidate_judge_cache()
    try:
        resp = await client.post(
            "/api/v1/tabular/preview-cost",
            headers=_bearer(user),
            json={
                "document_ids": [str(uuid.uuid4()) for _ in range(2)],
                "columns": [
                    {"name": "A", "query": "?", "ensemble_verification": True},
                ],
            },
        )
    finally:
        app.dependency_overrides.pop(get_gateway_client, None)

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["ensemble_cells_count"] == 0
    assert payload["ensemble_premium_usd"] == "0"


@pytest.mark.asyncio
async def test_preview_cost_ensemble_premium_applied(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """An ensemble-verified column drives a positive premium through the
    endpoint when the gateway returns an ensemble config."""

    user = await _make_user(db_session)
    config = EnsembleConfig(
        default_enabled=False,
        judge_models=("a", "b", "c"),
        aggregation_rule="strict",
        max_cost_per_message_usd=1.0,
        envelope_tier=3,
    )
    app.dependency_overrides[get_gateway_client] = lambda: _StubGateway(config)
    tabular_cost.invalidate_cache()
    invalidate_judge_cache()
    try:
        resp = await client.post(
            "/api/v1/tabular/preview-cost",
            headers=_bearer(user),
            json={
                "document_ids": [str(uuid.uuid4()) for _ in range(3)],
                "columns": [
                    {"name": "A", "query": "?", "ensemble_verification": True},
                ],
            },
        )
    finally:
        app.dependency_overrides.pop(get_gateway_client, None)

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    # 3 docs * 1 ensemble column = 3 ensemble cells.
    assert payload["ensemble_cells_count"] == 3
    assert float(payload["ensemble_premium_usd"]) > 0
