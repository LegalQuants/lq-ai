"""HTTP-level tests for the M3-A6 Phase 5 easy-playbook endpoints.

Exercises:

* ``POST   /api/v1/playbooks/easy`` — creates the
  :class:`EasyPlaybookGeneration` row + enqueues the ARQ job.
* ``GET    /api/v1/playbooks/easy/{generation_id}`` — polls the row.

ARQ enqueueing is mocked end-to-end: the test stack does not run the
worker. Worker-side verification lives in
``tests/test_easy_playbook_worker.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.document import Document
from app.models.file import File as FileModel
from app.models.playbook import EasyPlaybookGeneration
from app.models.user import User
from app.security import create_access_token, hash_password


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


@pytest_asyncio.fixture
async def mock_enqueue() -> AsyncIterator[AsyncMock]:
    """Patch the ARQ enqueue helper so tests don't hit Redis."""

    with patch(
        "app.api.playbooks.enqueue_easy_playbook_generation_job",
        new=AsyncMock(return_value=True),
    ) as mock:
        yield mock


async def _make_user(db: AsyncSession, *, is_admin: bool = False) -> User:
    u = User(
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=is_admin,
        role="admin" if is_admin else "member",
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


async def _make_owned_doc(db: AsyncSession, *, owner: User) -> Document:
    f = FileModel(
        owner_id=owner.id,
        filename=f"doc-{uuid.uuid4().hex[:6]}.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        hash_sha256="a" * 64,
        storage_path=f"easy-playbook-fixture/{uuid.uuid4()}",
        ingestion_status="ready",
    )
    db.add(f)
    await db.flush()
    doc = Document(
        file_id=f.id,
        parser="pymupdf-only",
        parser_version="pymupdf=1.27",
        page_count=1,
        character_count=20,
        normalized_content="A short contract text.",
        was_ocrd=False,
    )
    db.add(doc)
    await db.flush()
    return doc


# ---------------------------------------------------------------------------
# POST /api/v1/playbooks/easy
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_post_easy_playbook_happy_path_enqueues_and_returns_202(
    client: AsyncClient, db_session: AsyncSession, mock_enqueue: AsyncMock
) -> None:
    user = await _make_user(db_session)
    doc = await _make_owned_doc(db_session, owner=user)

    response = await client.post(
        "/api/v1/playbooks/easy",
        json={
            "document_ids": [str(doc.id)],
            "contract_type": "NDA",
            "name": "My NDA playbook",
        },
        headers=_bearer(user),
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["contract_type"] == "NDA"
    assert body["document_ids"] == [str(doc.id)]
    assert body["user_id"] == str(user.id)
    assert body["draft_playbook"] is None
    assert body["error_message"] is None

    # Row persisted.
    row = await db_session.get(EasyPlaybookGeneration, uuid.UUID(body["id"]))
    assert row is not None
    assert row.status == "pending"

    # Enqueue called with the row id.
    mock_enqueue.assert_awaited_once_with(uuid.UUID(body["id"]))


@pytest.mark.integration
async def test_post_easy_playbook_empty_document_ids_rejected_at_validation(
    client: AsyncClient, db_session: AsyncSession, mock_enqueue: AsyncMock
) -> None:
    """``document_ids`` has ``min_length=1`` on the schema; empty list → 422."""

    user = await _make_user(db_session)
    response = await client.post(
        "/api/v1/playbooks/easy",
        json={"document_ids": [], "contract_type": "NDA"},
        headers=_bearer(user),
    )
    assert response.status_code == 422
    mock_enqueue.assert_not_awaited()


@pytest.mark.integration
async def test_post_easy_playbook_nonexistent_document_returns_404(
    client: AsyncClient, db_session: AsyncSession, mock_enqueue: AsyncMock
) -> None:
    user = await _make_user(db_session)
    response = await client.post(
        "/api/v1/playbooks/easy",
        json={
            "document_ids": [str(uuid.uuid4())],
            "contract_type": "NDA",
        },
        headers=_bearer(user),
    )
    assert response.status_code == 404
    mock_enqueue.assert_not_awaited()


@pytest.mark.integration
async def test_post_easy_playbook_cross_user_document_returns_404(
    client: AsyncClient, db_session: AsyncSession, mock_enqueue: AsyncMock
) -> None:
    """A doc the caller doesn't own collapses to 404 (no information leakage)."""

    owner = await _make_user(db_session)
    other = await _make_user(db_session)
    doc = await _make_owned_doc(db_session, owner=owner)

    response = await client.post(
        "/api/v1/playbooks/easy",
        json={
            "document_ids": [str(doc.id)],
            "contract_type": "NDA",
        },
        headers=_bearer(other),
    )
    assert response.status_code == 404
    mock_enqueue.assert_not_awaited()


@pytest.mark.integration
async def test_post_easy_playbook_admin_can_use_any_documents(
    client: AsyncClient, db_session: AsyncSession, mock_enqueue: AsyncMock
) -> None:
    """Admin gets to start a generation against another user's documents.

    Matches the M3-A2 executor's admin-bypass for the same ownership
    check — admins act on operator-uploaded docs.
    """

    user = await _make_user(db_session)
    admin = await _make_user(db_session, is_admin=True)
    doc = await _make_owned_doc(db_session, owner=user)

    response = await client.post(
        "/api/v1/playbooks/easy",
        json={
            "document_ids": [str(doc.id)],
            "contract_type": "NDA",
        },
        headers=_bearer(admin),
    )
    assert response.status_code == 202, response.text
    assert response.json()["user_id"] == str(admin.id)
    mock_enqueue.assert_awaited_once()


@pytest.mark.integration
async def test_post_easy_playbook_skips_soft_deleted_file(
    client: AsyncClient, db_session: AsyncSession, mock_enqueue: AsyncMock
) -> None:
    """A document whose parent file is soft-deleted is treated as missing → 404."""

    from datetime import UTC, datetime

    user = await _make_user(db_session)
    doc = await _make_owned_doc(db_session, owner=user)
    file_row = await db_session.get(FileModel, doc.file_id)
    assert file_row is not None
    file_row.deleted_at = datetime.now(tz=UTC)
    await db_session.flush()

    response = await client.post(
        "/api/v1/playbooks/easy",
        json={
            "document_ids": [str(doc.id)],
            "contract_type": "NDA",
        },
        headers=_bearer(user),
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_post_easy_playbook_enqueue_failure_does_not_roll_back_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Enqueue failure logs at WARNING but the row is committed at status=pending.

    Matches the C5 ingest path's best-effort posture (the worker's
    startup sweep handles orphaned rows). Operators can re-enqueue
    manually if the worker stays down indefinitely.
    """

    user = await _make_user(db_session)
    doc = await _make_owned_doc(db_session, owner=user)
    with patch(
        "app.api.playbooks.enqueue_easy_playbook_generation_job",
        new=AsyncMock(return_value=False),
    ) as mock:
        response = await client.post(
            "/api/v1/playbooks/easy",
            json={
                "document_ids": [str(doc.id)],
                "contract_type": "NDA",
            },
            headers=_bearer(user),
        )
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "pending"
        mock.assert_awaited_once()
        # Row persisted despite enqueue failure.
        row = await db_session.get(EasyPlaybookGeneration, uuid.UUID(body["id"]))
        assert row is not None


@pytest.mark.integration
async def test_post_easy_playbook_rejects_unknown_body_fields(
    client: AsyncClient, db_session: AsyncSession, mock_enqueue: AsyncMock
) -> None:
    user = await _make_user(db_session)
    doc = await _make_owned_doc(db_session, owner=user)
    response = await client.post(
        "/api/v1/playbooks/easy",
        json={
            "document_ids": [str(doc.id)],
            "contract_type": "NDA",
            "extra_unwanted_field": "nope",
        },
        headers=_bearer(user),
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/playbooks/easy/{generation_id}
# ---------------------------------------------------------------------------


async def _make_generation(
    db: AsyncSession,
    *,
    owner: User,
    status: str = "pending",
    draft: dict[str, Any] | None = None,
) -> EasyPlaybookGeneration:
    row = EasyPlaybookGeneration(
        user_id=owner.id,
        contract_type="NDA",
        status=status,
        document_ids=[],
        draft_playbook=draft,
    )
    db.add(row)
    await db.flush()
    return row


@pytest.mark.integration
async def test_get_easy_playbook_owner_can_read(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    row = await _make_generation(db_session, owner=user, status="pending")
    response = await client.get(
        f"/api/v1/playbooks/easy/{row.id}",
        headers=_bearer(user),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"


@pytest.mark.integration
async def test_get_easy_playbook_other_user_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session)
    other = await _make_user(db_session)
    row = await _make_generation(db_session, owner=owner)
    response = await client.get(
        f"/api/v1/playbooks/easy/{row.id}",
        headers=_bearer(other),
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_get_easy_playbook_admin_can_read_any(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session)
    admin = await _make_user(db_session, is_admin=True)
    row = await _make_generation(db_session, owner=owner)
    response = await client.get(
        f"/api/v1/playbooks/easy/{row.id}",
        headers=_bearer(admin),
    )
    assert response.status_code == 200


@pytest.mark.integration
async def test_get_easy_playbook_missing_404(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    response = await client.get(
        f"/api/v1/playbooks/easy/{uuid.uuid4()}",
        headers=_bearer(user),
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_get_easy_playbook_completed_row_returns_draft_playbook(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A completed row surfaces ``draft_playbook`` for Step 3's inline editor."""

    user = await _make_user(db_session)
    draft = {
        "name": "Generated NDA Playbook",
        "contract_type": "NDA",
        "description": "",
        "version": "1.0.0",
        "positions": [
            {
                "issue": "Term",
                "description": "",
                "standard_language": "Three years.",
                "fallback_tiers": [],
                "redline_strategy": "",
                "severity_if_missing": "low",
                "detection_keywords": [],
                "detection_examples": [],
                "position_order": 0,
            }
        ],
    }
    row = await _make_generation(db_session, owner=user, status="completed", draft=draft)
    response = await client.get(
        f"/api/v1/playbooks/easy/{row.id}",
        headers=_bearer(user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["draft_playbook"]["name"] == "Generated NDA Playbook"
    assert len(body["draft_playbook"]["positions"]) == 1
