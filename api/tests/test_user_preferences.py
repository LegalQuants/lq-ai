"""Integration tests for /users/me/preferences — Wave A (PRD §3.2).

Covers:

* GET returns the current preferences slice (defaulting to ``disclosure``
  for newly-created users via the migration's server-default).
* GET /users/me also surfaces ``reasoning_visibility`` on the user shape.
* PATCH with a real change persists + writes a ``user.preferences_updated``
  audit row with before/after.
* Idempotent PATCH (same value) is a no-op — returns 200 with no audit row.
* PATCH with no fields supplied returns the current state, no audit row.
* Invalid enum value returns 422.
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
        email=f"prefs-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Prefs Test",
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
async def test_get_preferences_defaults_to_disclosure(client: AsyncClient, caller: User) -> None:
    resp = await client.get("/api/v1/users/me/preferences", headers=_bearer(caller))
    assert resp.status_code == 200
    assert resp.json()["reasoning_visibility"] == "disclosure"


@pytest.mark.integration
async def test_get_preferences_defaults_full_snapshot(client: AsyncClient, caller: User) -> None:
    """All 6 preference fields return their 'brave choice' server defaults."""
    resp = await client.get("/api/v1/users/me/preferences", headers=_bearer(caller))
    assert resp.status_code == 200
    data = resp.json()
    assert data["reasoning_visibility"] == "disclosure"
    assert data["featured_tools"] == "prominent"
    assert data["workspace_layout"] == "three_pane"
    assert data["trust_pills"] == "labels"
    assert data["provenance_pills"] == "always"
    assert data["autonomous_enabled"] is False


@pytest.mark.integration
async def test_users_me_surfaces_reasoning_visibility(client: AsyncClient, caller: User) -> None:
    resp = await client.get("/api/v1/users/me", headers=_bearer(caller))
    assert resp.status_code == 200
    assert resp.json()["reasoning_visibility"] == "disclosure"


@pytest.mark.integration
async def test_patch_preferences_changes_value_and_writes_audit(
    client: AsyncClient, db_session: AsyncSession, caller: User
) -> None:
    resp = await client.patch(
        "/api/v1/users/me/preferences",
        headers=_bearer(caller),
        json={"reasoning_visibility": "always_show"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["reasoning_visibility"] == "always_show"
    # Other preferences untouched — still at defaults.
    assert data["featured_tools"] == "prominent"

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
    assert changes["reasoning_visibility"]["before"] == "disclosure"
    assert changes["reasoning_visibility"]["after"] == "always_show"


@pytest.mark.integration
async def test_patch_preferences_idempotent_no_audit(
    client: AsyncClient, db_session: AsyncSession, caller: User
) -> None:
    # PATCH with the same value as the default; should not audit.
    resp = await client.patch(
        "/api/v1/users/me/preferences",
        headers=_bearer(caller),
        json={"reasoning_visibility": "disclosure"},
    )
    assert resp.status_code == 200

    audit = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.preferences_updated",
                    AuditLog.resource_id == str(caller.id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert audit == []


@pytest.mark.integration
async def test_patch_preferences_empty_body_is_noop(client: AsyncClient, caller: User) -> None:
    resp = await client.patch(
        "/api/v1/users/me/preferences",
        headers=_bearer(caller),
        json={},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["reasoning_visibility"] == "disclosure"
    assert data["featured_tools"] == "prominent"
    assert data["workspace_layout"] == "three_pane"
    assert data["trust_pills"] == "labels"
    assert data["provenance_pills"] == "always"


@pytest.mark.integration
async def test_patch_preferences_invalid_enum_returns_422(
    client: AsyncClient, caller: User
) -> None:
    resp = await client.patch(
        "/api/v1/users/me/preferences",
        headers=_bearer(caller),
        json={"reasoning_visibility": "loud_and_proud"},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_users_check_constraint_blocks_invalid_value(
    db_session: AsyncSession, caller: User
) -> None:
    """The DB-side CHECK is defense-in-depth — invalid values must not
    survive a direct write either."""

    from sqlalchemy.exc import IntegrityError

    caller.reasoning_visibility = "invalid_value"
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# Wave B v2 — PRD §3.2.1 personalization preference tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_patch_preferences_featured_tools_change_writes_audit(
    client: AsyncClient, db_session: AsyncSession, caller: User
) -> None:
    resp = await client.patch(
        "/api/v1/users/me/preferences",
        headers=_bearer(caller),
        json={"featured_tools": "inline"},
    )
    assert resp.status_code == 200
    assert resp.json()["featured_tools"] == "inline"

    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "user.preferences_updated",
                AuditLog.resource_id == str(caller.id),
            )
        )
    ).scalar_one()
    changes = audit.details["changes"]
    assert changes["featured_tools"]["before"] == "prominent"
    assert changes["featured_tools"]["after"] == "inline"


@pytest.mark.integration
async def test_patch_preferences_workspace_layout_change_writes_audit(
    client: AsyncClient, db_session: AsyncSession, caller: User
) -> None:
    resp = await client.patch(
        "/api/v1/users/me/preferences",
        headers=_bearer(caller),
        json={"workspace_layout": "two_pane"},
    )
    assert resp.status_code == 200
    assert resp.json()["workspace_layout"] == "two_pane"

    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "user.preferences_updated",
                AuditLog.resource_id == str(caller.id),
            )
        )
    ).scalar_one()
    changes = audit.details["changes"]
    assert changes["workspace_layout"]["before"] == "three_pane"
    assert changes["workspace_layout"]["after"] == "two_pane"


@pytest.mark.integration
async def test_patch_preferences_trust_pills_change_writes_audit(
    client: AsyncClient, db_session: AsyncSession, caller: User
) -> None:
    resp = await client.patch(
        "/api/v1/users/me/preferences",
        headers=_bearer(caller),
        json={"trust_pills": "dots"},
    )
    assert resp.status_code == 200
    assert resp.json()["trust_pills"] == "dots"

    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "user.preferences_updated",
                AuditLog.resource_id == str(caller.id),
            )
        )
    ).scalar_one()
    changes = audit.details["changes"]
    assert changes["trust_pills"]["before"] == "labels"
    assert changes["trust_pills"]["after"] == "dots"


@pytest.mark.integration
async def test_patch_preferences_provenance_pills_change_writes_audit(
    client: AsyncClient, db_session: AsyncSession, caller: User
) -> None:
    resp = await client.patch(
        "/api/v1/users/me/preferences",
        headers=_bearer(caller),
        json={"provenance_pills": "collapsed"},
    )
    assert resp.status_code == 200
    assert resp.json()["provenance_pills"] == "collapsed"

    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "user.preferences_updated",
                AuditLog.resource_id == str(caller.id),
            )
        )
    ).scalar_one()
    changes = audit.details["changes"]
    assert changes["provenance_pills"]["before"] == "always"
    assert changes["provenance_pills"]["after"] == "collapsed"


@pytest.mark.integration
async def test_patch_preferences_multi_field_change_single_audit_row(
    client: AsyncClient, db_session: AsyncSession, caller: User
) -> None:
    """Changing 3 fields in one PATCH produces a single audit row listing all 3."""
    resp = await client.patch(
        "/api/v1/users/me/preferences",
        headers=_bearer(caller),
        json={
            "featured_tools": "inline",
            "trust_pills": "dots",
            "provenance_pills": "collapsed",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["featured_tools"] == "inline"
    assert data["trust_pills"] == "dots"
    assert data["provenance_pills"] == "collapsed"
    # Untouched fields stay at defaults.
    assert data["workspace_layout"] == "three_pane"
    assert data["reasoning_visibility"] == "disclosure"

    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.preferences_updated",
                    AuditLog.resource_id == str(caller.id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    changes = audits[0].details["changes"]
    assert set(changes.keys()) == {"featured_tools", "trust_pills", "provenance_pills"}


@pytest.mark.integration
async def test_patch_preferences_invalid_featured_tools_enum_returns_422(
    client: AsyncClient, caller: User
) -> None:
    resp = await client.patch(
        "/api/v1/users/me/preferences",
        headers=_bearer(caller),
        json={"featured_tools": "floating_panel"},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_users_check_constraint_blocks_invalid_featured_tools_value(
    db_session: AsyncSession, caller: User
) -> None:
    """DB-level CHECK is defense-in-depth for the new personalization fields."""

    from sqlalchemy.exc import IntegrityError

    caller.featured_tools = "not_a_valid_value"
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.integration
async def test_idempotent_patch_no_audit_on_new_field(
    client: AsyncClient, db_session: AsyncSession, caller: User
) -> None:
    """PATCH with the server-default value for a new field is a no-op — no audit row."""
    resp = await client.patch(
        "/api/v1/users/me/preferences",
        headers=_bearer(caller),
        json={"featured_tools": "prominent"},  # same as server default
    )
    assert resp.status_code == 200

    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.preferences_updated",
                    AuditLog.resource_id == str(caller.id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert audits == []
