"""Hard-delete worker tests — D6 GDPR Article 17 cascade behavior.

Verifies:

* User row + owned chats / files / projects / KBs are removed.
* Audit-log entries are retained with user_id set NULL (PRD §5.3).
* MinIO bytes for owned files are deleted.

Tests bypass arq and call the worker's per-user logic directly via
:func:`hard_delete_user_for_test`.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditLog,
    Chat,
    File,
    KnowledgeBase,
    Project,
    User,
)
from app.security import hash_password
from app.workers.user_deletion import drain_storage_deletions, hard_delete_user_for_test


@pytest.mark.integration
async def test_hard_delete_cascades_owned_rows_and_anonymizes_audit(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hard-delete removes the user + their owned rows; audit entries survive with user_id NULL."""

    deleted_keys: list[str] = []

    async def _fake_delete(*, storage_path: str) -> None:
        deleted_keys.append(storage_path)

    monkeypatch.setattr("app.workers.user_deletion.delete_object", _fake_delete)

    user = User(
        email=f"harddelete-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Hard Delete User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
    )
    db_session.add(user)
    await db_session.flush()
    user_id = user.id

    # Build a small graph of owned rows.
    project = Project(owner_id=user_id, name="Project", slug=f"p-{uuid.uuid4().hex[:6]}")
    chat = Chat(owner_id=user_id, title="Pre-deletion chat")
    file_row = File(
        owner_id=user_id,
        filename="some.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        hash_sha256="0" * 64,
        storage_path=str(uuid.uuid4()),
    )
    kb = KnowledgeBase(owner_id=user_id, name="Some KB")
    audit = AuditLog(
        user_id=user_id,
        action="some.action",
        resource_type="user",
        resource_id=str(user_id),
    )
    db_session.add_all([project, chat, file_row, kb, audit])
    await db_session.flush()

    audit_id = audit.id
    file_storage_path = file_row.storage_path

    await hard_delete_user_for_test(db_session, user)
    await db_session.commit()
    await drain_storage_deletions(db_session)
    await db_session.flush()

    # User row gone.
    assert (await db_session.get(User, user_id)) is None
    # Owned rows gone.
    chats = (await db_session.execute(select(Chat).where(Chat.owner_id == user_id))).scalars().all()
    assert chats == []
    files = (await db_session.execute(select(File).where(File.owner_id == user_id))).scalars().all()
    assert files == []
    kbs = (
        (await db_session.execute(select(KnowledgeBase).where(KnowledgeBase.owner_id == user_id)))
        .scalars()
        .all()
    )
    assert kbs == []
    projects = (
        (await db_session.execute(select(Project).where(Project.owner_id == user_id)))
        .scalars()
        .all()
    )
    assert projects == []

    # Audit entry retained — user_id SET NULL by FK. Force a re-read so
    # the session cache doesn't return the pre-delete copy.
    db_session.expire_all()
    surviving = await db_session.get(AuditLog, audit_id)
    assert surviving is not None
    assert surviving.user_id is None
    assert surviving.action == "some.action"

    # File bytes were deleted from storage.
    assert file_storage_path in deleted_keys
