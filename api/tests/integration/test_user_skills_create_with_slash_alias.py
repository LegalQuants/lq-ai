"""Wave D.2 / Task 2.4 — integration: ``slash_alias`` on create + collision.

Three scenarios hit the live FastAPI app + Postgres fixture:

* Round-trip: create with ``slash_alias`` and ``forked_from`` set, then
  ``GET`` the row and confirm both fields surface on ``UserSkillResponse``.
* Collision: a second create for the same user with the same alias is
  rejected with 422 (the handler catches the partial-unique-index
  ``IntegrityError`` and translates it). The first row remains intact.
* Archive frees the alias: soft-deleting the first row lets a second
  create at the same alias succeed.

Fixture pattern mirrors ``test_projects_sandbox_ensure.py`` — this
codebase has no shared ``authed_client`` fixture, so each file wires
its own ``client`` + ``_h(user)`` Bearer-token helper.
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
        email=f"user-skill-slash-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Slash Alias Test User",
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


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "slug": "personal-nda",
        "display_name": "Personal NDA",
        "description": "My NDA workflow",
        "body": "You review NDAs.",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Round-trip — alias + forked_from surface on response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_user_skill_with_slash_alias_roundtrip(
    client: AsyncClient, db_user: User
) -> None:
    resp = await client.post(
        "/api/v1/user-skills",
        headers=_h(db_user),
        json=_payload(
            slug="personal-nda",
            slash_alias="/nda",
            forked_from="nda-review",
            source_message_id="00000000-0000-0000-0000-000000000123",
        ),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slash_alias"] == "/nda"
    assert body["forked_from"] == "nda-review"
    # source_message_id is documentary only and must NOT leak on the response.
    assert "source_message_id" not in body

    # GET the same row — the persisted fields round-trip.
    skill_id = body["id"]
    g = await client.get(f"/api/v1/user-skills/{skill_id}", headers=_h(db_user))
    assert g.status_code == 200, g.text
    got = g.json()
    assert got["slash_alias"] == "/nda"
    assert got["forked_from"] == "nda-review"
    assert "source_message_id" not in got


# ---------------------------------------------------------------------------
# Collision — second create at same alias rejected with 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_duplicate_slash_alias_returns_422(client: AsyncClient, db_user: User) -> None:
    first = await client.post(
        "/api/v1/user-skills",
        headers=_h(db_user),
        json=_payload(slug="first-skill", slash_alias="/nda"),
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/api/v1/user-skills",
        headers=_h(db_user),
        json=_payload(slug="second-skill", slash_alias="/nda"),
    )
    assert second.status_code == 422, second.text
    detail = second.json().get("detail", "")
    # Detail surfaces the offending alias so the UI can render a useful message.
    assert "/nda" in str(detail)


# ---------------------------------------------------------------------------
# Archive frees the alias
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_archive_frees_slash_alias(client: AsyncClient, db_user: User) -> None:
    first = await client.post(
        "/api/v1/user-skills",
        headers=_h(db_user),
        json=_payload(slug="first-skill", slash_alias="/nda"),
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]

    # Soft-delete the first row — frees both slug and slash_alias via the
    # partial unique indexes that filter on archived_at IS NULL.
    d = await client.delete(f"/api/v1/user-skills/{first_id}", headers=_h(db_user))
    assert d.status_code == 204, d.text

    second = await client.post(
        "/api/v1/user-skills",
        headers=_h(db_user),
        json=_payload(slug="second-skill", slash_alias="/nda"),
    )
    assert second.status_code == 201, second.text
    assert second.json()["slash_alias"] == "/nda"
