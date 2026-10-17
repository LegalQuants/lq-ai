"""Wave D.2 Task 2.1 — `__*__` slug reservation on `POST /api/v1/projects`.

User-supplied slugs matching the pattern ``^__[a-z0-9-]+__$`` are reserved
for system-managed matters (e.g., the per-user try-it sandbox). Regular
project-create calls that try to claim such a slug must be rejected with
422, surfacing the word "reserved" in the response body so frontends can
display a meaningful error.

The reservation is enforced inside the create handler (not via the
``POST /projects/sandbox/ensure`` endpoint, which constructs the slug
internally and bypasses the same check).

Fixture pattern mirrors ``test_projects_endpoints.py`` — there is no
shared ``authed_client`` in this codebase, so each test file defines its
own ``client`` + auth-header helper. The fixture omits the FakeS3 wiring
that other project tests use, because ``POST /projects`` never touches
object storage; this keeps the test runnable in the partially-bootstrapped
container test tree.
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

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "skills"


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """In-process AsyncClient with the fixture skill registry installed.

    ``POST /api/v1/projects`` doesn't touch object storage, so we skip the
    FakeS3 patch used elsewhere. The fixture skill registry is still
    needed because the handler's serializer looks up attached skills.
    """

    app.dependency_overrides[get_db] = _override_get_db(db_session)
    registry_present = FIXTURES_DIR.exists()
    prior_holder = getattr(app.state, "skill_registry", None)
    if registry_present:
        app.state.skill_registry = MutableSkillRegistry(load_registry(FIXTURES_DIR))
    elif prior_holder is None:
        # If the fixture dir was trimmed out of the container, fall back
        # to an empty mutable registry — this test only reserves slugs.
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
        email=f"slug-reserved-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Slug-Reservation Test User",
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
async def test_post_projects_rejects_double_underscore_slug(
    client: AsyncClient, db_user: User
) -> None:
    r = await client.post(
        "/api/v1/projects",
        json={"name": "Test", "slug": "__sandbox__", "description": "x"},
        headers=_h(db_user),
    )
    assert r.status_code == 422
    assert "reserved" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_post_projects_rejects_any_double_underscore_pattern(
    client: AsyncClient, db_user: User
) -> None:
    for slug in ("__system__", "__internal__", "__foo__"):
        r = await client.post(
            "/api/v1/projects",
            json={"name": "Test", "slug": slug, "description": "x"},
            headers=_h(db_user),
        )
        assert r.status_code == 422, f"slug {slug} should be reserved"
        assert "reserved" in r.json()["detail"].lower(), f"slug {slug} detail must say 'reserved'"
