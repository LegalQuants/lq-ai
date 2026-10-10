"""Tests for the DE-263 admin community-skill installer (ADR 0041).

Unit layer — ``app/skills/community_installer.py``:

* catalog scan against a tmp fixture dir (valid + malformed + name-
  mismatch skills; absent dir);
* submodule sha resolution via pure file reads of git plumbing
  (detached HEAD, symbolic ref → loose ref, packed-refs, absent →
  ``None``);
* provenance-ref formatting and attestation extraction (display-only,
  never synthesized).

Integration layer — ``app/api/community_skills.py``:

* 403 for a non-admin authenticated user on EVERY endpoint;
* catalog list (entries, load_errors surfaced, installed indication,
  source sha) and the empty/absent-submodule 200-with-hint;
* detail (full body + raw yaml + install_ref), 404 unknown slug,
  422 malformed SKILL.md;
* install happy path (user_skills row + ``forked_from`` provenance +
  ``community_skill.installed`` audit row), 409 already-installed,
  422 for bounds-violating content, 404 unknown slug.

The catalog dependency is overridden with a per-test tmp fixture dir so
the suite does not depend on the ``skills/community`` submodule being
initialized in the checkout (ADR 0041 §3 makes absence first-class).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import community_skills as community_skills_api
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.team import Team, TeamMember
from app.models.user import User
from app.models.user_skill import UserSkill
from app.security import create_access_token, hash_password
from app.skills.community_installer import (
    attestation_of,
    canonical_hash,
    forked_from_ref,
    installation_snapshot,
    public_repository_identity,
    resolve_catalog_dir,
    resolve_submodule_sha,
    scan_catalog,
)
from app.skills.registry import MutableSkillRegistry, SkillRegistry

_SHA = "abc123def4567890abc123def4567890abc123de"


# ---------------------------------------------------------------------------
# Fixture-corpus helpers
# ---------------------------------------------------------------------------


def _write_skill(
    base: Path,
    slug: str,
    *,
    description: str = "One-sentence trigger statement.",
    body: str = "You are reviewing a document.\n",
    lq_ai_block: str = '  title: "Fixture Skill"\n  version: "1.0.0"\n',
    top_level_extra: str = "",
    frontmatter_name: str | None = None,
) -> Path:
    folder = base / slug
    folder.mkdir(parents=True)
    name = frontmatter_name if frontmatter_name is not None else slug
    (folder / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"{top_level_extra}"
        "lq_ai:\n"
        f"{lq_ai_block}"
        "---\n"
        f"{body}",
        encoding="utf-8",
    )
    return folder


def _write_malformed_skill(base: Path, slug: str) -> Path:
    """A SKILL.md whose frontmatter is missing the required description."""

    folder = base / slug
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"---\nname: {slug}\n---\nbody\n", encoding="utf-8")
    return folder


def _write_submodule_plumbing(root: Path, sha: str = _SHA) -> None:
    """Fake the initialized-submodule git plumbing: ``.git`` file pointing
    at a gitdir whose HEAD is a detached sha (the normal submodule state)."""

    gitdir = root.parent / ".git" / "modules" / "community"
    gitdir.mkdir(parents=True)
    (gitdir / "config").write_text(
        '[remote "origin"]\nurl = https://github.com/LegalQuants/lq-skills.git\n', encoding="utf-8"
    )
    (gitdir / "HEAD").write_text(sha + "\n", encoding="utf-8")
    (root / ".git").write_text("gitdir: ../.git/modules/community\n", encoding="utf-8")


@pytest.fixture
def catalog_dir(tmp_path: Path) -> Path:
    """A populated community corpus: two valid skills, one malformed,
    one frontmatter/folder name mismatch, plus submodule git plumbing."""

    root = tmp_path / "community"
    catalog = root / "skills"
    catalog.mkdir(parents=True)
    _write_skill(
        catalog,
        "lease-review",
        description="First-pass review of commercial leases.",
        lq_ai_block=(
            '  title: "Lease Review"\n'
            '  version: "1.2.0"\n'
            '  author: "Jane Attorney"\n'
            "  tags: [real-estate, review]\n"
            "  jurisdiction: us\n"
            "  output_format: report\n"
        ),
        top_level_extra='attested_by: "Jane Attorney, NY Bar #12345"\n',
    )
    _write_skill(
        catalog,
        "nda-triage",
        description="Quick triage pass over inbound NDAs.",
        lq_ai_block='  version: "0.9.0"\n',
    )
    _write_malformed_skill(catalog, "broken-skill")
    _write_skill(catalog, "mismatched", frontmatter_name="other-name")
    _write_submodule_plumbing(root)
    return catalog


# ---------------------------------------------------------------------------
# Unit — catalog scan
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_scan_catalog_lists_valid_and_surfaces_failures(catalog_dir: Path) -> None:
    catalog = scan_catalog(catalog_dir)

    assert catalog.dir_present is True
    assert [r.name for r in catalog.records] == ["lease-review", "nda-triage"]
    # Both broken entries are visible as failures, not silently dropped.
    assert len(catalog.load_errors) == 2
    assert any("broken-skill" in err for err in catalog.load_errors)
    assert any("mismatched" in err for err in catalog.load_errors)
    assert catalog.sha == _SHA


@pytest.mark.unit
def test_scan_catalog_absent_dir_is_first_class_empty(tmp_path: Path) -> None:
    catalog = scan_catalog(tmp_path / "nope" / "skills")

    assert catalog.dir_present is False
    assert catalog.records == []
    assert catalog.load_errors == []
    assert catalog.sha is None


@pytest.mark.unit
def test_resolve_catalog_dir_prefers_operator_override(tmp_path: Path) -> None:
    settings = SimpleNamespace(
        community_skills_dir=str(tmp_path / "custom"), skills_dir=str(tmp_path / "skills")
    )
    assert resolve_catalog_dir(settings) == (tmp_path / "custom").resolve()  # type: ignore[arg-type]

    settings = SimpleNamespace(community_skills_dir=None, skills_dir=str(tmp_path / "skills"))
    expected = (tmp_path / "skills").resolve() / "community" / "skills"
    assert resolve_catalog_dir(settings) == expected  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Unit — sha resolution (pure file reads; no git subprocess)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sha_from_detached_head_via_gitdir_pointer(tmp_path: Path) -> None:
    root = tmp_path / "community"
    catalog = root / "skills"
    catalog.mkdir(parents=True)
    _write_submodule_plumbing(root)

    assert resolve_submodule_sha(catalog) == _SHA


@pytest.mark.unit
def test_sha_from_symbolic_ref_loose_file(tmp_path: Path) -> None:
    root = tmp_path / "community"
    catalog = root / "skills"
    catalog.mkdir(parents=True)
    gitdir = root / ".git"
    (gitdir / "refs" / "heads").mkdir(parents=True)
    (gitdir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (gitdir / "refs" / "heads" / "main").write_text(_SHA + "\n", encoding="utf-8")

    assert resolve_submodule_sha(catalog) == _SHA


@pytest.mark.unit
def test_sha_from_symbolic_ref_packed_refs(tmp_path: Path) -> None:
    root = tmp_path / "community"
    catalog = root / "skills"
    catalog.mkdir(parents=True)
    gitdir = root / ".git"
    gitdir.mkdir()
    (gitdir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (gitdir / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted\n"
        f"{_SHA} refs/heads/main\n"
        "^deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n",
        encoding="utf-8",
    )

    assert resolve_submodule_sha(catalog) == _SHA


@pytest.mark.unit
def test_sha_degrades_to_none_without_plumbing(tmp_path: Path) -> None:
    root = tmp_path / "community"
    catalog = root / "skills"
    catalog.mkdir(parents=True)

    assert resolve_submodule_sha(catalog) is None
    # An unparseable .git file also degrades instead of raising.
    (root / ".git").write_text("not a gitdir pointer\n", encoding="utf-8")
    assert resolve_submodule_sha(catalog) is None


@pytest.mark.unit
def test_forked_from_ref_degrades_sha_honestly() -> None:
    assert (
        forked_from_ref("lease-review", _SHA, "https://github.com/LegalQuants/lq-skills.git")
        == f"https://github.com/LegalQuants/lq-skills.git:lease-review@{_SHA}"
    )
    assert forked_from_ref("lease-review", None) == "unknown-source:lease-review@unknown"


@pytest.mark.unit
def test_attestation_is_read_never_synthesized(catalog_dir: Path) -> None:
    catalog = scan_catalog(catalog_dir)
    by_name = {r.name: r for r in catalog.records}

    assert attestation_of(by_name["lease-review"]) == "Jane Attorney, NY Bar #12345"
    assert attestation_of(by_name["nda-triage"]) is None


# ---------------------------------------------------------------------------
# Integration — endpoint fixtures
# ---------------------------------------------------------------------------


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


async def _make_user(
    db_session: AsyncSession,
    *,
    email: str,
    is_admin: bool,
) -> tuple[User, str]:
    user = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password("test-password-123"),
        is_admin=is_admin,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.commit()
    token = create_access_token(user_id=user.id, email=user.email, is_admin=user.is_admin)
    return user, token


def _install_catalog_override(catalog_path: Path) -> None:
    app.dependency_overrides[community_skills_api._catalog] = lambda: scan_catalog(catalog_path)


@pytest_asyncio.fixture
async def admin_client(
    db_session: AsyncSession, catalog_dir: Path
) -> AsyncIterator[tuple[AsyncClient, str, User]]:
    user, token = await _make_user(db_session, email="admin-community@example.com", is_admin=True)
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    _install_catalog_override(catalog_dir)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, token, user
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(community_skills_api._catalog, None)


@pytest_asyncio.fixture
async def member_client(
    db_session: AsyncSession, catalog_dir: Path
) -> AsyncIterator[tuple[AsyncClient, str]]:
    _user, token = await _make_user(
        db_session, email="member-community@example.com", is_admin=False
    )
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    _install_catalog_override(catalog_dir)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, token
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(community_skills_api._catalog, None)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _install_payload(
    ac: AsyncClient, token: str, slug: str, team_id: uuid.UUID | None = None
) -> dict:
    params = {"scope": "team", "owner_team_id": str(team_id)} if team_id else {}
    detail = await ac.get(
        f"/api/v1/admin/community-skills/{slug}", headers=_auth(token), params=params
    )
    fingerprint = (
        detail.json()["provenance"]["review_hash"] if detail.status_code == 200 else "0" * 64
    )
    return {
        "scope": "team" if team_id else "user",
        "owner_team_id": str(team_id) if team_id else None,
        "expected_review_hash": fingerprint,
    }


# ---------------------------------------------------------------------------
# Integration — admin gate (403 on EVERY endpoint for non-admins)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/admin/community-skills"),
        ("GET", "/api/v1/admin/community-skills/lease-review"),
        ("POST", "/api/v1/admin/community-skills/lease-review/install"),
    ],
)
async def test_non_admin_gets_403_on_every_endpoint(
    member_client: tuple[AsyncClient, str],
    method: str,
    path: str,
) -> None:
    ac, token = member_client
    res = await ac.request(method, path, headers=_auth(token))
    assert res.status_code == 403, res.text


# ---------------------------------------------------------------------------
# Integration — catalog list
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_returns_catalog_with_source_and_load_errors(
    admin_client: tuple[AsyncClient, str, User],
) -> None:
    ac, token, _user = admin_client
    res = await ac.get("/api/v1/admin/community-skills", headers=_auth(token))
    assert res.status_code == 200, res.text
    body = res.json()

    assert [item["slug"] for item in body["items"]] == ["lease-review", "nda-triage"]
    lease = body["items"][0]
    assert lease["title"] == "Lease Review"
    assert lease["version"] == "1.2.0"
    assert lease["attested_by"] == "Jane Attorney, NY Bar #12345"
    assert lease["installed"] is False
    assert lease["body_preview"].startswith("You are reviewing")
    # No attestation declared → null, never synthesized.
    assert body["items"][1]["attested_by"] is None

    assert body["source"]["sha"] == _SHA
    assert body["source"]["submodule_present"] is True
    assert body["source"]["operator_hint"] is None
    assert len(body["load_errors"]) == 2


@pytest.mark.integration
async def test_list_absent_submodule_is_200_with_operator_hint(
    admin_client: tuple[AsyncClient, str, User],
    tmp_path: Path,
) -> None:
    ac, token, _user = admin_client
    _install_catalog_override(tmp_path / "absent" / "skills")

    res = await ac.get("/api/v1/admin/community-skills", headers=_auth(token))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["items"] == []
    assert body["source"]["submodule_present"] is False
    assert body["source"]["sha"] is None
    assert "git submodule update --init" in body["source"]["operator_hint"]


# ---------------------------------------------------------------------------
# Integration — detail
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_detail_returns_full_skill_md(
    admin_client: tuple[AsyncClient, str, User],
) -> None:
    ac, token, _user = admin_client
    res = await ac.get("/api/v1/admin/community-skills/lease-review", headers=_auth(token))
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["slug"] == "lease-review"
    assert body["content_md"].startswith("You are reviewing")
    assert "name: lease-review" in body["content_yaml"]
    assert body["output_format"] == "report"
    assert (
        body["install_ref"] == f"https://github.com/LegalQuants/lq-skills.git:lease-review@{_SHA}"
    )


@pytest.mark.integration
async def test_detail_unknown_slug_404(admin_client: tuple[AsyncClient, str, User]) -> None:
    ac, token, _user = admin_client
    res = await ac.get("/api/v1/admin/community-skills/no-such-skill", headers=_auth(token))
    assert res.status_code == 404, res.text


@pytest.mark.integration
async def test_detail_malformed_skill_md_422_names_the_problem(
    admin_client: tuple[AsyncClient, str, User],
) -> None:
    ac, token, _user = admin_client
    res = await ac.get("/api/v1/admin/community-skills/broken-skill", headers=_auth(token))
    assert res.status_code == 422, res.text
    assert "malformed SKILL.md" in res.json()["detail"]


@pytest.mark.integration
async def test_path_shaped_slug_is_rejected_before_filesystem_join(
    admin_client: tuple[AsyncClient, str, User],
) -> None:
    ac, token, _user = admin_client
    res = await ac.get("/api/v1/admin/community-skills/Bad_Slug", headers=_auth(token))
    assert res.status_code == 422, res.text


# ---------------------------------------------------------------------------
# Integration — install
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_install_persists_row_with_provenance_and_audit(
    admin_client: tuple[AsyncClient, str, User],
    db_session: AsyncSession,
) -> None:
    ac, token, user = admin_client
    res = await ac.post(
        "/api/v1/admin/community-skills/lease-review/install",
        headers=_auth(token),
        json=await _install_payload(ac, token, "lease-review"),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["slug"] == "lease-review"
    assert body["scope"] == "user"
    assert body["owner_user_id"] == str(user.id)
    assert (
        body["forked_from"] == f"https://github.com/LegalQuants/lq-skills.git:lease-review@{_SHA}"
    )
    assert body["frontmatter_extra"] == {"jurisdiction": "us", "output_format": "report"}

    row = (
        await db_session.execute(select(UserSkill).where(UserSkill.id == uuid.UUID(body["id"])))
    ).scalar_one()
    assert row.forked_from == f"https://github.com/LegalQuants/lq-skills.git:lease-review@{_SHA}"
    assert row.owner_user_id == user.id
    assert row.display_name == "Lease Review"

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "community_skill.installed")
        )
    ).scalar_one()
    assert audit.resource_type == "user_skill"
    assert audit.resource_id == str(row.id)
    assert audit.user_id == user.id
    assert audit.details is not None
    assert (
        audit.details["forked_from"]
        == f"https://github.com/LegalQuants/lq-skills.git:lease-review@{_SHA}"
    )
    assert audit.details["source"]["revision"] == _SHA
    assert audit.details["source"]["declared_attestation"] == "Jane Attorney, NY Bar #12345"

    # The list now reports the slug as installed for this admin.
    res = await ac.get("/api/v1/admin/community-skills", headers=_auth(token))
    installed = {item["slug"]: item["installed"] for item in res.json()["items"]}
    assert installed == {"lease-review": True, "nda-triage": False}


@pytest.mark.integration
async def test_install_twice_409_until_archived(
    admin_client: tuple[AsyncClient, str, User],
) -> None:
    ac, token, _user = admin_client
    first = await ac.post(
        "/api/v1/admin/community-skills/lease-review/install",
        headers=_auth(token),
        json=await _install_payload(ac, token, "lease-review"),
    )
    assert first.status_code == 201, first.text

    second = await ac.post(
        "/api/v1/admin/community-skills/lease-review/install",
        headers=_auth(token),
        json=await _install_payload(ac, token, "lease-review"),
    )
    assert second.status_code == 409, second.text
    assert "archive it first" in second.json()["detail"]


@pytest.mark.integration
async def test_install_malformed_skill_md_422(
    admin_client: tuple[AsyncClient, str, User],
) -> None:
    ac, token, _user = admin_client
    res = await ac.post(
        "/api/v1/admin/community-skills/broken-skill/install",
        headers=_auth(token),
        json=await _install_payload(ac, token, "broken-skill"),
    )
    assert res.status_code == 422, res.text
    assert "malformed SKILL.md" in res.json()["detail"]


@pytest.mark.integration
async def test_install_bounds_violation_gets_user_skill_422(
    admin_client: tuple[AsyncClient, str, User],
    catalog_dir: Path,
) -> None:
    """A parseable SKILL.md whose fields violate the ADR 0012 bounds is
    rejected through the reused UserSkillCreate path (description > 2000)."""

    ac, token, _user = admin_client
    _write_skill(
        catalog_dir,
        "too-long",
        description="x" * 2_100,
        lq_ai_block='  version: "1.0.0"\n',
    )

    res = await ac.post(
        "/api/v1/admin/community-skills/too-long/install",
        headers=_auth(token),
        json=await _install_payload(ac, token, "too-long"),
    )
    assert res.status_code == 422, res.text
    assert "violates user-skill bounds" in res.json()["detail"]


@pytest.mark.integration
async def test_install_unknown_slug_404(admin_client: tuple[AsyncClient, str, User]) -> None:
    ac, token, _user = admin_client
    res = await ac.post(
        "/api/v1/admin/community-skills/no-such-skill/install",
        headers=_auth(token),
        json=await _install_payload(ac, token, "no-such-skill"),
    )
    assert res.status_code == 404, res.text


@pytest.mark.unit
def test_missing_git_metadata_retains_content_identity(tmp_path: Path) -> None:
    _write_skill(tmp_path, "review")
    catalog = scan_catalog(tmp_path)
    snapshot = installation_snapshot(catalog.records[0], catalog)
    assert snapshot["source"]["repository"] is None
    assert snapshot["source"]["revision"] is None
    assert snapshot["content_hash"] == canonical_hash(snapshot["installed_content"])
    assert len(snapshot["content_hash"]) == 64


@pytest.mark.unit
def test_local_edits_change_content_hash_without_verifying_head(catalog_dir: Path) -> None:
    original = scan_catalog(catalog_dir)
    before = installation_snapshot(original.records[0], original)
    path = catalog_dir / "lease-review" / "SKILL.md"
    path.write_text(path.read_text() + "Local revision.\n")
    modified = scan_catalog(catalog_dir)
    after = installation_snapshot(modified.records[0], modified)
    assert before["content_hash"] != after["content_hash"]
    assert after["source"]["revision"] == _SHA
    assert after["source"]["revision_content_verified"] is False


@pytest.mark.unit
def test_override_and_portable_manifest_do_not_inherit_default_origin(tmp_path: Path) -> None:
    _write_skill(tmp_path, "private-review")
    (tmp_path / "lq-catalog-provenance.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "repository": "https://user:secret@git.example.test/firm/skills.git?token=secret",
                "revision": _SHA,
            }
        )
    )
    catalog = scan_catalog(tmp_path)
    assert catalog.repository == "https://git.example.test/firm/skills.git"
    assert catalog.sha == _SHA
    assert catalog.metadata_source == "operator-manifest"
    assert "lq-skills" not in forked_from_ref("private-review", catalog.sha, catalog.repository)
    assert "secret" not in json.dumps(installation_snapshot(catalog.records[0], catalog))


@pytest.mark.unit
@pytest.mark.parametrize(
    "url", ["file:///private/secret", "not a repo", None, "https://x.test/\nsecret"]
)
def test_invalid_repository_identity_is_unknown(url: str | None) -> None:
    assert public_repository_identity(url) is None


@pytest.mark.integration
async def test_team_install_is_visible_usable_forkable_and_member_read_only(
    admin_client: tuple[AsyncClient, str, User],
    db_session: AsyncSession,
) -> None:
    ac, token, admin = admin_client
    member, member_token = await _make_user(
        db_session, email="team-member@example.com", is_admin=False
    )
    _outsider, outsider_token = await _make_user(
        db_session, email="outsider@example.com", is_admin=False
    )
    team = Team(id=uuid.uuid4(), name="Legal", slug="legal", created_by_user_id=admin.id)
    db_session.add(team)
    await db_session.flush()
    for user, role in ((admin, "admin"), (member, "member")):
        db_session.add(
            TeamMember(team_id=team.id, user_id=user.id, role=role, added_by_user_id=admin.id)
        )
    await db_session.commit()
    payload = await _install_payload(ac, token, "lease-review", team.id)
    res = await ac.post(
        "/api/v1/admin/community-skills/lease-review/install", headers=_auth(token), json=payload
    )
    assert res.status_code == 201, res.text
    installed = res.json()
    assert installed["scope"] == "team"
    assert installed["owner_team_id"] == str(team.id)
    assert installed["owner_user_id"] is None
    provenance = installed["installation_provenance"]
    assert provenance["distribution"]["installed_by_user_id"] == str(admin.id)
    assert provenance["distribution"]["owner_team_id"] == str(team.id)
    assert provenance["content_hash"] == canonical_hash(provenance["installed_content"])
    old_registry = getattr(app.state, "skill_registry", None)
    app.state.skill_registry = MutableSkillRegistry(SkillRegistry(records={}))
    try:
        picker = await ac.get("/api/v1/skills", headers=_auth(member_token))
        assert picker.status_code == 200, picker.text
        assert [(s["name"], s["scope"]) for s in picker.json()] == [("lease-review", "team")]
        use = await ac.get("/api/v1/skills/lease-review/contents", headers=_auth(member_token))
        assert use.status_code == 200, use.text
        assert use.json()["content_md"] == installed["body"]
        private = await ac.get(
            "/api/v1/skills/lease-review/contents", headers=_auth(outsider_token)
        )
        assert private.status_code == 404
        mutable = f"/api/v1/user-skills/{installed['id']}"
        for method in ("PATCH", "DELETE"):
            forbidden = await ac.request(
                method, mutable, headers=_auth(member_token), json={"body": "unauthorized edit"}
            )
            assert forbidden.status_code == 404, forbidden.text
        fork = await ac.post(
            "/api/v1/user-skills",
            headers=_auth(member_token),
            json={
                "slug": "lease-review",
                "display_name": installed["display_name"],
                "description": installed["description"],
                "body": installed["body"],
                "frontmatter_extra": installed["frontmatter_extra"],
                "forked_from": "lease-review",
            },
        )
        assert fork.status_code == 201, fork.text
        assert fork.json()["owner_user_id"] == str(member.id)
        shared = await ac.get(mutable, headers=_auth(token))
        assert shared.json()["body"] == installed["body"]
        # A personal shadow takes precedence in the member's picker.
        picker = await ac.get("/api/v1/skills", headers=_auth(member_token))
        assert [(s["name"], s["scope"]) for s in picker.json()] == [("lease-review", "user")]
    finally:
        app.state.skill_registry = old_registry


@pytest.mark.integration
async def test_deployment_admin_cannot_distribute_to_unmanaged_team(
    admin_client: tuple[AsyncClient, str, User],
    db_session: AsyncSession,
) -> None:
    ac, token, admin = admin_client
    team = Team(id=uuid.uuid4(), name="Other", slug="other", created_by_user_id=admin.id)
    db_session.add(team)
    await db_session.commit()
    for path in ("", "/lease-review"):
        res = await ac.get(
            f"/api/v1/admin/community-skills{path}",
            headers=_auth(token),
            params={"scope": "team", "owner_team_id": str(team.id)},
        )
        assert res.status_code == 404, res.text
    res = await ac.post(
        "/api/v1/admin/community-skills/lease-review/install",
        headers=_auth(token),
        json={
            "scope": "team",
            "owner_team_id": str(team.id),
            "expected_review_hash": "0" * 64,
        },
    )
    assert res.status_code == 404, res.text
    assert not (await db_session.execute(select(UserSkill))).scalars().all()
    assert (
        not (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "community_skill.installed")
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.integration
async def test_changed_catalog_requires_review_again(
    admin_client: tuple[AsyncClient, str, User],
    catalog_dir: Path,
    db_session: AsyncSession,
) -> None:
    ac, token, _admin = admin_client
    payload = await _install_payload(ac, token, "lease-review")
    path = catalog_dir / "lease-review" / "SKILL.md"
    path.write_text(path.read_text() + "Changed since review.\n")
    res = await ac.post(
        "/api/v1/admin/community-skills/lease-review/install", headers=_auth(token), json=payload
    )
    assert res.status_code == 409, res.text
    assert "changed since review" in res.json()["detail"]
    assert not (await db_session.execute(select(UserSkill))).scalars().all()


@pytest.mark.integration
async def test_installed_copy_edits_keep_original_provenance(
    admin_client: tuple[AsyncClient, str, User],
) -> None:
    ac, token, _admin = admin_client
    res = await ac.post(
        "/api/v1/admin/community-skills/lease-review/install",
        headers=_auth(token),
        json=await _install_payload(ac, token, "lease-review"),
    )
    assert res.status_code == 201, res.text
    original = res.json()
    edited = await ac.patch(
        f"/api/v1/user-skills/{original['id']}",
        headers=_auth(token),
        json={
            "body": "Personal edits after installation.",
            "installation_provenance": {"forged": True},
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["body"] != original["body"]
    assert edited.json()["installation_provenance"] == original["installation_provenance"]


@pytest.mark.integration
async def test_database_rejects_provenance_rewrite(
    admin_client: tuple[AsyncClient, str, User],
    db_session: AsyncSession,
) -> None:
    ac, token, _admin = admin_client
    res = await ac.post(
        "/api/v1/admin/community-skills/lease-review/install",
        headers=_auth(token),
        json=await _install_payload(ac, token, "lease-review"),
    )
    original = res.json()
    assert res.status_code == 201, res.text
    with pytest.raises(DBAPIError, match="write-once"):
        async with db_session.begin_nested():
            await db_session.execute(
                update(UserSkill)
                .where(UserSkill.id == uuid.UUID(original["id"]))
                .values(installation_provenance={"forged": True})
            )
    row = await db_session.get(UserSkill, uuid.UUID(original["id"]))
    assert row is not None
    await db_session.refresh(row)
    assert row.installation_provenance == original["installation_provenance"]


@pytest.mark.unit
def test_dangling_container_git_pointer_uses_portable_metadata(tmp_path: Path) -> None:
    _write_skill(tmp_path, "review")
    (tmp_path / ".git").write_text("gitdir: /nonexistent/git-metadata\n")
    (tmp_path / "lq-catalog-provenance.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "repository": "https://git.example.test/firm/private.git",
                "revision": _SHA,
            }
        )
    )
    catalog = scan_catalog(tmp_path)
    assert catalog.repository == "https://git.example.test/firm/private.git"
    assert catalog.metadata_source == "operator-manifest"
    assert catalog.sha == _SHA


@pytest.mark.unit
def test_catalog_does_not_read_skills_symlinked_outside_its_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    folder = _write_skill(outside, "private-skill", body="Synthetic private content.\n")
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()
    (catalog_dir / "private-skill").symlink_to(folder, target_is_directory=True)
    catalog = scan_catalog(catalog_dir)
    assert catalog.records == []
    assert catalog.load_errors == ["private-skill: skill path leaves the configured catalog"]
    assert "Synthetic private content" not in str(catalog)


@pytest.mark.unit
def test_installation_preserves_runtime_verification_and_tier_controls(tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        "review",
        lq_ai_block=(
            "  minimum_inference_tier: 4\n  ensemble_verification: true\n"
            "  use_organization_profile: false\n  output_format: report\n"
        ),
    )
    catalog = scan_catalog(tmp_path)
    snapshot = installation_snapshot(catalog.records[0], catalog)
    extra = snapshot["installed_content"]["frontmatter_extra"]
    assert extra["minimum_inference_tier"] == 4
    assert extra["ensemble_verification"] is True
    assert extra["use_organization_profile"] is False
    assert extra["output_format"] == "report"
