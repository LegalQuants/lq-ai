"""Owner inspection and reset remain available when execution is disabled."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.audit import audit_action
from app.db.session import get_db
from app.errors import NotFound
from app.models.project import Project
from app.models.skill_workspace import SkillWorkspace, SkillWorkspaceFile
from app.models.user import User
from app.skills.workspace import metadata

router = APIRouter(prefix="/skill-workspaces", tags=["skills"])
DB = Annotated[AsyncSession, Depends(get_db)]


class SavedFile(BaseModel):
    name: str
    revision: UUID
    size_bytes: int
    updated_at: datetime


class SavedContent(SavedFile):
    content: str


class SavedWorkspace(BaseModel):
    id: UUID
    skill_name: str
    project_id: UUID | None
    project_name: str | None
    format_version: int
    files: list[SavedFile]


@router.get("", response_model=list[SavedWorkspace])
async def list_workspaces(
    user: ActiveUser, db: DB, offset: Annotated[int, Query(ge=0)] = 0
) -> list[SavedWorkspace]:
    rows = (
        await db.execute(
            select(SkillWorkspace, Project.name)
            .outerjoin(Project, Project.id == SkillWorkspace.project_id)
            .where(SkillWorkspace.owner_id == user.id)
            .order_by(SkillWorkspace.skill_name, SkillWorkspace.id)
            .offset(offset)
            .limit(50)
        )
    ).all()
    result = []
    for workspace, project_name in rows:
        files = await db.scalars(
            select(SkillWorkspaceFile)
            .where(SkillWorkspaceFile.workspace_id == workspace.id)
            .order_by(SkillWorkspaceFile.name)
            .limit(32)
        )
        result.append(
            SavedWorkspace(
                id=workspace.id,
                skill_name=workspace.skill_name,
                project_id=workspace.project_id,
                project_name=project_name,
                format_version=workspace.format_version,
                files=[SavedFile.model_validate(metadata(f)) for f in files],
            )
        )
    return result


@router.get("/{workspace_id}/files/{name}", response_model=SavedContent)
async def read_file(workspace_id: UUID, name: str, user: ActiveUser, db: DB) -> SavedContent:
    row = await db.scalar(
        select(SkillWorkspaceFile)
        .join(SkillWorkspace)
        .where(
            SkillWorkspace.id == workspace_id,
            SkillWorkspace.owner_id == user.id,
            SkillWorkspaceFile.name == name,
        )
    )
    if row is None:
        raise NotFound(message="Saved file not found")
    return SavedContent.model_validate({**metadata(row), "content": row.content})


@router.delete("/{workspace_id}", status_code=204, response_class=Response)
async def reset_workspace(
    workspace_id: UUID, request: Request, user: ActiveUser, db: DB
) -> Response:
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    workspace = await db.scalar(
        select(SkillWorkspace).where(
            SkillWorkspace.id == workspace_id, SkillWorkspace.owner_id == user.id
        )
    )
    if workspace is None:
        raise NotFound(message="Workspace not found")
    await db.execute(delete(SkillWorkspace).where(SkillWorkspace.id == workspace_id))
    await audit_action(
        db,
        user_id=user.id,
        action="skill_workspace.reset",
        resource_type="skill_workspace",
        resource_id=str(workspace_id),
        project_id=workspace.project_id,
        request=request,
    )
    await db.commit()
    return Response(status_code=204)
