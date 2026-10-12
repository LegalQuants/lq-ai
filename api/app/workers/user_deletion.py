"""Hard-delete-due-users worker — Task D6 (GDPR Article 17).

Daily cron job (registered on :class:`WorkerSettings.cron_jobs`) that
scans for users whose grace period has elapsed and removes them
permanently. Soft-delete + grace period happen in the API endpoint
(``POST /api/v1/users/me/delete``); this worker is the irreversible
back end.

Per PRD §5.3:

* Audit-log entries are *retained* with the actor anonymized. The
  ``audit_log.user_id`` FK is already ``ON DELETE SET NULL``; deleting
  the user row anonymizes the entries naturally — no extra step
  required.
* Inference routing-log entries follow the same pattern (``ON DELETE
  SET NULL`` on ``inference_routing_log.user_id``).
* Object-store bytes for the user's files (active and soft-deleted) are
  hard-deleted; the user's right-to-erasure includes prior soft-deletes.
* Per-user error: log + continue. One stuck user must not block the
  rest of the batch.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session_factory
from app.models import (
    Chat,
    File,
    KnowledgeBase,
    Project,
    ProjectMember,
    User,
    UserExportJob,
)
from app.storage import delete_object

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


async def _hard_delete_user(session: AsyncSession, user: User) -> None:
    """Hard-delete one user and every row owned by them.

    Order matters because most owner FKs are ``ON DELETE RESTRICT`` (a
    deliberate posture so a stray user delete doesn't quietly nuke
    business data). We walk the graph: KB-files (cascade via KB
    delete), KBs, chats (messages cascade), projects (project_files/
    skills cascade), files (documents/chunks/kb_files cascade), then
    user_export_jobs (cascade on user delete) and finally the user
    row itself (sessions cascade; audit_log + inference_routing_log
    SET NULL).
    """

    from sqlalchemy import or_

    from app.errors import Conflict
    from app.models.project import ProjectFile
    from app.models.project_knowledge_base import ProjectKnowledgeBase

    # Lock the user before examining ownership so new FK-linked content cannot
    # arrive between preflight and deletion. Lock owned resources against late sharing.
    await session.execute(select(User.id).where(User.id == user.id).with_for_update())
    for model in (File, KnowledgeBase, Chat):
        await session.execute(
            select(model.__table__.c.id)
            .where(model.__table__.c.owner_id == user.id)
            .with_for_update()
        )
    # Serialize against roster changes / owner transfers on the user's matters.
    owned = (
        (
            await session.execute(
                select(Project).where(Project.owner_id == user.id).with_for_update()
            )
        )
        .scalars()
        .all()
    )
    retained = [p.id for p in owned if p.share_scope == "org"]
    other_members = (
        (
            await session.execute(
                select(ProjectMember.project_id).where(
                    ProjectMember.project_id.in_([p.id for p in owned]),
                    ProjectMember.user_id != user.id,
                )
            )
        )
        .scalars()
        .all()
    )
    retained.extend(other_members)
    foreign_files = (
        (
            await session.execute(
                select(File.id)
                .outerjoin(ProjectFile, ProjectFile.file_id == File.id)
                .where(
                    File.owner_id == user.id,
                    or_(
                        (
                            File.project_id.is_not(None)
                            & File.project_id.not_in([p.id for p in owned])
                        ),
                        (
                            ProjectFile.project_id.is_not(None)
                            & ProjectFile.project_id.not_in([p.id for p in owned])
                        ),
                    ),
                )
            )
        )
        .scalars()
        .first()
    )
    foreign_kbs = (
        (
            await session.execute(
                select(KnowledgeBase.id)
                .outerjoin(
                    ProjectKnowledgeBase, ProjectKnowledgeBase.knowledge_base_id == KnowledgeBase.id
                )
                .where(
                    KnowledgeBase.owner_id == user.id,
                    or_(
                        (
                            KnowledgeBase.project_id.is_not(None)
                            & KnowledgeBase.project_id.not_in([p.id for p in owned])
                        ),
                        (
                            ProjectKnowledgeBase.project_id.is_not(None)
                            & ProjectKnowledgeBase.project_id.not_in([p.id for p in owned])
                        ),
                    ),
                )
            )
        )
        .scalars()
        .first()
    )
    shared_chats = (
        (
            await session.execute(
                select(Chat.id).where(
                    Chat.owner_id == user.id,
                    (Chat.project_id.is_not(None) & Chat.project_id.not_in([p.id for p in owned])),
                )
            )
        )
        .scalars()
        .first()
    )
    if retained or foreign_files or foreign_kbs or shared_chats:
        raise Conflict(
            "User deletion requires reassignment of shared matter data and membership attribution before storage is removed."
        )

    from sqlalchemy.dialects.postgresql import insert

    from app.models.storage_deletion import StorageDeletion

    exports = (
        (
            await session.execute(
                select(UserExportJob.storage_key).where(
                    UserExportJob.user_id == user.id, UserExportJob.storage_key.is_not(None)
                )
            )
        )
        .scalars()
        .all()
    )
    files = (await session.execute(select(File).where(File.owner_id == user.id))).scalars().all()
    # Queue erasure in this transaction; never remove bytes before it commits.
    for storage_path in set(exports) | {f.storage_path for f in files}:
        await session.execute(
            insert(StorageDeletion).values(storage_path=storage_path).on_conflict_do_nothing()
        )

    # Knowledge bases — RESTRICT FK on owner; kb_files cascade.
    await session.execute(delete(KnowledgeBase).where(KnowledgeBase.owner_id == user.id))

    # Chats — RESTRICT FK on owner; messages + chat_attached_skills/files
    # cascade on chat delete.
    await session.execute(delete(Chat).where(Chat.owner_id == user.id))

    # Files — relational rows are removed atomically; object erasure is queued.
    await session.execute(delete(File).where(File.owner_id == user.id))

    # Projects — RESTRICT FK on owner; project_files/skills cascade,
    # chats.project_id is SET NULL (already moot since chats are gone).
    #
    # A matter this user owns but other people work on is NOT theirs alone
    # to erase: deleting it would destroy colleagues' chats, attachments,
    # and context along with it. Erasure covers the user's own data, not a
    # shared matter file. Those rows are left standing and named in the
    # log; an operator resolves them by transferring ownership before
    # re-running the deletion, and ``projects.owner_id`` is RESTRICT, so
    # the FK refuses the user delete below until they do — the job fails
    # loudly rather than erasing a colleague's work quietly.
    shared_project_ids = (
        (
            await session.execute(
                select(Project.id)
                .join(ProjectMember, ProjectMember.project_id == Project.id)
                .where(Project.owner_id == user.id, ProjectMember.user_id != user.id)
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    if shared_project_ids:
        log.warning(
            "user_deletion: %d matter(s) owned by %s have other members and were "
            "NOT deleted; transfer ownership before retrying: %s",
            len(shared_project_ids),
            user.id,
            ", ".join(str(pid) for pid in shared_project_ids),
        )

    stmt = delete(Project).where(Project.owner_id == user.id)
    if shared_project_ids:
        stmt = stmt.where(Project.id.not_in(shared_project_ids))
    await session.execute(stmt)

    # User row — sessions + export_jobs CASCADE; audit_log +
    # inference_routing_log SET NULL (PRD §5.3 audit retention).
    await session.delete(user)


async def hard_delete_due_users_job(ctx: dict[str, Any]) -> dict[str, Any]:
    """arq cron job: hard-delete every user past their grace period.

    Per-user transaction: a failure on user A leaves A's state intact
    and continues with users B, C, …. The summary returned to arq is
    operator-readable in the worker logs.
    """

    factory = get_session_factory()
    deleted = 0
    failed = 0
    skipped_emails: list[str] = []

    async with factory() as session:
        now = _utcnow()
        rows = (
            (
                await session.execute(
                    select(User).where(
                        User.deletion_scheduled_at.is_not(None),
                        User.deletion_scheduled_at < now,
                        User.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )

        for user in rows:
            try:
                await _hard_delete_user(session, user)
                await session.commit()
                deleted += 1
                log.info(
                    "user_deletion: hard-deleted user %s",
                    user.id,
                    extra={"event": "user_hard_deleted", "user_id": str(user.id)},
                )
            except Exception as exc:
                await session.rollback()
                failed += 1
                skipped_emails.append(user.email)
                log.exception(
                    "user_deletion: failed for user %s: %s",
                    user.id,
                    exc,
                )

    async with factory() as session:
        await drain_storage_deletions(session)

    return {
        "deleted": deleted,
        "failed": failed,
        "skipped": skipped_emails,
    }


# Test-only entry: callers that don't want to spin up arq can invoke
# the inner per-user logic directly. Returns nothing because the caller
# owns the commit.
async def hard_delete_user_for_test(session: AsyncSession, user: User) -> None:
    """Direct-call entry for tests; commits are the caller's responsibility."""

    await _hard_delete_user(session, user)


async def drain_storage_deletions(session: AsyncSession) -> None:
    """Retry committed object removals; failed removals remain durable work."""
    from app.models.storage_deletion import StorageDeletion

    paths = list(
        (
            await session.scalars(
                select(StorageDeletion.storage_path)
                .order_by(StorageDeletion.created_at)
                .limit(1000)
            )
        ).all()
    )
    for path in paths:
        try:
            await delete_object(storage_path=path)
            await session.execute(
                delete(StorageDeletion).where(StorageDeletion.storage_path == path)
            )
            await session.commit()
        except Exception:
            await session.rollback()
            log.exception("Queued object erasure failed; retained for retry")
