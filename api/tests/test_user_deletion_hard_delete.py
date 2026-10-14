"""Hard-delete worker tests — D6 GDPR Article 17 cascade behavior.

Verifies:

* User row + owned chats / files / projects / KBs are removed.
* Audit-log entries are retained with user_id set NULL (PRD §5.3).
* MinIO bytes for owned files are deleted.
* A governed run kept in one of the user's matters does not stop the erasure.

Tests bypass arq and call the worker's per-user logic directly via
:func:`hard_delete_user_for_test`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditLog,
    AutonomousSession,
    Chat,
    File,
    KnowledgeBase,
    Message,
    OrchestrationRoot,
    Project,
    User,
)
from app.security import hash_password
from app.workers.user_deletion import hard_delete_user_for_test


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


@pytest.mark.integration
async def test_hard_delete_removes_a_run_kept_in_one_of_the_users_matters(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run in the user's matter must not stop the erasure.

    ``orchestration_roots.project_id`` is ``ON DELETE RESTRICT`` and the tree
    trigger refuses to null an orchestrated session's project, so before the
    run's session was deleted ahead of the projects, this raised an integrity
    error after the file bytes were already gone and left the user in place.
    """

    deleted_keys: list[str] = []

    async def _fake_delete(*, storage_path: str) -> None:
        deleted_keys.append(storage_path)

    monkeypatch.setattr("app.workers.user_deletion.delete_object", _fake_delete)

    user = User(
        email=f"harddelete-run-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Hard Delete Run User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
    )
    db_session.add(user)
    await db_session.flush()
    user_id = user.id

    project = Project(owner_id=user_id, name="Matter", slug=f"p-{uuid.uuid4().hex[:6]}")
    db_session.add(project)
    await db_session.flush()
    chat = Chat(owner_id=user_id, project_id=project.id, title="Hosted run")
    run_session = AutonomousSession(
        user_id=user_id,
        project_id=project.id,
        trigger_kind="manual",
        current_phase="analysis",
        max_cost_usd=Decimal("1"),
    )
    db_session.add_all([chat, run_session])
    await db_session.flush()
    session_id = run_session.id
    db_session.add_all(
        [
            OrchestrationRoot(
                session_id=session_id,
                owner_id=user_id,
                project_id=project.id,
                plan_id=uuid.uuid4(),
                current_revision=None,
                profile="new_harness_v1",
                planning_snapshot={"contract_version": 3},
                status="planning",
            ),
            Message(
                chat_id=chat.id,
                role="assistant",
                kind="run",
                content="",
                autonomous_session_id=session_id,
            ),
        ]
    )
    await db_session.flush()

    await hard_delete_user_for_test(db_session, user)
    await db_session.flush()

    assert (await db_session.get(User, user_id)) is None
    for model, column in (
        (OrchestrationRoot, OrchestrationRoot.owner_id),
        (AutonomousSession, AutonomousSession.user_id),
        (Project, Project.owner_id),
        (Chat, Chat.owner_id),
    ):
        remaining = await db_session.scalar(
            select(func.count()).select_from(model).where(column == user_id)
        )
        assert remaining == 0, model.__name__
