"""Integration tests for M3-D4's admin intake-bridges surface.

Covers:

* ``GET /api/v1/admin/intake-bridges`` — returns live (non-soft-
  deleted) Slack workspaces + Teams tenants, sorted by
  ``installed_at DESC`` within each section.
* ``DELETE /api/v1/admin/intake-bridges/slack/{workspace_id}`` —
  soft-deletes the row; subsequent GET excludes it.
* ``DELETE /api/v1/admin/intake-bridges/teams/{tenant_id}`` — same.
* Admin gate — non-admin user → 403.
* 404 paths — deleting an already-soft-deleted row or a nonexistent
  id returns 404.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.slack_workspace import SlackWorkspace
from app.models.teams_tenant import TeamsTenant
from app.models.user import User
from app.security import create_access_token, hash_password


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


async def _make_user(
    db_session: AsyncSession,
    *,
    email: str,
    is_admin: bool,
) -> tuple[User, str]:
    """Insert a user + return the user + a bearer token for them."""
    user = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password("test-password-123"),
        is_admin=is_admin,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.commit()
    token = create_access_token(user_id=user.id, email=user.email, is_admin=user.is_admin)
    return user, token


@pytest_asyncio.fixture
async def admin_client(db_session: AsyncSession) -> AsyncIterator[tuple[AsyncClient, str]]:
    _user, token = await _make_user(
        db_session,
        email="admin-intake@example.com",
        is_admin=True,
    )
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, token
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def member_client(db_session: AsyncSession) -> AsyncIterator[tuple[AsyncClient, str]]:
    _user, token = await _make_user(
        db_session,
        email="member-intake@example.com",
        is_admin=False,
    )
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, token
    app.dependency_overrides.pop(get_db, None)


async def _insert_slack(
    db_session: AsyncSession,
    *,
    team_id: str,
    deleted: bool = False,
) -> SlackWorkspace:
    row = SlackWorkspace(
        team_id=team_id,
        team_name=f"Workspace {team_id}",
        bot_token_encrypted=b"opaque-ciphertext",
        bot_user_id=f"U-bot-{team_id}",
        installer_slack_user_id=f"U-installer-{team_id}",
        scope="commands,chat:write",
    )
    if deleted:
        row.deleted_at = datetime.now(tz=UTC)
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


async def _insert_teams(
    db_session: AsyncSession,
    *,
    tenant_id: str,
    deleted: bool = False,
) -> TeamsTenant:
    row = TeamsTenant(
        tenant_id=tenant_id,
        tenant_name=f"Tenant {tenant_id}",
        installer_oid=f"oid-{tenant_id}",
    )
    if deleted:
        row.deleted_at = datetime.now(tz=UTC)
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# GET /admin/intake-bridges
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_returns_live_slack_and_teams_rows(
    admin_client: tuple[AsyncClient, str],
    db_session: AsyncSession,
) -> None:
    ac, token = admin_client
    await _insert_slack(db_session, team_id="T-alpha")
    await _insert_slack(db_session, team_id="T-beta")
    await _insert_teams(db_session, tenant_id="00000000-0000-0000-0000-bbbbbbbbbbbb")

    res = await ac.get(
        "/api/v1/admin/intake-bridges",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["slack_workspaces"]) == 2
    assert len(body["teams_tenants"]) == 1
    slack_team_ids = {row["team_id"] for row in body["slack_workspaces"]}
    assert slack_team_ids == {"T-alpha", "T-beta"}


@pytest.mark.integration
async def test_list_excludes_soft_deleted_rows(
    admin_client: tuple[AsyncClient, str],
    db_session: AsyncSession,
) -> None:
    ac, token = admin_client
    await _insert_slack(db_session, team_id="T-live")
    await _insert_slack(db_session, team_id="T-dead", deleted=True)
    await _insert_teams(db_session, tenant_id="00000000-0000-0000-0000-cccccccccccc")
    await _insert_teams(
        db_session,
        tenant_id="00000000-0000-0000-0000-dddddddddddd",
        deleted=True,
    )

    res = await ac.get(
        "/api/v1/admin/intake-bridges",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert [row["team_id"] for row in body["slack_workspaces"]] == ["T-live"]
    assert [row["tenant_id"] for row in body["teams_tenants"]] == [
        "00000000-0000-0000-0000-cccccccccccc"
    ]


@pytest.mark.integration
async def test_list_sorts_by_installed_at_desc(
    admin_client: tuple[AsyncClient, str],
    db_session: AsyncSession,
) -> None:
    """The list endpoint sorts by installed_at DESC.

    Both rows are inserted back-to-back so the server-default
    ``now()`` may return the same microsecond for both; force a real
    delta by stamping ``installed_at`` manually before commit.
    """
    ac, token = admin_client
    older = await _insert_slack(db_session, team_id="T-older")
    newer = await _insert_slack(db_session, team_id="T-newer")
    older.installed_at = datetime(2026, 1, 1, tzinfo=UTC)
    newer.installed_at = datetime(2026, 2, 1, tzinfo=UTC)
    await db_session.commit()

    res = await ac.get(
        "/api/v1/admin/intake-bridges",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = res.json()
    assert [row["team_id"] for row in body["slack_workspaces"]] == ["T-newer", "T-older"]


@pytest.mark.integration
async def test_list_returns_403_for_non_admin(
    member_client: tuple[AsyncClient, str],
) -> None:
    ac, token = member_client
    res = await ac.get(
        "/api/v1/admin/intake-bridges",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /admin/intake-bridges/slack/{workspace_id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_delete_slack_soft_deletes_row(
    admin_client: tuple[AsyncClient, str],
    db_session: AsyncSession,
) -> None:
    ac, token = admin_client
    row = await _insert_slack(db_session, team_id="T-delete-me")

    res = await ac.delete(
        f"/api/v1/admin/intake-bridges/slack/{row.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 204
    assert res.content == b""

    await db_session.refresh(row)
    assert row.deleted_at is not None


@pytest.mark.integration
async def test_delete_slack_returns_404_for_already_deleted(
    admin_client: tuple[AsyncClient, str],
    db_session: AsyncSession,
) -> None:
    ac, token = admin_client
    row = await _insert_slack(db_session, team_id="T-already-dead", deleted=True)

    res = await ac.delete(
        f"/api/v1/admin/intake-bridges/slack/{row.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 404


@pytest.mark.integration
async def test_delete_slack_returns_404_for_missing_row(
    admin_client: tuple[AsyncClient, str],
) -> None:
    ac, token = admin_client
    res = await ac.delete(
        f"/api/v1/admin/intake-bridges/slack/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 404


@pytest.mark.integration
async def test_delete_slack_returns_403_for_non_admin(
    member_client: tuple[AsyncClient, str],
    db_session: AsyncSession,
) -> None:
    ac, token = member_client
    row = await _insert_slack(db_session, team_id="T-member-cant-delete")
    res = await ac.delete(
        f"/api/v1/admin/intake-bridges/slack/{row.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403

    # And the row is unchanged.
    await db_session.refresh(row)
    assert row.deleted_at is None


# ---------------------------------------------------------------------------
# DELETE /admin/intake-bridges/teams/{tenant_id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_delete_teams_soft_deletes_row(
    admin_client: tuple[AsyncClient, str],
    db_session: AsyncSession,
) -> None:
    ac, token = admin_client
    row = await _insert_teams(db_session, tenant_id="00000000-0000-0000-0000-eeeeeeeeeeee")

    res = await ac.delete(
        f"/api/v1/admin/intake-bridges/teams/{row.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 204
    await db_session.refresh(row)
    assert row.deleted_at is not None


@pytest.mark.integration
async def test_delete_teams_returns_404_for_missing_row(
    admin_client: tuple[AsyncClient, str],
) -> None:
    ac, token = admin_client
    res = await ac.delete(
        f"/api/v1/admin/intake-bridges/teams/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 404
