"""Integration tests for GET /api/v1/admin/users — Wave B v2 (PRD §5.2).

Covers:
* All non-deleted users returned, sorted by email ASC.
* Soft-deleted users (deleted_at set) are excluded.
* Role filter (?role=admin) returns only matching users.
* Email substring filter (?email_q=alice) is case-insensitive.
* Pagination: limit + offset work; total_count reflects the full filtered count.
* 403 for non-admin callers.
* 400 for invalid role filter value.
* deletion_scheduled_at surfaces for pending-deletion users.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


def _make_user(
    *,
    email: str,
    is_admin: bool = False,
    role: str = "member",
    deleted_at: datetime | None = None,
    deletion_scheduled_at: datetime | None = None,
) -> User:
    return User(
        email=email,
        display_name=email.split("@")[0].capitalize(),
        hashed_password=hash_password("s3cr3t-battery-staple"),
        is_admin=is_admin,
        role=role,
        mfa_enabled=False,
        must_change_password=False,
        deleted_at=deleted_at,
        deletion_scheduled_at=deletion_scheduled_at,
    )


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = _make_user(email=f"admin-{suffix}@example.com", is_admin=True, role="admin")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def member_user(db_session: AsyncSession) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = _make_user(email=f"member-{suffix}@example.com", is_admin=False, role="member")
    db_session.add(user)
    await db_session.flush()
    return user


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_users_returns_all_non_deleted_users(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    """Admin caller receives all non-deleted users, sorted by email ASC."""
    suffix = uuid.uuid4().hex[:6]
    u1 = _make_user(email=f"alice-{suffix}@example.com")
    u2 = _make_user(email=f"bob-{suffix}@example.com")
    u3 = _make_user(email=f"carol-{suffix}@example.com")
    db_session.add_all([u1, u2, u3])
    await db_session.flush()

    resp = await client.get("/api/v1/admin/users", headers=_bearer(admin_user))
    assert resp.status_code == 200
    data = resp.json()

    emails = [u["email"] for u in data["users"]]
    # All three new users must appear
    for expected in [u1.email, u2.email, u3.email]:
        assert expected in emails, f"{expected} missing from list"

    # Verify email-ASC ordering for the subset we can control
    subset = [e for e in emails if e.endswith(f"-{suffix}@example.com")]
    assert subset == sorted(subset)

    # total_count >= 4 (admin + 3 new)
    assert data["total_count"] >= 4


@pytest.mark.integration
async def test_list_users_excludes_soft_deleted(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    """Users with deleted_at set must not appear in the response."""
    suffix = uuid.uuid4().hex[:6]
    active = _make_user(email=f"active-{suffix}@example.com")
    deleted = _make_user(
        email=f"deleted-{suffix}@example.com",
        deleted_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    db_session.add_all([active, deleted])
    await db_session.flush()

    resp = await client.get("/api/v1/admin/users", headers=_bearer(admin_user))
    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()["users"]]

    assert active.email in emails
    assert deleted.email not in emails


@pytest.mark.integration
async def test_list_users_filters_by_role(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    """?role=viewer returns only viewer-role users."""
    suffix = uuid.uuid4().hex[:6]
    viewer = _make_user(email=f"viewer-{suffix}@example.com", role="viewer")
    also_member = _make_user(email=f"member-{suffix}@example.com", role="member")
    db_session.add_all([viewer, also_member])
    await db_session.flush()

    resp = await client.get(
        "/api/v1/admin/users",
        headers=_bearer(admin_user),
        params={"role": "viewer"},
    )
    assert resp.status_code == 200
    users = resp.json()["users"]
    roles = {u["role"] for u in users}
    emails = [u["email"] for u in users]

    assert viewer.email in emails
    assert also_member.email not in emails
    assert roles == {"viewer"}


@pytest.mark.integration
async def test_list_users_filters_by_email_q(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    """?email_q= does case-insensitive substring match on email."""
    suffix = uuid.uuid4().hex[:6]
    match = _make_user(email=f"alice-{suffix}@example.com")
    no_match = _make_user(email=f"zzznomatch-{suffix}@other.com")
    db_session.add_all([match, no_match])
    await db_session.flush()

    # Search with uppercase variant
    resp = await client.get(
        "/api/v1/admin/users",
        headers=_bearer(admin_user),
        params={"email_q": f"ALICE-{suffix}"},
    )
    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()["users"]]
    assert match.email in emails
    assert no_match.email not in emails


@pytest.mark.integration
async def test_list_users_pagination(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    """limit + offset page correctly; total_count reflects full filtered count."""
    suffix = uuid.uuid4().hex[:6]
    users = [_make_user(email=f"page-{i}-{suffix}@example.com") for i in range(5)]
    db_session.add_all(users)
    await db_session.flush()

    # Fetch first 2 rows of the email-q-filtered set
    resp = await client.get(
        "/api/v1/admin/users",
        headers=_bearer(admin_user),
        params={"email_q": f"-{suffix}@example.com", "limit": 2, "offset": 0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_count"] == 5
    assert data["limit"] == 2
    assert data["offset"] == 0
    assert len(data["users"]) == 2

    # Second page
    resp2 = await client.get(
        "/api/v1/admin/users",
        headers=_bearer(admin_user),
        params={"email_q": f"-{suffix}@example.com", "limit": 2, "offset": 2},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["total_count"] == 5
    assert data2["offset"] == 2
    assert len(data2["users"]) == 2

    # No overlap between pages
    page1_emails = {u["email"] for u in data["users"]}
    page2_emails = {u["email"] for u in data2["users"]}
    assert page1_emails.isdisjoint(page2_emails)


@pytest.mark.integration
async def test_list_users_403_for_non_admin(
    client: AsyncClient,
    member_user: User,
) -> None:
    """Member-role caller receives 403."""
    resp = await client.get("/api/v1/admin/users", headers=_bearer(member_user))
    assert resp.status_code == 403


@pytest.mark.integration
async def test_list_users_400_for_invalid_role_filter(
    client: AsyncClient,
    admin_user: User,
) -> None:
    """?role=invalid returns 400."""
    resp = await client.get(
        "/api/v1/admin/users",
        headers=_bearer(admin_user),
        params={"role": "superuser"},
    )
    assert resp.status_code == 400


@pytest.mark.integration
async def test_list_users_surfaces_deletion_scheduled_at(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    """Users with a pending deletion surface deletion_scheduled_at in the response."""
    suffix = uuid.uuid4().hex[:6]
    scheduled_ts = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    pending = _make_user(
        email=f"pending-delete-{suffix}@example.com",
        deletion_scheduled_at=scheduled_ts,
    )
    db_session.add(pending)
    await db_session.flush()

    resp = await client.get(
        "/api/v1/admin/users",
        headers=_bearer(admin_user),
        params={"email_q": f"pending-delete-{suffix}"},
    )
    assert resp.status_code == 200
    users = resp.json()["users"]
    assert len(users) == 1
    row = users[0]
    assert row["email"] == pending.email
    assert row["deletion_scheduled_at"] is not None
    # Verify it round-trips as an ISO-8601 timestamp
    parsed = datetime.fromisoformat(row["deletion_scheduled_at"].replace("Z", "+00:00"))
    assert parsed.year == 2026
    assert parsed.month == 6
