"""HTTP-level tests for the M3-A2 playbook executor endpoints.

Exercises:

* ``POST /api/v1/playbooks/{id}/execute`` — auth gating, 404 paths,
  the 202 happy path with a new execution row.
* ``GET /api/v1/playbook-executions/{id}`` — auth gating, 404 paths,
  the round-trip read of a row written by the kick-off endpoint.

The BackgroundTask is replaced with a no-op so these tests don't
actually run the LangGraph workflow — the executor itself is
covered by ``tests/playbooks/test_executor.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import playbooks as playbooks_module
from app.db.session import get_db
from app.main import app
from app.models.document import Document
from app.models.file import File as FileModel
from app.models.playbook import Playbook, PlaybookExecution, PlaybookPosition
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.security import create_access_token, hash_password


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


async def _make_document(db: AsyncSession, *, owner: User) -> tuple[FileModel, Document]:
    f = FileModel(
        owner_id=owner.id,
        filename=f"contract-{uuid.uuid4().hex[:6]}.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        hash_sha256="a" * 64,
        storage_path=f"endpoint-fixture/{uuid.uuid4()}",
        ingestion_status="ready",
    )
    db.add(f)
    await db.flush()
    doc = Document(
        file_id=f.id,
        parser="pymupdf-only",
        parser_version="pymupdf=1.27",
        page_count=1,
        character_count=100,
        normalized_content="x" * 100,
        was_ocrd=False,
    )
    db.add(doc)
    await db.flush()
    return f, doc


async def _make_playbook(
    db: AsyncSession, *, author: User | None = None, with_position: bool = True
) -> Playbook:
    pb = Playbook(
        name="Test",
        contract_type="NDA",
        created_by=author.id if author else None,
    )
    db.add(pb)
    await db.flush()
    if with_position:
        db.add(
            PlaybookPosition(
                playbook_id=pb.id,
                issue="Confidentiality",
                standard_language="standard",
                severity_if_missing="high",
                detection_keywords=["test"],
            )
        )
        await db.flush()
    return pb


def _bearer(user: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token(user.id, user.email, is_admin=user.is_admin)}"
        )
    }


# ---------------------------------------------------------------------------
# POST /api/v1/playbooks/{id}/execute
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("builtin", [False, True], ids=["own", "builtin"])
async def test_execute_returns_202_with_pending_execution(
    client: AsyncClient, db_session: AsyncSession, builtin: bool
) -> None:
    """A non-admin can execute every playbook visible to them on their own doc."""
    owner = await _make_user(db_session)
    _file, doc = await _make_document(db_session, owner=owner)
    playbook = await _make_playbook(db_session, author=None if builtin else owner)

    visible = await client.get(f"/api/v1/playbooks/{playbook.id}", headers=_bearer(owner))
    assert visible.status_code == 200, visible.text

    # No-op the background task — executor itself is tested separately.
    with patch.object(playbooks_module, "_run_in_background", new_callable=AsyncMock) as run:
        resp = await client.post(
            f"/api/v1/playbooks/{playbook.id}/execute",
            json={"target_document_id": str(doc.id)},
            headers=_bearer(owner),
        )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["playbook_id"] == str(playbook.id)
    assert body["target_document_id"] == str(doc.id)
    assert body["user_id"] == str(owner.id)
    assert body["results"] is None

    execution = await db_session.get(PlaybookExecution, uuid.UUID(body["id"]))
    assert execution is not None
    assert execution.user_id == owner.id
    run.assert_awaited_once()


@pytest.mark.integration
async def test_execute_requires_auth(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await _make_user(db_session)
    _file, doc = await _make_document(db_session, owner=owner)
    playbook = await _make_playbook(db_session, author=owner)

    resp = await client.post(
        f"/api/v1/playbooks/{playbook.id}/execute",
        json={"target_document_id": str(doc.id)},
    )
    assert resp.status_code == 401


@pytest.mark.integration
async def test_execute_returns_404_for_unknown_playbook(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session)
    _file, doc = await _make_document(db_session, owner=owner)

    resp = await client.post(
        f"/api/v1/playbooks/{uuid.uuid4()}/execute",
        json={"target_document_id": str(doc.id)},
        headers=_bearer(owner),
    )
    assert resp.status_code == 404


@pytest.mark.integration
async def test_execute_returns_404_for_unknown_document(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session)
    playbook = await _make_playbook(db_session, author=owner)

    resp = await client.post(
        f"/api/v1/playbooks/{playbook.id}/execute",
        json={"target_document_id": str(uuid.uuid4())},
        headers=_bearer(owner),
    )
    assert resp.status_code == 404


@pytest.mark.integration
async def test_execute_non_author_non_admin_gets_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A non-admin caller who isn't the playbook author sees 404 (not 403).

    Same per-user-isolation posture as the projects endpoints: avoid
    leaking the existence of a playbook the caller can't act on.
    """
    author = await _make_user(db_session)
    other = await _make_user(db_session)
    _file, doc = await _make_document(db_session, owner=other)
    playbook = await _make_playbook(db_session, author=author)

    resp = await client.post(
        f"/api/v1/playbooks/{playbook.id}/execute",
        json={"target_document_id": str(doc.id)},
        headers=_bearer(other),
    )
    assert resp.status_code == 404


@pytest.mark.integration
@pytest.mark.parametrize("builtin", [False, True], ids=["private", "builtin"])
async def test_execute_admin_can_act_on_any_playbook(
    client: AsyncClient, db_session: AsyncSession, builtin: bool
) -> None:
    """Admins can execute playbooks they didn't author (built-ins ship at deployment level)."""
    author = await _make_user(db_session)
    admin = await _make_user(db_session, is_admin=True)
    _file, doc = await _make_document(db_session, owner=author)
    playbook = await _make_playbook(db_session, author=None if builtin else author)

    with patch.object(playbooks_module, "_run_in_background", new=_noop_background):
        resp = await client.post(
            f"/api/v1/playbooks/{playbook.id}/execute",
            json={"target_document_id": str(doc.id)},
            headers=_bearer(admin),
        )

    assert resp.status_code == 202


@pytest.mark.integration
@pytest.mark.parametrize("is_admin", [False, True], ids=["member", "admin"])
async def test_execute_deleted_builtin_returns_404(
    client: AsyncClient, db_session: AsyncSession, is_admin: bool
) -> None:
    caller = await _make_user(db_session, is_admin=is_admin)
    _file, doc = await _make_document(db_session, owner=caller)
    playbook = await _make_playbook(db_session)
    playbook.deleted_at = datetime.now(UTC)
    await db_session.flush()

    with patch.object(playbooks_module, "_run_in_background", new_callable=AsyncMock) as run:
        response = await client.post(
            f"/api/v1/playbooks/{playbook.id}/execute",
            json={"target_document_id": str(doc.id)},
            headers=_bearer(caller),
        )
    assert response.status_code == 404, response.text
    run.assert_not_awaited()
    assert (
        await db_session.scalar(
            select(PlaybookExecution.id).where(PlaybookExecution.playbook_id == playbook.id)
        )
        is None
    )


@pytest.mark.integration
@pytest.mark.parametrize("file_state", ["foreign", "deleted"])
async def test_execute_builtin_rejects_unavailable_document(
    client: AsyncClient, db_session: AsyncSession, file_state: str
) -> None:
    caller = await _make_user(db_session)
    owner = await _make_user(db_session) if file_state == "foreign" else caller
    file_row, doc = await _make_document(db_session, owner=owner)
    if file_state == "deleted":
        file_row.deleted_at = datetime.now(UTC)
    playbook = await _make_playbook(db_session)
    await db_session.flush()

    with patch.object(playbooks_module, "_run_in_background", new_callable=AsyncMock) as run:
        response = await client.post(
            f"/api/v1/playbooks/{playbook.id}/execute",
            json={"target_document_id": str(doc.id)},
            headers=_bearer(caller),
        )
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "target document not found"
    run.assert_not_awaited()
    assert (
        await db_session.scalar(
            select(PlaybookExecution.id).where(PlaybookExecution.playbook_id == playbook.id)
        )
        is None
    )


@pytest.mark.integration
@pytest.mark.parametrize("is_admin", [False, True], ids=["member", "admin"])
@pytest.mark.parametrize("project_state", ["foreign", "archived", "own"])
async def test_execute_builtin_project_ownership(
    client: AsyncClient, db_session: AsyncSession, project_state: str, is_admin: bool
) -> None:
    caller = await _make_user(db_session, is_admin=is_admin)
    owner = await _make_user(db_session) if project_state == "foreign" else caller
    _file, doc = await _make_document(db_session, owner=caller)
    playbook = await _make_playbook(db_session)
    project = Project(owner_id=owner.id, name="Synthetic matter", slug="execution-fixture")
    if project_state == "archived":
        project.archived_at = datetime.now(UTC)
    db_session.add(project)
    await db_session.flush()
    if project_state == "foreign":
        # Matter write access does not replace ownership for non-admins.
        # Admins retain their ownership bypass, but still need this grant.
        db_session.add(
            ProjectMember(
                project_id=project.id,
                user_id=caller.id,
                added_by_user_id=owner.id,
                role="contributor",
            )
        )
        await db_session.flush()

    with patch.object(playbooks_module, "_run_in_background", new_callable=AsyncMock) as run:
        response = await client.post(
            f"/api/v1/playbooks/{playbook.id}/execute",
            json={"target_document_id": str(doc.id), "project_id": str(project.id)},
            headers=_bearer(caller),
        )
    execution = await db_session.scalar(
        select(PlaybookExecution).where(PlaybookExecution.playbook_id == playbook.id)
    )
    if project_state == "own" or (project_state == "foreign" and is_admin):
        assert response.status_code == 202, response.text
        assert execution is not None
        assert execution.project_id == project.id
        assert execution.user_id == caller.id
        assert response.json()["id"] == str(execution.id)
        assert response.json()["status"] == "pending"
        run.assert_awaited_once()
    else:
        assert response.status_code == 404, response.text
        assert execution is None
        run.assert_not_awaited()


@pytest.mark.integration
@pytest.mark.parametrize("is_admin", [False, True], ids=["member", "admin"])
@pytest.mark.parametrize("scope", ["document", "explicit_project"])
@pytest.mark.parametrize("membership,expected_status", [("blocked", 404), ("reader", 403)])
async def test_execute_builtin_retains_matter_write_checks(
    client: AsyncClient,
    db_session: AsyncSession,
    is_admin: bool,
    scope: str,
    membership: str,
    expected_status: int,
) -> None:
    caller = await _make_user(db_session, is_admin=is_admin)
    # A screen must override ownership. Otherwise the explicit-project case
    # could still return 404 from the ownership check if its matter guard broke.
    # Readers remain non-owners because ownership itself grants lead access.
    owner = caller if membership == "blocked" else await _make_user(db_session)
    file_row, doc = await _make_document(db_session, owner=caller)
    playbook = await _make_playbook(db_session)
    project = Project(owner_id=owner.id, name="Restricted matter", slug="restricted-fixture")
    db_session.add(project)
    await db_session.flush()
    db_session.add(
        ProjectMember(
            project_id=project.id,
            user_id=caller.id,
            added_by_user_id=owner.id,
            role=membership,
        )
    )
    payload = {"target_document_id": str(doc.id)}
    if scope == "document":
        file_row.project_id = project.id
    else:
        payload["project_id"] = str(project.id)
    await db_session.flush()

    with patch.object(playbooks_module, "_run_in_background", new_callable=AsyncMock) as run:
        response = await client.post(
            f"/api/v1/playbooks/{playbook.id}/execute", json=payload, headers=_bearer(caller)
        )
    assert response.status_code == expected_status, response.text
    run.assert_not_awaited()
    assert (
        await db_session.scalar(
            select(PlaybookExecution.id).where(PlaybookExecution.playbook_id == playbook.id)
        )
        is None
    )


# ---------------------------------------------------------------------------
# GET /api/v1/playbook-executions/{id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_execution_returns_row(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await _make_user(db_session)
    _file, doc = await _make_document(db_session, owner=owner)
    playbook = await _make_playbook(db_session, author=owner)
    execution = PlaybookExecution(
        playbook_id=playbook.id,
        target_document_id=doc.id,
        user_id=owner.id,
        status="pending",
    )
    db_session.add(execution)
    await db_session.flush()

    resp = await client.get(
        f"/api/v1/playbook-executions/{execution.id}",
        headers=_bearer(owner),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(execution.id)
    assert body["status"] == "pending"


@pytest.mark.integration
async def test_get_execution_returns_404_when_not_owner(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session)
    other = await _make_user(db_session)
    _file, doc = await _make_document(db_session, owner=owner)
    playbook = await _make_playbook(db_session, author=owner)
    execution = PlaybookExecution(
        playbook_id=playbook.id,
        target_document_id=doc.id,
        user_id=owner.id,
        status="pending",
    )
    db_session.add(execution)
    await db_session.flush()

    resp = await client.get(
        f"/api/v1/playbook-executions/{execution.id}",
        headers=_bearer(other),
    )
    assert resp.status_code == 404


@pytest.mark.integration
async def test_get_execution_returns_404_for_unknown_id(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session)
    resp = await client.get(
        f"/api/v1/playbook-executions/{uuid.uuid4()}",
        headers=_bearer(owner),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _noop_background(**_kwargs: Any) -> None:
    """Replaces ``_run_in_background`` so endpoint tests don't actually run the workflow."""
    return None
