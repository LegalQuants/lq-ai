"""Governed runs as turns in a chat thread (ADR 0038 D1).

Chat adds intake and two reads for the composer. Approval, rejection, halt,
closing and inspection stay on the owner-only routes in
:mod:`app.api.orchestration`; there is no second governance path (ADR 0016 P6).

* ``GET  /chats/{chat_id}/run-profiles`` — each registry profile's availability
  for this chat, with the reason when it is unavailable, and the owner's active
  run if one is blocking a new start.
* ``GET  /chats/{chat_id}/run-documents`` — the files a run could read here.
* ``POST /chats/{chat_id}/runs`` — accept one planning request (202).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select

from app.api.dependencies import ActiveUser, AutonomousEnabledUser
from app.api.orchestration import Service, begin_run
from app.autonomous.orchestration.contracts import TaskText
from app.autonomous.orchestration.intake import (
    MAX_SELECTED_DOCUMENTS,
    child_allowance,
    list_documents,
    prepare_intake,
)
from app.autonomous.orchestration.profiles import (
    RunProfile,
    composer_profile,
    registered_profiles,
)
from app.autonomous.orchestration.service import DemonstrationService
from app.autonomous.orchestration.tools import get_tool
from app.autonomous.orchestration.views import ChatRunRead, ToolRead
from app.errors import Forbidden, LQAIError, NotFound
from app.models.chat import Chat, Message
from app.models.orchestration import OrchestrationRoot
from app.models.project import Project
from app.models.user import User
from app.schemas.autonomous import Phase

router = APIRouter(prefix="/chats", tags=["chats"])

_ACTIVE = ("planning", "awaiting_approval", "queued", "running", "waiting_children", "uncertain")

Reason = Literal[
    "operator_disabled",
    "not_configured",
    "autonomous_opt_in_required",
    "project_required",
    "project_not_permitted",
    "route_unavailable",
    "active_run",
]

_REASON_TEXT: dict[str, str] = {
    "operator_disabled": "The operator has not enabled this profile.",
    "not_configured": "The operator has enabled this profile but its configuration is incomplete.",
    "autonomous_opt_in_required": "Turn on Autonomous in your settings to start a run.",
    "project_required": "Runs start from a chat inside a matter. This chat has no matter.",
    "project_not_permitted": "The operator has limited this profile to a dedicated demo matter.",
    "route_unavailable": "The profile's model route, protection or pricing is unavailable.",
    "active_run": "Another run of yours is still active. One run can be active at a time.",
}


class ProfileAvailability(BaseModel):
    """One registry profile, as the composer shows it for this chat."""

    profile: str
    title: str
    summary: str
    reads: str
    documents: Literal["packet", "selected"]
    evidence: Literal["unverified", "citations"]
    available: bool
    reason: Reason | None = None
    reason_text: str | None = None
    planning_notice: str
    model: str | None = None
    budget_usd: Decimal | None = None
    planning_allowance_usd: Decimal | None = None
    root_allowance_usd: Decimal | None = None
    child_allowance_usd: Decimal | None = None
    max_children: int | None = None
    attempt_timeout_seconds: int | None = None
    child_turn_limit: int
    max_documents: int | None = None
    tools: list[ToolRead]


class ActiveRun(BaseModel):
    """The owner's run that holds the single active-run allowance."""

    root_id: uuid.UUID
    status: str
    profile: str
    chat_id: uuid.UUID | None = None
    chat_title: str | None = None
    message_id: uuid.UUID | None = None


class RunProfilesRead(BaseModel):
    chat_id: uuid.UUID
    project_id: uuid.UUID | None
    profiles: list[ProfileAvailability]
    # The profile the composer offers as the New harness model, or None when
    # the registry offers none. Its availability is its entry in `profiles`.
    # The server names it so that a client never chooses between profiles.
    composer_profile: str | None = None
    active_run: ActiveRun | None = None


class RunDocument(BaseModel):
    file_id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    characters: int
    attached_to_project: bool
    selectable: bool
    # unsupported_type | not_ingested | ingestion_failed | no_text
    reason: str | None = None


class RunDocumentsRead(BaseModel):
    chat_id: uuid.UUID
    project_id: uuid.UUID
    max_documents: int
    documents: list[RunDocument]


class ChatRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: uuid.UUID
    """Client-generated. A repeated send with the same id returns the same run."""
    profile: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    goal: TaskText
    file_ids: Annotated[list[uuid.UUID], Field(max_length=MAX_SELECTED_DOCUMENTS)] = []
    """Documents the run may read, in the owner's order. Required by a profile
    that reads selected documents and refused by one that reads a fixed one.
    A file not yet attached to the chat's matter is attached when the run is
    accepted, with an audit row (ADR 0038 D5)."""


async def _owned_chat(runtime: DemonstrationService, chat_id: uuid.UUID, user: User) -> Chat:
    async with runtime.store.sessions() as db:
        chat = await db.scalar(
            select(Chat).where(
                Chat.id == chat_id,
                Chat.owner_id == user.id,
                Chat.autonomous_session_id.is_(None),
            )
        )
    if chat is None:
        raise NotFound(f"Chat {chat_id} not found.", details={"chat_id": str(chat_id)})
    return chat


def _tools(profile: RunProfile) -> list[ToolRead]:
    return [
        ToolRead(
            name=name,
            label=tool.label if (tool := get_tool(name)) else name,
            phase=phase.value,
            registered=tool is not None,
        )
        for phase in Phase
        for name in profile.child_tools.for_phase(phase)
    ]


async def _availability(
    runtime: DemonstrationService,
    profile: RunProfile,
    *,
    user: User,
    chat: Chat,
    project: Project | None,
    active: ActiveRun | None,
) -> ProfileAvailability:
    base: dict[str, Any] = {
        "profile": profile.id,
        "title": profile.title,
        "summary": profile.summary,
        "reads": profile.reads,
        "documents": profile.documents,
        "evidence": profile.evidence,
        "planning_notice": profile.planning_notice,
        "child_turn_limit": profile.limits.child_turn_limit,
        "max_documents": MAX_SELECTED_DOCUMENTS if profile.documents == "selected" else None,
        "tools": _tools(profile),
    }

    def unavailable(reason: Reason, text: str | None = None) -> ProfileAvailability:
        return ProfileAvailability(
            **base, available=False, reason=reason, reason_text=text or _REASON_TEXT[reason]
        )

    model = runtime.for_profile(profile.id)
    try:
        policy = model.policy()
    except Forbidden as exc:
        # Operator-facing detail is safe to show: it names a missing setting.
        return unavailable("not_configured", exc.message)
    if policy is None:
        return unavailable("operator_disabled")
    if not user.autonomous_enabled:
        return unavailable("autonomous_opt_in_required")
    if chat.archived_at is not None or project is None:
        return unavailable("project_required")
    if policy.demo_project_id is not None and policy.demo_project_id != project.id:
        return unavailable("project_not_permitted")
    routes = model.effects().inference
    assert routes is not None and policy.inference is not None
    try:
        quote = await prepare_intake(
            profile,
            settings=model.settings,
            skills=model.skills,
            policy=policy,
            routes=routes,
            root_id=uuid.uuid4(),
            owner_id=user.id,
            project_id=project.id,
            goal="Readiness quote",
            privileged=project.privileged,
            minimum_inference_tier=project.minimum_inference_tier or 5,
        )
    except LQAIError as exc:
        return unavailable("route_unavailable", exc.message)
    priced: dict[str, Any] = {
        "model": policy.inference.model_key,
        "budget_usd": quote.budget_usd,
        "planning_allowance_usd": quote.planning_allowance_usd,
        "root_allowance_usd": quote.root_allowance_usd,
        "child_allowance_usd": child_allowance(profile, quote),
        "max_children": quote.max_children,
        "attempt_timeout_seconds": quote.attempt_timeout_seconds,
    }
    if active is not None:
        return ProfileAvailability(
            **base,
            **priced,
            available=False,
            reason="active_run",
            reason_text=_REASON_TEXT["active_run"],
        )
    return ProfileAvailability(**base, **priced, available=True)


@router.get(
    "/{chat_id}/run-profiles",
    response_model=RunProfilesRead,
    summary="Run profiles available to this chat's composer",
)
async def run_profiles(chat_id: uuid.UUID, user: ActiveUser, runtime: Service) -> RunProfilesRead:
    """Each registry profile's availability here, and why when it is not.

    Reports the allowances a run would be quoted before any planning is paid
    for. Makes no model call. ``active_run`` names the owner's run that is
    holding the single active-run allowance, in any chat, so the composer can
    say which one is blocking and offer to close it when it is uncertain.
    """
    chat = await _owned_chat(runtime, chat_id, user)
    async with runtime.store.sessions() as db:
        project = (
            await db.scalar(
                select(Project).where(
                    Project.id == chat.project_id,
                    Project.owner_id == user.id,
                    Project.archived_at.is_(None),
                )
            )
            if chat.project_id is not None
            else None
        )
        row = (
            await db.execute(
                select(OrchestrationRoot, Message.chat_id, Message.id, Chat.title)
                .outerjoin(Message, Message.autonomous_session_id == OrchestrationRoot.session_id)
                .outerjoin(Chat, Chat.id == Message.chat_id)
                .where(
                    OrchestrationRoot.owner_id == user.id,
                    OrchestrationRoot.status.in_(_ACTIVE),
                )
                .limit(1)
            )
        ).one_or_none()
    active = (
        ActiveRun(
            root_id=row[0].session_id,
            status=row[0].status,
            profile=row[0].profile,
            chat_id=row[1],
            message_id=row[2],
            chat_title=row[3],
        )
        if row is not None
        else None
    )
    return RunProfilesRead(
        chat_id=chat.id,
        project_id=chat.project_id,
        profiles=[
            await _availability(
                runtime, profile, user=user, chat=chat, project=project, active=active
            )
            for profile in registered_profiles()
        ],
        composer_profile=offered.id if (offered := composer_profile()) else None,
        active_run=active,
    )


@router.get(
    "/{chat_id}/run-documents",
    response_model=RunDocumentsRead,
    summary="Files a run started from this chat could read",
)
async def run_documents(
    chat_id: uuid.UUID,
    user: ActiveUser,
    runtime: Service,
    file_id: Annotated[
        list[uuid.UUID] | None,
        Query(
            max_length=16,
            description=(
                "The owner's own files that are not attached to the matter, "
                "typically this chat's attachments, to list as candidates."
            ),
        ),
    ] = None,
) -> RunDocumentsRead:
    """The matter's files, plus named candidates, with whether each can be read.

    A file that cannot be read is listed with its reason and is not selectable;
    it is never silently omitted (ADR 0038 D5). Selecting a candidate attaches
    it to the matter when the run is accepted.
    """
    chat = await _owned_chat(runtime, chat_id, user)
    if chat.project_id is None:
        raise Forbidden(message=_REASON_TEXT["project_required"])
    async with runtime.store.sessions() as db:
        project = await db.scalar(
            select(Project.id).where(
                Project.id == chat.project_id,
                Project.owner_id == user.id,
                Project.archived_at.is_(None),
            )
        )
        if project is None:
            raise NotFound(message="Project not found")
        listed = await list_documents(
            db,
            owner_id=user.id,
            project_id=chat.project_id,
            candidate_file_ids=tuple(file_id or ()),
        )
    return RunDocumentsRead(
        chat_id=chat.id,
        project_id=chat.project_id,
        max_documents=MAX_SELECTED_DOCUMENTS,
        documents=[
            RunDocument(
                file_id=d.file_id,
                filename=d.filename,
                mime_type=d.mime_type,
                size_bytes=d.size_bytes,
                characters=d.characters,
                attached_to_project=d.attached_to_project,
                selectable=d.selectable,
                reason=d.reason,
            )
            for d in listed
        ],
    )


@router.post(
    "/{chat_id}/runs",
    response_model=ChatRunRead,
    status_code=202,
    summary="Start a governed run as a turn in this chat",
)
async def start_run(
    chat_id: uuid.UUID, body: ChatRunRequest, user: AutonomousEnabledUser, runtime: Service
) -> ChatRunRead:
    """Accept one planning request and write its two messages.

    The request becomes an ordinary user message. The reply is one assistant
    message of kind ``run`` linked to the run's root session; it carries the
    answer once the root delivers one, and stays empty otherwise. Accepting the
    request authorizes one planning call within the disclosed allowance. Child
    work needs the owner's approval of the exact plan on the existing route.

    The planning call receives ``goal`` only, never earlier messages.
    """
    chat = await _owned_chat(runtime, chat_id, user)
    if chat.archived_at is not None:
        raise NotFound(f"Chat {chat_id} not found.", details={"chat_id": str(chat_id)})
    if chat.project_id is None:
        raise Forbidden(message=_REASON_TEXT["project_required"])
    return await begin_run(
        runtime.for_profile(body.profile),
        user=user,
        request_id=body.request_id,
        project_id=chat.project_id,
        goal=body.goal,
        chat_id=chat.id,
        file_ids=tuple(body.file_ids),
    )
