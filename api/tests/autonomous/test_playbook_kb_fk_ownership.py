"""Playbook + target-KB FK ownership validation across the autonomous
schedule / watch / run-now surfaces (DE-322).

Post-#133, ``project_id`` is validated on every assignment site, but
``playbook_id`` and ``target_kb_id`` were still assigned unchecked. This
file exercises the closed gap:

* **Playbook** — a non-null ``playbook_id`` must be *visible* to the
  caller under the execute endpoint's rule
  (:func:`app.api.playbooks._load_visible_playbook`): own playbooks and
  built-ins (``created_by IS NULL``) are accepted; another user's or a
  soft-deleted playbook is rejected **404** (id-probing-safe) on
  create_schedule, update_schedule, create_watch, update_watch, and the
  run-now ``_spawn_manual_session``.
* **Target KB** — a non-null ``target_kb_id`` must be *owned* by the
  caller (same rule the watch's ``knowledge_base_id`` always had) on
  create_schedule, update_schedule, and run-now.
* On the update sites, the row MUST NOT be mutated when the foreign FK
  is rejected; an explicit ``null`` still clears the target.

Fixtures mirror ``test_project_reassign_ownership.py``: a per-file
``client`` fixture overriding ``get_db`` onto the SAVEPOINT session,
locally-built ``autonomous_enabled`` users, ``_bearer()`` headers, and a
stubbed enqueue so run-now never touches Redis.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
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
from app.models.playbook import Playbook
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
        email=f"fk-own-{suffix or uuid.uuid4().hex[:8]}@example.com",
        display_name=f"FK Ownership User {suffix}".strip(),
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


async def _make_playbook(
    db: AsyncSession,
    *,
    created_by: uuid.UUID | None,
    deleted_at: datetime | None = None,
) -> Playbook:
    """created_by=None mints a built-in (seed-style) playbook."""
    playbook = Playbook(
        name=f"FK Ownership Playbook {uuid.uuid4().hex[:8]}",
        contract_type="NDA",
        created_by=created_by,
        deleted_at=deleted_at,
    )
    db.add(playbook)
    await db.flush()
    await db.refresh(playbook)
    return playbook


async def _make_kb(db: AsyncSession, *, owner: User) -> KnowledgeBase:
    kb = KnowledgeBase(owner_id=owner.id, name="fk-own-kb")
    db.add(kb)
    await db.flush()
    await db.refresh(kb)
    return kb


async def _make_schedule(
    db: AsyncSession,
    *,
    user: User,
    playbook_id: uuid.UUID | None = None,
    target_kb_id: uuid.UUID | None = None,
    cron_expr: str = "*/5 * * * *",
) -> AutonomousSchedule:
    sched = AutonomousSchedule(
        user_id=user.id,
        cron_expr=cron_expr,
        enabled=True,
        playbook_id=playbook_id,
        target_kb_id=target_kb_id,
    )
    db.add(sched)
    await db.flush()
    await db.refresh(sched)
    return sched


async def _make_watch(
    db: AsyncSession,
    *,
    user: User,
    kb: KnowledgeBase,
    playbook_id: uuid.UUID | None = None,
) -> AutonomousWatch:
    watch = AutonomousWatch(
        user_id=user.id,
        knowledge_base_id=kb.id,
        enabled=True,
        playbook_id=playbook_id,
        deleted_at=None,
    )
    db.add(watch)
    await db.flush()
    await db.refresh(watch)
    return watch


# ===========================================================================
# Schedule — create (playbook visibility + target-KB ownership)
# ===========================================================================


@pytest.mark.integration
async def test_create_schedule_owned_playbook_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    playbook = await _make_playbook(db_session, created_by=user_a.id)
    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "*/5 * * * *", "playbook_id": str(playbook.id)},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["playbook_id"] == str(playbook.id)


@pytest.mark.integration
async def test_create_schedule_builtin_playbook_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Built-ins (created_by IS NULL) are visible to everyone."""
    builtin = await _make_playbook(db_session, created_by=None)
    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "*/5 * * * *", "playbook_id": str(builtin.id)},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["playbook_id"] == str(builtin.id)


@pytest.mark.integration
async def test_create_schedule_foreign_playbook_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """The closed gap: another user's playbook_id → 404, no row created."""
    foreign = await _make_playbook(db_session, created_by=user_b.id)
    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "*/5 * * * *", "playbook_id": str(foreign.id)},
    )
    assert resp.status_code == 404, resp.text
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
async def test_create_schedule_soft_deleted_playbook_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Soft-deleted playbooks are invisible to everyone — even their author."""
    tombstoned = await _make_playbook(
        db_session, created_by=user_a.id, deleted_at=datetime.now(UTC)
    )
    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "*/5 * * * *", "playbook_id": str(tombstoned.id)},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_create_schedule_nonexistent_playbook_returns_404(
    client: AsyncClient,
    user_a: User,
) -> None:
    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "*/5 * * * *", "playbook_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_create_schedule_owned_kb_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "*/5 * * * *", "target_kb_id": str(kb.id)},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["target_kb_id"] == str(kb.id)


@pytest.mark.integration
async def test_create_schedule_foreign_kb_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """The closed gap: another user's target_kb_id → 404, no row created."""
    foreign_kb = await _make_kb(db_session, owner=user_b)
    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "*/5 * * * *", "target_kb_id": str(foreign_kb.id)},
    )
    assert resp.status_code == 404, resp.text
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
async def test_create_schedule_nonexistent_kb_returns_404(
    client: AsyncClient,
    user_a: User,
) -> None:
    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "*/5 * * * *", "target_kb_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404, resp.text


# ===========================================================================
# Schedule — update (retarget / builtin / foreign-404 / null clears)
# ===========================================================================


@pytest.mark.integration
async def test_patch_schedule_owned_playbook_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    playbook = await _make_playbook(db_session, created_by=user_a.id)
    sched = await _make_schedule(db_session, user=user_a)

    resp = await client.patch(
        f"/api/v1/autonomous/schedules/{sched.id}",
        headers=_bearer(user_a),
        json={"playbook_id": str(playbook.id)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["playbook_id"] == str(playbook.id)

    await db_session.refresh(sched)
    assert sched.playbook_id == playbook.id


@pytest.mark.integration
async def test_patch_schedule_builtin_playbook_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    builtin = await _make_playbook(db_session, created_by=None)
    sched = await _make_schedule(db_session, user=user_a)

    resp = await client.patch(
        f"/api/v1/autonomous/schedules/{sched.id}",
        headers=_bearer(user_a),
        json={"playbook_id": str(builtin.id)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["playbook_id"] == str(builtin.id)


@pytest.mark.integration
async def test_patch_schedule_foreign_playbook_returns_404_no_mutation(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    original = await _make_playbook(db_session, created_by=user_a.id)
    foreign = await _make_playbook(db_session, created_by=user_b.id)
    sched = await _make_schedule(db_session, user=user_a, playbook_id=original.id)

    resp = await client.patch(
        f"/api/v1/autonomous/schedules/{sched.id}",
        headers=_bearer(user_a),
        json={"playbook_id": str(foreign.id)},
    )
    assert resp.status_code == 404, resp.text

    # The row's target is unchanged — the foreign assignment was rejected.
    await db_session.refresh(sched)
    assert sched.playbook_id == original.id


@pytest.mark.integration
async def test_patch_schedule_owned_kb_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    sched = await _make_schedule(db_session, user=user_a)

    resp = await client.patch(
        f"/api/v1/autonomous/schedules/{sched.id}",
        headers=_bearer(user_a),
        json={"target_kb_id": str(kb.id)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["target_kb_id"] == str(kb.id)

    await db_session.refresh(sched)
    assert sched.target_kb_id == kb.id


@pytest.mark.integration
async def test_patch_schedule_foreign_kb_returns_404_no_mutation(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    original_kb = await _make_kb(db_session, owner=user_a)
    foreign_kb = await _make_kb(db_session, owner=user_b)
    sched = await _make_schedule(db_session, user=user_a, target_kb_id=original_kb.id)

    resp = await client.patch(
        f"/api/v1/autonomous/schedules/{sched.id}",
        headers=_bearer(user_a),
        json={"target_kb_id": str(foreign_kb.id)},
    )
    assert resp.status_code == 404, resp.text

    await db_session.refresh(sched)
    assert sched.target_kb_id == original_kb.id


@pytest.mark.integration
async def test_patch_schedule_explicit_null_clears_targets(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Regression guard: an explicit null still clears playbook_id/target_kb_id."""
    playbook = await _make_playbook(db_session, created_by=user_a.id)
    kb = await _make_kb(db_session, owner=user_a)
    sched = await _make_schedule(
        db_session, user=user_a, playbook_id=playbook.id, target_kb_id=kb.id
    )

    resp = await client.patch(
        f"/api/v1/autonomous/schedules/{sched.id}",
        headers=_bearer(user_a),
        json={"playbook_id": None, "target_kb_id": None},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["playbook_id"] is None
    assert resp.json()["target_kb_id"] is None

    await db_session.refresh(sched)
    assert sched.playbook_id is None
    assert sched.target_kb_id is None


# ===========================================================================
# Watch — create (playbook visibility)
# ===========================================================================


@pytest.mark.integration
async def test_create_watch_owned_playbook_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    playbook = await _make_playbook(db_session, created_by=user_a.id)
    resp = await client.post(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        json={"knowledge_base_id": str(kb.id), "playbook_id": str(playbook.id)},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["playbook_id"] == str(playbook.id)


@pytest.mark.integration
async def test_create_watch_builtin_playbook_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    builtin = await _make_playbook(db_session, created_by=None)
    resp = await client.post(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        json={"knowledge_base_id": str(kb.id), "playbook_id": str(builtin.id)},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["playbook_id"] == str(builtin.id)


@pytest.mark.integration
async def test_create_watch_foreign_playbook_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """The closed gap: another user's playbook_id → 404, no row created."""
    kb = await _make_kb(db_session, owner=user_a)
    foreign = await _make_playbook(db_session, created_by=user_b.id)
    resp = await client.post(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        json={"knowledge_base_id": str(kb.id), "playbook_id": str(foreign.id)},
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


# ===========================================================================
# Watch — update (retarget / builtin / foreign-404)
# ===========================================================================


@pytest.mark.integration
async def test_patch_watch_builtin_playbook_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    builtin = await _make_playbook(db_session, created_by=None)
    watch = await _make_watch(db_session, user=user_a, kb=kb)

    resp = await client.patch(
        f"/api/v1/autonomous/watches/{watch.id}",
        headers=_bearer(user_a),
        json={"playbook_id": str(builtin.id)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["playbook_id"] == str(builtin.id)

    await db_session.refresh(watch)
    assert watch.playbook_id == builtin.id


@pytest.mark.integration
async def test_patch_watch_foreign_playbook_returns_404_no_mutation(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    original = await _make_playbook(db_session, created_by=user_a.id)
    foreign = await _make_playbook(db_session, created_by=user_b.id)
    watch = await _make_watch(db_session, user=user_a, kb=kb, playbook_id=original.id)

    resp = await client.patch(
        f"/api/v1/autonomous/watches/{watch.id}",
        headers=_bearer(user_a),
        json={"playbook_id": str(foreign.id)},
    )
    assert resp.status_code == 404, resp.text

    await db_session.refresh(watch)
    assert watch.playbook_id == original.id


# ===========================================================================
# Run-now — playbook visibility + target-KB ownership
# ===========================================================================


@pytest.mark.integration
async def test_run_now_owned_playbook_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    playbook = await _make_playbook(db_session, created_by=user_a.id)
    resp = await client.post(
        "/api/v1/autonomous/run-now",
        headers=_bearer(user_a),
        json={"playbook_id": str(playbook.id)},
    )
    assert resp.status_code == 201, resp.text
    session_id = uuid.UUID(resp.json()["id"])
    row = (
        await db_session.execute(
            select(AutonomousSession).where(AutonomousSession.id == session_id)
        )
    ).scalar_one()
    assert row.params.get("playbook_id") == str(playbook.id)


@pytest.mark.integration
async def test_run_now_builtin_playbook_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    builtin = await _make_playbook(db_session, created_by=None)
    resp = await client.post(
        "/api/v1/autonomous/run-now",
        headers=_bearer(user_a),
        json={"playbook_id": str(builtin.id)},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.integration
async def test_run_now_foreign_playbook_returns_404_no_session(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """The closed gap: another user's playbook_id → 404, no session spawned."""
    foreign = await _make_playbook(db_session, created_by=user_b.id)
    resp = await client.post(
        "/api/v1/autonomous/run-now",
        headers=_bearer(user_a),
        json={"playbook_id": str(foreign.id)},
    )
    assert resp.status_code == 404, resp.text
    rows = (
        (
            await db_session.execute(
                select(AutonomousSession).where(AutonomousSession.user_id == user_a.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


@pytest.mark.integration
async def test_run_now_owned_kb_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    resp = await client.post(
        "/api/v1/autonomous/run-now",
        headers=_bearer(user_a),
        json={"skill_ref": "nda-review", "target_kb_id": str(kb.id)},
    )
    assert resp.status_code == 201, resp.text
    session_id = uuid.UUID(resp.json()["id"])
    row = (
        await db_session.execute(
            select(AutonomousSession).where(AutonomousSession.id == session_id)
        )
    ).scalar_one()
    assert row.params.get("kb_id") == str(kb.id)


@pytest.mark.integration
async def test_run_now_foreign_kb_returns_404_no_session(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """The closed gap: another user's target_kb_id → 404, no session spawned."""
    foreign_kb = await _make_kb(db_session, owner=user_b)
    resp = await client.post(
        "/api/v1/autonomous/run-now",
        headers=_bearer(user_a),
        json={"skill_ref": "nda-review", "target_kb_id": str(foreign_kb.id)},
    )
    assert resp.status_code == 404, resp.text
    rows = (
        (
            await db_session.execute(
                select(AutonomousSession).where(AutonomousSession.user_id == user_a.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


# ---------------------------------------------------------------------------
# Archive predicate (DE-322 follow-up): a soft-deleted KB / project must not be
# re-attachable as an autonomous target. `_load_owned_kb` and `_load_owned_project`
# scoped by owner but not by `archived_at`, diverging from the house helpers
# `_load_visible_kb` / `_load_visible_project`. Invisible to CI until now because
# no fixture ever built an archived row.
# ---------------------------------------------------------------------------


async def _make_archived_kb(db: AsyncSession, *, owner: User) -> KnowledgeBase:
    """An owned KB that the owner has since deleted (DELETE /kb sets archived_at)."""
    kb = await _make_kb(db, owner=owner)
    kb.archived_at = datetime.now(UTC)
    await db.flush()
    return kb


async def _make_archived_project(db: AsyncSession, *, owner: User) -> Project:
    project = Project(owner_id=owner.id, name="archived matter", slug=f"m-{uuid.uuid4().hex[:8]}")
    db.add(project)
    await db.flush()
    project.archived_at = datetime.now(UTC)
    await db.flush()
    return project


@pytest.mark.integration
async def test_create_schedule_archived_kb_returns_404(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    """The owner's OWN archived KB is not a valid target — 404, no row.

    Without `archived_at IS NULL` the row still matches on id+owner, so a KB the
    user deleted would be silently resurrected as a recurring retrieval source.
    """
    archived = await _make_archived_kb(db_session, owner=user_a)
    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "*/5 * * * *", "target_kb_id": str(archived.id)},
    )
    assert resp.status_code == 404, resp.text
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
async def test_create_watch_archived_kb_returns_404(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    """Same on the watch surface — the highest-frequency trigger path."""
    archived = await _make_archived_kb(db_session, owner=user_a)
    resp = await client.post(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        json={"knowledge_base_id": str(archived.id)},
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
async def test_create_schedule_archived_project_returns_404(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    """`_load_owned_project` had the same omission — an archived matter must 404."""
    archived = await _make_archived_project(db_session, owner=user_a)
    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "*/5 * * * *", "project_id": str(archived.id)},
    )
    assert resp.status_code == 404, resp.text
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
