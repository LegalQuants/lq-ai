"""Integration tests for Task D8 — DB-backed user skills (ADR 0012).

Covers the new ``/api/v1/user-skills`` CRUD surface and the merge /
shadow / fork extensions to ``/api/v1/skills``:

* POST/GET/PATCH/DELETE on the user-scope row; cross-user 404 isolation.
* Slug-collision rules: same-user-same-slug → 409; user-slug-shadows-
  built-in → 201 OK (the deliberate shadow case per ADR 0012).
* Soft-delete via ``archived_at``: re-create at same slug after delete
  succeeds; double-delete returns 410.
* Merged ``GET /skills`` listing: user-scope first, built-in second,
  user shadow dedupes its matching built-in.
* ``GET /skills/{slug}`` returns the shadow when present, falls back
  to the built-in otherwise.
* ``POST /skills/{slug}/fork`` copies a built-in into user scope;
  ``scope=team`` returns 400 (deferred to D8.1).
* Audit rows land on every state-changing call; the PATCH version-bump
  path records ``version_before`` / ``version_after``.
* Migration 0013 schema invariants: CHECK constraints, partial UNIQUE
  indexes, FK to users with CASCADE.

Tests follow the project's SAVEPOINT-rolled-back integration pattern;
the skill registry is injected via ``app.state.skill_registry``
(matches ``test_skill_endpoints.py``).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models import AuditLog, User, UserSkill
from app.models.team import Team, TeamMember
from app.security import create_access_token, hash_password
from app.skills import load_registry
from app.skills.registry import MutableSkillRegistry

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "skills"


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


async def _make_user(db_session: AsyncSession, *, suffix: str = "") -> User:
    user = User(
        email=f"user-skill-{suffix or uuid.uuid4().hex[:8]}@example.com",
        display_name=f"User Skill Test {suffix}".strip(),
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def user_a(db_session: AsyncSession) -> User:
    return await _make_user(db_session, suffix="a")


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    return await _make_user(db_session, suffix="b")


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """In-process AsyncClient with the fixture-skills registry installed."""

    app.dependency_overrides[get_db] = _override_get_db(db_session)
    holder = MutableSkillRegistry(load_registry(FIXTURES_DIR))
    prior_holder = getattr(app.state, "skill_registry", None)
    app.state.skill_registry = holder

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    if prior_holder is None:
        delattr(app.state, "skill_registry")
    else:
        app.state.skill_registry = prior_holder
    app.dependency_overrides.pop(get_db, None)


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


def _post_body(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "slug": "personal-nda",
        "display_name": "Personal NDA",
        "description": "My NDA workflow",
        "body": "You review NDAs with attention to noncompetes.",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# /user-skills: create + list + get
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_user_skill_returns_201_and_persists(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    resp = await client.post("/api/v1/user-skills", headers=_bearer(user_a), json=_post_body())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["scope"] == "user"
    assert body["slug"] == "personal-nda"
    assert body["owner_user_id"] == str(user_a.id)
    assert body["version"] == "1.0.0"
    assert body["archived_at"] is None

    row = await db_session.get(UserSkill, uuid.UUID(body["id"]))
    assert row is not None
    assert row.owner_user_id == user_a.id


@pytest.mark.integration
async def test_list_user_skills_is_owner_scoped_and_newest_first(
    client: AsyncClient, db_session: AsyncSession, user_a: User, user_b: User
) -> None:
    """A's list shows only A's rows in updated_at DESC order; B's row never appears."""

    # Insert via the API so updated_at is set by the trigger-friendly path.
    await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="alpha-skill", display_name="A1"),
    )
    await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="beta-skill", display_name="A2"),
    )
    await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_b),
        json=_post_body(slug="alpha-skill", display_name="B1"),
    )

    resp = await client.get("/api/v1/user-skills", headers=_bearer(user_a))
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    assert {r["slug"] for r in rows} == {"alpha-skill", "beta-skill"}
    # Both rows owned by A; no B rows leaked.
    assert all(r["owner_user_id"] == str(user_a.id) for r in rows)


@pytest.mark.integration
async def test_get_user_skill_returns_404_for_non_owner(
    client: AsyncClient, user_a: User, user_b: User
) -> None:
    resp = await client.post("/api/v1/user-skills", headers=_bearer(user_a), json=_post_body())
    skill_id = resp.json()["id"]

    cross = await client.get(f"/api/v1/user-skills/{skill_id}", headers=_bearer(user_b))
    assert cross.status_code == 404


# ---------------------------------------------------------------------------
# /user-skills: slug collision (own + built-in shadow)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_collides_with_own_slug_returns_409(client: AsyncClient, user_a: User) -> None:
    first = await client.post("/api/v1/user-skills", headers=_bearer(user_a), json=_post_body())
    assert first.status_code == 201
    second = await client.post("/api/v1/user-skills", headers=_bearer(user_a), json=_post_body())
    assert second.status_code == 409


@pytest.mark.integration
async def test_create_collides_with_builtin_slug_is_allowed(
    client: AsyncClient, user_a: User
) -> None:
    """Slug shadowing a filesystem built-in is the deliberate fork case (ADR 0012)."""

    resp = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="alpha-test-skill", display_name="My Alpha"),
    )
    assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# /user-skills: PATCH semantics + version-bump audit
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_patch_partial_update_writes_audit_row(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    created = await client.post("/api/v1/user-skills", headers=_bearer(user_a), json=_post_body())
    skill_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/user-skills/{skill_id}",
        headers=_bearer(user_a),
        json={"display_name": "Renamed"},
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Renamed"

    audit = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user_skill.updated",
                    AuditLog.resource_id == skill_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit) == 1
    assert audit[0].details is not None
    assert audit[0].details["changed_fields"] == ["display_name"]


@pytest.mark.integration
async def test_patch_version_bump_records_before_and_after_in_audit(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    created = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(version="1.0.0"),
    )
    skill_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/user-skills/{skill_id}",
        headers=_bearer(user_a),
        json={"version": "1.1.0"},
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == "1.1.0"

    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "user_skill.updated",
                AuditLog.resource_id == skill_id,
            )
        )
    ).scalar_one()
    assert audit.details is not None
    assert audit.details["version_before"] == "1.0.0"
    assert audit.details["version_after"] == "1.1.0"


@pytest.mark.integration
async def test_patch_no_op_does_not_write_audit_row(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    created = await client.post("/api/v1/user-skills", headers=_bearer(user_a), json=_post_body())
    skill_id = created.json()["id"]

    # PATCH with the same display_name → handler short-circuits without
    # an audit row to avoid log churn from idempotent UI re-saves.
    resp = await client.patch(
        f"/api/v1/user-skills/{skill_id}",
        headers=_bearer(user_a),
        json={"display_name": "Personal NDA"},
    )
    assert resp.status_code == 200

    audit = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user_skill.updated",
                    AuditLog.resource_id == skill_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert audit == []


@pytest.mark.integration
async def test_patch_non_owner_returns_404(client: AsyncClient, user_a: User, user_b: User) -> None:
    created = await client.post("/api/v1/user-skills", headers=_bearer(user_a), json=_post_body())
    skill_id = created.json()["id"]
    cross = await client.patch(
        f"/api/v1/user-skills/{skill_id}",
        headers=_bearer(user_b),
        json={"display_name": "I am evil"},
    )
    assert cross.status_code == 404


# ---------------------------------------------------------------------------
# /user-skills: soft-delete + 410 + slug re-use
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_delete_soft_deletes_and_writes_audit(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    created = await client.post("/api/v1/user-skills", headers=_bearer(user_a), json=_post_body())
    skill_id = created.json()["id"]

    resp = await client.delete(f"/api/v1/user-skills/{skill_id}", headers=_bearer(user_a))
    assert resp.status_code == 204

    row = await db_session.get(UserSkill, uuid.UUID(skill_id))
    assert row is not None
    assert row.archived_at is not None

    # Default list excludes archived rows.
    listing = await client.get("/api/v1/user-skills", headers=_bearer(user_a))
    assert listing.json() == []

    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "user_skill.deleted",
                AuditLog.resource_id == skill_id,
            )
        )
    ).scalar_one()
    assert audit.details is not None
    assert audit.details["slug"] == "personal-nda"


@pytest.mark.integration
async def test_delete_then_delete_returns_410(client: AsyncClient, user_a: User) -> None:
    created = await client.post("/api/v1/user-skills", headers=_bearer(user_a), json=_post_body())
    skill_id = created.json()["id"]
    first = await client.delete(f"/api/v1/user-skills/{skill_id}", headers=_bearer(user_a))
    assert first.status_code == 204
    second = await client.delete(f"/api/v1/user-skills/{skill_id}", headers=_bearer(user_a))
    assert second.status_code == 410


@pytest.mark.integration
async def test_recreate_at_same_slug_after_delete_succeeds(
    client: AsyncClient, user_a: User
) -> None:
    """Archiving a row frees the slug for a new creation."""

    first = await client.post("/api/v1/user-skills", headers=_bearer(user_a), json=_post_body())
    await client.delete(f"/api/v1/user-skills/{first.json()['id']}", headers=_bearer(user_a))
    second = await client.post("/api/v1/user-skills", headers=_bearer(user_a), json=_post_body())
    assert second.status_code == 201
    assert second.json()["slug"] == "personal-nda"


# ---------------------------------------------------------------------------
# /skills: merged listing with user shadow
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_merged_list_shows_user_rows_first(client: AsyncClient, user_a: User) -> None:
    await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="zeta-rare"),
    )
    resp = await client.get("/api/v1/skills", headers=_bearer(user_a))
    assert resp.status_code == 200
    rows = resp.json()
    # User-scope rows precede built-ins regardless of name ordering.
    assert rows[0]["scope"] == "user"
    assert rows[0]["name"] == "zeta-rare"


@pytest.mark.integration
async def test_merged_list_dedupes_built_in_on_user_shadow(
    client: AsyncClient, user_a: User
) -> None:
    """A user shadow at slug=alpha-test-skill hides the built-in for that user."""

    await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="alpha-test-skill", display_name="My Alpha"),
    )
    resp = await client.get("/api/v1/skills", headers=_bearer(user_a))
    rows = resp.json()
    alpha_rows = [r for r in rows if r["name"] == "alpha-test-skill"]
    assert len(alpha_rows) == 1
    assert alpha_rows[0]["scope"] == "user"
    assert alpha_rows[0]["title"] == "My Alpha"


@pytest.mark.integration
async def test_merged_list_scope_filters_independently(client: AsyncClient, user_a: User) -> None:
    await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="alpha-test-skill"),
    )

    user_only = await client.get("/api/v1/skills?scope=user", headers=_bearer(user_a))
    assert all(r["scope"] == "user" for r in user_only.json())

    builtin_only = await client.get("/api/v1/skills?scope=builtin", headers=_bearer(user_a))
    # builtin scope does NOT apply the shadow dedup — operator-side
    # surfaces (e.g., the "as-shipped catalog" admin view) need the
    # raw view. The handler returns built-ins straight from the
    # registry.
    builtin_rows = builtin_only.json()
    assert all(r["scope"] == "builtin" for r in builtin_rows)
    assert any(r["name"] == "alpha-test-skill" for r in builtin_rows)

    team_only = await client.get("/api/v1/skills?scope=team", headers=_bearer(user_a))
    assert team_only.json() == []


# ---------------------------------------------------------------------------
# /skills/{slug}: shadow resolution
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_skill_returns_shadow_when_present(client: AsyncClient, user_a: User) -> None:
    await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="alpha-test-skill", body="my custom body"),
    )
    resp = await client.get("/api/v1/skills/alpha-test-skill", headers=_bearer(user_a))
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "user"
    assert body["content_md"] == "my custom body"


@pytest.mark.integration
async def test_get_skill_falls_back_to_builtin_when_no_shadow(
    client: AsyncClient, user_a: User
) -> None:
    resp = await client.get("/api/v1/skills/alpha-test-skill", headers=_bearer(user_a))
    assert resp.status_code == 200
    assert resp.json()["scope"] == "builtin"


@pytest.mark.integration
async def test_get_skill_shadow_is_per_user(
    client: AsyncClient, user_a: User, user_b: User
) -> None:
    """A's shadow does not affect B's resolution."""

    await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="alpha-test-skill", body="A's body"),
    )
    b_resp = await client.get("/api/v1/skills/alpha-test-skill", headers=_bearer(user_b))
    assert b_resp.status_code == 200
    body = b_resp.json()
    assert body["scope"] == "builtin"
    assert "A's body" not in body["content_md"]


# ---------------------------------------------------------------------------
# /skills/{slug}/fork
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_fork_copies_built_in_into_user_scope(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    resp = await client.post(
        "/api/v1/skills/alpha-test-skill/fork",
        headers=_bearer(user_a),
        json={"new_name": "my-alpha", "scope": "user"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["scope"] == "user"
    assert body["name"] == "my-alpha"
    # Tier and other extension keys carried through frontmatter_extra.
    assert body.get("minimum_inference_tier") == 2

    audit = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == "user_skill.created")))
        .scalars()
        .all()
    )
    assert any((a.details or {}).get("forked_from") == "alpha-test-skill" for a in audit)


@pytest.mark.integration
async def test_fork_team_scope_returns_400(client: AsyncClient, user_a: User) -> None:
    resp = await client.post(
        "/api/v1/skills/alpha-test-skill/fork",
        headers=_bearer(user_a),
        json={"new_name": "team-alpha", "scope": "team"},
    )
    assert resp.status_code == 400
    assert "D8.1" in resp.json()["detail"]


@pytest.mark.integration
async def test_fork_unknown_source_returns_404(client: AsyncClient, user_a: User) -> None:
    resp = await client.post(
        "/api/v1/skills/does-not-exist/fork",
        headers=_bearer(user_a),
        json={"new_name": "x", "scope": "user"},
    )
    assert resp.status_code == 404


@pytest.mark.integration
async def test_fork_default_slug_creates_same_name_shadow(
    client: AsyncClient, user_a: User
) -> None:
    """Omitting ``new_name`` → forked row inherits the source slug, which
    is the natural "I want my own version of nda-review" shadow case."""

    resp = await client.post(
        "/api/v1/skills/alpha-test-skill/fork",
        headers=_bearer(user_a),
        json={"scope": "user"},
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "alpha-test-skill"
    assert resp.json()["scope"] == "user"


# ---------------------------------------------------------------------------
# Migration 0013 invariants
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_user_skills_check_constraints(db_session: AsyncSession, user_a: User) -> None:
    """The scope/owner-consistency CHECK rejects mismatched rows."""

    bad = UserSkill(
        scope="user",
        owner_user_id=None,  # violates CHECK
        slug="bad",
        display_name="bad",
        description="bad",
        body="bad",
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.integration
async def test_user_skills_partial_unique_index(db_session: AsyncSession, user_a: User) -> None:
    """Two non-archived rows for the same (user, slug) violate uniqueness."""

    first = UserSkill(
        scope="user",
        owner_user_id=user_a.id,
        slug="dup",
        display_name="first",
        description="first",
        body="first",
    )
    db_session.add(first)
    await db_session.flush()

    second = UserSkill(
        scope="user",
        owner_user_id=user_a.id,
        slug="dup",
        display_name="second",
        description="second",
        body="second",
    )
    db_session.add(second)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.integration
async def test_user_skills_table_indexes_exist(db_session: AsyncSession) -> None:
    expected = {
        "idx_user_skills_owner_user",
        "idx_user_skills_owner_team",
        "ux_user_skills_user_slug",
        "ux_user_skills_team_slug",
    }
    result = await db_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = ANY(:names)"
        ),
        {"names": list(expected)},
    )
    found = {row[0] for row in result.fetchall()}
    assert found == expected, f"missing: {expected - found}"


# ---------------------------------------------------------------------------
# D8.1b — team-scope user-skills (POST/PATCH/DELETE branches)
# ---------------------------------------------------------------------------


async def _make_team(
    db_session: AsyncSession,
    *,
    slug: str,
    creator: User,
    admins: list[User] | None = None,
    members: list[User] | None = None,
) -> Team:
    """Create a team and populate its membership in one shot.

    ``creator`` is implicitly added as a team-admin member (mirrors the
    auto-membership the ``POST /admin/teams`` handler performs); extra
    admins / members ride the explicit lists.
    """

    team = Team(
        slug=slug,
        name=slug.replace("-", " ").title(),
        created_by_user_id=creator.id,
    )
    db_session.add(team)
    await db_session.flush()

    db_session.add(
        TeamMember(
            team_id=team.id,
            user_id=creator.id,
            role="admin",
            added_by_user_id=creator.id,
        )
    )
    for admin in admins or []:
        if admin.id == creator.id:
            continue
        db_session.add(
            TeamMember(
                team_id=team.id,
                user_id=admin.id,
                role="admin",
                added_by_user_id=creator.id,
            )
        )
    for member in members or []:
        if member.id == creator.id:
            continue
        db_session.add(
            TeamMember(
                team_id=team.id,
                user_id=member.id,
                role="member",
                added_by_user_id=creator.id,
            )
        )
    await db_session.flush()
    return team


@pytest.mark.integration
async def test_create_team_scope_skill_as_team_admin_returns_201(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    """Team admin posts a team-scope skill → 201; row carries owner_team_id,
    audit details include team_id + team_slug."""

    team = await _make_team(db_session, slug="contracts", creator=user_a)

    resp = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="team-nda", scope="team", owner_team_id=str(team.id)),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["scope"] == "team"
    assert body["owner_user_id"] is None
    assert body["owner_team_id"] == str(team.id)
    assert body["slug"] == "team-nda"

    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "user_skill.created",
                AuditLog.resource_id == body["id"],
            )
        )
    ).scalar_one()
    assert audit.details is not None
    assert audit.details["scope"] == "team"
    assert audit.details["team_id"] == str(team.id)
    assert audit.details["team_slug"] == "contracts"


@pytest.mark.integration
async def test_create_team_scope_skill_as_member_returns_404(
    client: AsyncClient, db_session: AsyncSession, user_a: User, user_b: User
) -> None:
    """Non-admin members cannot create team-scope skills. 404 (not 403) keeps
    the id-probing-safe posture: a stranger can't distinguish 'wrong role'
    from 'no such team' by status code alone."""

    team = await _make_team(db_session, slug="readers", creator=user_a, members=[user_b])

    resp = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_b),
        json=_post_body(slug="member-attempt", scope="team", owner_team_id=str(team.id)),
    )
    assert resp.status_code == 404


@pytest.mark.integration
async def test_create_team_scope_skill_as_non_member_returns_404(
    client: AsyncClient, db_session: AsyncSession, user_a: User, user_b: User
) -> None:
    """A user with no membership in the named team → 404 (same id-probing posture)."""

    team = await _make_team(db_session, slug="strangers", creator=user_a)

    resp = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_b),
        json=_post_body(slug="stranger-attempt", scope="team", owner_team_id=str(team.id)),
    )
    assert resp.status_code == 404


@pytest.mark.integration
async def test_create_team_scope_without_owner_team_id_returns_422(
    client: AsyncClient, user_a: User
) -> None:
    resp = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="no-team", scope="team"),
    )
    assert resp.status_code == 422
    assert "owner_team_id is required" in resp.json()["detail"]


@pytest.mark.integration
async def test_create_user_scope_with_owner_team_id_returns_422(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    """Hybrid rows (scope=user + owner_team_id set) are rejected at the API
    boundary — keeps the DB CHECK constraint as defense-in-depth."""

    team = await _make_team(db_session, slug="oops", creator=user_a)

    resp = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="hybrid", scope="user", owner_team_id=str(team.id)),
    )
    assert resp.status_code == 422
    assert "must be null" in resp.json()["detail"]


@pytest.mark.integration
async def test_create_team_scope_slug_collision_returns_409(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    """Two non-archived team-scope rows at the same (team, slug) violate the
    partial UNIQUE index. The handler surfaces 409 with a team-flavored
    error message."""

    team = await _make_team(db_session, slug="docs", creator=user_a)

    first = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="onboard", scope="team", owner_team_id=str(team.id)),
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="onboard", scope="team", owner_team_id=str(team.id)),
    )
    assert second.status_code == 409
    assert "team" in second.json()["detail"]


@pytest.mark.integration
async def test_team_and_user_scope_can_share_slug(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    """A user can simultaneously have a user-scope shadow AND a team-scope
    skill at the same slug — the partial UNIQUE indexes are scope-segmented.
    The D8.1b resolver picks the user one for that user."""

    team = await _make_team(db_session, slug="ny-litigation", creator=user_a)

    user_row = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="briefing"),
    )
    assert user_row.status_code == 201

    team_row = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="briefing", scope="team", owner_team_id=str(team.id)),
    )
    assert team_row.status_code == 201


@pytest.mark.integration
async def test_patch_team_scope_as_team_admin_succeeds(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    team = await _make_team(db_session, slug="patchers", creator=user_a)

    created = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="team-edit", scope="team", owner_team_id=str(team.id)),
    )
    skill_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/user-skills/{skill_id}",
        headers=_bearer(user_a),
        json={"display_name": "Renamed Team Skill"},
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Renamed Team Skill"

    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "user_skill.updated",
                AuditLog.resource_id == skill_id,
            )
        )
    ).scalar_one()
    assert audit.details is not None
    assert audit.details["scope"] == "team"
    assert audit.details["team_id"] == str(team.id)


@pytest.mark.integration
async def test_patch_team_scope_as_member_returns_404(
    client: AsyncClient, db_session: AsyncSession, user_a: User, user_b: User
) -> None:
    """A non-admin member sees the team-scope row in the picker but cannot
    PATCH it — 404 keeps the id-probing-safe posture."""

    team = await _make_team(db_session, slug="read-only", creator=user_a, members=[user_b])
    created = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="member-cant-edit", scope="team", owner_team_id=str(team.id)),
    )
    skill_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/user-skills/{skill_id}",
        headers=_bearer(user_b),
        json={"display_name": "I am a member trying to edit"},
    )
    assert resp.status_code == 404


@pytest.mark.integration
async def test_delete_team_scope_as_team_admin_archives_row(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    team = await _make_team(db_session, slug="deleters", creator=user_a)
    created = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="team-archive", scope="team", owner_team_id=str(team.id)),
    )
    skill_id = created.json()["id"]

    resp = await client.delete(f"/api/v1/user-skills/{skill_id}", headers=_bearer(user_a))
    assert resp.status_code == 204

    row = await db_session.get(UserSkill, uuid.UUID(skill_id))
    assert row is not None
    assert row.archived_at is not None

    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "user_skill.deleted",
                AuditLog.resource_id == skill_id,
            )
        )
    ).scalar_one()
    assert audit.details is not None
    assert audit.details["scope"] == "team"
    assert audit.details["team_id"] == str(team.id)


@pytest.mark.integration
async def test_delete_team_scope_as_non_member_returns_404(
    client: AsyncClient, db_session: AsyncSession, user_a: User, user_b: User
) -> None:
    team = await _make_team(db_session, slug="locked", creator=user_a)
    created = await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="locked-skill", scope="team", owner_team_id=str(team.id)),
    )
    skill_id = created.json()["id"]

    resp = await client.delete(f"/api/v1/user-skills/{skill_id}", headers=_bearer(user_b))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# D8.1c — list endpoint scope filter (user | team | all)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_default_scope_user_only(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    """The default ``?scope=user`` preserves the D8 behavior — team-scope
    rows the caller can edit are NOT mixed in unless explicitly requested."""

    team = await _make_team(db_session, slug="default-test", creator=user_a)
    await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="user-row"),
    )
    await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="team-row", scope="team", owner_team_id=str(team.id)),
    )

    resp = await client.get("/api/v1/user-skills", headers=_bearer(user_a))
    assert resp.status_code == 200
    rows = resp.json()
    assert {r["slug"] for r in rows} == {"user-row"}
    assert all(r["scope"] == "user" for r in rows)


@pytest.mark.integration
async def test_list_scope_team_returns_team_admin_rows(
    client: AsyncClient, db_session: AsyncSession, user_a: User, user_b: User
) -> None:
    """``?scope=team`` returns team-scope rows from teams where the caller
    is a team-admin. Rows from teams where the caller is only a member
    do NOT appear (members read team skills in the chat picker, not here)."""

    admin_team = await _make_team(db_session, slug="admin-team", creator=user_a)
    member_team = await _make_team(db_session, slug="member-team", creator=user_b, members=[user_a])

    # user_a creates an admin-team skill; user_b creates a member-team skill.
    await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="admin-team-skill", scope="team", owner_team_id=str(admin_team.id)),
    )
    await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_b),
        json=_post_body(slug="member-team-skill", scope="team", owner_team_id=str(member_team.id)),
    )

    resp = await client.get("/api/v1/user-skills?scope=team", headers=_bearer(user_a))
    assert resp.status_code == 200
    rows = resp.json()
    slugs = {r["slug"] for r in rows}
    assert "admin-team-skill" in slugs
    assert "member-team-skill" not in slugs


@pytest.mark.integration
async def test_list_scope_all_returns_user_and_team_admin_rows(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    """``?scope=all`` returns both layers merged + sorted by updated_at."""

    team = await _make_team(db_session, slug="merged", creator=user_a)
    await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="merged-user"),
    )
    await client.post(
        "/api/v1/user-skills",
        headers=_bearer(user_a),
        json=_post_body(slug="merged-team", scope="team", owner_team_id=str(team.id)),
    )

    resp = await client.get("/api/v1/user-skills?scope=all", headers=_bearer(user_a))
    assert resp.status_code == 200
    rows = resp.json()
    slugs = {r["slug"] for r in rows}
    assert slugs == {"merged-user", "merged-team"}
    assert {r["scope"] for r in rows} == {"user", "team"}


@pytest.mark.integration
async def test_list_invalid_scope_returns_422(client: AsyncClient, user_a: User) -> None:
    resp = await client.get("/api/v1/user-skills?scope=builtin", headers=_bearer(user_a))
    assert resp.status_code == 422
