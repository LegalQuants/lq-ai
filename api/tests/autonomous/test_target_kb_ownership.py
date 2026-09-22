"""Target knowledge-base ownership validation on the autonomous assignment
surfaces: schedule create / PATCH, run-now, and watch create.

KB twin of ``test_project_reassign_ownership.py`` (the #133 matter lockdown).
``target_kb_id`` is caller input that the dispatcher copies verbatim into the
spawned session's ``params["kb_id"]`` — the id ``emit_artifact`` writes into.
A non-null id the caller does not own, that does not exist, or that is
archived is rejected **404** (id-probing-safe via ``_load_owned_kb``) at
every assignment site, and a rejected PATCH must not mutate the row. An
explicit null on PATCH still clears the target; an omitted field leaves it
unchanged (``exclude_unset``).

The emit-time half of the same gate is pinned in ``test_emit_artifact.py``.

Fixtures mirror ``test_project_reassign_ownership.py``: a per-file ``client``
overriding ``get_db`` onto the SAVEPOINT session, locally-built
``autonomous_enabled`` users, ``_bearer()`` headers, and a stubbed enqueue so
run-now never touches Redis.
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
from app.models.user import User
from app.security import create_access_token, hash_password

SCHEDULES = "/api/v1/autonomous/schedules"
RUN_NOW = "/api/v1/autonomous/run-now"
WATCHES = "/api/v1/autonomous/watches"
CRON = "*/5 * * * *"

pytestmark = pytest.mark.integration


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
    monkeypatch.setattr(
        autonomous_api, "enqueue_autonomous_session_job", AsyncMock(return_value=True)
    )


async def _make_user(db: AsyncSession, *, suffix: str) -> User:
    user = User(
        email=f"kb-own-{suffix}-{uuid.uuid4().hex[:8]}@example.com",
        display_name=f"KB Ownership User {suffix}",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
        autonomous_enabled=True,
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


async def _make_kb(db: AsyncSession, *, owner: User, archived: bool = False) -> KnowledgeBase:
    kb = KnowledgeBase(
        owner_id=owner.id,
        name=f"kb-{uuid.uuid4().hex[:6]}",
        archived_at=datetime.now(UTC) if archived else None,
    )
    db.add(kb)
    await db.flush()
    await db.refresh(kb)
    return kb


async def _make_schedule(
    db: AsyncSession, *, user: User, target_kb_id: uuid.UUID | None = None
) -> AutonomousSchedule:
    sched = AutonomousSchedule(
        user_id=user.id,
        cron_expr=CRON,
        enabled=True,
        target_kb_id=target_kb_id,
    )
    db.add(sched)
    await db.flush()
    await db.refresh(sched)
    return sched


async def _schedules_of(db: AsyncSession, user: User) -> list[AutonomousSchedule]:
    return list(
        (await db.execute(select(AutonomousSchedule).where(AutonomousSchedule.user_id == user.id)))
        .scalars()
        .all()
    )


# ===========================================================================
# Schedule — create
# ===========================================================================


async def test_create_schedule_owned_kb_accepted(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    resp = await client.post(
        SCHEDULES, headers=_bearer(user_a), json={"cron_expr": CRON, "target_kb_id": str(kb.id)}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["target_kb_id"] == str(kb.id)


async def test_create_schedule_foreign_kb_returns_404(
    client: AsyncClient, db_session: AsyncSession, user_a: User, user_b: User
) -> None:
    """The closed gap: another user's KB id → 404 and no row persisted."""
    foreign = await _make_kb(db_session, owner=user_b)
    resp = await client.post(
        SCHEDULES,
        headers=_bearer(user_a),
        json={"cron_expr": CRON, "target_kb_id": str(foreign.id)},
    )
    assert resp.status_code == 404, resp.text
    assert await _schedules_of(db_session, user_a) == []


async def test_create_schedule_unknown_kb_returns_404(client: AsyncClient, user_a: User) -> None:
    resp = await client.post(
        SCHEDULES,
        headers=_bearer(user_a),
        json={"cron_expr": CRON, "target_kb_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404, resp.text


async def test_create_schedule_archived_own_kb_returns_404(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    """Archived targets are unreachable at assignment, as they are at emit."""
    kb = await _make_kb(db_session, owner=user_a, archived=True)
    resp = await client.post(
        SCHEDULES, headers=_bearer(user_a), json={"cron_expr": CRON, "target_kb_id": str(kb.id)}
    )
    assert resp.status_code == 404, resp.text
    assert await _schedules_of(db_session, user_a) == []


# ===========================================================================
# Schedule — PATCH (reassign / clear / omit / foreign-404)
# ===========================================================================


async def test_patch_schedule_foreign_kb_returns_404_and_row_unchanged(
    client: AsyncClient, db_session: AsyncSession, user_a: User, user_b: User
) -> None:
    own = await _make_kb(db_session, owner=user_a)
    foreign = await _make_kb(db_session, owner=user_b)
    sched = await _make_schedule(db_session, user=user_a, target_kb_id=own.id)

    resp = await client.patch(
        f"{SCHEDULES}/{sched.id}",
        headers=_bearer(user_a),
        json={"target_kb_id": str(foreign.id)},
    )
    assert resp.status_code == 404, resp.text
    await db_session.refresh(sched)
    assert sched.target_kb_id == own.id


async def test_patch_schedule_owned_kb_reassigns(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    old = await _make_kb(db_session, owner=user_a)
    new = await _make_kb(db_session, owner=user_a)
    sched = await _make_schedule(db_session, user=user_a, target_kb_id=old.id)

    resp = await client.patch(
        f"{SCHEDULES}/{sched.id}", headers=_bearer(user_a), json={"target_kb_id": str(new.id)}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["target_kb_id"] == str(new.id)
    await db_session.refresh(sched)
    assert sched.target_kb_id == new.id


async def test_patch_schedule_explicit_null_clears_target_kb(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    sched = await _make_schedule(db_session, user=user_a, target_kb_id=kb.id)

    resp = await client.patch(
        f"{SCHEDULES}/{sched.id}", headers=_bearer(user_a), json={"target_kb_id": None}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["target_kb_id"] is None
    await db_session.refresh(sched)
    assert sched.target_kb_id is None


async def test_patch_schedule_omitted_target_kb_unchanged(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    sched = await _make_schedule(db_session, user=user_a, target_kb_id=kb.id)

    resp = await client.patch(
        f"{SCHEDULES}/{sched.id}", headers=_bearer(user_a), json={"name": "renamed only"}
    )
    assert resp.status_code == 200, resp.text
    await db_session.refresh(sched)
    assert sched.target_kb_id == kb.id


# ===========================================================================
# Run-now
# ===========================================================================


async def test_run_now_foreign_kb_returns_404_and_spawns_nothing(
    client: AsyncClient, db_session: AsyncSession, user_a: User, user_b: User
) -> None:
    foreign = await _make_kb(db_session, owner=user_b)
    resp = await client.post(
        RUN_NOW,
        headers=_bearer(user_a),
        json={"skill_ref": "nda-review", "target_kb_id": str(foreign.id)},
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


async def test_run_now_owned_kb_lands_in_params(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    resp = await client.post(
        RUN_NOW,
        headers=_bearer(user_a),
        json={"skill_ref": "nda-review", "target_kb_id": str(kb.id)},
    )
    assert resp.status_code == 201, resp.text
    row = (
        await db_session.execute(
            select(AutonomousSession).where(AutonomousSession.id == uuid.UUID(resp.json()["id"]))
        )
    ).scalar_one()
    assert row.params.get("kb_id") == str(kb.id)


# ===========================================================================
# Watch — create (now routed through the same loader: archived is refused)
# ===========================================================================


async def test_create_watch_archived_own_kb_returns_404(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    kb = await _make_kb(db_session, owner=user_a, archived=True)
    resp = await client.post(
        WATCHES,
        headers=_bearer(user_a),
        json={"knowledge_base_id": str(kb.id), "skill_ref": "nda-review"},
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
