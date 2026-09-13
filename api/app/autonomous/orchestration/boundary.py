"""Scope narrowing inside guarded_tool_call, after R5 and before R4.

This is not approval or a worker claim. The execution adapter must obtain the
scope from the durable plan and admit the effect through OrchestrationStore.
Authority dispatch additionally requires an exact server-owned source binding.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.contracts import ExecutionScope
from app.autonomous.orchestration.inference import InferenceBinding
from app.autonomous.orchestration.sources import SourceBinding
from app.errors import ToolNotGranted
from app.models.autonomous import AutonomousSession
from app.models.document import Document
from app.models.file import File
from app.models.project import ProjectFile

_IMPLEMENTED = frozenset(
    {
        ToolIntent.retrieve_chunks,
        ToolIntent.run_skill,
        ToolIntent.plan,
        ToolIntent.emit_finding,
        ToolIntent.retrieve_authority,
    }
)


async def constrain_call(
    db: AsyncSession,
    session: AutonomousSession,
    intent: ToolIntent,
    params: dict[str, Any],
    scope: ExecutionScope,
    source_binding: SourceBinding | None = None,
    inference_binding: InferenceBinding | None = None,
) -> dict[str, Any]:
    """Return narrowed params, refusing unsupported or out-of-scope reads."""
    if intent not in _IMPLEMENTED or intent not in getattr(scope.grants, session.current_phase):
        raise ToolNotGranted("tool is outside implemented orchestration scope")
    if intent == ToolIntent.retrieve_authority:
        if (
            source_binding is None
            or source_binding.source.name not in scope.resources.source_names
            or source_binding.source.egress_tier > scope.maximum_egress_tier
            or source_binding.operation not in source_binding.source.operations
            or source_binding.anonymization_expected is not scope.anonymize
            or set(params) != {"source", "op", "args"}
            or params["source"] != source_binding.source.source_type
            or params["op"] != source_binding.operation
            or not isinstance(params["args"], dict)
        ):
            raise ToolNotGranted("authority call differs from supported source binding")
        return dict(params)
    if intent in {ToolIntent.run_skill, ToolIntent.plan}:
        if inference_binding is not None and (
            not inference_binding.matches(params)
            or inference_binding.routed_tier > scope.minimum_inference_tier
        ):
            raise ToolNotGranted("inference call differs from approved route binding")
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
