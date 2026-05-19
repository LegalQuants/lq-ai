"""HTTP-level tests for the M3-A4 playbook list + detail endpoints.

Exercises:

* ``GET /api/v1/playbooks`` — list visible to the caller. Built-in
  playbooks (``created_by IS NULL``) are visible to all authenticated
  users; non-admins additionally see playbooks they authored;
  admins see everything.
* ``GET /api/v1/playbooks/{id}`` — detail with positions inlined.
  Mirrors the execute endpoint's 404-on-unauthorized posture (never
  leaks the existence of a playbook the caller can't see).

Fixtures: uses the same ``client`` + ``db_session`` pattern as
``tests/test_playbooks_endpoints.py`` — there's no project-wide
``client_user`` / ``client_admin`` / ``db`` fixture; users are
created inline and JWTs minted via ``create_access_token``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.playbook import Playbook
from app.models.user import User
from app.security import create_access_token, hash_password


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


async def _make_user(db: AsyncSession, *, is_admin: bool = False) -> User:
    u = User(
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=is_admin,
        role="admin" if is_admin else "member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(u)
    await db.flush()
    return u


def _bearer(user: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token(user.id, user.email, is_admin=user.is_admin)}"
        )
    }


# ---------------------------------------------------------------------------
# GET /api/v1/playbooks
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_playbooks_returns_builtins_for_non_admin(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Built-in playbooks (``created_by IS NULL``) are visible to all users."""
    result = await db_session.execute(select(Playbook).where(Playbook.created_by.is_(None)))
    builtin_count = len(result.scalars().all())
    assert builtin_count >= 2, "seed migration 0032 should have created at least 2 NDA playbooks"

    user = await _make_user(db_session)
    response = await client.get("/api/v1/playbooks", headers=_bearer(user))
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)
    assert len(body) >= builtin_count
    names = {p["name"] for p in body}
    assert "NDA — Mutual" in names
    assert "NDA — Unilateral (Discloser-favorable)" in names
    # Each entry has the wire fields the UI needs:
    for entry in body:
        assert set(entry.keys()) >= {
            "id",
            "name",
            "contract_type",
            "description",
            "version",
            "created_by",
            "created_at",
            "updated_at",
        }
        # List view doesn't inline positions — defer to detail endpoint.
        assert entry["positions"] == []


# ---------------------------------------------------------------------------
# GET /api/v1/playbooks/{playbook_id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_playbook_returns_full_positions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Detail endpoint inlines the position list with fallback tiers."""
    result = await db_session.execute(select(Playbook).where(Playbook.name == "NDA — Mutual"))
    playbook = result.scalar_one()

    user = await _make_user(db_session)
    response = await client.get(
        f"/api/v1/playbooks/{playbook.id}",
        headers=_bearer(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "NDA — Mutual"
    assert body["contract_type"] == "NDA"
    assert isinstance(body["positions"], list)
    assert len(body["positions"]) == 8, "NDA — Mutual has 8 positions per the YAML"
    first = body["positions"][0]
    assert set(first.keys()) >= {
        "id",
        "issue",
        "description",
        "standard_language",
        "fallback_tiers",
        "redline_strategy",
        "severity_if_missing",
        "detection_keywords",
        "detection_examples",
        "position_order",
    }
    assert first["severity_if_missing"] in {"critical", "high", "medium", "low"}


@pytest.mark.integration
async def test_user_sees_own_playbook_in_list_and_detail(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A non-admin author can list + fetch the detail of their own playbook."""
    user = await _make_user(db_session, is_admin=False)
    own = Playbook(
        name="My private NDA playbook",
        contract_type="NDA",
        description="",
        version="1.0.0",
        created_by=user.id,
    )
    db_session.add(own)
    await db_session.flush()

    headers = _bearer(user)

    # List includes the user's own playbook AND the built-ins.
    list_resp = await client.get("/api/v1/playbooks", headers=headers)
    assert list_resp.status_code == 200, list_resp.text
    names = {entry["name"] for entry in list_resp.json()}
    assert "My private NDA playbook" in names
    assert "NDA — Mutual" in names  # built-ins still visible

    # Detail returns the user's own playbook.
    detail_resp = await client.get(f"/api/v1/playbooks/{own.id}", headers=headers)
    assert detail_resp.status_code == 200, detail_resp.text
    assert detail_resp.json()["name"] == "My private NDA playbook"


@pytest.mark.integration
async def test_get_playbook_404_for_unauthorized(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Non-admin gets 404 (not 403) for a playbook they don't own and isn't built-in."""
    author = await _make_user(db_session)
    other = await _make_user(db_session)
    playbook = Playbook(
        name="Private playbook",
        contract_type="custom",
        description="",
        version="1.0.0",
        created_by=author.id,
    )
    db_session.add(playbook)
    await db_session.flush()

    response = await client.get(
        f"/api/v1/playbooks/{playbook.id}",
        headers=_bearer(other),
    )
    assert response.status_code == 404
