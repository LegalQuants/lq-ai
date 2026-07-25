"""Integration tests for Wave C — PRD §5.2 + §3.3.

Covers:

* users.role column with DB-side CHECK + migration backfill from
  is_admin.
* GET /users/me surfaces ``role`` alongside is_admin.
* PATCH /admin/users/{id}/role updates role + keeps is_admin in sync,
  writes audit on change, idempotent on no-op, rejects invalid enum,
  refuses to demote the last admin.
* WorkProductAttribution row written on successful assistant message
  persistence + included in the export bundle.
"""

from __future__ import annotations

import json
import uuid
import zipfile
from collections.abc import AsyncIterator, Callable
from io import BytesIO

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models import AuditLog, User, WorkProductAttribution
from app.models.chat import Chat, Message
from app.security import create_access_token, hash_password
from app.workers.user_export import build_export_zip_for_test


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
        email=f"wavec-admin-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Admin",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=True,
        role="admin",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def member_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"wavec-member-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Member",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Users.role: schema + /users/me surface
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_users_role_default_is_member(
    db_session: AsyncSession,
) -> None:
    """New users default to role='member' via the server-default."""

    user = User(
        email=f"defrole-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("x"),
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    assert user.role == "member"
    assert user.is_admin is False


@pytest.mark.integration
async def test_users_role_check_constraint_blocks_invalid_value(
    db_session: AsyncSession, member_user: User
) -> None:
    member_user.role = "superuser"
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.integration
async def test_users_me_surfaces_role(client: AsyncClient, admin_user: User) -> None:
    resp = await client.get("/api/v1/users/me", headers=_bearer(admin_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "admin"
    assert body["is_admin"] is True


# ---------------------------------------------------------------------------
# PATCH /admin/users/{id}/role
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_update_user_role_admin_to_member_writes_audit(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    member_user: User,
) -> None:
    # Promote member to admin so we then demote them — and so we don't
    # trip the last-admin lockout (admin_user remains the only admin
    # AFTER the demotion, so we promote first to set up the state).
    resp = await client.patch(
        f"/api/v1/admin/users/{member_user.id}/role",
        headers=_bearer(admin_user),
        json={"role": "admin"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "admin"
    assert body["is_admin"] is True

    # Now demote — there are 2 admins, so lockout doesn't fire.
    resp = await client.patch(
        f"/api/v1/admin/users/{member_user.id}/role",
        headers=_bearer(admin_user),
        json={"role": "member"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "member"
    assert body["is_admin"] is False

    audit = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.role_updated",
                    AuditLog.resource_id == str(member_user.id),
                )
            )
        )
        .scalars()
        .all()
    )
    # Two updates (promote + demote) → two audit rows.
    assert len(audit) == 2
    assert audit[-1].details is not None
    assert audit[-1].details["after"]["role"] == "member"
    assert audit[-1].details["before"]["role"] == "admin"


@pytest.mark.integration
async def test_update_user_role_idempotent_skips_audit(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    member_user: User,
) -> None:
    resp = await client.patch(
        f"/api/v1/admin/users/{member_user.id}/role",
        headers=_bearer(admin_user),
        json={"role": "member"},
    )
    assert resp.status_code == 200

    audit = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.role_updated",
                    AuditLog.resource_id == str(member_user.id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert audit == []


@pytest.mark.integration
async def test_update_user_role_invalid_value_returns_422(
    client: AsyncClient, admin_user: User, member_user: User
) -> None:
    resp = await client.patch(
        f"/api/v1/admin/users/{member_user.id}/role",
        headers=_bearer(admin_user),
        json={"role": "superuser"},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_update_user_role_requires_admin(client: AsyncClient, member_user: User) -> None:
    resp = await client.patch(
        f"/api/v1/admin/users/{member_user.id}/role",
        headers=_bearer(member_user),
        json={"role": "viewer"},
    )
    assert resp.status_code == 403


@pytest.mark.integration
async def test_update_user_role_last_admin_demotion_blocked(
    client: AsyncClient, admin_user: User
) -> None:
    """The single admin in the deployment cannot demote themselves."""

    resp = await client.patch(
        f"/api/v1/admin/users/{admin_user.id}/role",
        headers=_bearer(admin_user),
        json={"role": "member"},
    )
    assert resp.status_code == 403
    assert "Cannot demote the last admin" in resp.json()["detail"]["message"]


@pytest.mark.integration
async def test_update_user_role_unknown_user_returns_404(
    client: AsyncClient, admin_user: User
) -> None:
    bogus = uuid.uuid4()
    resp = await client.patch(
        f"/api/v1/admin/users/{bogus}/role",
        headers=_bearer(admin_user),
        json={"role": "viewer"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# WorkProductAttribution: write on assistant message + export inclusion
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_work_product_attribution_table_check_constraint(
    db_session: AsyncSession, member_user: User
) -> None:
    chat = Chat(owner_id=member_user.id, title="x")
    db_session.add(chat)
    await db_session.flush()
    message = Message(chat_id=chat.id, role="assistant", content="x")
    db_session.add(message)
    await db_session.flush()

    bad = WorkProductAttribution(
        message_id=message.id,
        user_id=member_user.id,
        chat_id=chat.id,
        routed_inference_tier=99,  # out of range
        content_hash="abc",
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.integration
async def test_export_bundle_includes_work_product_attribution(
    db_session: AsyncSession, member_user: User
) -> None:
    """The user-export ZIP carries a work_product_attribution.json
    file populated from the table — backs PRD §5.3."""

    import hashlib

    chat = Chat(owner_id=member_user.id, title="Sample chat")
    db_session.add(chat)
    await db_session.flush()
    message = Message(
        chat_id=chat.id,
        role="assistant",
        content="Sample model output",
    )
    db_session.add(message)
    await db_session.flush()

    db_session.add(
        WorkProductAttribution(
            message_id=message.id,
            user_id=member_user.id,
            chat_id=chat.id,
            routed_inference_tier=3,
            provider="anthropic-prod",
            model="claude-sonnet-4-6",
            model_version="claude-sonnet-4-6",
            skill_ids=["nda-review"],
            content_hash=hashlib.sha256(message.content.encode()).hexdigest(),
        )
    )
    await db_session.flush()

    zip_bytes = await build_export_zip_for_test(db_session, member_user)
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        assert "work_product_attribution.json" in names
        attrib = json.loads(zf.read("work_product_attribution.json"))

    assert len(attrib) == 1
    row = attrib[0]
    assert row["routed_inference_tier"] == 3
    assert row["provider"] == "anthropic-prod"
    assert row["skill_ids"] == ["nda-review"]
    assert len(row["content_hash"]) == 64  # sha256 hex


@pytest.mark.integration
async def test_export_readme_mentions_work_product_attribution(
    db_session: AsyncSession, member_user: User
) -> None:
    """The README in the bundle documents the new file so the user can
    find it."""

    zip_bytes = await build_export_zip_for_test(db_session, member_user)
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        readme = zf.read("README.md").decode("utf-8")
    assert "work_product_attribution.json" in readme


# ---------------------------------------------------------------------------
# Cross-user auditor role — Task 1 (RBAC enum + migration 0065)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_update_user_role_to_auditor_sets_readonly(
    client: AsyncClient, admin_user: User, member_user: User
) -> None:
    """PATCH /admin/users/{id}/role accepts 'auditor' and keeps
    is_admin False -- auditor is a read-only cross-user reviewer role,
    not an operator-admin (see the cross-user auditor spec)."""

    resp = await client.patch(
        f"/api/v1/admin/users/{member_user.id}/role",
        headers=_bearer(admin_user),
        json={"role": "auditor"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "auditor"
    assert body["is_admin"] is False  # auditor is NOT an operator-admin


@pytest.mark.integration
async def test_auditor_is_non_mutating_via_get_mutating_user(
    db_session: AsyncSession,
) -> None:
    """auditor is deliberately excluded from ``_MUTATING_ROLES``
    (dependencies.py) so any endpoint gated by ``MutatingUser`` treats an
    auditor the same as a viewer: 403 forbidden.

    No endpoint currently depends on ``MutatingUser`` (it is defined but
    not yet wired to a handler), so this exercises the gate function
    directly rather than via an HTTP round-trip -- the assertion is on
    the gate's behavior for role='auditor', which is the contract this
    task must prove.
    """

    from app.api.dependencies import get_mutating_user
    from app.errors import Forbidden

    auditor = User(
        email=f"wavec-auditor-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Auditor",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        role="auditor",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(auditor)
    await db_session.flush()

    with pytest.raises(Forbidden) as exc_info:
        await get_mutating_user(auditor)
    assert exc_info.value.code == "forbidden"


@pytest.mark.integration
async def test_users_role_constraint_accepts_auditor_rejects_bogus(
    db_session: AsyncSession,
) -> None:
    """The DB-side ``chk_users_role_enum`` CHECK constraint (widened by
    migration 0065) accepts 'auditor' and still rejects an unknown
    role string."""

    auditor = User(
        email=f"wavec-auditor2-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("x"),
        role="auditor",
    )
    db_session.add(auditor)
    await db_session.flush()  # must not raise
    await db_session.refresh(auditor)
    assert auditor.role == "auditor"

    bogus = User(
        email=f"wavec-bogus-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("x"),
        role="notarole",
    )
    db_session.add(bogus)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
