"""Wave D.2 Task 2.2 — concurrent ``POST /sandbox/ensure`` returns one row.

When multiple concurrent ensure calls race, the unique-per-owner-active
partial index on ``projects(owner_id, slug) WHERE archived_at IS NULL``
guarantees only one row wins; the others hit ``ON CONFLICT DO NOTHING``
and re-read the winner. All three callers see the same project id.

This test wires a per-request DB session (not the shared
SAVEPOINT-bound ``db_session`` fixture used by other tests) so that
``asyncio.gather`` actually exercises three independent transactions
hitting the unique index in parallel. The user row is created and
committed up front in its own session so all three request-scoped
sessions can see it.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.security import create_access_token, hash_password
from app.skills import load_registry
from app.skills.registry import MutableSkillRegistry

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "skills"


@pytest_asyncio.fixture
async def real_session_factory(test_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Yield a session factory that creates a fresh AsyncSession per call.

    Used to override ``get_db`` so each in-flight request gets its own
    connection and transaction — required for the ``asyncio.gather``
    concurrency assertion below (sessions are not reentrant).
    """

    return async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def seeded_user(test_engine: AsyncEngine) -> AsyncIterator[User]:
    """Commit a fresh user row visible to all per-request sessions; clean up after."""

    factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as setup:
        user = User(
            email=f"sandbox-concurrency-{uuid.uuid4().hex[:8]}@example.com",
            display_name="Sandbox-Concurrency Test User",
            hashed_password=hash_password("correct-horse-battery-staple"),
            is_admin=False,
            mfa_enabled=False,
            must_change_password=False,
        )
        setup.add(user)
        await setup.commit()
        await setup.refresh(user)
        user_id = user.id
        yield user
    # Teardown — clean the rows this test wrote so subsequent runs see a
    # clean slate. We're outside the shared ``db_session`` fixture's
    # rollback envelope so we have to clean up ourselves.
    async with factory() as cleanup:
        await cleanup.execute(
            sql_text("DELETE FROM projects WHERE owner_id = :uid"),
            {"uid": user_id},
        )
        await cleanup.execute(
            sql_text("DELETE FROM users WHERE id = :uid"),
            {"uid": user_id},
        )
        await cleanup.commit()


@pytest_asyncio.fixture
async def client(
    real_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    """In-process AsyncClient where each request opens its own DB session."""

    async def _override() -> AsyncIterator[AsyncSession]:
        async with real_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override
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


def _h(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sandbox_ensure_concurrent_returns_same_row(
    client: AsyncClient, seeded_user: User
) -> None:
    headers = _h(seeded_user)
    results = await asyncio.gather(
        client.post("/api/v1/projects/sandbox/ensure", headers=headers),
        client.post("/api/v1/projects/sandbox/ensure", headers=headers),
        client.post("/api/v1/projects/sandbox/ensure", headers=headers),
    )
    for r in results:
        assert r.status_code in (200, 201), r.text
    ids = {r.json()["id"] for r in results}
    assert len(ids) == 1, f"expected one sandbox row, got {ids}"
