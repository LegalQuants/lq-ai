"""Policy administration without implicit access to matter content."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AdminUser
from app.api.matter_members import MatterMemberResponse, _list_members
from app.audit import audit_action
from app.authz.matters import blocked_project_ids, require_matter_management
from app.db.session import get_db
from app.errors import Conflict, NotFound, ValidationError
from app.models.chat import Chat
from app.models.file import File
from app.models.knowledge import KnowledgeBase
from app.models.project import Project, ProjectFile
from app.models.project_knowledge_base import ProjectKnowledgeBase
from app.models.project_member import ProjectMember
from app.models.user import User

router = APIRouter(prefix="/admin/matters", tags=["admin", "matters"])


class MatterAdministrationSummary(BaseModel):
    id: uuid.UUID
    name: str
    owner_id: uuid.UUID
    share_scope: str
    archived_at: datetime | None


class Intervention(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A reason is required.")
        return value.strip()


class MatterPolicyUpdate(Intervention):
    share_scope: Literal["personal", "members", "org"]


class MatterOwnershipTransfer(Intervention):
    owner_id: uuid.UUID
    former_owner_role: Literal["lead", "contributor", "reader", "blocked"] = "reader"


def summary(project: Project) -> MatterAdministrationSummary:
    return MatterAdministrationSummary(
        id=project.id,
        name=project.name,
        owner_id=project.owner_id,
        share_scope=project.share_scope,
        archived_at=project.archived_at,
    )


@router.get("", response_model=list[MatterAdministrationSummary])
async def list_matters(
    user: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MatterAdministrationSummary]:
    rows = (
        (
            await db.execute(
                select(Project)
                .where(Project.is_sandbox.is_(False), Project.id.not_in(blocked_project_ids(user)))
                .order_by(Project.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [summary(p) for p in rows]


@router.get("/{project_id}/members", response_model=list[MatterMemberResponse])
async def get_roster(
    project_id: uuid.UUID, user: AdminUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[MatterMemberResponse]:
    project = await require_matter_management(db, project_id, user)
    return await _list_members(db, project)


@router.patch("/{project_id}/policy", response_model=MatterAdministrationSummary)
async def update_policy(
    project_id: uuid.UUID,
    payload: MatterPolicyUpdate,
    request: Request,
    user: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MatterAdministrationSummary:
    project = await require_matter_management(db, project_id, user)
    previous = project.share_scope
    project.share_scope = payload.share_scope
    await audit_action(
        db,
        user_id=user.id,
        action="matter.policy_updated",
        resource_type="project",
        resource_id=str(project.id),
        request=request,
        project=project,
        details={"before": previous, "after": project.share_scope, "reason": payload.reason},
    )
    await db.commit()
    return summary(project)


@router.post("/{project_id}/transfer", response_model=MatterAdministrationSummary)
async def transfer_ownership(
    project_id: uuid.UUID,
    payload: MatterOwnershipTransfer,
    request: Request,
    user: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MatterAdministrationSummary:
    project = await require_matter_management(db, project_id, user)
    target = await db.scalar(select(User).where(User.id == payload.owner_id).with_for_update())
    if target is None or target.deleted_at is not None or target.deletion_scheduled_at is not None:
        raise NotFound("The new owner must be an active user without scheduled deletion.")
    target_member = await db.get(ProjectMember, (project.id, target.id))
    if target_member is not None and target_member.role == "blocked":
        raise Conflict(
            "Lift the new owner's screen in a separate audited operation before transferring ownership."
        )
    old_id = project.owner_id
    if target.id == old_id:
        raise ValidationError("The selected user already owns this matter.")
    # Slugs live in the owner's namespace. Never silently rename a transferred matter.
    collision = await db.scalar(
        select(Project.id).where(
            Project.owner_id == target.id,
            Project.slug == project.slug,
            Project.archived_at.is_(None),
            Project.id != project.id,
        )
    )
    if collision and project.archived_at is None:
        raise Conflict(
            "The new owner already has an active matter with this slug; rename it before transferring."
        )
    file_ids = select(File.id).where(File.owner_id == old_id, File.project_id == project.id)
    kb_ids = select(KnowledgeBase.id).where(
        KnowledgeBase.owner_id == old_id, KnowledgeBase.project_id == project.id
    )
    other_file = await db.scalar(
        select(ProjectFile.file_id)
        .where(ProjectFile.file_id.in_(file_ids), ProjectFile.project_id != project.id)
        .limit(1)
    )
    other_kb = await db.scalar(
        select(ProjectKnowledgeBase.knowledge_base_id)
        .where(
            ProjectKnowledgeBase.knowledge_base_id.in_(kb_ids),
            ProjectKnowledgeBase.project_id != project.id,
        )
        .limit(1)
    )
    if other_file or other_kb:
        raise Conflict(
            "Reconcile files or knowledge bases also attached to other matters before transferring their custody."
        )
    from app.models.autonomous import AutonomousSchedule, AutonomousSession, AutonomousWatch

    active = await db.scalar(
        select(AutonomousSession.id)
        .where(AutonomousSession.project_id == project.id, AutonomousSession.status == "running")
        .limit(1)
    )
    if active is not None:
        raise Conflict("Halt running autonomous sessions before transferring ownership.")
    for scheduled in [AutonomousSchedule, AutonomousWatch]:
        await db.execute(
            update(scheduled)
            .where(scheduled.__table__.c.project_id == project.id)
            .values(enabled=False)
        )
    project.owner_id = target.id
    old_member = await db.get(ProjectMember, (project.id, old_id))
    if old_member is None:
        old_member = ProjectMember(
            project_id=project.id,
            user_id=old_id,
            added_by_user_id=user.id,
            role=payload.former_owner_role,
        )
        db.add(old_member)
    else:
        old_member.role = payload.former_owner_role
    if target_member is None:
        db.add(
            ProjectMember(
                project_id=project.id, user_id=target.id, added_by_user_id=user.id, role="lead"
            )
        )
    else:
        target_member.role = "lead"
    counts = {}
    for model, label in [(Chat, "chats"), (File, "files"), (KnowledgeBase, "knowledge_bases")]:
        result = await db.execute(
            update(model)
            .where(model.__table__.c.owner_id == old_id, model.__table__.c.project_id == project.id)
            .values(owner_id=target.id)
            .returning(model.__table__.c.id)
        )
        counts[label] = len(result.scalars().all())
    await audit_action(
        db,
        user_id=user.id,
        action="matter.ownership_transferred",
        resource_type="project",
        resource_id=str(project.id),
        request=request,
        project=project,
        details={
            "before_owner_id": str(old_id),
            "after_owner_id": str(target.id),
            "former_owner_role": payload.former_owner_role,
            "custody_transferred": counts,
            "reason": payload.reason,
        },
    )
    await db.commit()
    return summary(project)
