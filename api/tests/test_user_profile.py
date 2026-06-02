"""Integration tests for PATCH /users/me — caller-scoped profile edit (Donna-3).

Covers:

* PATCH with a new ``display_name`` returns 200 with the updated
  ``UserPublic``; a follow-up GET /users/me reflects it.
* Whitespace around a valid name is trimmed.
* Empty / whitespace-only ``display_name`` returns 422.
* Empty body (no updatable fields) returns 422.
* Over-length ``display_name`` returns 422.
* The handler is caller-scoped — a second user's row is untouched.
* A ``user.profile_updated`` audit row is written listing the changed fields.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.users import _DISPLAY_NAME_MAX_LEN
from app.db.session import get_db
from app.main import app
from app.models import AuditLog, User
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


async def _make_user(db_session: AsyncSession, display_name: str) -> User:
    user = User(
        email=f"profile-{uuid.uuid4().hex[:8]}@example.com",
        display_name=display_name,
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def caller(db_session: AsyncSession) -> User:
    return await _make_user(db_session, "Original Name")


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
async def test_patch_me_updates_display_name(client: AsyncClient, caller: User) -> None:
    resp = await client.patch(
        "/api/v1/users/me",
        headers=_bearer(caller),
        json={"display_name": "New Name"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["display_name"] == "New Name"
    # Returned shape is UserPublic — same id/email as the caller.
    assert data["id"] == str(caller.id)
    assert data["email"] == caller.email

    # A follow-up GET reflects the change.
    get_resp = await client.get("/api/v1/users/me", headers=_bearer(caller))
    assert get_resp.status_code == 200
    assert get_resp.json()["display_name"] == "New Name"


@pytest.mark.integration
async def test_patch_me_trims_whitespace(client: AsyncClient, caller: User) -> None:
    resp = await client.patch(
        "/api/v1/users/me",
        headers=_bearer(caller),
        json={"display_name": "  Padded Name  "},
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Padded Name"


@pytest.mark.integration
async def test_patch_me_empty_display_name_returns_422(client: AsyncClient, caller: User) -> None:
    resp = await client.patch(
        "/api/v1/users/me",
        headers=_bearer(caller),
        json={"display_name": ""},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_patch_me_whitespace_only_display_name_returns_422(
    client: AsyncClient, caller: User
) -> None:
    resp = await client.patch(
        "/api/v1/users/me",
        headers=_bearer(caller),
        json={"display_name": "   "},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_patch_me_empty_body_returns_422(client: AsyncClient, caller: User) -> None:
    resp = await client.patch(
        "/api/v1/users/me",
        headers=_bearer(caller),
        json={},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_patch_me_overlong_display_name_returns_422(
    client: AsyncClient, caller: User
) -> None:
    resp = await client.patch(
        "/api/v1/users/me",
        headers=_bearer(caller),
        json={"display_name": "x" * (_DISPLAY_NAME_MAX_LEN + 1)},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_patch_me_is_caller_scoped(
    client: AsyncClient, db_session: AsyncSession, caller: User
) -> None:
    """Updating the caller leaves a second user's row untouched."""
    other = await _make_user(db_session, "Other Name")

    resp = await client.patch(
        "/api/v1/users/me",
        headers=_bearer(caller),
        json={"display_name": "Caller Renamed"},
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Caller Renamed"

    await db_session.refresh(other)
    assert other.display_name == "Other Name"


@pytest.mark.integration
async def test_patch_me_writes_audit_row(
    client: AsyncClient, db_session: AsyncSession, caller: User
) -> None:
    resp = await client.patch(
        "/api/v1/users/me",
        headers=_bearer(caller),
        json={"display_name": "Audited Name"},
    )
    assert resp.status_code == 200

    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "user.profile_updated",
                AuditLog.resource_id == str(caller.id),
            )
        )
    ).scalar_one()
    assert audit.resource_type == "user"
    assert audit.details["fields"] == ["display_name"]
