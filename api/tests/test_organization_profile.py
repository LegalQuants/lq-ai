"""Integration tests for the D4 Organization Profile surface.

Covers the M1-IMPLEMENTATION-ORDER Task D4 backend surface:

* GET returns ``content_md=""`` when no Profile is set.
* PUT (admin-only) upserts the singleton row; rerun replaces.
* PUT by a non-admin returns 403.
* GET by a non-admin user returns the current content (transparency).
* The /raw endpoint serves text/markdown.
* The PUT path audit-logs ``organization_profile.updated``.

The gateway-side prompt-assembly hook (auto-prepend to skills with
``use_organization_profile=true``) is filed as D4-coverage; tests for
that path will land alongside the gateway integration.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models import AuditLog, OrganizationProfile, User
from app.security import create_access_token, hash_password


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
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
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"orgprofile-admin-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Org Profile Admin",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=True,
        mfa_enabled=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def regular_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"orgprofile-user-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Regular User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# GET /organization-profile — readable by every authenticated user
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_returns_empty_when_no_profile_set(
    client: AsyncClient, regular_user: User
) -> None:
    """No row yet → return empty content + null timestamps; never 404."""

    resp = await client.get("/api/v1/organization-profile", headers=_bearer(regular_user))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["content_md"] == ""
    assert body["updated_at"] is None
    assert body["updated_by"] is None


@pytest.mark.integration
async def test_get_returns_existing_profile(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    regular_user: User,
) -> None:
    """A persisted Profile is readable by any authenticated user."""

    db_session.add(
        OrganizationProfile(
            content_md="# Acme voice\n\nWe always recommend Delaware as choice of law.",
            updated_by=admin_user.id,
        )
    )
    await db_session.flush()

    resp = await client.get("/api/v1/organization-profile", headers=_bearer(regular_user))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "Delaware" in body["content_md"]
    assert body["updated_at"] is not None
    assert body["updated_by"] == str(admin_user.id)


@pytest.mark.integration
async def test_get_without_bearer_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/organization-profile")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /organization-profile — admin-only upsert
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_put_creates_profile_when_none_exists(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    body = {"content_md": "# Voice\n\nWe always recommend Delaware as choice of law."}
    resp = await client.put("/api/v1/organization-profile", headers=_bearer(admin_user), json=body)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert "Delaware" in payload["content_md"]
    assert payload["updated_by"] == str(admin_user.id)

    rows = (await db_session.execute(select(OrganizationProfile))).scalars().all()
    assert len(rows) == 1
    assert "Delaware" in rows[0].content_md
    assert rows[0].updated_by == admin_user.id


@pytest.mark.integration
async def test_put_replaces_existing_profile(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    """PUT is idempotent / upsert — no second row, content replaced."""

    db_session.add(OrganizationProfile(content_md="# Old voice", updated_by=admin_user.id))
    await db_session.flush()

    resp = await client.put(
        "/api/v1/organization-profile",
        headers=_bearer(admin_user),
        json={"content_md": "# New voice"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["content_md"] == "# New voice"

    rows = (await db_session.execute(select(OrganizationProfile))).scalars().all()
    assert len(rows) == 1, "PUT must not create a second singleton row"
    assert rows[0].content_md == "# New voice"


@pytest.mark.integration
async def test_put_by_non_admin_returns_403(client: AsyncClient, regular_user: User) -> None:
    resp = await client.put(
        "/api/v1/organization-profile",
        headers=_bearer(regular_user),
        json={"content_md": "I shouldn't be allowed to set this"},
    )
    assert resp.status_code == 403


@pytest.mark.integration
async def test_put_audit_logs_the_update(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    """The PUT path emits an ``organization_profile.updated`` audit row."""

    resp = await client.put(
        "/api/v1/organization-profile",
        headers=_bearer(admin_user),
        json={"content_md": "# Audited update"},
    )
    assert resp.status_code == 200, resp.text

    rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.user_id == admin_user.id)))
        .scalars()
        .all()
    )
    assert any(r.action == "organization_profile.updated" for r in rows)


@pytest.mark.integration
async def test_put_accepts_empty_content(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    """Operators can clear the Profile to an empty body without deleting the row."""

    db_session.add(OrganizationProfile(content_md="# Will be cleared", updated_by=admin_user.id))
    await db_session.flush()

    resp = await client.put(
        "/api/v1/organization-profile",
        headers=_bearer(admin_user),
        json={"content_md": ""},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["content_md"] == ""


# ---------------------------------------------------------------------------
# /raw endpoint — text/markdown body
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_raw_endpoint_returns_markdown(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    regular_user: User,
) -> None:
    db_session.add(OrganizationProfile(content_md="# Raw markdown body", updated_by=admin_user.id))
    await db_session.flush()

    resp = await client.get("/api/v1/organization-profile/raw", headers=_bearer(regular_user))
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/markdown")
    assert resp.text == "# Raw markdown body"


@pytest.mark.integration
async def test_raw_endpoint_returns_empty_when_unset(
    client: AsyncClient, regular_user: User
) -> None:
    resp = await client.get("/api/v1/organization-profile/raw", headers=_bearer(regular_user))
    assert resp.status_code == 200, resp.text
    assert resp.text == ""
