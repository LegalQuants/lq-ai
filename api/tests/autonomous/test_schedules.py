"""Tests for M4-B3 scheduled autonomous tasks.

Covers:
- Cron helper (unit): next-run math for several expressions; invalid → ValueError.
- Dispatcher core ``_run_schedule_sweep`` (integration): due schedule spawns
  exactly one session with trigger_kind='schedule', trigger_ref, params; enqueue
  called once; next_run_at advances; last_run_at set; future/disabled/deleted
  skipped; two due → two sessions.
- Executor seam: initial_state reads kb_id/query from session.params.
- CRUD API: create computes next_run_at + 201 + audit; invalid cron → 422;
  list (empty/filter/pagination/newest-first/isolation/401); patch (name,
  enabled toggle, cron recompute, cross-user 404, 401); delete (soft-delete 200,
  excluded from list, re-delete 404, audit, cross-user 404, 401).
- OpenAPI conformance: 2 paths + 4 schemas.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.autonomous import AutonomousSchedule, AutonomousSession
from app.models.user import User
from app.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Fixtures and helpers (mirror test_precedents.py)
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


async def _make_user(db: AsyncSession, *, suffix: str = "") -> User:
    user = User(
        email=f"sched-test-{suffix or uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Schedule Test User {suffix}".strip(),
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
        autonomous_enabled=True,  # M4-C2: mutate endpoints require opt-in
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


async def _make_schedule(
    db: AsyncSession,
    *,
    user: User,
    cron_expr: str = "*/5 * * * *",
    enabled: bool = True,
    next_run_at: datetime | None = None,
    deleted: bool = False,
    target_kb_id: uuid.UUID | None = None,
    playbook_id: uuid.UUID | None = None,
    skill_ref: str | None = None,
    name: str | None = None,
) -> AutonomousSchedule:
    sched = AutonomousSchedule(
        user_id=user.id,
        cron_expr=cron_expr,
        enabled=enabled,
        next_run_at=next_run_at,
        deleted_at=datetime.now(UTC) if deleted else None,
        target_kb_id=target_kb_id,
        playbook_id=playbook_id,
        skill_ref=skill_ref,
        name=name,
    )
    db.add(sched)
    await db.flush()
    await db.refresh(sched)
    return sched


# ===========================================================================
# Cron helper — unit
# ===========================================================================


@pytest.mark.unit
def test_cron_every_five_minutes() -> None:
    from app.autonomous.cron import next_run_after

    after = datetime(2026, 5, 25, 10, 2, 30, tzinfo=UTC)
    nxt = next_run_after("*/5 * * * *", after)
    assert nxt == datetime(2026, 5, 25, 10, 5, 0, tzinfo=UTC)


@pytest.mark.unit
def test_cron_strictly_after_on_boundary() -> None:
    """A moment that itself matches is skipped — result is strictly after."""
    from app.autonomous.cron import next_run_after

    after = datetime(2026, 5, 25, 10, 5, 0, tzinfo=UTC)
    nxt = next_run_after("*/5 * * * *", after)
    assert nxt == datetime(2026, 5, 25, 10, 10, 0, tzinfo=UTC)


@pytest.mark.unit
def test_cron_weekly_monday_9am() -> None:
    """0 9 * * 1 → next Monday 09:00 (cron dow 1 == Monday)."""
    from app.autonomous.cron import next_run_after

    # 2026-05-25 is a Monday.
    after = datetime(2026, 5, 25, 12, 0, 0, tzinfo=UTC)
    nxt = next_run_after("0 9 * * 1", after)
    # Next Monday 09:00 is 2026-06-01.
    assert nxt == datetime(2026, 6, 1, 9, 0, 0, tzinfo=UTC)
    assert nxt.weekday() == 0


@pytest.mark.unit
def test_cron_daily_midnight() -> None:
    from app.autonomous.cron import next_run_after

    after = datetime(2026, 5, 25, 13, 0, 0, tzinfo=UTC)
    nxt = next_run_after("0 0 * * *", after)
    assert nxt == datetime(2026, 5, 26, 0, 0, 0, tzinfo=UTC)


@pytest.mark.unit
def test_cron_range_and_list() -> None:
    from app.autonomous.cron import next_run_after

    # minute in {0,30}, hour in 9-17 — at 08:45 the next is 09:00.
    after = datetime(2026, 5, 25, 8, 45, 0, tzinfo=UTC)
    nxt = next_run_after("0,30 9-17 * * *", after)
    assert nxt == datetime(2026, 5, 25, 9, 0, 0, tzinfo=UTC)


@pytest.mark.unit
def test_cron_naive_treated_as_utc() -> None:
    from app.autonomous.cron import next_run_after

    after = datetime(2026, 5, 25, 10, 2, 0)  # naive
    nxt = next_run_after("*/5 * * * *", after)
    assert nxt.tzinfo is not None
    assert nxt == datetime(2026, 5, 25, 10, 5, 0, tzinfo=UTC)


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    [
        "",
        "* * * *",  # 4 fields
        "* * * * * *",  # 6 fields
        "60 * * * *",  # minute out of bounds
        "* 24 * * *",  # hour out of bounds
        "* * 0 * *",  # day-of-month < 1
        "* * * 13 *",  # month out of bounds
        "* * * * 8",  # day-of-week out of bounds (cron 0-7)
        "*/0 * * * *",  # step zero
        "5-1 * * * *",  # descending range
        "abc * * * *",  # non-numeric
    ],
)
def test_cron_invalid_raises(bad: str) -> None:
    from app.autonomous.cron import next_run_after, validate_cron_expr

    with pytest.raises(ValueError):
        validate_cron_expr(bad)
    with pytest.raises(ValueError):
        next_run_after(bad, datetime.now(UTC))


# --- I-1: DoM/DoW OR semantics (Vixie/POSIX) -------------------------------


@pytest.mark.unit
def test_cron_dom_and_dow_both_restricted_uses_or() -> None:
    """When BOTH day-of-month and day-of-week are restricted, fire on EITHER.

    ``0 0 13 * 5`` from 2026-05-25: the next Friday (2026-05-29) comes before
    the next 13th (2026-06-13), so OR semantics must return the Friday — NOT
    require both (Friday-the-13th, which would be 2026-11-13).
    """
    from app.autonomous.cron import next_run_after

    after = datetime(2026, 5, 25, 0, 0, 0, tzinfo=UTC)
    nxt = next_run_after("0 0 13 * 5", after)
    assert nxt == datetime(2026, 5, 29, 0, 0, 0, tzinfo=UTC)
    assert nxt.weekday() == 4  # Friday


@pytest.mark.unit
def test_cron_dom_only_restricted_unchanged() -> None:
    """Only day-of-month restricted (dow=*) → plain AND: the next 13th."""
    from app.autonomous.cron import next_run_after

    after = datetime(2026, 5, 25, 0, 0, 0, tzinfo=UTC)
    nxt = next_run_after("0 0 13 * *", after)
    assert nxt == datetime(2026, 6, 13, 0, 0, 0, tzinfo=UTC)


@pytest.mark.unit
def test_cron_dow_only_restricted_unchanged() -> None:
    """Only day-of-week restricted (dom=*) → plain AND: the next Friday."""
    from app.autonomous.cron import next_run_after

    after = datetime(2026, 5, 25, 0, 0, 0, tzinfo=UTC)
    nxt = next_run_after("0 0 * * 5", after)
    assert nxt == datetime(2026, 5, 29, 0, 0, 0, tzinfo=UTC)
    assert nxt.weekday() == 4  # Friday


# --- I-2: unsatisfiable-but-in-bounds exprs rejected at validation ---------


@pytest.mark.unit
def test_cron_unsatisfiable_feb30_rejected() -> None:
    """Feb 30 never occurs: in-bounds per field but unsatisfiable → ValueError."""
    from app.autonomous.cron import validate_cron_expr

    with pytest.raises(ValueError):
        validate_cron_expr("0 0 30 2 *")


@pytest.mark.unit
def test_cron_feb29_is_satisfiable_and_accepted() -> None:
    """Feb 29 occurs on leap years (within the ~4y horizon) → must NOT raise."""
    from app.autonomous.cron import validate_cron_expr

    validate_cron_expr("0 0 29 2 *")  # no raise


# ===========================================================================
# Dispatcher core — _run_schedule_sweep
# ===========================================================================


@pytest.mark.integration
async def test_dispatcher_due_schedule_spawns_one_session(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    from app.workers.autonomous_worker import _run_schedule_sweep

    now = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    sched = await _make_schedule(
        db_session,
        user=user_a,
        cron_expr="*/5 * * * *",
        next_run_at=now - timedelta(minutes=1),
        skill_ref="nda-review",
    )

    enqueue = AsyncMock(return_value=True)
    result = await _run_schedule_sweep(db_session, now=now, enqueue=enqueue)

    assert result == {"spawned": 1}

    sessions = (
        (
            await db_session.execute(
                select(AutonomousSession).where(AutonomousSession.user_id == user_a.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(sessions) == 1
    sess = sessions[0]
    assert sess.trigger_kind == "schedule"
    assert sess.trigger_ref == sched.id
    assert sess.status == "running"
    assert sess.current_phase == "intake"
    assert sess.params["skill_ref"] == "nda-review"
    # kb_id and playbook_id were None — excluded from params (non-null subset).
    assert "kb_id" not in sess.params
    assert "playbook_id" not in sess.params

    enqueue.assert_awaited_once_with(sess.id)

    await db_session.refresh(sched)
    assert sched.last_run_at == now
    assert sched.next_run_at is not None
    assert sched.next_run_at > now


@pytest.mark.integration
async def test_dispatcher_future_schedule_not_picked_up(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    from app.workers.autonomous_worker import _run_schedule_sweep

    now = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    await _make_schedule(db_session, user=user_a, next_run_at=now + timedelta(minutes=10))

    enqueue = AsyncMock(return_value=True)
    result = await _run_schedule_sweep(db_session, now=now, enqueue=enqueue)

    assert result == {"spawned": 0}
    enqueue.assert_not_awaited()


@pytest.mark.integration
async def test_dispatcher_disabled_schedule_skipped(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    from app.workers.autonomous_worker import _run_schedule_sweep

    now = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    await _make_schedule(
        db_session,
        user=user_a,
        enabled=False,
        next_run_at=now - timedelta(minutes=1),
    )

    enqueue = AsyncMock(return_value=True)
    result = await _run_schedule_sweep(db_session, now=now, enqueue=enqueue)

    assert result == {"spawned": 0}
    enqueue.assert_not_awaited()


@pytest.mark.integration
async def test_dispatcher_deleted_schedule_skipped(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    from app.workers.autonomous_worker import _run_schedule_sweep

    now = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    await _make_schedule(
        db_session,
        user=user_a,
        deleted=True,
        next_run_at=now - timedelta(minutes=1),
    )

    enqueue = AsyncMock(return_value=True)
    result = await _run_schedule_sweep(db_session, now=now, enqueue=enqueue)

    assert result == {"spawned": 0}
    enqueue.assert_not_awaited()


@pytest.mark.integration
async def test_dispatcher_two_due_schedules_two_sessions(
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    from app.workers.autonomous_worker import _run_schedule_sweep

    now = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    await _make_schedule(db_session, user=user_a, next_run_at=now - timedelta(minutes=1))
    await _make_schedule(db_session, user=user_b, next_run_at=now - timedelta(minutes=2))

    enqueue = AsyncMock(return_value=True)
    result = await _run_schedule_sweep(db_session, now=now, enqueue=enqueue)

    assert result == {"spawned": 2}
    assert enqueue.await_count == 2

    total = (
        await db_session.execute(select(func.count()).select_from(AutonomousSession))
    ).scalar_one()
    assert total == 2


@pytest.mark.integration
async def test_dispatcher_one_bad_schedule_does_not_abort_sweep(
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A schedule whose next_run_after raises must not block other due schedules.

    Validation now blocks poison exprs at create time, so drive the failure by
    monkeypatching the module's ``next_run_after`` symbol to raise for one
    schedule's cron and succeed for the other. The good schedule must still
    spawn + enqueue; the sweep must return without propagating.
    """
    import app.workers.autonomous_worker as worker_mod

    now = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    good = await _make_schedule(
        db_session,
        user=user_a,
        cron_expr="*/5 * * * *",
        next_run_at=now - timedelta(minutes=1),
        skill_ref="nda-review",
    )
    bad = await _make_schedule(
        db_session,
        user=user_b,
        cron_expr="0 0 30 2 *",  # pretend-poison row
        next_run_at=now - timedelta(minutes=2),
    )

    real_next = worker_mod.next_run_after

    def _fake_next(cron_expr: str, after: datetime) -> datetime:
        if cron_expr == bad.cron_expr:
            raise ValueError("no run time within the scan window")
        return real_next(cron_expr, after)

    monkeypatch.setattr(worker_mod, "next_run_after", _fake_next)

    enqueue = AsyncMock(return_value=True)
    # Must NOT raise even though one schedule's next_run_after raises.
    result = await _run_schedule_sweep_safe(db_session, now=now, enqueue=enqueue)

    # The good schedule spawned + enqueued.
    good_sessions = (
        (
            await db_session.execute(
                select(AutonomousSession).where(AutonomousSession.user_id == user_a.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(good_sessions) == 1
    enqueue.assert_any_await(good_sessions[0].id)
    assert result["spawned"] >= 1

    await db_session.refresh(good)
    assert good.next_run_at is not None and good.next_run_at > now


async def _run_schedule_sweep_safe(db_session, *, now, enqueue):  # type: ignore[no-untyped-def]
    """Helper: call the sweep and assert it returns rather than propagating."""
    from app.workers.autonomous_worker import _run_schedule_sweep

    return await _run_schedule_sweep(db_session, now=now, enqueue=enqueue)


# ===========================================================================
# Executor seam — initial_state reads from session.params
# ===========================================================================


@pytest.mark.integration
async def test_executor_seam_reads_kb_and_query_from_params(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """run_autonomous_session builds initial_state.kb_id/query from session.params."""
    captured: dict[str, object] = {}

    class _FakeGraph:
        async def ainvoke(self, state: dict[str, object]) -> dict[str, object]:
            captured.update(state)
            return {**state, "error": None}

    kb_id = str(uuid.uuid4())
    sess = AutonomousSession(
        user_id=user_a.id,
        trigger_kind="schedule",
        halt_state="running",
        status="running",
        current_phase="intake",
        params={"kb_id": kb_id, "query": "scan for liability caps"},
    )
    db_session.add(sess)
    await db_session.flush()
    await db_session.refresh(sess)

    import app.autonomous.executor as executor_mod
    from app.autonomous.executor import run_autonomous_session

    original_build = executor_mod._build_graph
    executor_mod._build_graph = lambda **_kw: _FakeGraph()  # type: ignore[assignment]
    try:
        await run_autonomous_session(db_session, session_id=sess.id, gateway=object())
    finally:
        executor_mod._build_graph = original_build  # type: ignore[assignment]

    assert captured["kb_id"] == kb_id
    assert captured["query"] == "scan for liability caps"


# ===========================================================================
# CRUD API — create
# ===========================================================================


@pytest.mark.integration
async def test_create_schedule_computes_next_run_and_audits(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    from app.models.audit import AuditLog

    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "*/5 * * * *", "name": "five-min scan"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["cron_expr"] == "*/5 * * * *"
    assert body["name"] == "five-min scan"
    assert body["enabled"] is True
    assert body["next_run_at"] is not None
    assert body["user_id"] == str(user_a.id)

    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_schedule.create")
                .where(AuditLog.resource_id == body["id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
async def test_create_schedule_invalid_cron_returns_422(
    client: AsyncClient,
    user_a: User,
) -> None:
    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "not a cron"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
async def test_create_schedule_unsatisfiable_cron_returns_422(
    client: AsyncClient,
    user_a: User,
) -> None:
    """An in-bounds-but-unsatisfiable expr (Feb 30) is rejected at create → 422."""
    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "0 0 30 2 *"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
async def test_create_schedule_unauth_returns_401(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/autonomous/schedules", json={"cron_expr": "*/5 * * * *"})
    assert resp.status_code == 401, resp.text


# ===========================================================================
# CRUD API — list
# ===========================================================================


@pytest.mark.integration
async def test_list_schedules_empty_for_new_user(
    client: AsyncClient,
    user_a: User,
) -> None:
    resp = await client.get("/api/v1/autonomous/schedules", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schedules"] == []
    assert body["total_count"] == 0
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.integration
async def test_list_schedules_excludes_deleted(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    live = await _make_schedule(db_session, user=user_a)
    gone = await _make_schedule(db_session, user=user_a, deleted=True)

    resp = await client.get("/api/v1/autonomous/schedules", headers=_bearer(user_a))
    body = resp.json()
    ids = {s["id"] for s in body["schedules"]}
    assert str(live.id) in ids
    assert str(gone.id) not in ids
    assert body["total_count"] == 1


@pytest.mark.integration
async def test_list_schedules_filter_by_enabled(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    on = await _make_schedule(db_session, user=user_a, enabled=True)
    off = await _make_schedule(db_session, user=user_a, enabled=False)

    resp = await client.get(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        params={"enabled": "true"},
    )
    ids = {s["id"] for s in resp.json()["schedules"]}
    assert str(on.id) in ids
    assert str(off.id) not in ids

    resp = await client.get(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        params={"enabled": "false"},
    )
    ids = {s["id"] for s in resp.json()["schedules"]}
    assert str(off.id) in ids
    assert str(on.id) not in ids


@pytest.mark.integration
async def test_list_schedules_pagination_and_clamp(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    for _ in range(5):
        await _make_schedule(db_session, user=user_a)

    resp = await client.get(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        params={"limit": 2, "offset": 1},
    )
    body = resp.json()
    assert len(body["schedules"]) == 2
    assert body["total_count"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 1

    resp = await client.get(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        params={"limit": 9999},
    )
    assert resp.json()["limit"] == 200


@pytest.mark.integration
async def test_list_schedules_newest_first(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    import datetime as _dt

    for _ in range(3):
        await _make_schedule(db_session, user=user_a)

    resp = await client.get("/api/v1/autonomous/schedules", headers=_bearer(user_a))
    created = [_dt.datetime.fromisoformat(s["created_at"]) for s in resp.json()["schedules"]]
    for i in range(len(created) - 1):
        assert created[i] >= created[i + 1]


@pytest.mark.integration
async def test_list_schedules_isolation(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    sa = await _make_schedule(db_session, user=user_a)
    sb = await _make_schedule(db_session, user=user_b)

    resp = await client.get("/api/v1/autonomous/schedules", headers=_bearer(user_a))
    ids = {s["id"] for s in resp.json()["schedules"]}
    assert str(sa.id) in ids
    assert str(sb.id) not in ids
    assert resp.json()["total_count"] == 1


@pytest.mark.integration
async def test_list_schedules_unauth_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/autonomous/schedules")
    assert resp.status_code == 401, resp.text


# ===========================================================================
# CRUD API — patch
# ===========================================================================


@pytest.mark.integration
async def test_patch_schedule_edits_name(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    sched = await _make_schedule(db_session, user=user_a, name="old")

    resp = await client.patch(
        f"/api/v1/autonomous/schedules/{sched.id}",
        headers=_bearer(user_a),
        json={"name": "new"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "new"


@pytest.mark.integration
async def test_patch_schedule_toggles_enabled(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    sched = await _make_schedule(db_session, user=user_a, enabled=True)

    resp = await client.patch(
        f"/api/v1/autonomous/schedules/{sched.id}",
        headers=_bearer(user_a),
        json={"enabled": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["enabled"] is False


@pytest.mark.integration
async def test_patch_schedule_cron_recomputes_next_run(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    import datetime as _dt

    sched = await _make_schedule(
        db_session,
        user=user_a,
        cron_expr="0 0 1 1 *",  # once a year
        next_run_at=datetime(2027, 1, 1, 0, 0, tzinfo=UTC),
    )

    resp = await client.patch(
        f"/api/v1/autonomous/schedules/{sched.id}",
        headers=_bearer(user_a),
        json={"cron_expr": "*/5 * * * *"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cron_expr"] == "*/5 * * * *"
    # next_run_at recomputed from now → soon, not the old 2027 value.
    new_next = _dt.datetime.fromisoformat(body["next_run_at"])
    assert new_next < datetime(2027, 1, 1, 0, 0, tzinfo=UTC)


@pytest.mark.integration
async def test_patch_schedule_invalid_cron_returns_422(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    sched = await _make_schedule(db_session, user=user_a)
    resp = await client.patch(
        f"/api/v1/autonomous/schedules/{sched.id}",
        headers=_bearer(user_a),
        json={"cron_expr": "bogus"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
async def test_patch_schedule_cross_user_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    sched_b = await _make_schedule(db_session, user=user_b)
    resp = await client.patch(
        f"/api/v1/autonomous/schedules/{sched_b.id}",
        headers=_bearer(user_a),
        json={"name": "hijack"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_patch_schedule_writes_audit_row(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    from app.models.audit import AuditLog

    sched = await _make_schedule(db_session, user=user_a)
    await client.patch(
        f"/api/v1/autonomous/schedules/{sched.id}",
        headers=_bearer(user_a),
        json={"name": "audited"},
    )
    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_schedule.update")
                .where(AuditLog.resource_id == str(sched.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
async def test_patch_schedule_unauth_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    sched = await _make_schedule(db_session, user=user_a)
    resp = await client.patch(f"/api/v1/autonomous/schedules/{sched.id}", json={"name": "x"})
    assert resp.status_code == 401, resp.text


# ===========================================================================
# CRUD API — delete (soft-delete, 200)
# ===========================================================================


@pytest.mark.integration
async def test_delete_schedule_soft_deletes_returns_200(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    sched = await _make_schedule(db_session, user=user_a)

    resp = await client.delete(f"/api/v1/autonomous/schedules/{sched.id}", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(sched.id)
    assert body["deleted_at"] is not None

    await db_session.refresh(sched)
    assert sched.deleted_at is not None


@pytest.mark.integration
async def test_delete_schedule_excluded_from_list(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    sched = await _make_schedule(db_session, user=user_a)
    await client.delete(f"/api/v1/autonomous/schedules/{sched.id}", headers=_bearer(user_a))

    resp = await client.get("/api/v1/autonomous/schedules", headers=_bearer(user_a))
    assert str(sched.id) not in {s["id"] for s in resp.json()["schedules"]}
    assert resp.json()["total_count"] == 0


@pytest.mark.integration
async def test_delete_schedule_redelete_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    sched = await _make_schedule(db_session, user=user_a)
    await client.delete(f"/api/v1/autonomous/schedules/{sched.id}", headers=_bearer(user_a))

    resp = await client.delete(f"/api/v1/autonomous/schedules/{sched.id}", headers=_bearer(user_a))
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_delete_schedule_cross_user_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    sched_b = await _make_schedule(db_session, user=user_b)
    resp = await client.delete(
        f"/api/v1/autonomous/schedules/{sched_b.id}", headers=_bearer(user_a)
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_delete_schedule_writes_audit_row(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    from app.models.audit import AuditLog

    sched = await _make_schedule(db_session, user=user_a)
    await client.delete(f"/api/v1/autonomous/schedules/{sched.id}", headers=_bearer(user_a))

    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_schedule.delete")
                .where(AuditLog.resource_id == str(sched.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
async def test_delete_schedule_unauth_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    sched = await _make_schedule(db_session, user=user_a)
    resp = await client.delete(f"/api/v1/autonomous/schedules/{sched.id}")
    assert resp.status_code == 401, resp.text


# ===========================================================================
# OpenAPI conformance — unit
# ===========================================================================


@pytest.mark.unit
def test_openapi_schedule_paths_registered() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/autonomous/schedules" in paths
    assert "/api/v1/autonomous/schedules/{schedule_id}" in paths


@pytest.mark.unit
def test_openapi_schedule_schemas_in_components() -> None:
    schemas = app.openapi().get("components", {}).get("schemas", {})
    assert "AutonomousScheduleRead" in schemas
    assert "AutonomousScheduleListResponse" in schemas
    assert "AutonomousScheduleCreate" in schemas
    assert "AutonomousScheduleUpdate" in schemas
