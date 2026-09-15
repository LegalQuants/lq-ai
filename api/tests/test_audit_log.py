"""Integration tests for the D3 audit-log critical path.

Covers the verification step from M1-IMPLEMENTATION-ORDER.md Task D3:

    Create privileged project, send chat, query audit log filtered
    by ``privilege_marked = true``, get expected entries.

Plus the admin-only gate, cross-filter composition, and pagination
behavior of the new ``GET /api/v1/admin/audit-log`` endpoint. Wider
audit-coverage tests (auth events, file uploads, project CRUD, KB
CRUD) belong with the corresponding subsystem instrumentation in a
follow-on D3-coverage commit.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit_action
from app.db.session import get_db
from app.main import app
from app.models import AuditLog, Project, User
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


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Audit Admin",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=True,
        mfa_enabled=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def regular_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"user-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Audit Reader (non-admin)",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def privileged_project(db_session: AsyncSession, regular_user: User) -> Project:
    project = Project(
        owner_id=regular_user.id,
        name="Acme v Smith — privileged",
        slug=f"priv-{uuid.uuid4().hex[:6]}",
        privileged=True,
        minimum_inference_tier=3,
    )
    db_session.add(project)
    await db_session.flush()
    return project


@pytest_asyncio.fixture
async def non_privileged_project(db_session: AsyncSession, regular_user: User) -> Project:
    project = Project(
        owner_id=regular_user.id,
        name="Internal — research",
        slug=f"open-{uuid.uuid4().hex[:6]}",
        privileged=False,
    )
    db_session.add(project)
    await db_session.flush()
    return project


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# audit_action helper — privilege resolution
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_audit_action_marks_privileged_when_project_is_privileged(
    db_session: AsyncSession,
    regular_user: User,
    privileged_project: Project,
) -> None:
    await audit_action(
        db_session,
        user_id=regular_user.id,
        action="chat.message_sent",
        resource_type="message",
        resource_id=str(uuid.uuid4()),
        project=privileged_project,
        routed_inference_tier=4,
        details={"chat_id": str(uuid.uuid4())},
    )
    await db_session.flush()

    rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.user_id == regular_user.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.privilege_marked is True
    assert row.privilege_basis is not None
    assert privileged_project.name in row.privilege_basis
    assert row.routed_inference_tier == 4


@pytest.mark.integration
async def test_audit_action_unmarked_when_project_is_not_privileged(
    db_session: AsyncSession,
    regular_user: User,
    non_privileged_project: Project,
) -> None:
    await audit_action(
        db_session,
        user_id=regular_user.id,
        action="chat.message_sent",
        resource_type="message",
        resource_id=str(uuid.uuid4()),
        project=non_privileged_project,
    )
    await db_session.flush()

    rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.user_id == regular_user.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].privilege_marked is False
    assert rows[0].privilege_basis is None


@pytest.mark.integration
async def test_audit_action_unmarked_with_no_project(
    db_session: AsyncSession, regular_user: User
) -> None:
    """No-project actions (e.g., user.export_requested) leave privilege false/null."""

    await audit_action(
        db_session,
        user_id=regular_user.id,
        action="user.export_requested",
        resource_type="user",
        resource_id=str(regular_user.id),
    )
    await db_session.flush()

    rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.user_id == regular_user.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].privilege_marked is False
    assert rows[0].privilege_basis is None


# ---------------------------------------------------------------------------
# /admin/audit-log GET — filtering, pagination, admin gate
# ---------------------------------------------------------------------------


async def _seed_audit_rows(
    db_session: AsyncSession,
    *,
    user: User,
    privileged_project: Project,
    non_privileged_project: Project,
    privileged_count: int = 3,
    non_privileged_count: int = 2,
) -> None:
    """Insert a mix of privileged + non-privileged audit rows."""

    base = datetime.now(tz=UTC) - timedelta(hours=1)
    for i in range(privileged_count):
        row = AuditLog(
            user_id=user.id,
            action="chat.message_sent",
            resource_type="message",
            resource_id=str(uuid.uuid4()),
            privilege_marked=True,
            privilege_basis=f"project:{privileged_project.name}",
            routed_inference_tier=3,
            timestamp=base + timedelta(minutes=i),
        )
        db_session.add(row)
    for i in range(non_privileged_count):
        row = AuditLog(
            user_id=user.id,
            action="chat.message_sent",
            resource_type="message",
            resource_id=str(uuid.uuid4()),
            privilege_marked=False,
            routed_inference_tier=4,
            timestamp=base + timedelta(minutes=privileged_count + i),
        )
        db_session.add(row)
    await db_session.flush()


@pytest.mark.integration
async def test_audit_log_endpoint_returns_all_entries_unfiltered(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    regular_user: User,
    privileged_project: Project,
    non_privileged_project: Project,
) -> None:
    await _seed_audit_rows(
        db_session,
        user=regular_user,
        privileged_project=privileged_project,
        non_privileged_project=non_privileged_project,
    )

    resp = await client.get("/api/v1/admin/audit-log", headers=_bearer(admin_user))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) >= 5  # 3 privileged + 2 non-privileged seeded


@pytest.mark.integration
async def test_audit_log_endpoint_filters_by_privilege_marked_true(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    regular_user: User,
    privileged_project: Project,
    non_privileged_project: Project,
) -> None:
    """The D3 verification path: ?privilege_marked=true returns only privileged rows."""

    await _seed_audit_rows(
        db_session,
        user=regular_user,
        privileged_project=privileged_project,
        non_privileged_project=non_privileged_project,
    )

    resp = await client.get(
        "/api/v1/admin/audit-log",
        headers=_bearer(admin_user),
        params={"privilege_marked": "true"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 3
    for entry in body["items"]:
        assert entry["privilege_marked"] is True
        assert entry["privilege_basis"] is not None


@pytest.mark.integration
async def test_audit_log_endpoint_filters_by_privilege_marked_false(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    regular_user: User,
    privileged_project: Project,
    non_privileged_project: Project,
) -> None:
    await _seed_audit_rows(
        db_session,
        user=regular_user,
        privileged_project=privileged_project,
        non_privileged_project=non_privileged_project,
    )

    resp = await client.get(
        "/api/v1/admin/audit-log",
        headers=_bearer(admin_user),
        params={"privilege_marked": "false"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 2
    for entry in body["items"]:
        assert entry["privilege_marked"] is False


@pytest.mark.integration
async def test_audit_log_endpoint_filters_by_routed_inference_tier(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    regular_user: User,
    privileged_project: Project,
    non_privileged_project: Project,
) -> None:
    await _seed_audit_rows(
        db_session,
        user=regular_user,
        privileged_project=privileged_project,
        non_privileged_project=non_privileged_project,
    )

    resp = await client.get(
        "/api/v1/admin/audit-log",
        headers=_bearer(admin_user),
        params={"routed_inference_tier": 3},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 3
    for entry in body["items"]:
        assert entry["routed_inference_tier"] == 3


@pytest.mark.integration
async def test_audit_log_endpoint_pagination(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    regular_user: User,
    privileged_project: Project,
    non_privileged_project: Project,
) -> None:
    """Cursor pagination walks the full set without overlap."""

    await _seed_audit_rows(
        db_session,
        user=regular_user,
        privileged_project=privileged_project,
        non_privileged_project=non_privileged_project,
        privileged_count=4,
        non_privileged_count=4,
    )

    seen: set[str] = set()
    cursor: str | None = None
    pages = 0
    while pages < 10:  # safety cap so a runaway loop fails the test fast
        params: dict[str, str | int] = {"limit": 3}
        if cursor is not None:
            params["cursor"] = cursor
        resp = await client.get(
            "/api/v1/admin/audit-log",
            headers=_bearer(admin_user),
            params=params,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        for entry in body["items"]:
            assert entry["id"] not in seen, "pagination returned the same row twice"
            seen.add(entry["id"])
        cursor = body.get("next_cursor")
        pages += 1
        if cursor is None:
            break

    # We seeded 8 rows; the walk should have surfaced all of them.
    assert len(seen) >= 8


@pytest.mark.integration
async def test_audit_log_endpoint_requires_admin(
    client: AsyncClient,
    regular_user: User,
) -> None:
    """Non-admin users get 403, not 200, even with a valid bearer token."""

    resp = await client.get("/api/v1/admin/audit-log", headers=_bearer(regular_user))
    assert resp.status_code == 403


@pytest.mark.integration
async def test_audit_log_endpoint_without_bearer_returns_401(
    client: AsyncClient,
) -> None:
    resp = await client.get("/api/v1/admin/audit-log")
    assert resp.status_code == 401
