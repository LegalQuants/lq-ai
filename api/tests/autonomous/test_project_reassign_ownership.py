"""Matter (project_id) reassignment + ownership validation across the
autonomous schedule / watch / run-now surfaces.

Two concerns are exercised here:

1. **Reassignment** — ``project_id`` is now patchable on schedules and
   watches. An owned project_id is accepted (200, row reflects it); an
   explicit ``null`` clears the matter (unassign); an omitted project_id
   leaves the existing matter unchanged (``exclude_unset`` back-compat).

2. **Ownership** — assigning a non-null project_id the caller does not own
   (another user's project, or a random UUID) is rejected **404**
   (id-probing-safe via ``_load_owned_project``) on EVERY assignment site:
   create_schedule, update_schedule, create_watch, update_watch, and the
   run-now ``_spawn_manual_session``. On the update sites, the row MUST NOT
   be mutated when the foreign project is rejected.

Fixtures mirror ``test_schedules.py`` / ``test_watches.py`` / ``test_run_now.py``:
a per-file ``client`` fixture overriding ``get_db`` onto the SAVEPOINT
session, locally-built ``autonomous_enabled`` users, ``_bearer()`` headers,
and a stubbed enqueue so run-now never touches Redis.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.autonomous as autonomous_api
from app.db.session import get_db
from app.main import app
from app.models.autonomous import AutonomousSchedule, AutonomousSession, AutonomousWatch
from app.models.knowledge import KnowledgeBase
from app.models.project import Project
from app.models.user import User
from app.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


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


@pytest.fixture(autouse=True)
def _stub_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    """run-now enqueues onto arq; stub to an async no-op so missing Redis never errors."""
    monkeypatch.setattr(
        autonomous_api, "enqueue_autonomous_session_job", AsyncMock(return_value=True)
    )


async def _make_user(db: AsyncSession, *, suffix: str = "") -> User:
    user = User(
        email=f"reassign-{suffix or uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Reassign User {suffix}".strip(),
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
        autonomous_enabled=True,  # mutate endpoints require opt-in
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def user_a(db_session: AsyncSession) -> User:
    return await _make_user(db_session, suffix="a")


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    return await _make_user(db_session, suffix="b")


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


async def _make_project(db: AsyncSession, *, owner: User, name: str = "Acme Deal") -> Project:
    project = Project(
        owner_id=owner.id,
        name=name,
        slug=f"acme-{uuid.uuid4().hex[:8]}",
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return project


async def _make_schedule(
    db: AsyncSession,
    *,
    user: User,
    project_id: uuid.UUID | None = None,
    cron_expr: str = "*/5 * * * *",
) -> AutonomousSchedule:
    sched = AutonomousSchedule(
        user_id=user.id,
        cron_expr=cron_expr,
        enabled=True,
        project_id=project_id,
    )
    db.add(sched)
    await db.flush()
    await db.refresh(sched)
    return sched


async def _make_kb(db: AsyncSession, *, owner: User) -> KnowledgeBase:
    kb = KnowledgeBase(owner_id=owner.id, name="watched")
    db.add(kb)
    await db.flush()
    await db.refresh(kb)
    return kb


async def _make_watch(
    db: AsyncSession,
    *,
    user: User,
    kb: KnowledgeBase,
    project_id: uuid.UUID | None = None,
) -> AutonomousWatch:
    watch = AutonomousWatch(
        user_id=user.id,
        knowledge_base_id=kb.id,
        enabled=True,
        project_id=project_id,
        deleted_at=None,
    )
    db.add(watch)
    await db.flush()
    await db.refresh(watch)
    return watch


# ===========================================================================
# Schedule — create ownership
# ===========================================================================


@pytest.mark.integration
async def test_create_schedule_owned_project_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    project = await _make_project(db_session, owner=user_a)
    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "*/5 * * * *", "project_id": str(project.id)},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["project_id"] == str(project.id)


@pytest.mark.integration
async def test_create_schedule_no_project_succeeds(
    client: AsyncClient,
    user_a: User,
) -> None:
    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "*/5 * * * *"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["project_id"] is None


@pytest.mark.integration
async def test_create_schedule_foreign_project_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """The closed gap: project_id is from user input; another user's → 404 (no row)."""
    foreign = await _make_project(db_session, owner=user_b)
    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "*/5 * * * *", "project_id": str(foreign.id)},
    )
    assert resp.status_code == 404, resp.text
    # No schedule was created for user_a.
    rows = (
        (
            await db_session.execute(
                select(AutonomousSchedule).where(AutonomousSchedule.user_id == user_a.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


@pytest.mark.integration
async def test_create_schedule_nonexistent_project_returns_404(
    client: AsyncClient,
    user_a: User,
) -> None:
    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "*/5 * * * *", "project_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404, resp.text


# ===========================================================================
# Schedule — update (reassign / unassign / omit / foreign-404)
# ===========================================================================


@pytest.mark.integration
async def test_patch_schedule_reassigns_matter(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    old_project = await _make_project(db_session, owner=user_a, name="Old Matter")
    new_project = await _make_project(db_session, owner=user_a, name="New Matter")
    sched = await _make_schedule(db_session, user=user_a, project_id=old_project.id)

    resp = await client.patch(
        f"/api/v1/autonomous/schedules/{sched.id}",
        headers=_bearer(user_a),
        json={"project_id": str(new_project.id)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_id"] == str(new_project.id)

    await db_session.refresh(sched)
    assert sched.project_id == new_project.id


@pytest.mark.integration
async def test_patch_schedule_explicit_null_unassigns_matter(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    project = await _make_project(db_session, owner=user_a)
    sched = await _make_schedule(db_session, user=user_a, project_id=project.id)

    resp = await client.patch(
        f"/api/v1/autonomous/schedules/{sched.id}",
        headers=_bearer(user_a),
        json={"project_id": None},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_id"] is None

    await db_session.refresh(sched)
    assert sched.project_id is None


@pytest.mark.integration
async def test_patch_schedule_omitted_project_leaves_matter_unchanged(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """exclude_unset: a PATCH that does not send project_id must not clear it."""
    project = await _make_project(db_session, owner=user_a)
    sched = await _make_schedule(db_session, user=user_a, project_id=project.id)

    resp = await client.patch(
        f"/api/v1/autonomous/schedules/{sched.id}",
        headers=_bearer(user_a),
        json={"name": "renamed only"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_id"] == str(project.id)

    await db_session.refresh(sched)
    assert sched.project_id == project.id


@pytest.mark.integration
async def test_patch_schedule_foreign_project_returns_404_no_mutation(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    original = await _make_project(db_session, owner=user_a)
    foreign = await _make_project(db_session, owner=user_b)
    sched = await _make_schedule(db_session, user=user_a, project_id=original.id)

    resp = await client.patch(
        f"/api/v1/autonomous/schedules/{sched.id}",
        headers=_bearer(user_a),
        json={"project_id": str(foreign.id)},
    )
    assert resp.status_code == 404, resp.text

    # The row's matter is unchanged — the foreign assignment was rejected.
    await db_session.refresh(sched)
    assert sched.project_id == original.id


@pytest.mark.integration
async def test_patch_schedule_nonexistent_project_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    sched = await _make_schedule(db_session, user=user_a)
    resp = await client.patch(
        f"/api/v1/autonomous/schedules/{sched.id}",
        headers=_bearer(user_a),
        json={"project_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404, resp.text
    await db_session.refresh(sched)
    assert sched.project_id is None


# ===========================================================================
# Watch — create ownership
# ===========================================================================


@pytest.mark.integration
async def test_create_watch_owned_project_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    project = await _make_project(db_session, owner=user_a)
    resp = await client.post(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        json={"knowledge_base_id": str(kb.id), "project_id": str(project.id)},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["project_id"] == str(project.id)


@pytest.mark.integration
async def test_create_watch_no_project_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    resp = await client.post(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        json={"knowledge_base_id": str(kb.id)},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["project_id"] is None


@pytest.mark.integration
async def test_create_watch_foreign_project_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    foreign = await _make_project(db_session, owner=user_b)
    resp = await client.post(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        json={"knowledge_base_id": str(kb.id), "project_id": str(foreign.id)},
    )
    assert resp.status_code == 404, resp.text
    rows = (
        (
            await db_session.execute(
                select(AutonomousWatch).where(AutonomousWatch.user_id == user_a.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


@pytest.mark.integration
async def test_create_watch_nonexistent_project_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    resp = await client.post(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        json={"knowledge_base_id": str(kb.id), "project_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404, resp.text


# ===========================================================================
# Watch — update (reassign / unassign / omit / foreign-404)
# ===========================================================================


@pytest.mark.integration
async def test_patch_watch_reassigns_matter(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    old_project = await _make_project(db_session, owner=user_a, name="Old")
    new_project = await _make_project(db_session, owner=user_a, name="New")
    watch = await _make_watch(db_session, user=user_a, kb=kb, project_id=old_project.id)

    resp = await client.patch(
        f"/api/v1/autonomous/watches/{watch.id}",
        headers=_bearer(user_a),
        json={"project_id": str(new_project.id)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_id"] == str(new_project.id)

    await db_session.refresh(watch)
    assert watch.project_id == new_project.id


@pytest.mark.integration
async def test_patch_watch_explicit_null_unassigns_matter(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    project = await _make_project(db_session, owner=user_a)
    watch = await _make_watch(db_session, user=user_a, kb=kb, project_id=project.id)

    resp = await client.patch(
        f"/api/v1/autonomous/watches/{watch.id}",
        headers=_bearer(user_a),
        json={"project_id": None},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_id"] is None

    await db_session.refresh(watch)
    assert watch.project_id is None


@pytest.mark.integration
async def test_patch_watch_omitted_project_leaves_matter_unchanged(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    project = await _make_project(db_session, owner=user_a)
    watch = await _make_watch(db_session, user=user_a, kb=kb, project_id=project.id)

    resp = await client.patch(
        f"/api/v1/autonomous/watches/{watch.id}",
        headers=_bearer(user_a),
        json={"enabled": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_id"] == str(project.id)

    await db_session.refresh(watch)
    assert watch.project_id == project.id


@pytest.mark.integration
async def test_patch_watch_foreign_project_returns_404_no_mutation(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    original = await _make_project(db_session, owner=user_a)
    foreign = await _make_project(db_session, owner=user_b)
    watch = await _make_watch(db_session, user=user_a, kb=kb, project_id=original.id)

    resp = await client.patch(
        f"/api/v1/autonomous/watches/{watch.id}",
        headers=_bearer(user_a),
        json={"project_id": str(foreign.id)},
    )
    assert resp.status_code == 404, resp.text

    await db_session.refresh(watch)
    assert watch.project_id == original.id


@pytest.mark.integration
async def test_patch_watch_nonexistent_project_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    watch = await _make_watch(db_session, user=user_a, kb=kb)
    resp = await client.patch(
        f"/api/v1/autonomous/watches/{watch.id}",
        headers=_bearer(user_a),
        json={"project_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404, resp.text
    await db_session.refresh(watch)
    assert watch.project_id is None


# ===========================================================================
# Run-now — ownership
# ===========================================================================


@pytest.mark.integration
async def test_run_now_owned_project_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    project = await _make_project(db_session, owner=user_a)
    resp = await client.post(
        "/api/v1/autonomous/run-now",
        headers=_bearer(user_a),
        json={"skill_ref": "nda-review", "project_id": str(project.id)},
    )
    assert resp.status_code == 201, resp.text
    session_id = uuid.UUID(resp.json()["id"])
    row = (
        await db_session.execute(
            select(AutonomousSession).where(AutonomousSession.id == session_id)
        )
    ).scalar_one()
    assert row.project_id == project.id


@pytest.mark.integration
async def test_run_now_no_project_succeeds(
    client: AsyncClient,
    user_a: User,
) -> None:
    resp = await client.post(
        "/api/v1/autonomous/run-now",
        headers=_bearer(user_a),
        json={"skill_ref": "nda-review"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["project_id"] is None


@pytest.mark.integration
async def test_run_now_foreign_project_returns_404_no_session(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    foreign = await _make_project(db_session, owner=user_b)

    # Count sessions before to assert none were spawned for user_a.
    before = (
        (
            await db_session.execute(
                select(AutonomousSession).where(AutonomousSession.user_id == user_a.id)
            )
        )
        .scalars()
        .all()
    )

    resp = await client.post(
        "/api/v1/autonomous/run-now",
        headers=_bearer(user_a),
        json={"skill_ref": "nda-review", "project_id": str(foreign.id)},
    )
    assert resp.status_code == 404, resp.text

    after = (
        (
            await db_session.execute(
                select(AutonomousSession).where(AutonomousSession.user_id == user_a.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(after) == len(before)


@pytest.mark.integration
async def test_run_now_nonexistent_project_returns_404(
    client: AsyncClient,
    user_a: User,
) -> None:
    resp = await client.post(
        "/api/v1/autonomous/run-now",
        headers=_bearer(user_a),
        json={"skill_ref": "nda-review", "project_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404, resp.text


# ===========================================================================
# OpenAPI conformance — project_id on Update schemas
# ===========================================================================


@pytest.mark.unit
def test_openapi_update_schemas_carry_project_id() -> None:
    schemas = app.openapi().get("components", {}).get("schemas", {})
    sched_props = schemas["AutonomousScheduleUpdate"].get("properties", {})
    watch_props = schemas["AutonomousWatchUpdate"].get("properties", {})
    assert "project_id" in sched_props
    assert "project_id" in watch_props
