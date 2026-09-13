"""Scope narrowing inside guarded_tool_call, after R5 and before R4.

This is not approval or a worker claim. The execution adapter must obtain the
scope from the durable plan and admit the effect through OrchestrationStore.
Only the implemented document/inference/finding paths are enabled here; source
dispatch stays closed until exact provider/operation and pricing binding land.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.contracts import ExecutionScope
from app.errors import ToolNotGranted
from app.models.autonomous import AutonomousSession
from app.models.document import Document
from app.models.file import File
from app.models.project import ProjectFile

_IMPLEMENTED = frozenset(
    {ToolIntent.retrieve_chunks, ToolIntent.run_skill, ToolIntent.plan, ToolIntent.emit_finding}
)


async def constrain_call(
    db: AsyncSession,
    session: AutonomousSession,
    intent: ToolIntent,
    params: dict[str, Any],
    scope: ExecutionScope,
) -> dict[str, Any]:
    """Return narrowed params, refusing unsupported or out-of-scope reads."""
    if intent not in _IMPLEMENTED or intent not in getattr(scope.grants, session.current_phase):
        raise ToolNotGranted("tool is outside implemented orchestration scope")
    if intent in {ToolIntent.run_skill, ToolIntent.plan}:
        # These values come from server authority, never from planner params.
        return {
            **params,
            "anonymize": scope.anonymize,
            "minimum_inference_tier": scope.minimum_inference_tier,
            "lq_ai_project_minimum_inference_tier": scope.minimum_inference_tier,
            "lq_ai_privileged": scope.privileged,
        }
    if intent == ToolIntent.retrieve_chunks:
        # Do not silently reinterpret a KB-wide search as a selected-file read.
        if set(params) != {"file_id"}:
            raise ToolNotGranted("orchestration retrieval requires one selected file")
        try:
            file_id = UUID(str(params["file_id"]))
        except (TypeError, ValueError, AttributeError):
            raise ToolNotGranted("orchestration retrieval requires one selected file") from None
        visible = await db.scalar(
            select(Document.id)
            .join(File, File.id == Document.file_id)
            .join(ProjectFile, ProjectFile.file_id == File.id)
            .where(
                File.id == file_id,
                Document.id.in_(scope.resources.document_ids),
                File.owner_id == session.user_id,
                File.deleted_at.is_(None),
                ProjectFile.project_id == session.project_id,
            )
            .with_for_update(read=True, of=(Document, File, ProjectFile))
        )
        if visible is None:
            raise ToolNotGranted("document is outside the current selected project scope")
        return {"file_id": str(file_id)}
    return dict(params)
