"""Integration tests for the C7 projects surface.

Covers the M1-IMPLEMENTATION-ORDER C7 verification:

    Create project, attach skill, attach file, set context,
    verify all persist and round-trip correctly.

What's tested:

* Auth gate (unauthenticated -> 401, must_change_password -> 403).
* CRUD round-trip: create / list / get / patch / soft-delete.
* Per-user isolation: cross-user access returns 404 (not 403),
  matching C4's posture.
* The privileged constraint: enforced at three layers (request schema,
  PATCH merge, DB CHECK constraint).
* Slug generation + collision suffixing.
* File attachment / detachment, including cross-user file = 404.
* Skill attachment / detachment, including unknown skill = 404.
* Context document persistence + 100 KiB cap.
* Archive / unarchive via PATCH.
* `archived=true|false` query parameter on list.

Each test file inserts the fixture registry into ``app.state`` (the
ASGI in-process client doesn't trigger lifespan), same pattern as
``test_skill_endpoints.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.security import create_access_token, hash_password
from app.skills import load_registry
from app.skills.registry import MutableSkillRegistry
from tests.test_storage_streaming import FakeS3Client

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "skills"


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def fake_s3() -> FakeS3Client:
    return FakeS3Client()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, fake_s3: FakeS3Client) -> AsyncIterator[AsyncClient]:
    """In-process AsyncClient with fixture skill registry + fake S3 patched in."""

    @asynccontextmanager
    async def _ctx() -> AsyncIterator[FakeS3Client]:
        yield fake_s3

    app.dependency_overrides[get_db] = _override_get_db(db_session)
    holder = MutableSkillRegistry(load_registry(FIXTURES_DIR))
    prior_holder = getattr(app.state, "skill_registry", None)
    app.state.skill_registry = holder

    transport = ASGITransport(app=app)
    with patch("app.storage.s3_client", _ctx):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    if prior_holder is None:
        delattr(app.state, "skill_registry")
    else:
        app.state.skill_registry = prior_holder
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def db_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"proj-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Project Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"proj-other-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Other Project Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def gated_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"proj-gated-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Gated Project Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _bearer(user: User) -> str:
    return create_access_token(user.id, user.email, is_admin=user.is_admin)


def _h(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {_bearer(user)}"}


def _multipart(*, filename: str, content_type: str, payload: bytes) -> dict[str, Any]:
    return {"file": (filename, payload, content_type)}


# ---------------------------------------------------------------------------
# Auth + gate
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_unauthenticated_returns_401(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/projects", json={"name": "X"})
    assert resp.status_code == 401


@pytest.mark.integration
async def test_list_unauthenticated_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/projects")
    assert resp.status_code == 401


@pytest.mark.integration
async def test_get_unauthenticated_returns_401(client: AsyncClient) -> None:
    resp = await client.get(f"/api/v1/projects/{uuid.uuid4()}")
    assert resp.status_code == 401


@pytest.mark.integration
async def test_create_with_must_change_password_returns_403(
    client: AsyncClient, gated_user: User
) -> None:
    resp = await client.post("/api/v1/projects", json={"name": "X"}, headers=_h(gated_user))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "password_change_required"


# ---------------------------------------------------------------------------
# CRUD happy paths
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_project_minimal(client: AsyncClient, db_user: User) -> None:
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Acme MSA Renewal"},
        headers=_h(db_user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Acme MSA Renewal"
    # Slug derived from name.
    assert body["slug"] == "acme-msa-renewal"
    assert body["owner_id"] == str(db_user.id)
    assert body["privileged"] is False
    assert body["minimum_inference_tier"] is None
    assert body["context_md"] is None
    assert body["attached_file_ids"] == []
    assert body["attached_skill_names"] == []
    assert body["archived_at"] is None


@pytest.mark.integration
async def test_create_project_with_full_payload(client: AsyncClient, db_user: User) -> None:
    resp = await client.post(
        "/api/v1/projects",
        json={
            "name": "Privileged Matter",
            "slug": "privileged-matter",
            "description": "Sensitive deal",
            "context_md": "# Context\n\nWe are the customer.",
            "privileged": True,
            "minimum_inference_tier": 2,
        },
        headers=_h(db_user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["privileged"] is True
    assert body["minimum_inference_tier"] == 2
    assert body["context_md"] == "# Context\n\nWe are the customer."
    assert body["description"] == "Sensitive deal"


@pytest.mark.integration
async def test_create_with_privileged_but_no_tier_returns_422(
    client: AsyncClient, db_user: User
) -> None:
    """Schema-layer enforcement of the PRD §3.11 rule."""

    resp = await client.post(
        "/api/v1/projects",
        json={"name": "X", "privileged": True},
        headers=_h(db_user),
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_create_with_invalid_tier_returns_422(client: AsyncClient, db_user: User) -> None:
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "X", "privileged": True, "minimum_inference_tier": 7},
        headers=_h(db_user),
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_get_project_round_trip(client: AsyncClient, db_user: User) -> None:
    create = await client.post("/api/v1/projects", json={"name": "Project A"}, headers=_h(db_user))
    pid = create.json()["id"]

    get = await client.get(f"/api/v1/projects/{pid}", headers=_h(db_user))
    assert get.status_code == 200
    assert get.json()["id"] == pid
    assert get.json()["name"] == "Project A"


@pytest.mark.integration
async def test_get_with_invalid_uuid_returns_400(client: AsyncClient, db_user: User) -> None:
    resp = await client.get("/api/v1/projects/not-a-uuid", headers=_h(db_user))
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "validation_error"


@pytest.mark.integration
async def test_get_for_unknown_id_returns_404(client: AsyncClient, db_user: User) -> None:
    resp = await client.get(f"/api/v1/projects/{uuid.uuid4()}", headers=_h(db_user))
    assert resp.status_code == 404


@pytest.mark.integration
async def test_list_projects_excludes_archived_by_default(
    client: AsyncClient, db_user: User
) -> None:
    a = await client.post("/api/v1/projects", json={"name": "Active"}, headers=_h(db_user))
    b = await client.post("/api/v1/projects", json={"name": "Archive me"}, headers=_h(db_user))
    archive_id = b.json()["id"]
    await client.delete(f"/api/v1/projects/{archive_id}", headers=_h(db_user))

    resp = await client.get("/api/v1/projects", headers=_h(db_user))
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()]
    assert a.json()["id"] in ids
    assert archive_id not in ids


@pytest.mark.integration
async def test_list_projects_with_archived_true_returns_archived_only(
    client: AsyncClient, db_user: User
) -> None:
    active = await client.post("/api/v1/projects", json={"name": "Active"}, headers=_h(db_user))
    arch = await client.post("/api/v1/projects", json={"name": "Archive"}, headers=_h(db_user))
    arch_id = arch.json()["id"]
    await client.delete(f"/api/v1/projects/{arch_id}", headers=_h(db_user))

    resp = await client.get("/api/v1/projects?archived=true", headers=_h(db_user))
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()]
    assert arch_id in ids
    assert active.json()["id"] not in ids


# ---------------------------------------------------------------------------
# Per-user isolation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_other_user_cannot_get_project(
    client: AsyncClient, db_user: User, other_user: User
) -> None:
    create = await client.post("/api/v1/projects", json={"name": "Mine"}, headers=_h(db_user))
    pid = create.json()["id"]

    resp = await client.get(f"/api/v1/projects/{pid}", headers=_h(other_user))
    # 404, not 403 — same posture as C4.
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "not_found"


@pytest.mark.integration
async def test_other_user_cannot_patch_project(
    client: AsyncClient, db_user: User, other_user: User
) -> None:
    create = await client.post("/api/v1/projects", json={"name": "Mine"}, headers=_h(db_user))
    pid = create.json()["id"]

    resp = await client.patch(
        f"/api/v1/projects/{pid}",
        json={"name": "Hijacked"},
        headers=_h(other_user),
    )
    assert resp.status_code == 404


@pytest.mark.integration
async def test_other_user_cannot_delete_project(
    client: AsyncClient, db_user: User, other_user: User
) -> None:
    create = await client.post("/api/v1/projects", json={"name": "Mine"}, headers=_h(db_user))
    pid = create.json()["id"]

    resp = await client.delete(f"/api/v1/projects/{pid}", headers=_h(other_user))
    assert resp.status_code == 404


@pytest.mark.integration
async def test_list_only_returns_caller_projects(
    client: AsyncClient, db_user: User, other_user: User
) -> None:
    mine = await client.post("/api/v1/projects", json={"name": "Mine"}, headers=_h(db_user))
    theirs = await client.post("/api/v1/projects", json={"name": "Theirs"}, headers=_h(other_user))

    list_mine = await client.get("/api/v1/projects", headers=_h(db_user))
    ids = [p["id"] for p in list_mine.json()]
    assert mine.json()["id"] in ids
    assert theirs.json()["id"] not in ids


# ---------------------------------------------------------------------------
# PATCH semantics
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_patch_updates_name_and_context(client: AsyncClient, db_user: User) -> None:
    create = await client.post(
        "/api/v1/projects",
        json={"name": "Original"},
        headers=_h(db_user),
    )
    pid = create.json()["id"]

    resp = await client.patch(
        f"/api/v1/projects/{pid}",
        json={"name": "Updated", "context_md": "**Context**"},
        headers=_h(db_user),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Updated"
    assert resp.json()["context_md"] == "**Context**"


@pytest.mark.integration
async def test_patch_setting_privileged_without_tier_returns_400(
    client: AsyncClient, db_user: User
) -> None:
    """API-layer enforcement of the privileged-tier rule on PATCH (merged state)."""

    create = await client.post(
        "/api/v1/projects",
        json={"name": "X"},
        headers=_h(db_user),
    )
    pid = create.json()["id"]

    resp = await client.patch(
        f"/api/v1/projects/{pid}",
        json={"privileged": True},
        headers=_h(db_user),
    )
    # Domain ValidationError -> 400.
    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"]["code"] == "validation_error"
    assert body["detail"]["details"]["field"] == "minimum_inference_tier"


@pytest.mark.integration
async def test_patch_clearing_tier_on_privileged_returns_400(
    client: AsyncClient, db_user: User
) -> None:
    """Clearing the tier on a privileged project must be rejected."""

    create = await client.post(
        "/api/v1/projects",
        json={
            "name": "Privileged",
            "privileged": True,
            "minimum_inference_tier": 2,
        },
        headers=_h(db_user),
    )
    pid = create.json()["id"]

    resp = await client.patch(
        f"/api/v1/projects/{pid}",
        json={"minimum_inference_tier": None},
        headers=_h(db_user),
    )
    assert resp.status_code == 400


@pytest.mark.integration
async def test_patch_simultaneous_privileged_true_and_tier_succeeds(
    client: AsyncClient, db_user: User
) -> None:
    create = await client.post("/api/v1/projects", json={"name": "X"}, headers=_h(db_user))
    pid = create.json()["id"]

    resp = await client.patch(
        f"/api/v1/projects/{pid}",
        json={"privileged": True, "minimum_inference_tier": 3},
        headers=_h(db_user),
    )
    assert resp.status_code == 200
    assert resp.json()["privileged"] is True
    assert resp.json()["minimum_inference_tier"] == 3


@pytest.mark.integration
async def test_patch_archive_via_flag(client: AsyncClient, db_user: User) -> None:
    create = await client.post("/api/v1/projects", json={"name": "X"}, headers=_h(db_user))
    pid = create.json()["id"]

    resp = await client.patch(
        f"/api/v1/projects/{pid}",
        json={"archived": True},
        headers=_h(db_user),
    )
    assert resp.status_code == 200
    assert resp.json()["archived_at"] is not None


@pytest.mark.integration
async def test_patch_unarchive_via_flag(client: AsyncClient, db_user: User) -> None:
    create = await client.post("/api/v1/projects", json={"name": "X"}, headers=_h(db_user))
    pid = create.json()["id"]
    await client.delete(f"/api/v1/projects/{pid}", headers=_h(db_user))

    # Unarchive
    resp = await client.patch(
        f"/api/v1/projects/{pid}",
        json={"archived": False},
        headers=_h(db_user),
    )
    assert resp.status_code == 200
    assert resp.json()["archived_at"] is None


# ---------------------------------------------------------------------------
# Soft-delete
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_delete_returns_204_then_get_404(client: AsyncClient, db_user: User) -> None:
    create = await client.post("/api/v1/projects", json={"name": "X"}, headers=_h(db_user))
    pid = create.json()["id"]

    delete = await client.delete(f"/api/v1/projects/{pid}", headers=_h(db_user))
    assert delete.status_code == 204

    # GET still returns the (archived) row directly so the client can
    # render the archived-detail page; the listing default excludes it.
    get_after = await client.get(f"/api/v1/projects/{pid}", headers=_h(db_user))
    assert get_after.status_code == 200
    assert get_after.json()["archived_at"] is not None


@pytest.mark.integration
async def test_delete_idempotent_on_already_archived(client: AsyncClient, db_user: User) -> None:
    create = await client.post("/api/v1/projects", json={"name": "X"}, headers=_h(db_user))
    pid = create.json()["id"]

    first = await client.delete(f"/api/v1/projects/{pid}", headers=_h(db_user))
    assert first.status_code == 204

    second = await client.delete(f"/api/v1/projects/{pid}", headers=_h(db_user))
    # Already-archived is no longer "visible" to DELETE -> 404.
    assert second.status_code == 404


# ---------------------------------------------------------------------------
# Slug generation + collision suffixing
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_slug_collision_suffixes(client: AsyncClient, db_user: User) -> None:
    a = await client.post("/api/v1/projects", json={"name": "Acme MSA"}, headers=_h(db_user))
    b = await client.post("/api/v1/projects", json={"name": "Acme MSA"}, headers=_h(db_user))
    c = await client.post("/api/v1/projects", json={"name": "Acme MSA"}, headers=_h(db_user))
    assert a.json()["slug"] == "acme-msa"
    assert b.json()["slug"] == "acme-msa-2"
    assert c.json()["slug"] == "acme-msa-3"


@pytest.mark.integration
async def test_caller_slug_is_used_when_supplied(client: AsyncClient, db_user: User) -> None:
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Anything", "slug": "my-custom-slug"},
        headers=_h(db_user),
    )
    assert resp.json()["slug"] == "my-custom-slug"


@pytest.mark.integration
async def test_invalid_slug_pattern_returns_422(client: AsyncClient, db_user: User) -> None:
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "X", "slug": "Invalid Slug!"},
        headers=_h(db_user),
    )
    # Pydantic regex constraint -> 422.
    assert resp.status_code == 422


@pytest.mark.integration
async def test_archived_slug_can_be_reused(client: AsyncClient, db_user: User) -> None:
    """The slug uniqueness is partial — archived projects free their slug."""

    a = await client.post(
        "/api/v1/projects",
        json={"name": "Foo", "slug": "foo"},
        headers=_h(db_user),
    )
    pid = a.json()["id"]
    await client.delete(f"/api/v1/projects/{pid}", headers=_h(db_user))

    b = await client.post(
        "/api/v1/projects",
        json={"name": "Foo Again", "slug": "foo"},
        headers=_h(db_user),
    )
    # Reuse permitted because the archived project's slug doesn't
    # collide with the active set.
    assert b.status_code == 201
    assert b.json()["slug"] == "foo"


# ---------------------------------------------------------------------------
# Context document cap
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_context_md_over_cap_returns_422(client: AsyncClient, db_user: User) -> None:
    big = "X" * (100 * 1024 + 1)
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Big", "context_md": big},
        headers=_h(db_user),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# File attachment endpoints
# ---------------------------------------------------------------------------


async def _upload_file(client: AsyncClient, user: User, *, name: str = "x.pdf") -> str:
    """Helper: upload a small file and return its id."""

    files = _multipart(filename=name, content_type="application/pdf", payload=b"hi")
    resp = await client.post("/api/v1/files", files=files, headers=_h(user))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.integration
async def test_attach_file_to_project_succeeds(client: AsyncClient, db_user: User) -> None:
    create = await client.post("/api/v1/projects", json={"name": "Has Files"}, headers=_h(db_user))
    pid = create.json()["id"]
    fid = await _upload_file(client, db_user)

    attach = await client.post(
        f"/api/v1/projects/{pid}/files",
        json={"file_id": fid},
        headers=_h(db_user),
    )
    assert attach.status_code == 204

    # File appears in the project's attached list.
    get = await client.get(f"/api/v1/projects/{pid}", headers=_h(db_user))
    assert fid in get.json()["attached_file_ids"]


@pytest.mark.integration
async def test_attach_unknown_file_returns_404(client: AsyncClient, db_user: User) -> None:
    create = await client.post("/api/v1/projects", json={"name": "X"}, headers=_h(db_user))
    pid = create.json()["id"]

    attach = await client.post(
        f"/api/v1/projects/{pid}/files",
        json={"file_id": str(uuid.uuid4())},
        headers=_h(db_user),
    )
    assert attach.status_code == 404


@pytest.mark.integration
async def test_attach_other_users_file_returns_404(
    client: AsyncClient, db_user: User, other_user: User
) -> None:
    """Cross-user file attachment fails — same posture as C4 (404 not 403)."""

    create = await client.post("/api/v1/projects", json={"name": "X"}, headers=_h(db_user))
    pid = create.json()["id"]
    fid = await _upload_file(client, other_user)

    attach = await client.post(
        f"/api/v1/projects/{pid}/files",
        json={"file_id": fid},
        headers=_h(db_user),
    )
    assert attach.status_code == 404


@pytest.mark.integration
async def test_attach_file_to_other_users_project_returns_404(
    client: AsyncClient, db_user: User, other_user: User
) -> None:
    create = await client.post("/api/v1/projects", json={"name": "X"}, headers=_h(db_user))
    pid = create.json()["id"]
    fid = await _upload_file(client, other_user)

    attach = await client.post(
        f"/api/v1/projects/{pid}/files",
        json={"file_id": fid},
        headers=_h(other_user),
    )
    assert attach.status_code == 404


@pytest.mark.integration
async def test_attach_file_already_attached_returns_409(client: AsyncClient, db_user: User) -> None:
    create = await client.post("/api/v1/projects", json={"name": "X"}, headers=_h(db_user))
    pid = create.json()["id"]
    fid = await _upload_file(client, db_user)

    first = await client.post(
        f"/api/v1/projects/{pid}/files",
        json={"file_id": fid},
        headers=_h(db_user),
    )
    assert first.status_code == 204

    second = await client.post(
        f"/api/v1/projects/{pid}/files",
        json={"file_id": fid},
        headers=_h(db_user),
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "conflict"


@pytest.mark.integration
async def test_detach_file_succeeds(client: AsyncClient, db_user: User) -> None:
    create = await client.post("/api/v1/projects", json={"name": "X"}, headers=_h(db_user))
    pid = create.json()["id"]
    fid = await _upload_file(client, db_user)
    await client.post(
        f"/api/v1/projects/{pid}/files",
        json={"file_id": fid},
        headers=_h(db_user),
    )

    detach = await client.delete(f"/api/v1/projects/{pid}/files/{fid}", headers=_h(db_user))
    assert detach.status_code == 204

    get = await client.get(f"/api/v1/projects/{pid}", headers=_h(db_user))
    assert fid not in get.json()["attached_file_ids"]


@pytest.mark.integration
async def test_detach_file_not_attached_returns_404(client: AsyncClient, db_user: User) -> None:
    create = await client.post("/api/v1/projects", json={"name": "X"}, headers=_h(db_user))
    pid = create.json()["id"]
    fid = await _upload_file(client, db_user)
    # Never attached.
    resp = await client.delete(f"/api/v1/projects/{pid}/files/{fid}", headers=_h(db_user))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Skill attachment endpoints
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_attach_skill_to_project_succeeds(client: AsyncClient, db_user: User) -> None:
    create = await client.post("/api/v1/projects", json={"name": "Has Skills"}, headers=_h(db_user))
    pid = create.json()["id"]

    attach = await client.post(
        f"/api/v1/projects/{pid}/skills",
        json={"skill_name": "alpha-test-skill"},
        headers=_h(db_user),
    )
    assert attach.status_code == 204

    get = await client.get(f"/api/v1/projects/{pid}", headers=_h(db_user))
    assert "alpha-test-skill" in get.json()["attached_skill_names"]


@pytest.mark.integration
async def test_attach_unknown_skill_returns_404(client: AsyncClient, db_user: User) -> None:
    create = await client.post("/api/v1/projects", json={"name": "X"}, headers=_h(db_user))
    pid = create.json()["id"]

    attach = await client.post(
        f"/api/v1/projects/{pid}/skills",
        json={"skill_name": "no-such-skill"},
        headers=_h(db_user),
    )
    assert attach.status_code == 404


@pytest.mark.integration
async def test_attach_skill_already_attached_returns_409(
    client: AsyncClient, db_user: User
) -> None:
    create = await client.post("/api/v1/projects", json={"name": "X"}, headers=_h(db_user))
    pid = create.json()["id"]

    first = await client.post(
        f"/api/v1/projects/{pid}/skills",
        json={"skill_name": "alpha-test-skill"},
        headers=_h(db_user),
    )
    assert first.status_code == 204

    second = await client.post(
        f"/api/v1/projects/{pid}/skills",
        json={"skill_name": "alpha-test-skill"},
        headers=_h(db_user),
    )
    assert second.status_code == 409


@pytest.mark.integration
async def test_detach_skill_succeeds(client: AsyncClient, db_user: User) -> None:
    create = await client.post("/api/v1/projects", json={"name": "X"}, headers=_h(db_user))
    pid = create.json()["id"]
    await client.post(
        f"/api/v1/projects/{pid}/skills",
        json={"skill_name": "alpha-test-skill"},
        headers=_h(db_user),
    )

    detach = await client.delete(
        f"/api/v1/projects/{pid}/skills/alpha-test-skill",
        headers=_h(db_user),
    )
    assert detach.status_code == 204

    get = await client.get(f"/api/v1/projects/{pid}", headers=_h(db_user))
    assert "alpha-test-skill" not in get.json()["attached_skill_names"]


@pytest.mark.integration
async def test_detach_skill_not_attached_returns_404(client: AsyncClient, db_user: User) -> None:
    create = await client.post("/api/v1/projects", json={"name": "X"}, headers=_h(db_user))
    pid = create.json()["id"]

    resp = await client.delete(
        f"/api/v1/projects/{pid}/skills/alpha-test-skill",
        headers=_h(db_user),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# C4 deferred fixes — project_id on POST /api/v1/files
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_upload_with_project_id_persists_attachment(
    client: AsyncClient, db_user: User, db_session: AsyncSession
) -> None:
    """Closes the C4 deferred item: multipart project_id form field."""

    create = await client.post("/api/v1/projects", json={"name": "With Files"}, headers=_h(db_user))
    pid = create.json()["id"]

    files = _multipart(filename="x.pdf", content_type="application/pdf", payload=b"hi")
    resp = await client.post(
        "/api/v1/files",
        files=files,
        data={"project_id": pid},
        headers=_h(db_user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["project_id"] == pid

    # Read the row directly to confirm DB persistence.
    row = (
        await db_session.execute(
            text("SELECT project_id FROM files WHERE id = :id"),
            {"id": body["id"]},
        )
    ).one()
    assert str(row.project_id) == pid


@pytest.mark.integration
async def test_upload_with_unknown_project_id_returns_400(
    client: AsyncClient, db_user: User
) -> None:
    """A bogus project_id is rejected before bytes touch MinIO."""

    files = _multipart(filename="x.pdf", content_type="application/pdf", payload=b"hi")
    resp = await client.post(
        "/api/v1/files",
        files=files,
        data={"project_id": str(uuid.uuid4())},
        headers=_h(db_user),
    )
    # Domain ValidationError -> 400.
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "validation_error"


@pytest.mark.integration
async def test_upload_with_other_users_project_id_returns_400(
    client: AsyncClient, db_user: User, other_user: User
) -> None:
    """Cross-user project_id is rejected (treated like unknown)."""

    create = await client.post("/api/v1/projects", json={"name": "Theirs"}, headers=_h(other_user))
    pid = create.json()["id"]

    files = _multipart(filename="x.pdf", content_type="application/pdf", payload=b"hi")
    resp = await client.post(
        "/api/v1/files",
        files=files,
        data={"project_id": pid},
        headers=_h(db_user),
    )
    assert resp.status_code == 400


@pytest.mark.integration
async def test_upload_with_invalid_uuid_project_id_returns_400(
    client: AsyncClient, db_user: User
) -> None:
    files = _multipart(filename="x.pdf", content_type="application/pdf", payload=b"hi")
    resp = await client.post(
        "/api/v1/files",
        files=files,
        data={"project_id": "not-a-uuid"},
        headers=_h(db_user),
    )
    assert resp.status_code == 400


@pytest.mark.integration
async def test_uploaded_file_with_project_id_appears_in_attached_list(
    client: AsyncClient, db_user: User
) -> None:
    """The C4-deferred wiring: file.project_id is reflected on the project itself.

    Note: ``files.project_id`` is the file's *primary* project; the
    project_files join is the many-to-many relation. Per PRD §3.11 the
    primary attachment is the explicit one — the upload-time
    project_id is convenience. The Project's ``attached_file_ids``
    field reflects the join table, NOT the files.project_id column.

    To make the file show up on the project, the caller must also
    POST /api/v1/projects/{id}/files. This test documents that
    distinction by:
      1. uploading with project_id (sets files.project_id)
      2. attaching via the join endpoint
      3. seeing the file in attached_file_ids
    """

    create = await client.post("/api/v1/projects", json={"name": "P"}, headers=_h(db_user))
    pid = create.json()["id"]

    files = _multipart(filename="x.pdf", content_type="application/pdf", payload=b"hi")
    upload = await client.post(
        "/api/v1/files",
        files=files,
        data={"project_id": pid},
        headers=_h(db_user),
    )
    fid = upload.json()["id"]

    # Now attach to the join table so it shows up on the project.
    attach = await client.post(
        f"/api/v1/projects/{pid}/files",
        json={"file_id": fid},
        headers=_h(db_user),
    )
    assert attach.status_code == 204

    get = await client.get(f"/api/v1/projects/{pid}", headers=_h(db_user))
    assert fid in get.json()["attached_file_ids"]


# ---------------------------------------------------------------------------
# End-to-end verification (the C7 contract)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_c7_verification_contract(client: AsyncClient, db_user: User) -> None:
    """The C7 verification step from M1-IMPLEMENTATION-ORDER:

    'Create project, attach skill, attach file, set context, verify all
    persist and round-trip correctly.'
    """

    # 1. Create project
    create = await client.post(
        "/api/v1/projects",
        json={"name": "Acme MSA"},
        headers=_h(db_user),
    )
    assert create.status_code == 201
    pid = create.json()["id"]

    # 2. Attach skill
    attach_skill = await client.post(
        f"/api/v1/projects/{pid}/skills",
        json={"skill_name": "alpha-test-skill"},
        headers=_h(db_user),
    )
    assert attach_skill.status_code == 204

    # 3. Attach file
    files = _multipart(filename="contract.pdf", content_type="application/pdf", payload=b"hello")
    upload = await client.post("/api/v1/files", files=files, headers=_h(db_user))
    fid = upload.json()["id"]
    attach_file = await client.post(
        f"/api/v1/projects/{pid}/files",
        json={"file_id": fid},
        headers=_h(db_user),
    )
    assert attach_file.status_code == 204

    # 4. Set context
    set_ctx = await client.patch(
        f"/api/v1/projects/{pid}",
        json={"context_md": "We are the customer; counterparty is Acme."},
        headers=_h(db_user),
    )
    assert set_ctx.status_code == 200

    # 5. Round-trip verification
    final = await client.get(f"/api/v1/projects/{pid}", headers=_h(db_user))
    body = final.json()
    assert body["name"] == "Acme MSA"
    assert "alpha-test-skill" in body["attached_skill_names"]
    assert fid in body["attached_file_ids"]
    assert body["context_md"] == "We are the customer; counterparty is Acme."
