"""Tests for M4-B4 KB-arrival watches.

Covers:
- Trigger core ``fire_watches_for_kb`` (integration): a watched KB spawns
  exactly one session with trigger_kind='watch', trigger_ref, owner=watch.user,
  params{kb_id,file_id,target}; enqueue called once; unwatched kb → zero;
  two enabled watches → two; disabled/soft-deleted skipped; owner is the
  watch's user not the attacher.
- Best-effort regression (the M1-path guarantee): drive the real attach_file
  endpoint with the watch trigger monkeypatched to RAISE → attach still 204
  AND the join row is committed.
- CRUD API: create (201 + audit + KB-ownership 404); list (empty/filter by
  enabled + knowledge_base_id/pagination/newest-first/isolation/401); patch
  (toggle enabled, edit target, cross-user 404, 401); delete (soft-delete 200,
  excluded from list, re-delete 404, audit, cross-user 404, 401).
- OpenAPI conformance: 2 paths + 4 schemas.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.autonomous import AutonomousSession, AutonomousWatch
from app.models.file import File as FileModel
from app.models.knowledge import KnowledgeBase, KnowledgeBaseFile
from app.models.user import User
from app.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Fixtures and helpers (mirror test_schedules.py)
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
        email=f"watch-test-{suffix or uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Watch Test User {suffix}".strip(),
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


async def _make_kb(db: AsyncSession, *, owner: User, name: str = "watched") -> KnowledgeBase:
    kb = KnowledgeBase(owner_id=owner.id, name=name)
    db.add(kb)
    await db.flush()
    await db.refresh(kb)
    return kb


def _make_ready_file(owner_id: uuid.UUID, filename: str = "doc.pdf") -> FileModel:
    return FileModel(
        owner_id=owner_id,
        filename=filename,
        mime_type="application/pdf",
        size_bytes=10,
        hash_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        storage_path=str(uuid.uuid4()),
        ingestion_status="ready",
    )


async def _make_watch(
    db: AsyncSession,
    *,
    user: User,
    kb: KnowledgeBase,
    enabled: bool = True,
    deleted: bool = False,
    playbook_id: uuid.UUID | None = None,
    skill_ref: str | None = None,
) -> AutonomousWatch:
    watch = AutonomousWatch(
        user_id=user.id,
        knowledge_base_id=kb.id,
        enabled=enabled,
        deleted_at=datetime.now(UTC) if deleted else None,
        playbook_id=playbook_id,
        skill_ref=skill_ref,
    )
    db.add(watch)
    await db.flush()
    await db.refresh(watch)
    return watch


# ===========================================================================
# Trigger core — fire_watches_for_kb
# ===========================================================================


@pytest.mark.integration
async def test_fire_watches_spawns_one_session(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    from app.autonomous.watch_trigger import fire_watches_for_kb

    kb = await _make_kb(db_session, owner=user_a)
    watch = await _make_watch(db_session, user=user_a, kb=kb, skill_ref="nda-review")
    file_id = uuid.uuid4()

    enqueue = AsyncMock(return_value=True)
    count = await fire_watches_for_kb(db_session, kb_id=kb.id, file_id=file_id, enqueue=enqueue)

    assert count == 1

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
    assert sess.trigger_kind == "watch"
    assert sess.trigger_ref == watch.id
    assert sess.user_id == watch.user_id
    assert sess.status == "running"
    assert sess.current_phase == "intake"
    assert sess.params["kb_id"] == str(kb.id)
    assert sess.params["file_id"] == str(file_id)
    assert sess.params["skill_ref"] == "nda-review"
    # playbook_id was None — excluded from params (non-null subset).
    assert "playbook_id" not in sess.params

    enqueue.assert_awaited_once_with(sess.id)


@pytest.mark.integration
async def test_fire_watches_unwatched_kb_spawns_nothing(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    from app.autonomous.watch_trigger import fire_watches_for_kb

    # A watch exists, but on a DIFFERENT kb.
    other_kb = await _make_kb(db_session, owner=user_a, name="other")
    await _make_watch(db_session, user=user_a, kb=other_kb)

    enqueue = AsyncMock(return_value=True)
    count = await fire_watches_for_kb(
        db_session, kb_id=uuid.uuid4(), file_id=uuid.uuid4(), enqueue=enqueue
    )

    assert count == 0
    enqueue.assert_not_awaited()

    total = (
        await db_session.execute(select(func.count()).select_from(AutonomousSession))
    ).scalar_one()
    assert total == 0


@pytest.mark.integration
async def test_fire_watches_two_enabled_watches_two_sessions(
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    from app.autonomous.watch_trigger import fire_watches_for_kb

    # Two users can both watch the same KB (B is given a watch even though
    # KB ownership is A's — the trigger spawns per-watch regardless).
    kb = await _make_kb(db_session, owner=user_a)
    await _make_watch(db_session, user=user_a, kb=kb)
    await _make_watch(db_session, user=user_b, kb=kb)

    enqueue = AsyncMock(return_value=True)
    count = await fire_watches_for_kb(
        db_session, kb_id=kb.id, file_id=uuid.uuid4(), enqueue=enqueue
    )

    assert count == 2
    assert enqueue.await_count == 2

    total = (
        await db_session.execute(select(func.count()).select_from(AutonomousSession))
    ).scalar_one()
    assert total == 2


@pytest.mark.integration
async def test_fire_watches_disabled_skipped(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    from app.autonomous.watch_trigger import fire_watches_for_kb

    kb = await _make_kb(db_session, owner=user_a)
    await _make_watch(db_session, user=user_a, kb=kb, enabled=False)

    enqueue = AsyncMock(return_value=True)
    count = await fire_watches_for_kb(
        db_session, kb_id=kb.id, file_id=uuid.uuid4(), enqueue=enqueue
    )

    assert count == 0
    enqueue.assert_not_awaited()


@pytest.mark.integration
async def test_fire_watches_soft_deleted_skipped(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    from app.autonomous.watch_trigger import fire_watches_for_kb

    kb = await _make_kb(db_session, owner=user_a)
    await _make_watch(db_session, user=user_a, kb=kb, deleted=True)

    enqueue = AsyncMock(return_value=True)
    count = await fire_watches_for_kb(
        db_session, kb_id=kb.id, file_id=uuid.uuid4(), enqueue=enqueue
    )

    assert count == 0
    enqueue.assert_not_awaited()


@pytest.mark.integration
async def test_fire_watches_session_owned_by_watch_user_not_attacher(
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """The spawned session is owned by the watch's user, not whoever triggered.

    user_b owns the KB; user_a placed a watch on it. The session must be
    owned by user_a (the watch's user).
    """
    from app.autonomous.watch_trigger import fire_watches_for_kb

    kb = await _make_kb(db_session, owner=user_b)
    watch = await _make_watch(db_session, user=user_a, kb=kb)

    enqueue = AsyncMock(return_value=True)
    await fire_watches_for_kb(db_session, kb_id=kb.id, file_id=uuid.uuid4(), enqueue=enqueue)

    sess = (await db_session.execute(select(AutonomousSession))).scalars().one()
    assert sess.user_id == watch.user_id == user_a.id
    assert sess.user_id != user_b.id


# ===========================================================================
# Best-effort regression — attach is NOT rolled back by a trigger failure
# ===========================================================================


@pytest.mark.integration
async def test_attach_succeeds_even_when_watch_trigger_raises(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A watch-trigger failure must NOT fail or roll back the attach (M1 path).

    Drive the real attach_file endpoint with a watched KB where the trigger
    raises; assert the attach still returns 204 AND the join row is committed.
    """
    import app.autonomous.watch_trigger as wt_mod

    kb = await _make_kb(db_session, owner=user_a)
    await _make_watch(db_session, user=user_a, kb=kb)
    file_row = _make_ready_file(user_a.id)
    db_session.add(file_row)
    await db_session.flush()

    async def _boom(*_args: object, **_kwargs: object) -> int:
        raise RuntimeError("watch trigger exploded")

    monkeypatch.setattr(wt_mod, "fire_watches_for_kb", _boom)

    resp = await client.post(
        f"/api/v1/knowledge-bases/{kb.id}/files",
        headers=_bearer(user_a),
        json={"file_id": str(file_row.id)},
    )
    assert resp.status_code == 204, resp.text

    # The join row is committed despite the trigger blowing up.
    join = (
        await db_session.execute(
            select(KnowledgeBaseFile).where(
                KnowledgeBaseFile.kb_id == kb.id,
                KnowledgeBaseFile.file_id == file_row.id,
            )
        )
    ).scalar_one_or_none()
    assert join is not None


# ===========================================================================
# CRUD API — create
# ===========================================================================


@pytest.mark.integration
async def test_create_watch_returns_201_and_audits(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    from app.models.audit import AuditLog

    kb = await _make_kb(db_session, owner=user_a)

    resp = await client.post(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        json={"knowledge_base_id": str(kb.id), "skill_ref": "nda-review"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["knowledge_base_id"] == str(kb.id)
    assert body["skill_ref"] == "nda-review"
    assert body["enabled"] is True
    assert body["user_id"] == str(user_a.id)

    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_watch.create")
                .where(AuditLog.resource_id == body["id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
async def test_create_watch_on_unowned_kb_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """A caller cannot watch a KB they do not own — 404 (not 403)."""
    kb_b = await _make_kb(db_session, owner=user_b)

    resp = await client.post(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        json={"knowledge_base_id": str(kb_b.id)},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_create_watch_unknown_kb_returns_404(
    client: AsyncClient,
    user_a: User,
) -> None:
    resp = await client.post(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        json={"knowledge_base_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_create_watch_unauth_returns_401(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/autonomous/watches",
        json={"knowledge_base_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 401, resp.text


# ===========================================================================
# CRUD API — list
# ===========================================================================


@pytest.mark.integration
async def test_list_watches_empty_for_new_user(
    client: AsyncClient,
    user_a: User,
) -> None:
    resp = await client.get("/api/v1/autonomous/watches", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["watches"] == []
    assert body["total_count"] == 0
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.integration
async def test_list_watches_excludes_deleted(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    live = await _make_watch(db_session, user=user_a, kb=kb)
    gone = await _make_watch(db_session, user=user_a, kb=kb, deleted=True)

    resp = await client.get("/api/v1/autonomous/watches", headers=_bearer(user_a))
    ids = {w["id"] for w in resp.json()["watches"]}
    assert str(live.id) in ids
    assert str(gone.id) not in ids
    assert resp.json()["total_count"] == 1


@pytest.mark.integration
async def test_list_watches_filter_by_enabled(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    on = await _make_watch(db_session, user=user_a, kb=kb, enabled=True)
    off = await _make_watch(db_session, user=user_a, kb=kb, enabled=False)

    resp = await client.get(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        params={"enabled": "true"},
    )
    ids = {w["id"] for w in resp.json()["watches"]}
    assert str(on.id) in ids
    assert str(off.id) not in ids

    resp = await client.get(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        params={"enabled": "false"},
    )
    ids = {w["id"] for w in resp.json()["watches"]}
    assert str(off.id) in ids
    assert str(on.id) not in ids


@pytest.mark.integration
async def test_list_watches_filter_by_kb(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb1 = await _make_kb(db_session, owner=user_a, name="kb1")
    kb2 = await _make_kb(db_session, owner=user_a, name="kb2")
    w1 = await _make_watch(db_session, user=user_a, kb=kb1)
    w2 = await _make_watch(db_session, user=user_a, kb=kb2)

    resp = await client.get(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        params={"knowledge_base_id": str(kb1.id)},
    )
    ids = {w["id"] for w in resp.json()["watches"]}
    assert str(w1.id) in ids
    assert str(w2.id) not in ids


@pytest.mark.integration
async def test_list_watches_pagination_and_clamp(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    for _ in range(5):
        await _make_watch(db_session, user=user_a, kb=kb)

    resp = await client.get(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        params={"limit": 2, "offset": 1},
    )
    body = resp.json()
    assert len(body["watches"]) == 2
    assert body["total_count"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 1

    resp = await client.get(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        params={"limit": 9999},
    )
    assert resp.json()["limit"] == 200


@pytest.mark.integration
async def test_list_watches_newest_first(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    import datetime as _dt

    kb = await _make_kb(db_session, owner=user_a)
    for _ in range(3):
        await _make_watch(db_session, user=user_a, kb=kb)

    resp = await client.get("/api/v1/autonomous/watches", headers=_bearer(user_a))
    created = [_dt.datetime.fromisoformat(w["created_at"]) for w in resp.json()["watches"]]
    for i in range(len(created) - 1):
        assert created[i] >= created[i + 1]


@pytest.mark.integration
async def test_list_watches_isolation(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    kb_a = await _make_kb(db_session, owner=user_a)
    kb_b = await _make_kb(db_session, owner=user_b)
    wa = await _make_watch(db_session, user=user_a, kb=kb_a)
    wb = await _make_watch(db_session, user=user_b, kb=kb_b)

    resp = await client.get("/api/v1/autonomous/watches", headers=_bearer(user_a))
    ids = {w["id"] for w in resp.json()["watches"]}
    assert str(wa.id) in ids
    assert str(wb.id) not in ids
    assert resp.json()["total_count"] == 1


@pytest.mark.integration
async def test_list_watches_unauth_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/autonomous/watches")
    assert resp.status_code == 401, resp.text


# ===========================================================================
# CRUD API — patch
# ===========================================================================


@pytest.mark.integration
async def test_patch_watch_toggles_enabled(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    watch = await _make_watch(db_session, user=user_a, kb=kb, enabled=True)

    resp = await client.patch(
        f"/api/v1/autonomous/watches/{watch.id}",
        headers=_bearer(user_a),
        json={"enabled": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["enabled"] is False


@pytest.mark.integration
async def test_patch_watch_edits_target(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    watch = await _make_watch(db_session, user=user_a, kb=kb)

    resp = await client.patch(
        f"/api/v1/autonomous/watches/{watch.id}",
        headers=_bearer(user_a),
        json={"skill_ref": "msa-review-saas"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["skill_ref"] == "msa-review-saas"
    # knowledge_base_id is immutable — unchanged.
    assert resp.json()["knowledge_base_id"] == str(kb.id)


@pytest.mark.integration
async def test_patch_watch_cross_user_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    kb_b = await _make_kb(db_session, owner=user_b)
    watch_b = await _make_watch(db_session, user=user_b, kb=kb_b)
    resp = await client.patch(
        f"/api/v1/autonomous/watches/{watch_b.id}",
        headers=_bearer(user_a),
        json={"enabled": False},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_patch_watch_writes_audit_row(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    from app.models.audit import AuditLog

    kb = await _make_kb(db_session, owner=user_a)
    watch = await _make_watch(db_session, user=user_a, kb=kb)
    await client.patch(
        f"/api/v1/autonomous/watches/{watch.id}",
        headers=_bearer(user_a),
        json={"enabled": False},
    )
    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_watch.update")
                .where(AuditLog.resource_id == str(watch.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
async def test_patch_watch_unauth_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    watch = await _make_watch(db_session, user=user_a, kb=kb)
    resp = await client.patch(f"/api/v1/autonomous/watches/{watch.id}", json={"enabled": False})
    assert resp.status_code == 401, resp.text


# ===========================================================================
# CRUD API — delete (soft-delete, 200)
# ===========================================================================


@pytest.mark.integration
async def test_delete_watch_soft_deletes_returns_200(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    watch = await _make_watch(db_session, user=user_a, kb=kb)

    resp = await client.delete(f"/api/v1/autonomous/watches/{watch.id}", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(watch.id)
    assert body["deleted_at"] is not None

    await db_session.refresh(watch)
    assert watch.deleted_at is not None


@pytest.mark.integration
async def test_delete_watch_excluded_from_list(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    watch = await _make_watch(db_session, user=user_a, kb=kb)
    await client.delete(f"/api/v1/autonomous/watches/{watch.id}", headers=_bearer(user_a))

    resp = await client.get("/api/v1/autonomous/watches", headers=_bearer(user_a))
    assert str(watch.id) not in {w["id"] for w in resp.json()["watches"]}
    assert resp.json()["total_count"] == 0


@pytest.mark.integration
async def test_delete_watch_redelete_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    watch = await _make_watch(db_session, user=user_a, kb=kb)
    await client.delete(f"/api/v1/autonomous/watches/{watch.id}", headers=_bearer(user_a))

    resp = await client.delete(f"/api/v1/autonomous/watches/{watch.id}", headers=_bearer(user_a))
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_delete_watch_cross_user_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    kb_b = await _make_kb(db_session, owner=user_b)
    watch_b = await _make_watch(db_session, user=user_b, kb=kb_b)
    resp = await client.delete(f"/api/v1/autonomous/watches/{watch_b.id}", headers=_bearer(user_a))
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_delete_watch_writes_audit_row(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    from app.models.audit import AuditLog

    kb = await _make_kb(db_session, owner=user_a)
    watch = await _make_watch(db_session, user=user_a, kb=kb)
    await client.delete(f"/api/v1/autonomous/watches/{watch.id}", headers=_bearer(user_a))

    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_watch.delete")
                .where(AuditLog.resource_id == str(watch.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
async def test_delete_watch_unauth_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    kb = await _make_kb(db_session, owner=user_a)
    watch = await _make_watch(db_session, user=user_a, kb=kb)
    resp = await client.delete(f"/api/v1/autonomous/watches/{watch.id}")
    assert resp.status_code == 401, resp.text


# ===========================================================================
# OpenAPI conformance — unit
# ===========================================================================


@pytest.mark.unit
def test_openapi_watch_paths_registered() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/autonomous/watches" in paths
    assert "/api/v1/autonomous/watches/{watch_id}" in paths


@pytest.mark.unit
def test_openapi_watch_schemas_in_components() -> None:
    schemas = app.openapi().get("components", {}).get("schemas", {})
    assert "AutonomousWatchRead" in schemas
    assert "AutonomousWatchListResponse" in schemas
    assert "AutonomousWatchCreate" in schemas
    assert "AutonomousWatchUpdate" in schemas
