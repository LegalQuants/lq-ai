"""Integration tests for Task D8.1a — teams + team_members CRUD.

Covers the operator-admin-controlled team management surface:

* POST /admin/teams creates with auto-admin-membership for the creator.
* CRUD round-trip + ownership / admin gates.
* Slug collision (409) and slug validation (422).
* Membership add / role-change / remove + role validation.
* DELETE cascades to team_members (and to user_skills with scope='team').
* User-facing /teams shows only teams the caller belongs to.
* Non-admins on /admin/teams* return 403.
* Audit rows land on every state-changing call with the right
  details payload.
* Migration 0014 invariants: role CHECK, team-member PK, FK CASCADE,
  user_skills team FK enforces existence of the team.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models import AuditLog, Team, TeamMember, User, UserSkill
from app.security import create_access_token, hash_password


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


async def _make_user(db_session: AsyncSession, *, suffix: str = "", is_admin: bool = False) -> User:
    user = User(
        email=f"team-{suffix or uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Team Test {suffix}".strip(),
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=is_admin,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    return await _make_user(db_session, suffix="adm", is_admin=True)


@pytest_asyncio.fixture
async def member_user(db_session: AsyncSession) -> User:
    return await _make_user(db_session, suffix="mem", is_admin=False)


@pytest_asyncio.fixture
async def other_admin(db_session: AsyncSession) -> User:
    return await _make_user(db_session, suffix="adm2", is_admin=True)


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Admin: create / list / get / update / delete
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_team_returns_201_and_auto_adds_creator_as_admin(
    client: AsyncClient, admin_user: User, db_session: AsyncSession
) -> None:
    resp = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "contracts", "name": "Contracts", "description": "test"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slug"] == "contracts"
    assert body["member_count"] == 1
    assert len(body["members"]) == 1
    assert body["members"][0]["user_id"] == str(admin_user.id)
    assert body["members"][0]["role"] == "admin"

    row = await db_session.get(Team, uuid.UUID(body["id"]))
    assert row is not None
    assert row.slug == "contracts"


@pytest.mark.integration
async def test_create_team_slug_collision_returns_409(
    client: AsyncClient, admin_user: User
) -> None:
    first = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "contracts", "name": "Contracts"},
    )
    assert first.status_code == 201
    dup = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "contracts", "name": "Dup"},
    )
    assert dup.status_code == 409


@pytest.mark.integration
async def test_create_team_invalid_slug_returns_422(client: AsyncClient, admin_user: User) -> None:
    resp = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "Contracts!", "name": "Contracts"},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_non_admin_cannot_create_team(client: AsyncClient, member_user: User) -> None:
    resp = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(member_user),
        json={"slug": "contracts", "name": "Contracts"},
    )
    assert resp.status_code == 403


@pytest.mark.integration
async def test_update_team_writes_audit_when_changed(
    client: AsyncClient, admin_user: User, db_session: AsyncSession
) -> None:
    created = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "c", "name": "Old"},
    )
    team_id = created.json()["id"]
    resp = await client.patch(
        f"/api/v1/admin/teams/{team_id}",
        headers=_bearer(admin_user),
        json={"name": "New name"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New name"

    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "team.updated",
                AuditLog.resource_id == team_id,
            )
        )
    ).scalar_one()
    assert audit.details is not None
    assert audit.details["changed_fields"] == ["name"]


@pytest.mark.integration
async def test_delete_team_cascades_to_members_and_skills(
    client: AsyncClient,
    admin_user: User,
    member_user: User,
    db_session: AsyncSession,
) -> None:
    created = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "c", "name": "C"},
    )
    team_id = uuid.UUID(created.json()["id"])

    # Add a second member.
    add = await client.post(
        f"/api/v1/admin/teams/{team_id}/members",
        headers=_bearer(admin_user),
        json={"user_id": str(member_user.id), "role": "member"},
    )
    assert add.status_code == 201

    # Manually insert a team-scope user_skill so we can prove the
    # CASCADE removes it on team delete.
    db_session.add(
        UserSkill(
            scope="team",
            owner_team_id=team_id,
            slug="team-skill",
            display_name="Team Skill",
            description="t",
            body="t",
        )
    )
    await db_session.flush()

    delete = await client.delete(f"/api/v1/admin/teams/{team_id}", headers=_bearer(admin_user))
    assert delete.status_code == 204

    # Team gone.
    assert await db_session.get(Team, team_id) is None
    # Memberships gone (CASCADE).
    stmt = select(TeamMember).where(TeamMember.team_id == team_id)
    assert (await db_session.execute(stmt)).scalars().all() == []
    # Team-scope skills gone (CASCADE on owner_team_id).
    skill_stmt = select(UserSkill).where(UserSkill.owner_team_id == team_id)
    assert (await db_session.execute(skill_stmt)).scalars().all() == []


@pytest.mark.integration
async def test_admin_team_id_probing_returns_404(client: AsyncClient, admin_user: User) -> None:
    resp = await client.get(f"/api/v1/admin/teams/{uuid.uuid4()}", headers=_bearer(admin_user))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Membership: add / role change / remove
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_add_member_writes_audit(
    client: AsyncClient,
    admin_user: User,
    member_user: User,
    db_session: AsyncSession,
) -> None:
    created = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "c", "name": "C"},
    )
    team_id = created.json()["id"]

    resp = await client.post(
        f"/api/v1/admin/teams/{team_id}/members",
        headers=_bearer(admin_user),
        json={"user_id": str(member_user.id), "role": "member"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["user_id"] == str(member_user.id)
    assert body["role"] == "member"

    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "team.member_added",
                AuditLog.resource_id == team_id,
            )
        )
    ).scalar_one()
    assert audit.details is not None
    assert audit.details["user_email"] == member_user.email
    assert audit.details["role"] == "member"


@pytest.mark.integration
async def test_add_member_duplicate_returns_409(
    client: AsyncClient, admin_user: User, member_user: User
) -> None:
    created = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "c", "name": "C"},
    )
    team_id = created.json()["id"]
    first = await client.post(
        f"/api/v1/admin/teams/{team_id}/members",
        headers=_bearer(admin_user),
        json={"user_id": str(member_user.id), "role": "member"},
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/v1/admin/teams/{team_id}/members",
        headers=_bearer(admin_user),
        json={"user_id": str(member_user.id), "role": "member"},
    )
    assert second.status_code == 409


@pytest.mark.integration
async def test_add_member_invalid_role_returns_422(
    client: AsyncClient, admin_user: User, member_user: User
) -> None:
    created = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "c", "name": "C"},
    )
    team_id = created.json()["id"]
    resp = await client.post(
        f"/api/v1/admin/teams/{team_id}/members",
        headers=_bearer(admin_user),
        json={"user_id": str(member_user.id), "role": "owner"},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_role_change_records_before_and_after(
    client: AsyncClient,
    admin_user: User,
    member_user: User,
    db_session: AsyncSession,
) -> None:
    created = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "c", "name": "C"},
    )
    team_id = created.json()["id"]
    await client.post(
        f"/api/v1/admin/teams/{team_id}/members",
        headers=_bearer(admin_user),
        json={"user_id": str(member_user.id), "role": "member"},
    )
    resp = await client.patch(
        f"/api/v1/admin/teams/{team_id}/members/{member_user.id}",
        headers=_bearer(admin_user),
        json={"role": "admin"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"

    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "team.member_role_changed",
                AuditLog.resource_id == team_id,
            )
        )
    ).scalar_one()
    assert audit.details is not None
    assert audit.details["role_before"] == "member"
    assert audit.details["role_after"] == "admin"


@pytest.mark.integration
async def test_role_change_no_op_does_not_audit(
    client: AsyncClient,
    admin_user: User,
    member_user: User,
    db_session: AsyncSession,
) -> None:
    created = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "c", "name": "C"},
    )
    team_id = created.json()["id"]
    await client.post(
        f"/api/v1/admin/teams/{team_id}/members",
        headers=_bearer(admin_user),
        json={"user_id": str(member_user.id), "role": "member"},
    )

    # Set role to the same value -> no-op.
    resp = await client.patch(
        f"/api/v1/admin/teams/{team_id}/members/{member_user.id}",
        headers=_bearer(admin_user),
        json={"role": "member"},
    )
    assert resp.status_code == 200

    audit = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "team.member_role_changed",
                    AuditLog.resource_id == team_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert audit == []


@pytest.mark.integration
async def test_remove_member_audits_role_at_removal(
    client: AsyncClient,
    admin_user: User,
    member_user: User,
    db_session: AsyncSession,
) -> None:
    created = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "c", "name": "C"},
    )
    team_id = created.json()["id"]
    await client.post(
        f"/api/v1/admin/teams/{team_id}/members",
        headers=_bearer(admin_user),
        json={"user_id": str(member_user.id), "role": "admin"},
    )

    resp = await client.delete(
        f"/api/v1/admin/teams/{team_id}/members/{member_user.id}",
        headers=_bearer(admin_user),
    )
    assert resp.status_code == 204

    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "team.member_removed",
                AuditLog.resource_id == team_id,
            )
        )
    ).scalar_one()
    assert audit.details is not None
    assert audit.details["role_at_removal"] == "admin"


# ---------------------------------------------------------------------------
# User-facing /teams (read-only, membership-scoped)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_my_teams_shows_only_caller_membership(
    client: AsyncClient,
    admin_user: User,
    member_user: User,
) -> None:
    """Admin creates two teams; only adds member_user to one of them.
    member_user's /teams listing should show exactly one team."""

    a = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "alpha", "name": "Alpha"},
    )
    b = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "beta", "name": "Beta"},
    )
    assert a.status_code == 201
    assert b.status_code == 201

    await client.post(
        f"/api/v1/admin/teams/{a.json()['id']}/members",
        headers=_bearer(admin_user),
        json={"user_id": str(member_user.id), "role": "member"},
    )

    mine = await client.get("/api/v1/teams", headers=_bearer(member_user))
    assert mine.status_code == 200
    rows = mine.json()
    assert {r["slug"] for r in rows} == {"alpha"}


@pytest.mark.integration
async def test_my_team_returns_404_for_non_member(
    client: AsyncClient, admin_user: User, member_user: User
) -> None:
    created = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "secret", "name": "Secret"},
    )
    team_id = created.json()["id"]
    resp = await client.get(f"/api/v1/teams/{team_id}", headers=_bearer(member_user))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# D8.1c — caller_role on user-facing endpoints + ?role= filter
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_my_teams_includes_caller_role(
    client: AsyncClient, admin_user: User, member_user: User
) -> None:
    """The caller's role on each team rides the list response so the UI
    can render the admin-only mutate affordances without a second
    round-trip."""

    a = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "admin-here", "name": "Admin Here"},
    )
    b = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "member-here", "name": "Member Here"},
    )
    # member_user is added as admin on 'admin-here' and member on 'member-here'.
    await client.post(
        f"/api/v1/admin/teams/{a.json()['id']}/members",
        headers=_bearer(admin_user),
        json={"user_id": str(member_user.id), "role": "admin"},
    )
    await client.post(
        f"/api/v1/admin/teams/{b.json()['id']}/members",
        headers=_bearer(admin_user),
        json={"user_id": str(member_user.id), "role": "member"},
    )

    mine = await client.get("/api/v1/teams", headers=_bearer(member_user))
    assert mine.status_code == 200
    rows = {r["slug"]: r for r in mine.json()}
    assert rows["admin-here"]["caller_role"] == "admin"
    assert rows["member-here"]["caller_role"] == "member"


@pytest.mark.integration
async def test_my_teams_role_filter_admin_only(
    client: AsyncClient, admin_user: User, member_user: User
) -> None:
    """``?role=admin`` restricts the list to teams where the caller can
    mutate team-scope skills — what the UI's team-picker needs."""

    a = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "ra-1", "name": "RA1"},
    )
    b = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "ra-2", "name": "RA2"},
    )
    await client.post(
        f"/api/v1/admin/teams/{a.json()['id']}/members",
        headers=_bearer(admin_user),
        json={"user_id": str(member_user.id), "role": "admin"},
    )
    await client.post(
        f"/api/v1/admin/teams/{b.json()['id']}/members",
        headers=_bearer(admin_user),
        json={"user_id": str(member_user.id), "role": "member"},
    )

    admins_only = await client.get("/api/v1/teams?role=admin", headers=_bearer(member_user))
    assert admins_only.status_code == 200
    rows = admins_only.json()
    assert {r["slug"] for r in rows} == {"ra-1"}
    assert all(r["caller_role"] == "admin" for r in rows)


@pytest.mark.integration
async def test_my_teams_invalid_role_returns_422(client: AsyncClient, admin_user: User) -> None:
    resp = await client.get("/api/v1/teams?role=owner", headers=_bearer(admin_user))
    assert resp.status_code == 422


@pytest.mark.integration
async def test_get_my_team_includes_caller_role(
    client: AsyncClient, admin_user: User, member_user: User
) -> None:
    created = await client.post(
        "/api/v1/admin/teams",
        headers=_bearer(admin_user),
        json={"slug": "cr-team", "name": "CR Team"},
    )
    team_id = created.json()["id"]
    await client.post(
        f"/api/v1/admin/teams/{team_id}/members",
        headers=_bearer(admin_user),
        json={"user_id": str(member_user.id), "role": "member"},
    )

    resp = await client.get(f"/api/v1/teams/{team_id}", headers=_bearer(member_user))
    assert resp.status_code == 200
    assert resp.json()["caller_role"] == "member"


# ---------------------------------------------------------------------------
# Migration 0014 invariants
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_team_members_role_check_constraint(
    db_session: AsyncSession, admin_user: User, member_user: User
) -> None:
    """team_members.role accepts only 'admin' and 'member'."""

    team = Team(
        slug="c-check",
        name="Check",
        created_by_user_id=admin_user.id,
    )
    db_session.add(team)
    await db_session.flush()

    bad = TeamMember(
        team_id=team.id,
        user_id=member_user.id,
        role="owner",
        added_by_user_id=admin_user.id,
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.integration
async def test_team_members_unique_per_user(
    db_session: AsyncSession, admin_user: User, member_user: User
) -> None:
    """A user can only join a team once (composite PK on team_id, user_id)."""

    team = Team(slug="c-uniq", name="C", created_by_user_id=admin_user.id)
    db_session.add(team)
    await db_session.flush()

    db_session.add(
        TeamMember(
            team_id=team.id,
            user_id=member_user.id,
            role="member",
            added_by_user_id=admin_user.id,
        )
    )
    await db_session.flush()

    dup = TeamMember(
        team_id=team.id,
        user_id=member_user.id,
        role="admin",
        added_by_user_id=admin_user.id,
    )
    db_session.add(dup)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.integration
async def test_user_skill_team_fk_rejects_unknown_team(
    db_session: AsyncSession, admin_user: User
) -> None:
    """user_skills.owner_team_id must reference an existing team row."""

    bad = UserSkill(
        scope="team",
        owner_team_id=uuid.uuid4(),
        slug="orphan",
        display_name="Orphan",
        description="orphan",
        body="orphan",
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.integration
async def test_team_indexes_exist(db_session: AsyncSession) -> None:
    expected = {
        "uq_teams_slug",
        "pk_team_members",
        "idx_team_members_user",
    }
    # uq_teams_slug is a unique constraint, not a separate index — Postgres
    # creates a backing unique index for it. Verify by querying pg_indexes
    # for backing indexes plus the join-table index.
    result = await db_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = ANY(:names)"
        ),
        {"names": list(expected)},
    )
    found = {row[0] for row in result.fetchall()}
    assert found == expected, f"missing indexes: {expected - found}"
