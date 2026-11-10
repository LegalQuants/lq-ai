"""Wave D.2 / Task 2.6 — integration: ``GET /user-skills/{id}/versions``.

Two scenarios hit the live FastAPI app + Postgres fixture:

* Timeline ordering: create + two patches yield three audit rows,
  returned most-recent-first. The oldest row (``items[-1]``) is the
  ``user_skill.created`` entry.
* Cross-user access: a second user requesting the same skill's
  timeline gets 404 (id-probing-safe per ``_load_mutable``).

Fixture pattern mirrors ``test_user_skills_create_with_slash_alias.py`` —
this codebase has no shared ``authed_client`` fixture, so the file wires
its own ``client`` + ``_h(user)`` Bearer-token helper and seeds two
``User`` rows for the cross-user case.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path

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


async def _make_user(db_session: AsyncSession, label: str) -> User:
    user = User(
        email=f"versions-{label}-{uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Versions Test {label}",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def db_user(db_session: AsyncSession) -> User:
    return await _make_user(db_session, "owner")


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    return await _make_user(db_session, "outsider")


def _h(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


def _create_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "scope": "user",
        "slug": "timeline-skill",
        "display_name": "Timeline Skill",
        "description": "initial description",
        "body": "initial body",
        "version": "1.0.0",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Timeline ordering — create + two updates, ordered most-recent-first
# ---------------------------------------------------------------------------


async def _bump_latest_audit_timestamp(
    db_session: AsyncSession, *, skill_id: str, delta_seconds: int
) -> None:
    """Push the most-recent audit row's timestamp forward by ``delta_seconds``.

    The shared ``conftest.db_session`` fixture uses SAVEPOINTs inside a
    single outer transaction, so Postgres ``now()`` (== transaction_timestamp())
    returns the same value for every audit row written across the test's
    sequential HTTP calls. Production traffic doesn't share a transaction
    so this collision can't happen there. The bump ensures the ORDER BY
    timestamp DESC ordering this test exercises matches the chronological
    order the operations actually fired in.
    """

    await db_session.execute(
        text(
            "UPDATE audit_log SET timestamp = timestamp + make_interval(secs => :delta) "
            "WHERE id = (SELECT id FROM audit_log WHERE resource_type = 'user_skill' "
            "AND resource_id = :sid ORDER BY timestamp DESC, id DESC LIMIT 1)"
        ),
        {"delta": delta_seconds, "sid": skill_id},
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_versions_lists_create_and_updates(
    client: AsyncClient, db_session: AsyncSession, db_user: User
) -> None:
    headers = _h(db_user)

    created = await client.post("/api/v1/user-skills", headers=headers, json=_create_payload())
    assert created.status_code == 201, created.text
    skill_id = created.json()["id"]
    # Distinguish the create row's timestamp from the patches that follow —
    # see _bump_latest_audit_timestamp for the fixture rationale.
    await _bump_latest_audit_timestamp(db_session, skill_id=skill_id, delta_seconds=-2)

    patch1 = await client.patch(
        f"/api/v1/user-skills/{skill_id}",
        headers=headers,
        json={"description": "second description"},
    )
    assert patch1.status_code == 200, patch1.text
    await _bump_latest_audit_timestamp(db_session, skill_id=skill_id, delta_seconds=-1)

    patch2 = await client.patch(
        f"/api/v1/user-skills/{skill_id}",
        headers=headers,
        json={"body": "second body"},
    )
    assert patch2.status_code == 200, patch2.text

    resp = await client.get(f"/api/v1/user-skills/{skill_id}/versions", headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 3, items

    actions = [i["action"] for i in items]
    # Newest first; the oldest (last) entry is the create row.
    assert actions[-1] == "user_skill.created", actions
    assert actions.count("user_skill.updated") == 2, actions

    # Each row carries an actor handle for the management UI.
    assert all(i["actor_user_id"] == str(db_user.id) for i in items)
    assert all(i["actor_email"] == db_user.email for i in items)


# ---------------------------------------------------------------------------
# Cross-user access — 404 (id-probing-safe per _load_mutable)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_versions_forbidden_for_non_owner(
    client: AsyncClient, db_user: User, other_user: User
) -> None:
    created = await client.post(
        "/api/v1/user-skills",
        headers=_h(db_user),
        json=_create_payload(slug="owner-skill"),
    )
    assert created.status_code == 201, created.text
    skill_id = created.json()["id"]

    resp = await client.get(
        f"/api/v1/user-skills/{skill_id}/versions",
        headers=_h(other_user),
    )
    assert resp.status_code in (403, 404), resp.text
