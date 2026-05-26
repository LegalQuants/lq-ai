"""autonomous_enabled rides the /users/me/preferences GET + PATCH."""

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


@pytest_asyncio.fixture
async def caller(db_session: AsyncSession) -> User:
    user = User(
        email=f"autonomous-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Autonomous Test",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
async def test_preferences_get_includes_autonomous_enabled(
    client: AsyncClient, caller: User
) -> None:
    resp = await client.get("/api/v1/users/me/preferences", headers=_bearer(caller))
    assert resp.status_code == 200
    assert resp.json()["autonomous_enabled"] is False  # default off


@pytest.mark.integration
async def test_preferences_patch_opt_in(
    client: AsyncClient, db_session: AsyncSession, caller: User
) -> None:
    resp = await client.patch(
        "/api/v1/users/me/preferences",
        headers=_bearer(caller),
        json={"autonomous_enabled": True},
    )
    assert resp.status_code == 200
    assert resp.json()["autonomous_enabled"] is True

    # Verify persistence by re-fetching.
    again = await client.get("/api/v1/users/me/preferences", headers=_bearer(caller))
    assert again.json()["autonomous_enabled"] is True

    # Audit row written with before/after.
    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "user.preferences_updated",
                AuditLog.resource_id == str(caller.id),
            )
        )
    ).scalar_one()
    changes = audit.details["changes"]
    assert changes["autonomous_enabled"]["before"] == "False"
    assert changes["autonomous_enabled"]["after"] == "True"
