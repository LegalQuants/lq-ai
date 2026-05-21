"""Worker-side tests for the M3-A6 Phase 5 Easy Playbook pipeline.

The :func:`easy_playbook_generation_job` worker function runs against
a real Postgres (the same conftest pattern as the executor tests).
The expensive pipeline pieces (extract / cluster / assemble) are
mocked at the module-import-site level so the worker's *orchestration*
is tested without re-running Phase 3/4 logic — which has its own
test coverage already.

Verifies:

* Happy path — row moves ``pending → running → completed``,
  ``draft_playbook`` is populated with the mocked
  :class:`PlaybookCreate`, ``started_at`` / ``completed_at`` are set.
* Missing row — graceful early return.
* Per-document extraction failure — non-fatal; the run continues
  with whatever clauses came back from the other documents.
* Mid-pipeline exception — row lands at ``status='error'`` with
  ``error_message`` populated.
* Documents are loaded in ``document_ids`` order; missing
  documents are silently skipped.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session_factory
from app.models.document import Document
from app.models.file import File as FileModel
from app.models.playbook import EasyPlaybookGeneration
from app.models.user import User
from app.playbooks.easy.extractor import ExtractedClause
from app.schemas.playbooks import PlaybookCreate
from app.security import hash_password
from app.workers.easy_playbook_worker import easy_playbook_generation_job


@pytest_asyncio.fixture
async def patch_session_factory(
    db_session: AsyncSession,
) -> AsyncIterator[None]:
    """Make ``get_session_factory()`` return a factory bound to the test session.

    The worker opens its own session via ``async with factory() as session``;
    we patch the factory to return one that yields ``db_session`` so the
    test's transaction-rollback isolation covers the worker's writes too.
    """

    class _FakeAsyncContext:
        async def __aenter__(self) -> AsyncSession:
            return db_session

        async def __aexit__(self, *_exc: Any) -> None:
            # The conftest fixture handles rollback at test teardown.
            return None

    class _FakeFactory:
        def __call__(self) -> _FakeAsyncContext:
            return _FakeAsyncContext()

    real_factory = get_session_factory()
    fake_factory = _FakeFactory()

    with patch(
        "app.workers.easy_playbook_worker.get_session_factory",
        return_value=fake_factory,
    ):
        yield

    # Touch real factory to suppress unused-var warnings; it's the
    # canonical path the worker uses outside tests.
    _ = real_factory


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


async def _make_doc(db: AsyncSession, *, owner: User, text: str = "Some contract.") -> Document:
    f = FileModel(
        owner_id=owner.id,
        filename=f"doc-{uuid.uuid4().hex[:6]}.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        hash_sha256="b" * 64,
        storage_path=f"easy-worker-fixture/{uuid.uuid4()}",
        ingestion_status="ready",
    )
    db.add(f)
    await db.flush()
    doc = Document(
        file_id=f.id,
        parser="pymupdf-only",
        parser_version="pymupdf=1.27",
        page_count=1,
        character_count=len(text),
        normalized_content=text,
        was_ocrd=False,
    )
    db.add(doc)
    await db.flush()
    return doc


async def _make_generation(
    db: AsyncSession,
    *,
    owner: User,
    document_ids: list[uuid.UUID],
    contract_type: str = "NDA",
) -> EasyPlaybookGeneration:
    row = EasyPlaybookGeneration(
        user_id=owner.id,
        contract_type=contract_type,
        status="pending",
        document_ids=document_ids,
    )
    db.add(row)
    await db.flush()
    return row


def _stub_playbook() -> PlaybookCreate:
    return PlaybookCreate(
        name="Generated NDA Playbook",
        contract_type="NDA",
        description="",
        version="1.0.0",
        positions=[],
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_worker_happy_path_writes_draft_playbook_and_completes(
    db_session: AsyncSession,
    patch_session_factory: None,
) -> None:
    user = await _make_user(db_session)
    doc = await _make_doc(db_session, owner=user, text="Contract text.")
    generation = await _make_generation(
        db_session,
        owner=user,
        document_ids=[doc.id],
    )
    await db_session.commit()

    extract_mock = AsyncMock(
        return_value=[
            ExtractedClause(issue="Term", clause_text="Three years."),
        ]
    )
    cluster_mock = AsyncMock(return_value=["one-cluster-placeholder"])
    assemble_mock = AsyncMock(return_value=_stub_playbook())

    with (
        patch(
            "app.workers.easy_playbook_worker.extract_clauses_from_document",
            new=extract_mock,
        ),
        patch(
            "app.workers.easy_playbook_worker.cluster_clauses_by_issue",
            new=cluster_mock,
        ),
        patch(
            "app.workers.easy_playbook_worker.assemble_playbook",
            new=assemble_mock,
        ),
    ):
        result = await easy_playbook_generation_job({}, str(generation.id))

    assert result["status"] == "completed"

    # Row state.
    await db_session.refresh(generation)
    assert generation.status == "completed"
    assert generation.started_at is not None
    assert generation.completed_at is not None
    assert generation.draft_playbook is not None
    assert generation.draft_playbook["name"] == "Generated NDA Playbook"
    assert generation.error_message is None

    # Each pipeline stage called once with the expected shape.
    extract_mock.assert_awaited_once()
    cluster_mock.assert_awaited_once()
    assemble_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# Missing row
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_worker_missing_row_returns_early(
    db_session: AsyncSession,
    patch_session_factory: None,
) -> None:
    """Worker handed a generation_id with no row returns a graceful 'missing' result."""

    extract_mock = AsyncMock()
    with patch(
        "app.workers.easy_playbook_worker.extract_clauses_from_document",
        new=extract_mock,
    ):
        result = await easy_playbook_generation_job({}, str(uuid.uuid4()))

    assert result["status"] == "missing"
    extract_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# Per-document extraction failure — non-fatal
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_worker_per_document_extract_failure_does_not_kill_run(
    db_session: AsyncSession,
    patch_session_factory: None,
) -> None:
    """A single bad document degrades signal but the run completes."""

    user = await _make_user(db_session)
    doc_a = await _make_doc(db_session, owner=user, text="Doc A.")
    doc_b = await _make_doc(db_session, owner=user, text="Doc B.")
    generation = await _make_generation(
        db_session,
        owner=user,
        document_ids=[doc_a.id, doc_b.id],
    )
    await db_session.commit()

    extract_mock = AsyncMock(
        side_effect=[
            ConnectionError("doc A extraction failed"),
            [ExtractedClause(issue="Term", clause_text="Three years.")],
        ]
    )

    with (
        patch(
            "app.workers.easy_playbook_worker.extract_clauses_from_document",
            new=extract_mock,
        ),
        patch(
            "app.workers.easy_playbook_worker.cluster_clauses_by_issue",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.workers.easy_playbook_worker.assemble_playbook",
            new=AsyncMock(return_value=_stub_playbook()),
        ),
    ):
        result = await easy_playbook_generation_job({}, str(generation.id))

    assert result["status"] == "completed"
    assert extract_mock.await_count == 2

    await db_session.refresh(generation)
    assert generation.status == "completed"
    # draft_playbook was written even though doc A failed.
    assert generation.draft_playbook is not None


# ---------------------------------------------------------------------------
# Mid-pipeline exception — status='error'
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_worker_assembly_exception_lands_status_error(
    db_session: AsyncSession,
    patch_session_factory: None,
) -> None:
    user = await _make_user(db_session)
    doc = await _make_doc(db_session, owner=user)
    generation = await _make_generation(
        db_session,
        owner=user,
        document_ids=[doc.id],
    )
    await db_session.commit()

    with (
        patch(
            "app.workers.easy_playbook_worker.extract_clauses_from_document",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.workers.easy_playbook_worker.cluster_clauses_by_issue",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.workers.easy_playbook_worker.assemble_playbook",
            new=AsyncMock(side_effect=RuntimeError("assembly blew up")),
        ),
    ):
        result = await easy_playbook_generation_job({}, str(generation.id))

    assert result["status"] == "error"
    assert "assembly blew up" in result["error"]

    await db_session.refresh(generation)
    assert generation.status == "error"
    assert generation.completed_at is not None
    assert generation.error_message is not None
    assert "RuntimeError" in generation.error_message
    assert "assembly blew up" in generation.error_message
    # draft_playbook stays None since assembly itself raised.
    assert generation.draft_playbook is None


# ---------------------------------------------------------------------------
# Missing source documents — silently skipped
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_worker_silently_skips_documents_that_no_longer_exist(
    db_session: AsyncSession,
    patch_session_factory: None,
) -> None:
    """If a source document was deleted between enqueue and pickup, the worker continues."""

    user = await _make_user(db_session)
    doc = await _make_doc(db_session, owner=user)
    missing_id = uuid.uuid4()
    generation = await _make_generation(
        db_session,
        owner=user,
        document_ids=[missing_id, doc.id],
    )
    await db_session.commit()

    extract_mock = AsyncMock(return_value=[])
    with (
        patch(
            "app.workers.easy_playbook_worker.extract_clauses_from_document",
            new=extract_mock,
        ),
        patch(
            "app.workers.easy_playbook_worker.cluster_clauses_by_issue",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.workers.easy_playbook_worker.assemble_playbook",
            new=AsyncMock(return_value=_stub_playbook()),
        ),
    ):
        result = await easy_playbook_generation_job({}, str(generation.id))

    assert result["status"] == "completed"
    # Extract called once — only for the real document; the missing
    # id was skipped silently.
    assert extract_mock.await_count == 1


# ---------------------------------------------------------------------------
# Pipeline-wire integration — extract output flows into cluster input
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_worker_extract_output_flows_into_cluster_input(
    db_session: AsyncSession,
    patch_session_factory: None,
) -> None:
    """Each ExtractedClause becomes a ClauseInput with the document_id attached."""

    from app.playbooks.easy.clustering import ClauseInput

    user = await _make_user(db_session)
    doc = await _make_doc(db_session, owner=user)
    generation = await _make_generation(
        db_session,
        owner=user,
        document_ids=[doc.id],
    )
    await db_session.commit()

    cluster_mock = AsyncMock(return_value=[])
    with (
        patch(
            "app.workers.easy_playbook_worker.extract_clauses_from_document",
            new=AsyncMock(
                return_value=[
                    ExtractedClause(issue="Governing Law", clause_text="Delaware."),
                    ExtractedClause(issue="Term", clause_text="Three years."),
                ]
            ),
        ),
        patch(
            "app.workers.easy_playbook_worker.cluster_clauses_by_issue",
            new=cluster_mock,
        ),
        patch(
            "app.workers.easy_playbook_worker.assemble_playbook",
            new=AsyncMock(return_value=_stub_playbook()),
        ),
    ):
        await easy_playbook_generation_job({}, str(generation.id))

    cluster_call = cluster_mock.await_args
    assert cluster_call is not None
    passed_clauses: list[ClauseInput] = cluster_call.kwargs["clauses"]
    assert len(passed_clauses) == 2
    # Every clause carries the source document's id.
    assert all(c.document_id == doc.id for c in passed_clauses)
    assert {c.issue for c in passed_clauses} == {"Governing Law", "Term"}
