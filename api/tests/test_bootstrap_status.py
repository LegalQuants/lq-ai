"""Tests for the M3-0.1 / DE-283 bootstrap-status endpoint.

Covers the contract documented in :mod:`app.api.bootstrap`:

* The endpoint is unauthenticated (login screen consults it pre-auth).
* ``default_password_active`` is True when an admin with
  ``must_change_password=True`` exists.
* ``default_password_active`` flips to False once the operator has
  rotated (the existing change-password flow clears the flag).
* Soft-deleted admins do not keep the hint visible.
* The ``logs_hint`` string matches the grep target operators are told
  to use in :doc:`/quickstart`.

Tests run against the same SAVEPOINT-rolled-back per-test session as
the rest of the API tests (per ``tests/conftest.py``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.security import hash_password


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Async HTTP client wired to the in-process app, sharing the test session."""
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.integration
async def test_bootstrap_status_active_when_admin_has_must_change_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Fresh-install state: admin exists with ``must_change_password=True``."""
    db_session.add(
        User(
            email="admin@lq.ai",
            hashed_password=hash_password("bootstrap-pw"),
            is_admin=True,
            role="admin",
            mfa_enabled=False,
            must_change_password=True,
        )
    )
    await db_session.flush()

    resp = await client.get("/api/v1/admin/bootstrap-status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["default_password_active"] is True
    assert body["logs_hint"] == ('docker compose logs api 2>&1 | grep "First-run admin password"')


@pytest.mark.integration
async def test_bootstrap_status_inactive_after_password_rotation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Once the operator rotates, ``must_change_password`` flips False."""
    db_session.add(
        User(
            email="admin@lq.ai",
            hashed_password=hash_password("a-rotated-password"),
            is_admin=True,
            role="admin",
            mfa_enabled=False,
            must_change_password=False,
        )
    )
    await db_session.flush()

    resp = await client.get("/api/v1/admin/bootstrap-status")
    assert resp.status_code == 200
    assert resp.json()["default_password_active"] is False


@pytest.mark.integration
async def test_bootstrap_status_inactive_when_no_admin_exists(
    client: AsyncClient,
) -> None:
    """Defensive: zero admin rows → not "active" (there is nothing to hint at)."""
    resp = await client.get("/api/v1/admin/bootstrap-status")
    assert resp.status_code == 200
    assert resp.json()["default_password_active"] is False


@pytest.mark.integration
async def test_bootstrap_status_ignores_soft_deleted_admins(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A soft-deleted admin must not keep the hint visible."""
    db_session.add(
        User(
            email="ex-admin@lq.ai",
            hashed_password=hash_password("doesn't matter"),
            is_admin=True,
            role="admin",
            mfa_enabled=False,
            must_change_password=True,
            deleted_at=datetime.now(UTC),
        )
    )
    await db_session.flush()

    resp = await client.get("/api/v1/admin/bootstrap-status")
    assert resp.status_code == 200
    assert resp.json()["default_password_active"] is False


@pytest.mark.integration
async def test_bootstrap_status_ignores_non_admin_users_with_flag(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """``must_change_password`` on a non-admin is irrelevant to this signal."""
    db_session.add(
        User(
            email="member@example.com",
            hashed_password=hash_password("pw"),
            is_admin=False,
            role="member",
            mfa_enabled=False,
            must_change_password=True,
        )
    )
    await db_session.flush()

    resp = await client.get("/api/v1/admin/bootstrap-status")
    assert resp.status_code == 200
    assert resp.json()["default_password_active"] is False


@pytest.mark.integration
async def test_bootstrap_status_is_unauthenticated(client: AsyncClient) -> None:
    """No bearer token, no must_change_password gate — anyone can probe.

    The endpoint is consulted by the login screen before the operator has
    credentials. A 401 here would defeat the entire purpose.
    """
    resp = await client.get("/api/v1/admin/bootstrap-status")
    # 200 (or whatever the actual state is) — emphatically not 401/403.
    assert resp.status_code == 200
