"""Integration tests for ``POST/DELETE /api/v1/projects/{id}/knowledge-bases``.

Wave D.1 Task 3 — matter <-> KB attach/detach endpoints. Mirrors the
existing ``/files`` and ``/skills`` attach pattern in ``app.api.projects``
but with the idempotency posture pinned by the Wave D.1 spec:

* POST returns 200 + the updated ``ProjectResponse`` (so the UI gets
  back the canonical attached-KB list without a second round trip).
* POST is idempotent — re-attaching an already-attached KB is a 200.
* DELETE returns 204; detaching a non-attached KB is also 204.
* Both writes write an ``audit_log`` row (action
  ``project.knowledge_base_attached`` / ``project.knowledge_base_detached``).
* Owner-only on both project and KB; cross-user is 404 (matches the
  ``/files`` posture — see ``app.api.projects._load_visible_project``).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.knowledge import KnowledgeBase
from app.models.project import Project
from app.models.project_knowledge_base import ProjectKnowledgeBase
from app.models.user import User
from app.security import create_access_token, hash_password
from app.skills import load_registry
from app.skills.registry import MutableSkillRegistry
from tests.test_storage_streaming import FakeS3Client

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "skills"


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def fake_s3() -> FakeS3Client:
    return FakeS3Client()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, fake_s3: FakeS3Client) -> AsyncIterator[AsyncClient]:
    """In-process AsyncClient — same shape as test_projects_endpoints.py."""

    @asynccontextmanager
    async def _ctx() -> AsyncIterator[FakeS3Client]:
        yield fake_s3

    app.dependency_overrides[get_db] = _override_get_db(db_session)
    holder = MutableSkillRegistry(load_registry(FIXTURES_DIR))
    prior_holder = getattr(app.state, "skill_registry", None)
    app.state.skill_registry = holder

    transport = ASGITransport(app=app)
    with patch("app.storage.s3_client", _ctx):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    if prior_holder is None:
        delattr(app.state, "skill_registry")
    else:
        app.state.skill_registry = prior_holder
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def db_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"kbproj-{uuid.uuid4().hex[:8]}@example.com",
        display_name="KB Project Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"kbproj-other-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Other KB Project Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
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


async def _make_project(db_session: AsyncSession, owner: User, name: str = "Matter") -> Project:
    """Create a project owned by ``owner`` directly via the ORM."""

    project = Project(
        owner_id=owner.id,
        name=name,
        slug=f"matter-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(project)
    await db_session.flush()
    return project


async def _make_kb(db_session: AsyncSession, owner: User, name: str = "KB") -> KnowledgeBase:
    """Create a knowledge base owned by ``owner`` directly via the ORM."""

    kb = KnowledgeBase(
        owner_id=owner.id,
        name=name,
    )
    db_session.add(kb)
    await db_session.flush()
    return kb


# ---------------------------------------------------------------------------
# POST /api/v1/projects/{id}/knowledge-bases — attach
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_attach_kb_to_project_creates_junction(
    client: AsyncClient, db_user: User, db_session: AsyncSession
) -> None:
    project = await _make_project(db_session, db_user)
    kb = await _make_kb(db_session, db_user)

    response = await client.post(
        f"/api/v1/projects/{project.id}/knowledge-bases",
        json={"knowledge_base_id": str(kb.id)},
        headers=_h(db_user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # ProjectResponse exposes attached KB ids analogous to attached_file_ids.
    assert str(kb.id) in body.get("attached_knowledge_base_ids", [])

    pkb_row = await db_session.execute(
        select(ProjectKnowledgeBase).where(
            ProjectKnowledgeBase.project_id == project.id,
            ProjectKnowledgeBase.knowledge_base_id == kb.id,
        )
    )
    assert pkb_row.scalar_one_or_none() is not None


@pytest.mark.integration
async def test_attach_kb_writes_audit_row(
    client: AsyncClient, db_user: User, db_session: AsyncSession
) -> None:
    project = await _make_project(db_session, db_user)
    kb = await _make_kb(db_session, db_user)

    response = await client.post(
        f"/api/v1/projects/{project.id}/knowledge-bases",
        json={"knowledge_base_id": str(kb.id)},
        headers=_h(db_user),
    )
    assert response.status_code == 200, response.text

    audit_q = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "project.knowledge_base_attached",
            AuditLog.user_id == db_user.id,
        )
    )
    row = audit_q.scalar_one_or_none()
    assert row is not None
    assert row.resource_id == str(project.id)
    assert row.resource_type == "project"
    assert row.details is not None
    assert row.details.get("knowledge_base_id") == str(kb.id)


@pytest.mark.integration
async def test_attach_kb_idempotent(
    client: AsyncClient, db_user: User, db_session: AsyncSession
) -> None:
    """Re-attaching an already-attached KB returns 200 (no duplicate row)."""

    project = await _make_project(db_session, db_user)
    kb = await _make_kb(db_session, db_user)

    r1 = await client.post(
        f"/api/v1/projects/{project.id}/knowledge-bases",
        json={"knowledge_base_id": str(kb.id)},
        headers=_h(db_user),
    )
    r2 = await client.post(
        f"/api/v1/projects/{project.id}/knowledge-bases",
        json={"knowledge_base_id": str(kb.id)},
        headers=_h(db_user),
    )
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text

    # Composite PK means only one junction row exists.
    rows = await db_session.execute(
        select(ProjectKnowledgeBase).where(
            ProjectKnowledgeBase.project_id == project.id,
            ProjectKnowledgeBase.knowledge_base_id == kb.id,
        )
    )
    assert len(list(rows.scalars().all())) == 1


@pytest.mark.integration
async def test_attach_kb_nonexistent_kb_returns_404(
    client: AsyncClient, db_user: User, db_session: AsyncSession
) -> None:
    project = await _make_project(db_session, db_user)

    response = await client.post(
        f"/api/v1/projects/{project.id}/knowledge-bases",
        json={"knowledge_base_id": str(uuid.uuid4())},
        headers=_h(db_user),
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_attach_kb_non_owner_returns_404(
    client: AsyncClient,
    db_user: User,
    other_user: User,
    db_session: AsyncSession,
) -> None:
    """Cross-user attach fails — 404 (same posture as /files attach).

    The task spec allows 403 or 404; the existing codebase posture
    (see _load_visible_project) collapses cross-user to 404 to avoid
    leaking project existence.
    """

    project = await _make_project(db_session, db_user)
    kb = await _make_kb(db_session, db_user)

    response = await client.post(
        f"/api/v1/projects/{project.id}/knowledge-bases",
        json={"knowledge_base_id": str(kb.id)},
        headers=_h(other_user),
    )
    assert response.status_code in (403, 404)


@pytest.mark.integration
async def test_attach_cross_user_kb_returns_404(
    client: AsyncClient,
    db_user: User,
    other_user: User,
    db_session: AsyncSession,
) -> None:
    """Attaching another user's KB fails — 404, mirroring the cross-user file path."""

    project = await _make_project(db_session, db_user)
    foreign_kb = await _make_kb(db_session, other_user, name="theirs")

    response = await client.post(
        f"/api/v1/projects/{project.id}/knowledge-bases",
        json={"knowledge_base_id": str(foreign_kb.id)},
        headers=_h(db_user),
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/projects/{id}/knowledge-bases/{kb_id} — detach
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_detach_kb_removes_junction(
    client: AsyncClient, db_user: User, db_session: AsyncSession
) -> None:
    project = await _make_project(db_session, db_user)
    kb = await _make_kb(db_session, db_user)
    db_session.add(
        ProjectKnowledgeBase(
            project_id=project.id,
            knowledge_base_id=kb.id,
            attached_by_user_id=db_user.id,
        )
    )
    await db_session.flush()

    response = await client.delete(
        f"/api/v1/projects/{project.id}/knowledge-bases/{kb.id}",
        headers=_h(db_user),
    )
    assert response.status_code == 204

    result = await db_session.execute(
        select(ProjectKnowledgeBase).where(
            ProjectKnowledgeBase.project_id == project.id,
            ProjectKnowledgeBase.knowledge_base_id == kb.id,
        )
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.integration
async def test_detach_kb_writes_audit_row(
    client: AsyncClient, db_user: User, db_session: AsyncSession
) -> None:
    project = await _make_project(db_session, db_user)
    kb = await _make_kb(db_session, db_user)
    db_session.add(
        ProjectKnowledgeBase(
            project_id=project.id,
            knowledge_base_id=kb.id,
            attached_by_user_id=db_user.id,
        )
    )
    await db_session.flush()

    response = await client.delete(
        f"/api/v1/projects/{project.id}/knowledge-bases/{kb.id}",
        headers=_h(db_user),
    )
    assert response.status_code == 204

    audit_q = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "project.knowledge_base_detached",
            AuditLog.user_id == db_user.id,
        )
    )
    row = audit_q.scalar_one_or_none()
    assert row is not None
    assert row.resource_id == str(project.id)
    assert row.details is not None
    assert row.details.get("knowledge_base_id") == str(kb.id)


@pytest.mark.integration
async def test_detach_kb_idempotent_when_not_attached(
    client: AsyncClient, db_user: User, db_session: AsyncSession
) -> None:
    """Detaching a KB that isn't attached is a no-op 204."""

    project = await _make_project(db_session, db_user)
    kb = await _make_kb(db_session, db_user)

    response = await client.delete(
        f"/api/v1/projects/{project.id}/knowledge-bases/{kb.id}",
        headers=_h(db_user),
    )
    assert response.status_code == 204

    # No audit row should have been written (the handler only audits when
    # a join row is actually removed).
    audit_q = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "project.knowledge_base_detached")
    )
    assert audit_q.scalar_one_or_none() is None


@pytest.mark.integration
async def test_detach_kb_cross_user_project_returns_404(
    client: AsyncClient,
    db_user: User,
    other_user: User,
    db_session: AsyncSession,
) -> None:
    """Detaching from another user's project returns 404."""

    project = await _make_project(db_session, db_user)
    kb = await _make_kb(db_session, db_user)

    response = await client.delete(
        f"/api/v1/projects/{project.id}/knowledge-bases/{kb.id}",
        headers=_h(other_user),
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_detach_kb_invalid_uuid_returns_400(
    client: AsyncClient, db_user: User, db_session: AsyncSession
) -> None:
    """Invalid UUID in the path returns 400 — same as the detach_file path."""

    project = await _make_project(db_session, db_user)

    response = await client.delete(
        f"/api/v1/projects/{project.id}/knowledge-bases/not-a-uuid",
        headers=_h(db_user),
    )
    assert response.status_code == 400
