"""Owner-scoped persistence, keyset queries and explicit source lifecycle.

All mutations use the existing audit helper and a savepoint, but never commit
the caller's transaction. No source bodies, logs, network calls or background
jobs are introduced. Only trusted, source-authorizing adapters may write here.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Select, delete, exists, literal, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit_action
from app.authz.matters import matter_scope_filter, require_matter
from app.errors import Conflict, NotFound
from app.models.project import Project
from app.models.user import User
from app.models.workspace_event import WorkspaceEvent
from app.schemas.workspace_events import EventSource, WorkspaceEventCreate, WorkspaceEventQuery


async def _check_owner(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.scalar(
        select(User)
        .where(User.id == user_id, User.deleted_at.is_(None))
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise NotFound("Workspace event owner is unavailable")
    return user


def _visible_events(user: User) -> Select[tuple[WorkspaceEvent]]:
    active_accessible_project = exists().where(
        Project.id == WorkspaceEvent.project_id,
        Project.archived_at.is_(None),
        matter_scope_filter(user),
    )
    return select(WorkspaceEvent).where(
        WorkspaceEvent.user_id == user.id,
        or_(WorkspaceEvent.project_id.is_(None), active_accessible_project),
    )


async def record_event(
    db: AsyncSession, *, user_id: uuid.UUID, event: WorkspaceEventCreate
) -> WorkspaceEvent:
    """Record one signal and its audit atomically; retrying preserves the first row.

    Source identity is deduplicated, not content: distinct findings remain
    distinct signals. The caller supplies an authenticated/server-derived owner
    and must establish access to the actual source before calling this helper.
    """
    user = await _check_owner(db, user_id)
    project_privileged = False
    if event.project_id is not None:
        # The central resolver refreshes policy and enforces ethical screens,
        # even against the matter owner/admin. Do not duplicate its rules.
        project = await require_matter(db, event.project_id, user)
        project_privileged = project.privileged

    sensitivity = "privileged" if project_privileged else event.sensitivity
    identity = f"{user_id}:{event.source_kind}:{event.source_ref}:{event.event_type}"
    observed_at = datetime.now(UTC)
    async with db.begin_nested():
        row = (
            await db.execute(
                insert(WorkspaceEvent)
                .values(
                    user_id=user_id,
                    project_id=event.project_id,
                    source_kind=event.source_kind,
                    source_ref=event.source_ref,
                    event_type=event.event_type,
                    occurred_at=(event.occurred_at or observed_at).astimezone(UTC),
                    observed_at=observed_at,
                    provenance=event.provenance.model_dump(mode="json"),
                    sensitivity=sensitivity,
                    dedupe_digest=hashlib.sha256(identity.encode()).hexdigest(),
                )
                .on_conflict_do_nothing(constraint="uq_workspace_events_source")
                .returning(WorkspaceEvent)
            )
        ).scalar_one_or_none()
        if row is None:
            row = await db.scalar(
                _visible_events(user).where(
                    WorkspaceEvent.source_kind == event.source_kind,
                    WorkspaceEvent.source_ref == event.source_ref,
                    WorkspaceEvent.event_type == event.event_type,
                )
            )
            if row is None or row.project_id != event.project_id or row.sensitivity != sensitivity:
                raise Conflict("Workspace event identity has incompatible metadata")
            return row

        await audit_action(
            db,
            user_id=user_id,
            action="workspace_event.record",
            resource_type="workspace_event",
            resource_id=str(row.id),
            privilege_marked=sensitivity == "privileged",
            privilege_basis="workspace_event:privileged" if sensitivity == "privileged" else None,
            details={"source_kind": event.source_kind, "event_type": event.event_type},
        )
        return row


async def list_events(
    db: AsyncSession, *, user_id: uuid.UUID, query: WorkspaceEventQuery
) -> Sequence[WorkspaceEvent]:
    """Return owner-scoped metadata in (occurred_at, id) order, never source bodies.

    Source-level visibility must also be checked by the source adapter/Today
    projection before exposing source details. This function is not an HTTP API.
    """
    user = await _check_owner(db, user_id)
    stmt = _visible_events(user)
    if query.start_at is not None:
        stmt = stmt.where(WorkspaceEvent.occurred_at >= query.start_at)
    if query.end_at is not None:
        stmt = stmt.where(WorkspaceEvent.occurred_at < query.end_at)
    if query.source_kind is not None:
        stmt = stmt.where(WorkspaceEvent.source_kind == query.source_kind)
    if query.event_type is not None:
        stmt = stmt.where(WorkspaceEvent.event_type == query.event_type)
    if query.project_id is not None:
        stmt = stmt.where(WorkspaceEvent.project_id == query.project_id)
    if query.after is not None:
        stmt = stmt.where(
            tuple_(WorkspaceEvent.occurred_at, WorkspaceEvent.id)
            > tuple_(literal(query.after.occurred_at), literal(query.after.event_id))
        )
    return (
        await db.scalars(
            stmt.order_by(WorkspaceEvent.occurred_at, WorkspaceEvent.id).limit(query.limit)
        )
    ).all()


async def remove_source_events(db: AsyncSession, *, user_id: uuid.UUID, source: EventSource) -> int:
    """Remove an owner's source-derived metadata and audit in the caller's transaction.

    The next producer slice must invoke this alongside source removal; no
    polling/GC, source-deletion hooks or new retention policy are enabled here.
    """
    await _check_owner(db, user_id)
    async with db.begin_nested():
        removed = (
            await db.execute(
                delete(WorkspaceEvent)
                .where(
                    WorkspaceEvent.user_id == user_id,
                    WorkspaceEvent.source_kind == source.source_kind,
                    WorkspaceEvent.source_ref == source.source_ref,
                )
                .returning(WorkspaceEvent.id, WorkspaceEvent.sensitivity)
            )
        ).all()
        if removed:
            privileged = any(sensitivity == "privileged" for _, sensitivity in removed)
            await audit_action(
                db,
                user_id=user_id,
                action="workspace_event.remove_source",
                resource_type="workspace_event",
                privilege_marked=privileged,
                privilege_basis="workspace_event:privileged" if privileged else None,
                details={"source_kind": source.source_kind, "removed_count": len(removed)},
            )
        return len(removed)
