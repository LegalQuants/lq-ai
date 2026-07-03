"""Unit tests for the cross-user auditor authz substrate (Task 2).

Covers:

* ``is_privileged_reader`` — the {admin, auditor} truth table that later
  tasks (3/4/5) gate the ledger/sources/session-ledger/receipts GET
  handlers on.
* ``auditor_audit`` — the closed-enum "audit the auditor" wrapper that
  writes one ``audit_log`` row per privileged cross-user read.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import is_privileged_reader
from app.auditor_audit import auditor_audit
from app.models.audit import AuditLog
from app.models.user import User
from app.security import hash_password


class _FakeUser:
    def __init__(self, is_admin: bool = False, role: str = "member", uid: uuid.UUID | None = None):
        self.is_admin = is_admin
        self.role = role
        self.id = uid or uuid.uuid4()


@pytest_asyncio.fixture
async def make_user(db_session: AsyncSession):
    """Factory fixture mirroring the local ``make_user`` helper pattern used
    elsewhere in this suite (e.g. test_internal_skills.py, test_wave_c.py),
    but parameterized on ``role`` for this task's purposes."""

    async def _make_user(*, email: str, role: str = "member", is_admin: bool = False) -> User:
        user = User(
            email=email,
            display_name=email,
            hashed_password=hash_password("correct-horse-battery-staple"),
            is_admin=is_admin,
            role=role,
            mfa_enabled=False,
            must_change_password=False,
        )
        db_session.add(user)
        await db_session.flush()
        return user

    return _make_user


def test_is_privileged_reader_truth_table():
    assert is_privileged_reader(_FakeUser(is_admin=True, role="admin")) is True
    assert is_privileged_reader(_FakeUser(is_admin=False, role="auditor")) is True
    assert is_privileged_reader(_FakeUser(is_admin=False, role="member")) is False
    assert is_privileged_reader(_FakeUser(is_admin=False, role="viewer")) is False


@pytest.mark.integration
async def test_auditor_audit_writes_row(db_session: AsyncSession, make_user) -> None:
    reader = await make_user(email="r@example.com", role="auditor")
    viewed = uuid.uuid4()
    await auditor_audit(
        db_session,
        user=reader,
        event="ledger_viewed",
        resource_type="chat",
        resource_id=str(uuid.uuid4()),
        viewed_user_id=viewed,
    )
    await db_session.flush()
    row = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "auditor.ledger_viewed")
            )
        )
        .scalars()
        .one()
    )
    assert row.user_id == reader.id
    assert row.details["viewed_user_id"] == str(viewed)


@pytest.mark.integration
async def test_auditor_audit_rejects_unknown_event(db_session: AsyncSession, make_user) -> None:
    reader = await make_user(email="r2@example.com", role="auditor")
    with pytest.raises(AssertionError):
        await auditor_audit(
            db_session,
            user=reader,
            event="not_an_event",
            resource_type="chat",
            resource_id="x",
            viewed_user_id=uuid.uuid4(),
        )
