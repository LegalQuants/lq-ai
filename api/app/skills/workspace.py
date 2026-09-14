"""Bounded optional persistence; caller owns transaction and audit/receipt."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ToolNotGranted
from app.models.project import Project
from app.models.skill_workspace import SkillWorkspace, SkillWorkspaceFile
from app.models.user import User
from app.skills.binding import SkillBinding
from app.skills.capabilities import (
    MAX_FILES,
    MAX_WORKSPACE_BYTES,
    EmptyInput,
    FileRead,
    FileWrite,
)


async def check_owner(db: AsyncSession, owner_id: UUID, project_id: UUID | None) -> None:
    if (
        await db.scalar(select(User.id).where(User.id == owner_id, User.deleted_at.is_(None)))
        is None
    ):
        raise ToolNotGranted("Workspace owner is unavailable")
    if (
        project_id is not None
        and await db.scalar(
            select(Project.id).where(
                Project.id == project_id,
                Project.owner_id == owner_id,
                Project.archived_at.is_(None),
            )
        )
        is None
    ):
        raise ToolNotGranted("Workspace project is unavailable")


def metadata(row: SkillWorkspaceFile) -> dict[str, Any]:
    return {
        "name": row.name,
        "revision": str(row.revision),
        "size_bytes": row.size_bytes,
        "updated_at": row.updated_at.isoformat(),
    }


async def workspace_operation(
    db: AsyncSession,
    *,
    binding: SkillBinding,
    owner_id: UUID,
    project_id: UUID | None,
    operation: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    version = binding.capabilities.workspace_version
    if version is None:
        raise ToolNotGranted("This skill has not opted in to persistent storage")
    await check_owner(db, owner_id, project_id)
    request = (
        FileWrite if operation == "write" else FileRead if operation == "read" else EmptyInput
    ).model_validate(params)
    if operation not in {"list", "read", "write", "reset"}:
        raise ToolNotGranted("Unknown workspace operation")
    # Serialize namespace creation and reset with ordinary writes. Locking the
    # owner is consistent with orchestration's existing owner/project lock order.
    await db.execute(select(User.id).where(User.id == owner_id).with_for_update())
    if project_id is not None:
        await db.execute(select(Project.id).where(Project.id == project_id).with_for_update())
    await check_owner(db, owner_id, project_id)
    query = select(SkillWorkspace).where(
        SkillWorkspace.owner_id == owner_id,
        SkillWorkspace.project_id == project_id,
        SkillWorkspace.skill_key == binding.key,
        SkillWorkspace.format_version == version,
    )
    workspace = await db.scalar(query)
    if workspace is None and operation != "write":
        return {"files": []} if operation in {"list", "reset"} else {"error": "file_unavailable"}
    if workspace is None:
        await db.execute(
            insert(SkillWorkspace)
            .values(
                id=uuid4(),
                owner_id=owner_id,
                project_id=project_id,
                skill_key=binding.key,
                skill_name=binding.name,
                format_version=version,
            )
            .on_conflict_do_nothing(constraint="uq_skill_workspace_scope")
        )
        workspace = await db.scalar(query)
    assert workspace is not None
    if operation == "reset":
        await db.execute(delete(SkillWorkspace).where(SkillWorkspace.id == workspace.id))
        return {"files": []}
    if operation == "list":
        return {
            "files": [
                metadata(row)
                for row in await db.scalars(
                    select(SkillWorkspaceFile)
                    .where(SkillWorkspaceFile.workspace_id == workspace.id)
                    .order_by(SkillWorkspaceFile.name)
                    .limit(MAX_FILES)
                )
            ]
        }
    assert isinstance(request, FileRead)
    row = await db.get(SkillWorkspaceFile, (workspace.id, request.name), populate_existing=True)
    if operation == "read":
        return {**metadata(row), "content": row.content} if row else {"error": "file_unavailable"}
    assert isinstance(request, FileWrite)
    if request.expected_revision != (row.revision if row else None):
        return {"error": "revision_conflict"}
    count, total = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(SkillWorkspaceFile.size_bytes), 0)).where(
                SkillWorkspaceFile.workspace_id == workspace.id
            )
        )
    ).one()
    size = len(request.content.encode("utf-8"))
    if (row is None and count >= MAX_FILES) or total - (
        row.size_bytes if row else 0
    ) + size > MAX_WORKSPACE_BYTES:
        return {"error": "storage_limit"}
    if row is None:
        row = SkillWorkspaceFile(workspace_id=workspace.id, name=request.name)
        db.add(row)
    row.content, row.size_bytes, row.revision = request.content, size, uuid4()
    row.updated_at = datetime.now(UTC)
    await db.flush()
    return metadata(row)
