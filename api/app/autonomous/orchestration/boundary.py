"""Scope narrowing inside guarded_tool_call, after R5 and before R4.

This is not approval or a worker claim. The execution adapter must obtain the
scope from the durable plan and admit the effect through OrchestrationStore.
Authority dispatch additionally requires an exact server-owned source binding.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.contracts import ExecutionScope
from app.autonomous.orchestration.inference import InferenceBinding
from app.autonomous.orchestration.reading import read_locks, readable_documents
from app.autonomous.orchestration.sources import SourceBinding
from app.autonomous.orchestration.workspace import WORKSPACE_INTENTS, parse_request
from app.errors import ToolNotGranted
from app.models.autonomous import AutonomousSession
from app.models.file import File
from app.skills.tools import SKILL_TOOL_INTENTS, parse_skill_tool

_IMPLEMENTED = frozenset(
    {
        ToolIntent.retrieve_chunks,
        ToolIntent.run_skill,
        ToolIntent.plan,
        ToolIntent.emit_finding,
        ToolIntent.retrieve_authority,
        *WORKSPACE_INTENTS,
        *SKILL_TOOL_INTENTS,
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
    if intent in WORKSPACE_INTENTS:
        return parse_request(intent, params).model_dump(mode="json")
    if intent in SKILL_TOOL_INTENTS:
        return parse_skill_tool(intent, params)
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
        if "lq_ai_restore_tool_arguments" in params and inference_binding is None:
            # Only a call bound to the approved route may ask the gateway to
            # restore its tool-call arguments. The binding says whether the
            # route pseudonymizes at all, and ``matches`` below refuses a call
            # whose request and binding disagree. A restored call is sent back
            # on the next turn as part of the conversation, which the gateway
            # pseudonymizes again, so the originals do not leave.
            raise ToolNotGranted("only a bound call may have its arguments restored")
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
        if "kb_ids" in params:
            return _knowledge_search(session, params, scope)
        # Do not silently reinterpret a KB-wide search as a selected-file read.
        # A read is the whole file's chunks, or one bounded span of its text.
        if set(params) not in ({"file_id"}, {"file_id", "offset", "max_chars"}):
            raise ToolNotGranted("orchestration retrieval requires one selected file")
        try:
            file_id = UUID(str(params["file_id"]))
        except (TypeError, ValueError, AttributeError):
            raise ToolNotGranted("orchestration retrieval requires one selected file") from None
        span: dict[str, Any] = {}
        if "max_chars" in params:
            offset, max_chars = params["offset"], params["max_chars"]
            if (
                type(offset) is not int
                or type(max_chars) is not int
                or not 0 <= offset <= 50_000_000
                or not 1 <= max_chars <= 65_536
            ):
                raise ToolNotGranted("orchestration document read is out of bounds")
            span = {"offset": offset, "max_chars": max_chars}
        # The same rule intake and the policy check apply; see ``reading``. A
        # run outside a matter reads the owner's selected files wherever they
        # are filed, under their matters' terms, which the store has checked.
        visible = await db.scalar(
            readable_documents(
                owner_id=session.user_id,
                project_id=session.project_id,
                document_ids=scope.resources.document_ids,
            )
            .where(File.id == file_id)
            .with_for_update(read=True, of=read_locks(session.project_id))
        )
        if visible is None:
            raise ToolNotGranted(
                "document is outside the current selected project scope"
                if session.project_id is not None
                else "document is outside this run's current selection"
            )
        return {"file_id": str(file_id), **span}
    return dict(params)


def _knowledge_search(
    session: AutonomousSession, params: dict[str, Any], scope: ExecutionScope
) -> dict[str, Any]:
    """A keyword search of knowledge bases the approved plan lists (ADR 0038 D5).

    Checked here: the request's shape and bounds, that the run is in a matter,
    and that every named knowledge base is in the approved scope. Nothing here
    depends on what has changed since approval, so a replayed search has the
    same identity as the first attempt. Whether each knowledge base is still
    the owner's, not archived and still attached to the matter is checked when
    the search runs, in the same transaction and before anything is read
    (``guard._handle_search_knowledge_bases``); one that is not is not searched.
    """
    if set(params) != {"kb_ids", "query", "top_k", "max_chars"}:
        raise ToolNotGranted("orchestration knowledge search has a fixed request shape")
    raw, query, top_k, max_chars = (
        params["kb_ids"],
        params["query"],
        params["top_k"],
        params["max_chars"],
    )
    if session.project_id is None:
        raise ToolNotGranted("a run outside a matter searches no knowledge base")
    if (
        not isinstance(raw, list)
        or not 1 <= len(raw) <= 16
        or not isinstance(query, str)
        or not 1 <= len(query) <= 512
        or type(top_k) is not int
        or not 1 <= top_k <= 10
        or type(max_chars) is not int
        or not 256 <= max_chars <= 65_536
    ):
        raise ToolNotGranted("orchestration knowledge search is out of bounds")
    try:
        wanted = sorted({UUID(str(value)) for value in raw})
    except (TypeError, ValueError, AttributeError):
        raise ToolNotGranted("orchestration knowledge search names a knowledge base") from None
    if len(wanted) != len(raw) or not set(wanted) <= set(scope.resources.knowledge_base_ids):
        raise ToolNotGranted("knowledge base is outside the approved plan")
    return {
        "kb_ids": [str(value) for value in wanted],
        "query": query,
        "top_k": top_k,
        "max_chars": max_chars,
        # From the server's own record of the run, never from the request.
        "project_id": str(session.project_id),
    }
