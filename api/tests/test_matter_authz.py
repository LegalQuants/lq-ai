"""The matter access-control matrix — app/authz/matters.py.

This is the file that has to be right. Every rule below is one a firm
would be asked to demonstrate if a privilege dispute ever reached a
motion, so each is asserted directly rather than inferred from an
endpoint's behaviour:

* an explicit screen (``role='blocked'``) beats firm-wide scope, beats an
  explicit grant, and **beats ``is_admin``**;
* ``share_scope='org'`` confers read and never write;
* a caller with no path to a matter gets 404, not 403 — the
  existence-safe posture the matter surface already documents;
* a caller who *can* read but is asking for more gets 403, because at
  that point the 403 leaks nothing they could not already see;
* sandbox matters cannot be shared (DB CHECK, not just the API);
* an admin's *listing* stays their own even though they can read a
  known-id matter cross-user.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz.matters import matter_access, matter_scope_filter, require_matter
from app.errors import Forbidden, NotFound
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.security import hash_password

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _mk_user(db: AsyncSession, *, is_admin: bool = False, role: str = "member") -> User:
    user = User(
        email=f"u-{uuid.uuid4().hex[:10]}@example.com",
        display_name="Test User",
        hashed_password=hash_password("s3cr3t-battery-staple"),
        is_admin=is_admin,
        role=role,
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    return user


async def _mk_project(
    db: AsyncSession,
    owner: User,
    *,
    share_scope: str = "personal",
    privileged: bool = False,
    tier: int | None = None,
    is_sandbox: bool = False,
) -> Project:
    project = Project(
        owner_id=owner.id,
        name="Acme MSA renewal",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        share_scope=share_scope,
        privileged=privileged,
        minimum_inference_tier=tier,
        is_sandbox=is_sandbox,
    )
    db.add(project)
    await db.flush()
    # Mirror what `create_project` and migration 0067's backfill both do.
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=owner.id,
            role="lead",
            added_by_user_id=owner.id,
        )
    )
    await db.flush()
    return project


async def _grant(db: AsyncSession, project: Project, user: User, role: str) -> ProjectMember:
    row = ProjectMember(
        project_id=project.id,
        user_id=user.id,
        role=role,
        added_by_user_id=project.owner_id,
    )
    db.add(row)
    await db.flush()
    return row


@pytest_asyncio.fixture
async def owner(db_session: AsyncSession) -> User:
    return await _mk_user(db_session)


@pytest_asyncio.fixture
async def colleague(db_session: AsyncSession) -> User:
    return await _mk_user(db_session)


@pytest_asyncio.fixture
async def stranger(db_session: AsyncSession) -> User:
    return await _mk_user(db_session)


@pytest_asyncio.fixture
async def admin(db_session: AsyncSession) -> User:
    return await _mk_user(db_session, is_admin=True, role="admin")


@pytest_asyncio.fixture
async def auditor(db_session: AsyncSession) -> User:
    return await _mk_user(db_session, role="auditor")


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_is_lead(db_session: AsyncSession, owner: User) -> None:
    project = await _mk_project(db_session, owner)
    assert await matter_access(db_session, project, owner) == ("lead", "owner")


@pytest.mark.asyncio
async def test_personal_matter_is_invisible_to_a_stranger(
    db_session: AsyncSession, owner: User, stranger: User
) -> None:
    project = await _mk_project(db_session, owner)
    assert await matter_access(db_session, project, stranger) == ("none", "no_grant")


@pytest.mark.parametrize(
    ("role", "expected"),
    [("lead", "lead"), ("contributor", "write"), ("reader", "read")],
)
@pytest.mark.asyncio
async def test_explicit_grant_confers_its_level(
    db_session: AsyncSession, owner: User, colleague: User, role: str, expected: str
) -> None:
    project = await _mk_project(db_session, owner)
    await _grant(db_session, project, colleague, role)
    level, basis = await matter_access(db_session, project, colleague)
    assert (level, basis) == (expected, "member")


@pytest.mark.asyncio
async def test_org_scope_grants_read_and_only_read(
    db_session: AsyncSession, owner: User, stranger: User
) -> None:
    project = await _mk_project(db_session, owner, share_scope="org")
    level, basis = await matter_access(db_session, project, stranger)
    assert (level, basis) == ("read", "org")

    # Contributing to a firm-wide matter still needs an explicit row, so the
    # roster stays a truthful answer to "who worked this matter".
    with pytest.raises(Forbidden):
        await require_matter(db_session, project.id, stranger, need="write")


@pytest.mark.asyncio
async def test_explicit_grant_beats_org_scope_for_write(
    db_session: AsyncSession, owner: User, colleague: User
) -> None:
    project = await _mk_project(db_session, owner, share_scope="org")
    await _grant(db_session, project, colleague, "contributor")
    assert await matter_access(db_session, project, colleague) == ("write", "member")


# ---------------------------------------------------------------------------
# Screens — the rules that must never be "optimised"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_screen_beats_org_scope(
    db_session: AsyncSession, owner: User, colleague: User
) -> None:
    project = await _mk_project(db_session, owner, share_scope="org")
    await _grant(db_session, project, colleague, "blocked")
    assert await matter_access(db_session, project, colleague) == ("none", "blocked")


@pytest.mark.asyncio
async def test_screen_beats_is_admin(db_session: AsyncSession, owner: User, admin: User) -> None:
    """An ethical wall an operator-admin can walk through is not a wall.

    In a small firm the operator-admin is usually also a practising lawyer,
    so admin bypass would defeat the screen in exactly the deployment that
    needs it most. The remedy for an admin who must see the matter is to
    lift the screen — an attributed, audited act — not to ignore it.
    """
    project = await _mk_project(db_session, owner, share_scope="org")
    await _grant(db_session, project, admin, "blocked")
    assert await matter_access(db_session, project, admin) == ("none", "blocked")


@pytest.mark.asyncio
async def test_screen_beats_auditor(db_session: AsyncSession, owner: User, auditor: User) -> None:
    project = await _mk_project(db_session, owner, share_scope="org")
    await _grant(db_session, project, auditor, "blocked")
    assert await matter_access(db_session, project, auditor) == ("none", "blocked")


@pytest.mark.asyncio
async def test_screened_caller_gets_404_not_403(
    db_session: AsyncSession, owner: User, admin: User
) -> None:
    """A fired screen must be indistinguishable from a missing matter."""
    project = await _mk_project(db_session, owner, share_scope="org")
    await _grant(db_session, project, admin, "blocked")
    with pytest.raises(NotFound):
        await require_matter(db_session, project.id, admin)


@pytest.mark.asyncio
async def test_screen_is_excluded_from_the_scope_filter(
    db_session: AsyncSession, owner: User, colleague: User
) -> None:
    """The listing and the fetch must agree — a screen hidden on the detail
    page but leaking through the list is worse than no screen, because it
    is believed."""
    from sqlalchemy import select

    visible = await _mk_project(db_session, owner, share_scope="org")
    screened = await _mk_project(db_session, owner, share_scope="org")
    await _grant(db_session, screened, colleague, "blocked")

    rows = (
        (await db_session.execute(select(Project.id).where(matter_scope_filter(colleague))))
        .scalars()
        .all()
    )
    assert visible.id in rows
    assert screened.id not in rows


# ---------------------------------------------------------------------------
# No operator-admin bypass
# ---------------------------------------------------------------------------
#
# These three pin the *absence* of a capability, which is the kind of thing
# that gets reintroduced by a well-meaning patch unless a test names it.
# Before membership existed, `is_admin` did not let anyone read another
# user's matter — the loaders were plain owner checks. Membership must not
# smuggle in a cross-user read under cover of a collaboration feature.


@pytest.mark.asyncio
async def test_admin_cannot_read_a_personal_matter(
    db_session: AsyncSession, owner: User, admin: User
) -> None:
    project = await _mk_project(db_session, owner)
    assert await matter_access(db_session, project, admin) == ("none", "no_grant")
    with pytest.raises(NotFound):
        await require_matter(db_session, project.id, admin)


@pytest.mark.asyncio
async def test_auditor_cannot_read_a_personal_matter(
    db_session: AsyncSession, owner: User, auditor: User
) -> None:
    """The deployment-wide auditor role still reaches the ledger and receipt
    surfaces the way it always did (``_load_chat_for_reader``); it gains no
    new reach over matters here."""
    project = await _mk_project(db_session, owner)
    assert await matter_access(db_session, project, auditor) == ("none", "no_grant")


@pytest.mark.asyncio
async def test_admin_listing_does_not_enumerate_other_peoples_matters(
    db_session: AsyncSession, owner: User, admin: User
) -> None:
    from sqlalchemy import select

    personal = await _mk_project(db_session, owner)
    rows = (
        (await db_session.execute(select(Project.id).where(matter_scope_filter(admin))))
        .scalars()
        .all()
    )
    assert personal.id not in rows


@pytest.mark.asyncio
async def test_admin_reaches_a_firm_wide_matter_like_anyone_else(
    db_session: AsyncSession, owner: User, admin: User
) -> None:
    """An admin's read of a shared matter comes from the same ambient rule
    every other user gets — read, never write."""
    project = await _mk_project(db_session, owner, share_scope="org")
    assert await matter_access(db_session, project, admin) == ("read", "org")
    with pytest.raises(Forbidden):
        await require_matter(db_session, project.id, admin, need="write")


# ---------------------------------------------------------------------------
# require_matter status-code contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_matter_is_404(db_session: AsyncSession, owner: User) -> None:
    with pytest.raises(NotFound):
        await require_matter(db_session, uuid.uuid4(), owner)


@pytest.mark.asyncio
async def test_archived_matter_hidden_unless_requested(
    db_session: AsyncSession, owner: User
) -> None:
    from datetime import UTC, datetime

    project = await _mk_project(db_session, owner)
    project.archived_at = datetime.now(tz=UTC)
    await db_session.flush()

    with pytest.raises(NotFound):
        await require_matter(db_session, project.id, owner)

    got = await require_matter(db_session, project.id, owner, include_archived=True)
    assert got.id == project.id


@pytest.mark.asyncio
async def test_reader_asking_for_write_gets_403(
    db_session: AsyncSession, owner: User, colleague: User
) -> None:
    project = await _mk_project(db_session, owner)
    await _grant(db_session, project, colleague, "reader")
    with pytest.raises(Forbidden):
        await require_matter(db_session, project.id, colleague, need="write")


@pytest.mark.asyncio
async def test_contributor_asking_for_lead_gets_403(
    db_session: AsyncSession, owner: User, colleague: User
) -> None:
    project = await _mk_project(db_session, owner)
    await _grant(db_session, project, colleague, "contributor")
    with pytest.raises(Forbidden):
        await require_matter(db_session, project.id, colleague, need="lead")


# ---------------------------------------------------------------------------
# DB-level invariants — defense in depth, not just the API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sandbox_matter_cannot_be_shared(db_session: AsyncSession, owner: User) -> None:
    with pytest.raises(IntegrityError):
        await _mk_project(db_session, owner, is_sandbox=True, share_scope="org")
    await db_session.rollback()


@pytest.mark.asyncio
async def test_share_scope_enum_is_enforced_by_the_db(
    db_session: AsyncSession, owner: User
) -> None:
    with pytest.raises(IntegrityError):
        await _mk_project(db_session, owner, share_scope="everyone")
    await db_session.rollback()


@pytest.mark.asyncio
async def test_member_role_enum_is_enforced_by_the_db(
    db_session: AsyncSession, owner: User, colleague: User
) -> None:
    project = await _mk_project(db_session, owner)
    with pytest.raises(IntegrityError):
        await _grant(db_session, project, colleague, "partner")
    await db_session.rollback()


@pytest.mark.asyncio
async def test_one_role_per_person_per_matter(
    db_session: AsyncSession, owner: User, colleague: User
) -> None:
    """The composite PK is what makes "is this person screened?" have
    exactly one answer — a grant and a screen can never coexist."""
    project = await _mk_project(db_session, owner)
    await _grant(db_session, project, colleague, "reader")
    with pytest.raises(IntegrityError):
        await _grant(db_session, project, colleague, "blocked")
    await db_session.rollback()


@pytest.mark.asyncio
async def test_membership_cascades_on_matter_delete(
    db_session: AsyncSession, owner: User, colleague: User
) -> None:
    from sqlalchemy import delete, select

    project = await _mk_project(db_session, owner)
    await _grant(db_session, project, colleague, "contributor")

    await db_session.execute(delete(Project).where(Project.id == project.id))
    await db_session.flush()

    remaining = (
        (
            await db_session.execute(
                select(ProjectMember).where(ProjectMember.project_id == project.id)
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []


@pytest.mark.asyncio
async def test_default_share_scope_is_personal(db_session: AsyncSession, owner: User) -> None:
    """The column default is fail-restrictive (ADR 0016 P4); a deployment
    opts into ambient visibility via LQ_AI_MATTER_DEFAULT_SHARE_SCOPE."""
    project = Project(owner_id=owner.id, name="M", slug=f"m-{uuid.uuid4().hex[:8]}")
    db_session.add(project)
    await db_session.flush()
    await db_session.refresh(project)
    assert project.share_scope == "personal"


# ---------------------------------------------------------------------------
# Migration 0067's backfill invariant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_reaches_a_matter_with_no_membership_row(
    db_session: AsyncSession, owner: User
) -> None:
    """Ownership short-circuits the roster lookup, so a matter whose lead
    row was deleted by hand never becomes unreachable by its own owner."""
    from sqlalchemy import delete

    project = await _mk_project(db_session, owner)
    await db_session.execute(delete(ProjectMember).where(ProjectMember.project_id == project.id))
    await db_session.flush()
    assert await matter_access(db_session, project, owner) == ("lead", "owner")


# ---------------------------------------------------------------------------
# The batch path must agree with the single-row path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_resolution_matches_the_single_row_path(
    db_session: AsyncSession, owner: User, colleague: User, admin: User
) -> None:
    """`matter_access_map` exists so a listing costs one membership query
    instead of one per row. It must never answer differently."""
    from app.authz.matters import matter_access_map

    owned = await _mk_project(db_session, owner)
    granted = await _mk_project(db_session, owner)
    await _grant(db_session, granted, colleague, "contributor")
    firm_wide = await _mk_project(db_session, owner, share_scope="org")
    screened = await _mk_project(db_session, owner, share_scope="org")
    await _grant(db_session, screened, colleague, "blocked")
    invisible = await _mk_project(db_session, owner)

    projects = [owned, granted, firm_wide, screened, invisible]
    for caller in (owner, colleague, admin):
        batch = await matter_access_map(db_session, projects, caller)
        for project in projects:
            assert batch[project.id] == await matter_access(db_session, project, caller), (
                f"{caller.email} on {project.slug}"
            )


@pytest.mark.asyncio
async def test_batch_resolution_on_an_empty_page(db_session: AsyncSession, owner: User) -> None:
    from app.authz.matters import matter_access_map

    assert await matter_access_map(db_session, [], owner) == {}
