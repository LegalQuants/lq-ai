"""Wave D.2 Task 2.2 — ``POST /api/v1/projects/sandbox/ensure`` idempotency.

The endpoint find-or-creates the caller's per-user "try-it" sandbox
matter. Calling it once creates the row (201); calling it again returns
the same row (200). After the sandbox is soft-deleted via the standard
``DELETE /api/v1/projects/{id}``, the next ``ensure`` recreates it.

Fixture pattern mirrors ``test_projects_sandbox_slug_reserved.py`` (the
Task 2.1 sibling): there is no shared ``authed_client`` fixture in this
codebase, so each test file wires its own ``client`` + ``_h(user)``
Bearer-token helper.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.security import create_access_token, hash_password
from app.skills import load_registry
from app.skills.registry import MutableSkillRegistry

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "skills"


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """In-process AsyncClient with the fixture skill registry installed."""

    app.dependency_overrides[get_db] = _override_get_db(db_session)
    registry_present = FIXTURES_DIR.exists()
    prior_holder = getattr(app.state, "skill_registry", None)
    if registry_present:
        app.state.skill_registry = MutableSkillRegistry(load_registry(FIXTURES_DIR))
    elif prior_holder is None:
        app.state.skill_registry = MutableSkillRegistry(load_registry(Path("/nonexistent")))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    if prior_holder is None:
        if hasattr(app.state, "skill_registry"):
            delattr(app.state, "skill_registry")
    else:
        app.state.skill_registry = prior_holder
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def db_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"sandbox-ensure-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Sandbox-Ensure Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _h(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sandbox_ensure_creates_then_idempotent(client: AsyncClient, db_user: User) -> None:
    r1 = await client.post("/api/v1/projects/sandbox/ensure", headers=_h(db_user))
    assert r1.status_code == 201, r1.text
    p1 = r1.json()
    assert p1["is_sandbox"] is True
    assert p1["slug"] == "__sandbox__"
    assert p1["privileged"] is False
    assert p1["minimum_inference_tier"] is None

    r2 = await client.post("/api/v1/projects/sandbox/ensure", headers=_h(db_user))
    assert r2.status_code == 200, r2.text
    p2 = r2.json()
    assert p2["id"] == p1["id"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sandbox_ensure_recreates_after_archive(client: AsyncClient, db_user: User) -> None:
    r1 = await client.post("/api/v1/projects/sandbox/ensure", headers=_h(db_user))
    assert r1.status_code == 201, r1.text
    pid1 = r1.json()["id"]

    # archive via the standard delete endpoint
    rdel = await client.delete(f"/api/v1/projects/{pid1}", headers=_h(db_user))
    assert rdel.status_code == 204, rdel.text

    r2 = await client.post("/api/v1/projects/sandbox/ensure", headers=_h(db_user))
    assert r2.status_code == 201, r2.text
    assert r2.json()["id"] != pid1


# ---------------------------------------------------------------------------
# Wave D.2 Task 2.3 — ``is_sandbox`` query filters on ``GET /projects``
# ---------------------------------------------------------------------------
#
# The list endpoint returns a bare JSON array (``list[ProjectResponse]``),
# not an ``{"items": [...]}`` envelope — so these tests iterate ``r.json()``
# directly rather than ``r.json()["items"]`` as the task plan sketched.


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_projects_excludes_sandbox_by_default(
    client: AsyncClient, db_user: User
) -> None:
    await client.post("/api/v1/projects/sandbox/ensure", headers=_h(db_user))
    await client.post(
        "/api/v1/projects",
        json={"name": "Acme NDA", "slug": "acme-nda", "description": ""},
        headers=_h(db_user),
    )
    r = await client.get("/api/v1/projects", headers=_h(db_user))
    assert r.status_code == 200, r.text
    slugs = {p["slug"] for p in r.json()}
    assert "acme-nda" in slugs
    assert "__sandbox__" not in slugs


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_projects_include_sandbox(client: AsyncClient, db_user: User) -> None:
    await client.post("/api/v1/projects/sandbox/ensure", headers=_h(db_user))
    r = await client.get("/api/v1/projects?include_sandbox=true", headers=_h(db_user))
    assert r.status_code == 200, r.text
    slugs = {p["slug"] for p in r.json()}
    assert "__sandbox__" in slugs


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_projects_only_sandbox(client: AsyncClient, db_user: User) -> None:
    await client.post("/api/v1/projects/sandbox/ensure", headers=_h(db_user))
    r = await client.get("/api/v1/projects?only_sandbox=true", headers=_h(db_user))
    assert r.status_code == 200, r.text
    items = r.json()
    assert items, "only_sandbox=true should return at least the ensured sandbox row"
    assert all(p["is_sandbox"] for p in items)
