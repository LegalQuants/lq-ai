"""Integration tests for the M4-B1 per-user memory curation API.

Covers:
- No silent kept writes: propose_memory chokepoint always writes state='proposed'.
- GET /memory: filter by state, exclude soft-deleted, paginated, newest-first.
- POST /memory/{id}/keep: proposed→kept sets kept_at; edit-on-keep overrides content;
  re-keep (already kept) is allowed; dismissed→kept is allowed.
- POST /memory/{id}/dismiss: proposed→dismissed; kept→dismissed.
- DELETE /memory/{id}: soft-delete sets deleted_at; returns 200; subsequent GET
  excludes it; keep/dismiss/delete on deleted entry → 404.
- Isolation: user A's GET never returns user B's entries; A keep/dismiss/delete
  on B's entry → 404.
- load_kept_memory: returns only kept, non-deleted (excludes proposed/dismissed/deleted).
- Unauth → 401.
- OpenAPI conformance for the 4 memory paths.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.autonomous import AutonomousMemory, AutonomousSession
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


async def _make_user(db: AsyncSession, *, suffix: str = "") -> User:
    user = User(
        email=f"mem-test-{suffix or uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Memory Test User {suffix}".strip(),
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


async def _make_memory(
    db: AsyncSession,
    *,
    user: User,
    state: str = "proposed",
    category: str = "test_category",
    content: str = "test memory content",
    deleted: bool = False,
) -> AutonomousMemory:
    from datetime import UTC, datetime

    mem = AutonomousMemory(
        user_id=user.id,
        state=state,
        category=category,
        content=content,
        kept_at=datetime.now(UTC) if state == "kept" else None,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    db.add(mem)
    await db.flush()
    await db.refresh(mem)
    return mem


async def _make_session(db: AsyncSession, *, user: User) -> AutonomousSession:
    sess = AutonomousSession(
        user_id=user.id,
        trigger_kind="manual",
        halt_state="running",
        status="running",
        current_phase="intake",
    )
    db.add(sess)
    await db.flush()
    await db.refresh(sess)
    return sess


# ---------------------------------------------------------------------------
# No silent kept writes — propose_memory writes state='proposed'
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_propose_memory_always_writes_proposed(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """The propose_memory chokepoint handler always writes state='proposed'.

    The agent can only propose memory notes — it cannot directly write
    'kept' rows.  Keeping is exclusively a user curation action via the
    POST /memory/{id}/keep endpoint.
    """
    from app.autonomous.enums import ToolIntent
    from app.autonomous.guard import guarded_tool_call

    sess = await _make_session(db_session, user=user_a)
    # Phase must grant propose_memory — 'delivery' phase has it per PHASE_GRANTS.
    # Let's check: use 'intake' which is the starting phase.
    # We need a phase that grants propose_memory.
    from app.autonomous.enums import PHASE_GRANTS

    # Find a phase that grants propose_memory.
    granting_phase = next(
        (p for p, grants in PHASE_GRANTS.items() if ToolIntent.propose_memory in grants),
        None,
    )
    assert granting_phase is not None, "propose_memory must be granted in at least one phase"
    sess.current_phase = str(granting_phase)
    await db_session.flush()

    class _StubGateway:
        pass

    result = await guarded_tool_call(
        sess,
        ToolIntent.propose_memory,
        {"category": "drafting_preference", "content": "always use Oxford comma"},
        db_session,
        _StubGateway(),
    )

    memory_id = uuid.UUID(result.data["memory_id"])
    row = (
        await db_session.execute(select(AutonomousMemory).where(AutonomousMemory.id == memory_id))
    ).scalar_one()

    assert row.state == "proposed", (
        f"propose_memory must write state='proposed', got {row.state!r}. "
        "The agent cannot silently write 'kept' rows."
    )
    assert row.kept_at is None, "proposed rows must not have kept_at set"


# ---------------------------------------------------------------------------
# GET /autonomous/memory — list
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_memory_empty_for_new_user(
    client: AsyncClient,
    user_a: User,
) -> None:
    """A user with no memory entries gets entries=[] and total_count=0."""
    resp = await client.get("/api/v1/autonomous/memory", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["entries"] == []
    assert body["total_count"] == 0
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.integration
async def test_list_memory_excludes_soft_deleted(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Soft-deleted entries are excluded from list results."""
    _kept = await _make_memory(db_session, user=user_a, state="kept")
    _deleted = await _make_memory(db_session, user=user_a, state="proposed", deleted=True)

    resp = await client.get("/api/v1/autonomous/memory", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    ids = {e["id"] for e in body["entries"]}
    assert str(_kept.id) in ids
    assert str(_deleted.id) not in ids
    assert body["total_count"] == 1


@pytest.mark.integration
async def test_list_memory_filter_by_state(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """?state= filters to only that state; non-matching entries are excluded."""
    proposed = await _make_memory(db_session, user=user_a, state="proposed")
    kept = await _make_memory(db_session, user=user_a, state="kept")
    dismissed = await _make_memory(db_session, user=user_a, state="dismissed")

    # Filter proposed
    resp = await client.get(
        "/api/v1/autonomous/memory", headers=_bearer(user_a), params={"state": "proposed"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {e["id"] for e in body["entries"]}
    assert str(proposed.id) in ids
    assert str(kept.id) not in ids
    assert str(dismissed.id) not in ids
    assert body["total_count"] == 1

    # Filter kept
    resp = await client.get(
        "/api/v1/autonomous/memory", headers=_bearer(user_a), params={"state": "kept"}
    )
    body = resp.json()
    ids = {e["id"] for e in body["entries"]}
    assert str(kept.id) in ids
    assert str(proposed.id) not in ids
    assert body["total_count"] == 1

    # Filter dismissed
    resp = await client.get(
        "/api/v1/autonomous/memory", headers=_bearer(user_a), params={"state": "dismissed"}
    )
    body = resp.json()
    ids = {e["id"] for e in body["entries"]}
    assert str(dismissed.id) in ids
    assert str(proposed.id) not in ids
    assert body["total_count"] == 1


@pytest.mark.integration
async def test_list_memory_no_filter_returns_all_non_deleted(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Without a state filter, all non-deleted entries are returned."""
    proposed = await _make_memory(db_session, user=user_a, state="proposed")
    kept = await _make_memory(db_session, user=user_a, state="kept")
    dismissed = await _make_memory(db_session, user=user_a, state="dismissed")
    _deleted = await _make_memory(db_session, user=user_a, deleted=True)

    resp = await client.get("/api/v1/autonomous/memory", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {e["id"] for e in body["entries"]}
    assert str(proposed.id) in ids
    assert str(kept.id) in ids
    assert str(dismissed.id) in ids
    assert str(_deleted.id) not in ids
    assert body["total_count"] == 3


@pytest.mark.integration
async def test_list_memory_pagination(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """limit and offset are honoured; total_count reflects unfiltered count."""
    for _ in range(5):
        await _make_memory(db_session, user=user_a, state="proposed")

    resp = await client.get(
        "/api/v1/autonomous/memory",
        headers=_bearer(user_a),
        params={"limit": 2, "offset": 1},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["entries"]) == 2
    assert body["total_count"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 1


@pytest.mark.integration
async def test_list_memory_limit_clamped(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """limit > 200 is clamped to 200."""
    resp = await client.get(
        "/api/v1/autonomous/memory",
        headers=_bearer(user_a),
        params={"limit": 9999},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["limit"] == 200


@pytest.mark.integration
async def test_list_memory_newest_first(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Entries are returned in created_at DESC order.

    Within the same transaction, all rows may share the same `created_at`
    timestamp (DB `now()` is constant per statement in a txn).  The test
    verifies the sort key is non-increasing across the returned entries,
    which is the correct contract regardless of whether timestamps differ.
    """
    mem1 = await _make_memory(db_session, user=user_a, content="first")
    mem2 = await _make_memory(db_session, user=user_a, content="second")
    mem3 = await _make_memory(db_session, user=user_a, content="third")

    resp = await client.get("/api/v1/autonomous/memory", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    entries = body["entries"]
    ids = [e["id"] for e in entries]

    # All present
    assert str(mem1.id) in ids
    assert str(mem2.id) in ids
    assert str(mem3.id) in ids
    assert body["total_count"] == 3

    # Sort key is non-increasing (DESC) across all returned entries.
    import datetime as _dt

    created_ats = [_dt.datetime.fromisoformat(e["created_at"]) for e in entries]
    for i in range(len(created_ats) - 1):
        assert created_ats[i] >= created_ats[i + 1], (
            f"List is not in created_at DESC order at index {i}: "
            f"{created_ats[i]} < {created_ats[i + 1]}"
        )


@pytest.mark.integration
async def test_list_memory_isolation(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """User A's list never returns user B's entries."""
    mem_a = await _make_memory(db_session, user=user_a)
    mem_b = await _make_memory(db_session, user=user_b)

    resp = await client.get("/api/v1/autonomous/memory", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {e["id"] for e in body["entries"]}
    assert str(mem_a.id) in ids
    assert str(mem_b.id) not in ids
    assert body["total_count"] == 1


@pytest.mark.integration
async def test_list_memory_filter_by_source_session_id(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """?source_session_id= narrows to the memories a specific run proposed.

    Omitting the filter returns all of the user's non-deleted memories
    (back-compat); supplying it returns only the matching run's memories.
    """
    sess_a = await _make_session(db_session, user=user_a)
    sess_b = await _make_session(db_session, user=user_a)

    mem_a1 = await _make_memory(db_session, user=user_a)
    mem_a1.source_session_id = sess_a.id
    mem_a2 = await _make_memory(db_session, user=user_a)
    mem_a2.source_session_id = sess_a.id
    mem_b = await _make_memory(db_session, user=user_a)
    mem_b.source_session_id = sess_b.id
    await db_session.flush()

    # Filtered to run A
    resp = await client.get(
        "/api/v1/autonomous/memory",
        headers=_bearer(user_a),
        params={"source_session_id": str(sess_a.id)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {e["id"] for e in body["entries"]}
    assert ids == {str(mem_a1.id), str(mem_a2.id)}
    assert str(mem_b.id) not in ids
    assert body["total_count"] == 2

    # Omitted → all three (back-compat).
    resp = await client.get("/api/v1/autonomous/memory", headers=_bearer(user_a))
    body = resp.json()
    assert body["total_count"] == 3


@pytest.mark.integration
async def test_list_memory_unauth_returns_401(client: AsyncClient) -> None:
    """No Authorization header returns 401."""
    resp = await client.get("/api/v1/autonomous/memory")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# POST /autonomous/memory/{id}/keep
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_keep_proposed_sets_kept_at(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Keep transitions proposed→kept and sets kept_at."""
    mem = await _make_memory(db_session, user=user_a, state="proposed")

    resp = await client.post(
        f"/api/v1/autonomous/memory/{mem.id}/keep",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "kept"
    assert body["kept_at"] is not None
    assert body["id"] == str(mem.id)

    # DB reflects the change
    await db_session.refresh(mem)
    assert mem.state == "kept"
    assert mem.kept_at is not None


@pytest.mark.integration
async def test_keep_edit_on_keep_overrides_content(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Edit-on-keep: providing content in the body overwrites the entry's text."""
    mem = await _make_memory(db_session, user=user_a, state="proposed", content="original")

    resp = await client.post(
        f"/api/v1/autonomous/memory/{mem.id}/keep",
        headers=_bearer(user_a),
        json={"content": "updated content"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["content"] == "updated content"
    assert body["state"] == "kept"

    await db_session.refresh(mem)
    assert mem.content == "updated content"


@pytest.mark.integration
async def test_keep_no_body_preserves_content(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Keep without body leaves content unchanged."""
    mem = await _make_memory(db_session, user=user_a, state="proposed", content="preserve me")

    resp = await client.post(
        f"/api/v1/autonomous/memory/{mem.id}/keep",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["content"] == "preserve me"


@pytest.mark.integration
async def test_keep_null_content_in_body_preserves_content(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Keep with content=null in body leaves content unchanged."""
    mem = await _make_memory(db_session, user=user_a, state="proposed", content="preserve me")

    resp = await client.post(
        f"/api/v1/autonomous/memory/{mem.id}/keep",
        headers=_bearer(user_a),
        json={"content": None},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["content"] == "preserve me"


@pytest.mark.integration
async def test_keep_dismissed_to_kept_allowed(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """dismissed→kept transition is allowed (un-dismiss)."""
    mem = await _make_memory(db_session, user=user_a, state="dismissed")

    resp = await client.post(
        f"/api/v1/autonomous/memory/{mem.id}/keep",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "kept"


@pytest.mark.integration
async def test_keep_already_kept_is_idempotent(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Re-keeping an already-kept entry is allowed; kept_at is preserved."""
    mem = await _make_memory(db_session, user=user_a, state="kept")
    original_kept_at = mem.kept_at

    resp = await client.post(
        f"/api/v1/autonomous/memory/{mem.id}/keep",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "kept"
    # kept_at should be preserved (not reset)
    assert body["kept_at"] is not None
    # The kept_at value should match the original
    import datetime as _dt

    returned_kept_at = _dt.datetime.fromisoformat(body["kept_at"])
    if original_kept_at is not None:
        # Allow timezone-aware comparison
        if returned_kept_at.tzinfo is None:
            returned_kept_at = returned_kept_at.replace(tzinfo=_dt.UTC)
        if original_kept_at.tzinfo is None:
            original_kept_at = original_kept_at.replace(tzinfo=_dt.UTC)
        assert returned_kept_at == original_kept_at


@pytest.mark.integration
async def test_keep_writes_audit_row(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Keep writes an autonomous_memory.keep audit row."""
    from sqlalchemy import select as _select

    from app.models.audit import AuditLog

    mem = await _make_memory(db_session, user=user_a, state="proposed")

    await client.post(
        f"/api/v1/autonomous/memory/{mem.id}/keep",
        headers=_bearer(user_a),
    )

    rows = (
        (
            await db_session.execute(
                _select(AuditLog)
                .where(AuditLog.action == "autonomous_memory.keep")
                .where(AuditLog.resource_id == str(mem.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
async def test_keep_cross_user_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """Keep on another user's memory entry returns 404."""
    mem_b = await _make_memory(db_session, user=user_b, state="proposed")

    resp = await client.post(
        f"/api/v1/autonomous/memory/{mem_b.id}/keep",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_keep_unauth_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """No Authorization header returns 401."""
    mem = await _make_memory(db_session, user=user_a)
    resp = await client.post(f"/api/v1/autonomous/memory/{mem.id}/keep")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# POST /autonomous/memory/{id}/dismiss
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_dismiss_proposed_to_dismissed(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Dismiss transitions proposed→dismissed."""
    mem = await _make_memory(db_session, user=user_a, state="proposed")

    resp = await client.post(
        f"/api/v1/autonomous/memory/{mem.id}/dismiss",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "dismissed"
    assert body["id"] == str(mem.id)

    await db_session.refresh(mem)
    assert mem.state == "dismissed"


@pytest.mark.integration
async def test_dismiss_kept_to_dismissed(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Dismiss transitions kept→dismissed."""
    mem = await _make_memory(db_session, user=user_a, state="kept")

    resp = await client.post(
        f"/api/v1/autonomous/memory/{mem.id}/dismiss",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "dismissed"


@pytest.mark.integration
async def test_dismiss_writes_audit_row(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Dismiss writes an autonomous_memory.dismiss audit row."""
    from sqlalchemy import select as _select

    from app.models.audit import AuditLog

    mem = await _make_memory(db_session, user=user_a, state="proposed")
    await client.post(
        f"/api/v1/autonomous/memory/{mem.id}/dismiss",
        headers=_bearer(user_a),
    )

    rows = (
        (
            await db_session.execute(
                _select(AuditLog)
                .where(AuditLog.action == "autonomous_memory.dismiss")
                .where(AuditLog.resource_id == str(mem.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
async def test_dismiss_cross_user_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """Dismiss on another user's memory entry returns 404."""
    mem_b = await _make_memory(db_session, user=user_b, state="proposed")

    resp = await client.post(
        f"/api/v1/autonomous/memory/{mem_b.id}/dismiss",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_dismiss_unauth_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """No Authorization header returns 401."""
    mem = await _make_memory(db_session, user=user_a)
    resp = await client.post(f"/api/v1/autonomous/memory/{mem.id}/dismiss")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# DELETE /autonomous/memory/{id} — soft delete
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_delete_soft_deletes_entry(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Delete sets deleted_at, returns 200 with the updated entry."""
    mem = await _make_memory(db_session, user=user_a, state="proposed")

    resp = await client.delete(
        f"/api/v1/autonomous/memory/{mem.id}",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(mem.id)
    assert body["deleted_at"] is not None

    await db_session.refresh(mem)
    assert mem.deleted_at is not None


@pytest.mark.integration
async def test_delete_excluded_from_subsequent_list(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """After delete, the entry is excluded from GET /memory list."""
    mem = await _make_memory(db_session, user=user_a, state="proposed")

    await client.delete(f"/api/v1/autonomous/memory/{mem.id}", headers=_bearer(user_a))

    resp = await client.get("/api/v1/autonomous/memory", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {e["id"] for e in body["entries"]}
    assert str(mem.id) not in ids
    assert body["total_count"] == 0


@pytest.mark.integration
async def test_keep_on_deleted_entry_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Keep on a soft-deleted entry returns 404."""
    mem = await _make_memory(db_session, user=user_a, deleted=True)

    resp = await client.post(
        f"/api/v1/autonomous/memory/{mem.id}/keep",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_dismiss_on_deleted_entry_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Dismiss on a soft-deleted entry returns 404."""
    mem = await _make_memory(db_session, user=user_a, deleted=True)

    resp = await client.post(
        f"/api/v1/autonomous/memory/{mem.id}/dismiss",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_delete_on_deleted_entry_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Delete on an already soft-deleted entry returns 404."""
    mem = await _make_memory(db_session, user=user_a, deleted=True)

    resp = await client.delete(
        f"/api/v1/autonomous/memory/{mem.id}",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_delete_writes_audit_row(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Delete writes an autonomous_memory.delete audit row."""
    from sqlalchemy import select as _select

    from app.models.audit import AuditLog

    mem = await _make_memory(db_session, user=user_a, state="proposed")
    await client.delete(f"/api/v1/autonomous/memory/{mem.id}", headers=_bearer(user_a))

    rows = (
        (
            await db_session.execute(
                _select(AuditLog)
                .where(AuditLog.action == "autonomous_memory.delete")
                .where(AuditLog.resource_id == str(mem.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
async def test_delete_cross_user_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """Delete on another user's memory entry returns 404."""
    mem_b = await _make_memory(db_session, user=user_b, state="proposed")

    resp = await client.delete(
        f"/api/v1/autonomous/memory/{mem_b.id}",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_delete_unauth_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """No Authorization header returns 401."""
    mem = await _make_memory(db_session, user=user_a)
    resp = await client.delete(f"/api/v1/autonomous/memory/{mem.id}")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# load_kept_memory — injection helper
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_load_kept_memory_returns_only_kept_non_deleted(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """load_kept_memory returns only kept, non-deleted entries.

    Explicitly verifies:
    - proposed entries are excluded
    - dismissed entries are excluded
    - soft-deleted kept entries are excluded
    - non-deleted kept entries are included
    """
    from app.autonomous.memory import load_kept_memory

    kept = await _make_memory(db_session, user=user_a, state="kept")
    _proposed = await _make_memory(db_session, user=user_a, state="proposed")
    _dismissed = await _make_memory(db_session, user=user_a, state="dismissed")
    _kept_deleted = await _make_memory(db_session, user=user_a, state="kept", deleted=True)

    result = await load_kept_memory(db_session, user_a.id)
    result_ids = {r.id for r in result}

    assert kept.id in result_ids, "kept non-deleted entry must be included"
    assert _proposed.id not in result_ids, "proposed entry must be excluded"
    assert _dismissed.id not in result_ids, "dismissed entry must be excluded"
    assert _kept_deleted.id not in result_ids, "soft-deleted kept entry must be excluded"


@pytest.mark.integration
async def test_load_kept_memory_isolation(
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """load_kept_memory returns only the specified user's kept entries."""
    from app.autonomous.memory import load_kept_memory

    kept_a = await _make_memory(db_session, user=user_a, state="kept")
    _kept_b = await _make_memory(db_session, user=user_b, state="kept")

    result_a = await load_kept_memory(db_session, user_a.id)
    ids_a = {r.id for r in result_a}
    assert kept_a.id in ids_a
    assert _kept_b.id not in ids_a


@pytest.mark.integration
async def test_load_kept_memory_empty_for_no_kept(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """load_kept_memory returns empty list when no kept entries exist."""
    from app.autonomous.memory import load_kept_memory

    await _make_memory(db_session, user=user_a, state="proposed")

    result = await load_kept_memory(db_session, user_a.id)
    assert result == []


# ---------------------------------------------------------------------------
# OpenAPI conformance
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_openapi_memory_paths_registered() -> None:
    """The four memory curation paths are registered in the OpenAPI spec."""
    schema = app.openapi()
    paths = schema["paths"]
    assert "/api/v1/autonomous/memory" in paths
    assert "/api/v1/autonomous/memory/{memory_id}/keep" in paths
    assert "/api/v1/autonomous/memory/{memory_id}/dismiss" in paths
    assert "/api/v1/autonomous/memory/{memory_id}" in paths


@pytest.mark.unit
def test_openapi_memory_list_response_schema() -> None:
    """GET /memory response references AutonomousMemoryListResponse."""
    schema = app.openapi()
    get_op = schema["paths"]["/api/v1/autonomous/memory"]["get"]
    resp_200 = get_op["responses"]["200"]
    content = resp_200["content"]["application/json"]["schema"]
    ref = content.get("$ref", "")
    assert "AutonomousMemoryListResponse" in ref or "entries" in content.get("properties", {})


@pytest.mark.unit
def test_openapi_memory_list_accepts_state_filter() -> None:
    """GET /memory accepts a ?state query parameter."""
    schema = app.openapi()
    params = schema["paths"]["/api/v1/autonomous/memory"]["get"]["parameters"]
    names = {p["name"] for p in params}
    assert "state" in names
    assert "limit" in names
    assert "offset" in names


@pytest.mark.unit
def test_openapi_memory_keep_endpoint_documented() -> None:
    """POST /memory/{id}/keep is a POST with 200/401/404."""
    schema = app.openapi()
    keep_path = schema["paths"]["/api/v1/autonomous/memory/{memory_id}/keep"]
    assert "post" in keep_path
    post_op = keep_path["post"]
    assert "200" in post_op["responses"]
    assert "401" in post_op["responses"]
    assert "404" in post_op["responses"]


@pytest.mark.unit
def test_openapi_memory_keep_response_schema() -> None:
    """POST /memory/{id}/keep response references AutonomousMemoryRead."""
    schema = app.openapi()
    post_op = schema["paths"]["/api/v1/autonomous/memory/{memory_id}/keep"]["post"]
    resp_200 = post_op["responses"]["200"]
    content = resp_200["content"]["application/json"]["schema"]
    ref = content.get("$ref", "")
    assert "AutonomousMemoryRead" in ref or "state" in content.get("properties", {})


@pytest.mark.unit
def test_openapi_memory_dismiss_endpoint_documented() -> None:
    """POST /memory/{id}/dismiss is a POST with 200/401/404."""
    schema = app.openapi()
    dismiss_path = schema["paths"]["/api/v1/autonomous/memory/{memory_id}/dismiss"]
    assert "post" in dismiss_path
    post_op = dismiss_path["post"]
    assert "200" in post_op["responses"]
    assert "401" in post_op["responses"]
    assert "404" in post_op["responses"]


@pytest.mark.unit
def test_openapi_memory_delete_endpoint_documented() -> None:
    """DELETE /memory/{id} is a DELETE with 200/401/404."""
    schema = app.openapi()
    delete_path = schema["paths"]["/api/v1/autonomous/memory/{memory_id}"]
    assert "delete" in delete_path
    delete_op = delete_path["delete"]
    assert "200" in delete_op["responses"]
    assert "401" in delete_op["responses"]
    assert "404" in delete_op["responses"]


@pytest.mark.unit
def test_openapi_memory_schemas_in_components() -> None:
    """AutonomousMemoryRead and AutonomousMemoryListResponse are in components/schemas."""
    schema = app.openapi()
    schemas = schema.get("components", {}).get("schemas", {})
    assert "AutonomousMemoryRead" in schemas
    assert "AutonomousMemoryListResponse" in schemas
    assert "MemoryKeepRequest" in schemas

    # AutonomousMemoryRead has required fields
    mem_schema = schemas["AutonomousMemoryRead"]
    props = mem_schema.get("properties", {})
    assert "id" in props
    assert "user_id" in props
    assert "state" in props
    assert "category" in props
    assert "content" in props
    assert "created_at" in props

    # AutonomousMemoryListResponse has list envelope
    list_schema = schemas["AutonomousMemoryListResponse"]
    list_props = list_schema.get("properties", {})
    assert "entries" in list_props
    assert "total_count" in list_props
    assert "limit" in list_props
    assert "offset" in list_props
