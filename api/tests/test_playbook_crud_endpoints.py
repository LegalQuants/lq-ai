"""HTTP-level tests for the M3-A6 Phase 2 playbook CRUD endpoints.

Exercises:

* ``POST   /api/v1/playbooks`` — create owned by caller (admins too;
  no anonymous built-ins via the HTTP surface)
* ``PATCH  /api/v1/playbooks/{id}`` — header update + atomic positions
  replacement; built-ins are 403 to everyone
* ``DELETE /api/v1/playbooks/{id}`` — soft-delete; built-ins are 403;
  already-deleted is 404; cross-user is 404

Test fixtures follow the same inline-make-user pattern as
``test_playbook_list_endpoints.py`` — no project-wide fixtures.
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
from app.models.playbook import Playbook, PlaybookPosition
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


def _minimal_create_body(name: str = "My playbook") -> dict:
    """Smallest valid PlaybookCreate body — header only, no positions."""
    return {
        "name": name,
        "contract_type": "NDA",
        "description": "test",
        "version": "1.0.0",
        "positions": [],
    }


def _create_body_with_one_position() -> dict:
    return {
        "name": "Playbook with a position",
        "contract_type": "NDA",
        "description": "",
        "version": "1.0.0",
        "positions": [
            {
                "issue": "Definition of Confidential Information",
                "description": "How CI is defined",
                "standard_language": "All non-public information disclosed by either party...",
                "fallback_tiers": [
                    {
                        "rank": 1,
                        "description": "narrower marking-required scope",
                        "language": "Information clearly marked 'Confidential'...",
                    },
                ],
                "redline_strategy": "expand toward standard",
                "severity_if_missing": "critical",
                "detection_keywords": ["confidential", "non-public"],
                "detection_examples": ["The term 'Confidential Information' means..."],
                "position_order": 0,
            }
        ],
    }


# ---------------------------------------------------------------------------
# POST /api/v1/playbooks
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_playbook_sets_caller_as_owner(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    response = await client.post(
        "/api/v1/playbooks",
        json=_minimal_create_body(),
        headers=_bearer(user),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "My playbook"
    assert body["contract_type"] == "NDA"
    assert body["created_by"] == str(user.id)
    assert body["positions"] == []
    # DB row matches the response.
    row = await db_session.get(Playbook, uuid.UUID(body["id"]))
    assert row is not None
    assert row.created_by == user.id
    assert row.deleted_at is None


@pytest.mark.integration
async def test_create_playbook_admin_caller_still_owns_the_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Admins do not get to mint built-ins (``created_by IS NULL``) via HTTP."""

    admin = await _make_user(db_session, is_admin=True)
    response = await client.post(
        "/api/v1/playbooks",
        json=_minimal_create_body("Admin's playbook"),
        headers=_bearer(admin),
    )
    assert response.status_code == 201, response.text
    assert response.json()["created_by"] == str(admin.id)


@pytest.mark.integration
async def test_create_playbook_persists_positions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    response = await client.post(
        "/api/v1/playbooks",
        json=_create_body_with_one_position(),
        headers=_bearer(user),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["positions"]) == 1
    pos = body["positions"][0]
    assert pos["issue"] == "Definition of Confidential Information"
    assert pos["severity_if_missing"] == "critical"
    assert pos["fallback_tiers"][0]["rank"] == 1
    assert pos["detection_keywords"] == ["confidential", "non-public"]


@pytest.mark.integration
async def test_create_playbook_rejects_unknown_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """PlaybookCreate has ``extra='forbid'`` — extra fields fail validation."""

    user = await _make_user(db_session)
    body = _minimal_create_body()
    body["bogus_field"] = "nope"
    response = await client.post("/api/v1/playbooks", json=body, headers=_bearer(user))
    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# PATCH /api/v1/playbooks/{playbook_id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_patch_playbook_owner_updates_header(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    playbook = Playbook(
        name="Old name",
        contract_type="NDA",
        description="",
        version="1.0.0",
        created_by=user.id,
    )
    db_session.add(playbook)
    await db_session.flush()

    response = await client.patch(
        f"/api/v1/playbooks/{playbook.id}",
        json={"name": "New name", "description": "edited"},
        headers=_bearer(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "New name"
    assert body["description"] == "edited"
    # Other fields untouched.
    assert body["contract_type"] == "NDA"
    assert body["version"] == "1.0.0"


@pytest.mark.integration
async def test_patch_playbook_atomic_positions_replacement(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    playbook = Playbook(
        name="With positions",
        contract_type="NDA",
        description="",
        version="1.0.0",
        created_by=user.id,
    )
    playbook.positions.append(
        PlaybookPosition(
            issue="Old issue",
            description="",
            standard_language="old text",
            fallback_tiers=[],
            redline_strategy="",
            severity_if_missing="low",
            detection_keywords=[],
            detection_examples=[],
            position_order=0,
        )
    )
    db_session.add(playbook)
    await db_session.flush()
    old_position_id = playbook.positions[0].id

    new_positions = [
        {
            "issue": "New issue A",
            "description": "",
            "standard_language": "A",
            "fallback_tiers": [],
            "redline_strategy": "",
            "severity_if_missing": "high",
            "detection_keywords": [],
            "detection_examples": [],
            "position_order": 0,
        },
        {
            "issue": "New issue B",
            "description": "",
            "standard_language": "B",
            "fallback_tiers": [],
            "redline_strategy": "",
            "severity_if_missing": "medium",
            "detection_keywords": [],
            "detection_examples": [],
            "position_order": 1,
        },
    ]
    response = await client.patch(
        f"/api/v1/playbooks/{playbook.id}",
        json={"positions": new_positions},
        headers=_bearer(user),
    )
    assert response.status_code == 200, response.text
    issues = [p["issue"] for p in response.json()["positions"]]
    assert issues == ["New issue A", "New issue B"]
    # Old position row gone (atomic delete-then-insert).
    gone = await db_session.get(PlaybookPosition, old_position_id)
    assert gone is None


@pytest.mark.integration
async def test_patch_playbook_omitting_positions_leaves_them_alone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    playbook = Playbook(
        name="Keep positions",
        contract_type="NDA",
        description="",
        version="1.0.0",
        created_by=user.id,
    )
    playbook.positions.append(
        PlaybookPosition(
            issue="Kept",
            description="",
            standard_language="x",
            fallback_tiers=[],
            redline_strategy="",
            severity_if_missing="low",
            detection_keywords=[],
            detection_examples=[],
            position_order=0,
        )
    )
    db_session.add(playbook)
    await db_session.flush()
    kept_id = playbook.positions[0].id

    response = await client.patch(
        f"/api/v1/playbooks/{playbook.id}",
        json={"description": "new desc"},
        headers=_bearer(user),
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["positions"]) == 1
    still_there = await db_session.get(PlaybookPosition, kept_id)
    assert still_there is not None


@pytest.mark.integration
async def test_patch_playbook_admin_can_edit_other_users_playbook(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author = await _make_user(db_session)
    admin = await _make_user(db_session, is_admin=True)
    playbook = Playbook(
        name="Author's",
        contract_type="NDA",
        description="",
        version="1.0.0",
        created_by=author.id,
    )
    db_session.add(playbook)
    await db_session.flush()

    response = await client.patch(
        f"/api/v1/playbooks/{playbook.id}",
        json={"name": "Edited by admin"},
        headers=_bearer(admin),
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Edited by admin"


@pytest.mark.integration
async def test_patch_playbook_other_user_gets_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author = await _make_user(db_session)
    other = await _make_user(db_session)
    playbook = Playbook(
        name="Author's private",
        contract_type="NDA",
        description="",
        version="1.0.0",
        created_by=author.id,
    )
    db_session.add(playbook)
    await db_session.flush()

    response = await client.patch(
        f"/api/v1/playbooks/{playbook.id}",
        json={"name": "Mine now"},
        headers=_bearer(other),
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_patch_builtin_returns_403_for_anyone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Built-ins (``created_by IS NULL``) are immutable through the HTTP surface."""

    # Built-ins ship via seed migration 0032; use one of them.
    result = await db_session.execute(
        select(Playbook).where(Playbook.created_by.is_(None)).limit(1)
    )
    builtin = result.scalar_one_or_none()
    assert builtin is not None, "seed migration 0032 should have created builtin playbooks"

    user = await _make_user(db_session)
    admin = await _make_user(db_session, is_admin=True)
    for caller in (user, admin):
        response = await client.patch(
            f"/api/v1/playbooks/{builtin.id}",
            json={"name": "Hacked"},
            headers=_bearer(caller),
        )
        assert response.status_code == 403, response.text


@pytest.mark.integration
async def test_patch_soft_deleted_playbook_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from datetime import UTC, datetime

    user = await _make_user(db_session)
    playbook = Playbook(
        name="Already gone",
        contract_type="NDA",
        description="",
        version="1.0.0",
        created_by=user.id,
        deleted_at=datetime.now(tz=UTC),
    )
    db_session.add(playbook)
    await db_session.flush()

    response = await client.patch(
        f"/api/v1/playbooks/{playbook.id}",
        json={"name": "Resurrected"},
        headers=_bearer(user),
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/playbooks/{playbook_id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_delete_playbook_owner_soft_deletes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    playbook = Playbook(
        name="To delete",
        contract_type="NDA",
        description="",
        version="1.0.0",
        created_by=user.id,
    )
    db_session.add(playbook)
    await db_session.flush()

    response = await client.delete(
        f"/api/v1/playbooks/{playbook.id}",
        headers=_bearer(user),
    )
    assert response.status_code == 204

    # Soft-delete: row exists with deleted_at populated.
    await db_session.refresh(playbook)
    assert playbook.deleted_at is not None

    # Subsequent GET 404 — invisible via the visibility helper.
    get_resp = await client.get(
        f"/api/v1/playbooks/{playbook.id}",
        headers=_bearer(user),
    )
    assert get_resp.status_code == 404
    # Subsequent DELETE 404 — same reason.
    second_delete = await client.delete(
        f"/api/v1/playbooks/{playbook.id}",
        headers=_bearer(user),
    )
    assert second_delete.status_code == 404


@pytest.mark.integration
async def test_delete_playbook_admin_can_delete_other_users(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author = await _make_user(db_session)
    admin = await _make_user(db_session, is_admin=True)
    playbook = Playbook(
        name="Will be admin-deleted",
        contract_type="NDA",
        description="",
        version="1.0.0",
        created_by=author.id,
    )
    db_session.add(playbook)
    await db_session.flush()

    response = await client.delete(
        f"/api/v1/playbooks/{playbook.id}",
        headers=_bearer(admin),
    )
    assert response.status_code == 204
    await db_session.refresh(playbook)
    assert playbook.deleted_at is not None


@pytest.mark.integration
async def test_delete_playbook_other_user_gets_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author = await _make_user(db_session)
    other = await _make_user(db_session)
    playbook = Playbook(
        name="Private",
        contract_type="NDA",
        description="",
        version="1.0.0",
        created_by=author.id,
    )
    db_session.add(playbook)
    await db_session.flush()

    response = await client.delete(
        f"/api/v1/playbooks/{playbook.id}",
        headers=_bearer(other),
    )
    assert response.status_code == 404
    await db_session.refresh(playbook)
    assert playbook.deleted_at is None  # Untouched.


@pytest.mark.integration
async def test_delete_builtin_returns_403(client: AsyncClient, db_session: AsyncSession) -> None:
    result = await db_session.execute(
        select(Playbook).where(Playbook.created_by.is_(None)).limit(1)
    )
    builtin = result.scalar_one_or_none()
    assert builtin is not None, "seed migration 0032 should have created builtin playbooks"

    admin = await _make_user(db_session, is_admin=True)
    response = await client.delete(
        f"/api/v1/playbooks/{builtin.id}",
        headers=_bearer(admin),
    )
    assert response.status_code == 403
    await db_session.refresh(builtin)
    assert builtin.deleted_at is None  # Builtin untouched.


@pytest.mark.integration
async def test_deleted_playbook_excluded_from_list(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """List endpoint filters ``deleted_at IS NULL``."""
    from datetime import UTC, datetime

    user = await _make_user(db_session)
    alive = Playbook(
        name="Alive playbook",
        contract_type="NDA",
        description="",
        version="1.0.0",
        created_by=user.id,
    )
    dead = Playbook(
        name="Dead playbook",
        contract_type="NDA",
        description="",
        version="1.0.0",
        created_by=user.id,
        deleted_at=datetime.now(tz=UTC),
    )
    db_session.add_all([alive, dead])
    await db_session.flush()

    response = await client.get("/api/v1/playbooks", headers=_bearer(user))
    assert response.status_code == 200
    names = {entry["name"] for entry in response.json()}
    assert "Alive playbook" in names
    assert "Dead playbook" not in names
