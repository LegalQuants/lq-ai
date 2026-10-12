"""GET /api/v1/users/directory — the people-picker source.

Sharing a matter is impossible without this: the roster endpoints take a
``user_id``, and a matter lead who is not an operator-admin cannot reach
``GET /admin/users`` to find one.

What matters here is the *shape*: id, email, display_name, and nothing
else. Role, admin flag, MFA state, password state, and last-login stay
behind the admin surface, and a regression that leaks one of them is the
failure this file is here to catch.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.security import create_access_token, hash_password


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


async def _mk_user(
    db: AsyncSession,
    *,
    email: str | None = None,
    display_name: str | None = "Test User",
    is_admin: bool = False,
    role: str = "member",
    deleted: bool = False,
) -> User:
    from datetime import UTC, datetime

    user = User(
        email=email or f"u-{uuid.uuid4().hex[:10]}@example.com",
        display_name=display_name,
        hashed_password=hash_password("s3cr3t-battery-staple"),
        is_admin=is_admin,
        role=role,
        # Deliberately non-default so a regression that widens the payload
        # shows up as real state rather than a coincidence of the fixture.
        mfa_enabled=True,
        must_change_password=False,
        deleted_at=datetime.now(tz=UTC) if deleted else None,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_ordinary_member_can_list_colleagues(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    caller = await _mk_user(db_session)
    colleague = await _mk_user(db_session)

    resp = await client.get("/api/v1/users/directory", headers=_bearer(caller))
    assert resp.status_code == 200, resp.text
    ids = {row["id"] for row in resp.json()}
    assert str(caller.id) in ids
    assert str(colleague.id) in ids


@pytest.mark.asyncio
async def test_directory_exposes_only_identity_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Everything else stays behind GET /admin/users."""
    caller = await _mk_user(db_session, is_admin=True, role="admin")

    resp = await client.get("/api/v1/users/directory", headers=_bearer(caller))
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == str(caller.id))
    assert set(row) == {"id", "email", "display_name"}


@pytest.mark.asyncio
async def test_soft_deleted_users_are_hidden(client: AsyncClient, db_session: AsyncSession) -> None:
    caller = await _mk_user(db_session)
    erased = await _mk_user(db_session, deleted=True)

    resp = await client.get("/api/v1/users/directory", headers=_bearer(caller))
    assert str(erased.id) not in {row["id"] for row in resp.json()}


@pytest.mark.asyncio
async def test_query_matches_email_and_display_name(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    caller = await _mk_user(db_session)
    marker = uuid.uuid4().hex[:8]
    by_email = await _mk_user(db_session, email=f"{marker}@example.com", display_name=None)
    by_name = await _mk_user(db_session, display_name=f"Ana {marker}")

    resp = await client.get(f"/api/v1/users/directory?q={marker}", headers=_bearer(caller))
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()}
    assert ids == {str(by_email.id), str(by_name.id)}


@pytest.mark.asyncio
async def test_query_is_case_insensitive(client: AsyncClient, db_session: AsyncSession) -> None:
    caller = await _mk_user(db_session)
    marker = uuid.uuid4().hex[:8]
    target = await _mk_user(db_session, email=f"{marker}@example.com", display_name=None)

    resp = await client.get(f"/api/v1/users/directory?q={marker.upper()}", headers=_bearer(caller))
    assert {row["id"] for row in resp.json()} == {str(target.id)}


@pytest.mark.asyncio
async def test_limit_is_honoured(client: AsyncClient, db_session: AsyncSession) -> None:
    caller = await _mk_user(db_session)
    for _ in range(4):
        await _mk_user(db_session)

    resp = await client.get("/api/v1/users/directory?limit=2", headers=_bearer(caller))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_requires_authentication(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/directory")
    assert resp.status_code == 401, resp.text
