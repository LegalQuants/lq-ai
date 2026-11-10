"""Governed runs as turns in a chat thread (ADR 0038 D1).

Chat adds intake and two reads for the composer. Approval, rejection, halt,
closing and inspection stay on the routes in
:mod:`app.api.orchestration`; there is no second governance path (ADR 0016 P6).

* ``GET  /chats/{chat_id}/run-profiles`` — each registry profile's availability
  for this chat, with the reason when it is unavailable, and the owner's active
  run if one is blocking a new start.
* ``GET  /chats/{chat_id}/run-documents`` — the files a run could read here, and
  the knowledge bases its tasks could search.
* ``POST /chats/{chat_id}/runs`` — accept one planning request (202).

A chat need not be in a matter. A profile says whether it may start from a chat
outside any matter; New harness may, the fictional fixture may not.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select

from app.api.dependencies import ActiveUser, RunActor
from app.api.orchestration import Service, begin_run
from app.authz.matters import matter_scope_filter, require_chat_run_access, require_matter
from app.autonomous.orchestration.contracts import TaskText
from app.autonomous.orchestration.intake import (
    MAX_SELECTED_DOCUMENTS,
    child_allowance,
    list_documents,
    list_knowledge_bases,
    quote_intake,
    searches_knowledge,
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
from app.models.user import MUTATING_ROLES, User
from app.schemas.autonomous import Phase

router = APIRouter(prefix="/chats", tags=["chats"])

_ACTIVE = ("planning", "awaiting_approval", "queued", "running", "waiting_children", "uncertain")

Reason = Literal[
    "operator_disabled",
    "not_configured",
    "autonomous_opt_in_required",
    "role_read_only",
    "chat_archived",
    "project_required",
    "project_unavailable",
    "project_not_permitted",
    "route_unavailable",
    "active_run",
]


def _reason_text(reason: str, profile: RunProfile) -> str:
    """Why a profile cannot be used here, in words the composer can show as they are."""
    return {
        "operator_disabled": f"The operator has not enabled {profile.title}.",
        "not_configured": (
            f"The operator has enabled {profile.title} but its configuration is incomplete."
        ),
        "autonomous_opt_in_required": "Turn on Autonomous in your settings to start a run.",
        "role_read_only": "Your role has read-only access, so you cannot start a run.",
        "chat_archived": "This chat is archived.",
        "project_required": (
            f"{profile.title} starts from a chat inside a matter. This chat has no matter."
        ),
        "project_unavailable": "This chat's matter is archived or unavailable.",
        "project_not_permitted": (
            f"The operator has limited {profile.title} to a dedicated demo matter."
        ),
        "route_unavailable": "The model route, protection or pricing is unavailable.",
        "active_run": "Another run of yours is still active. One run can be active at a time.",
    }[reason]


class InstructionsRef(BaseModel):
    """What instructs one role of a profile: an installed skill or an engine prompt file.

    For a prompt, ``name`` is ``<family>/<role>.v<N>`` and its text is at
    ``GET /autonomous/orchestration/prompts/{family}/{role}.v{N}``, so it can
    be read before anything is sent.
    """

    role: Literal["orchestrator", "sub-agent"]
    kind: Literal["skill", "prompt"]
    name: str
    version: str | None = None
    digest: str | None = None


class ProfileAvailability(BaseModel):
    """One registry profile, as the composer shows it for this chat."""

    profile: str
    title: str
    summary: str
    reads: str
    documents: Literal["packet", "selected", "optional"]
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
    # 1 where at least one document must be selected; 0 where none is needed.
    min_documents: int = 0
    tools: list[ToolRead]
    instructions: list[InstructionsRef] = []
    # The inference tier the pinned route resolves to for this chat, and whether
    # calls on it are pseudonymized by the gateway. Known once the route is
    # priced; null otherwise. For a profile that follows the operator's setting
    # this is that setting's effect at the routed tier. It covers the whole
    # request: the gateway also rewrites what a task reads (a tool result) and the
    # arguments of earlier tool calls for a run, which holds them as originals.
    routed_tier: int | None = None
    pseudonymized: bool | None = None
    reasoning_effort: str | None = None
    # True where the orchestrator may answer a request by itself: the reply is
    # then delivered with no plan and no approval, having read nothing.
    answers_directly: bool = False


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
    # unsupported_type | not_ingested | ingestion_failed | no_text | in_another_matter
    reason: str | None = None
    # For a file that brings a matter's terms: the owner's matters that hold
    # it, the lowest inference tier floor any such matter sets (null when none
    # sets one), and whether one of them is privileged. For a chat outside any
    # matter those are the matters that hold the file, and a run that selects
    # it runs under these terms. For a chat in a matter they are the other
    # matters that hold it through a knowledge base, and a run that selects it
    # runs under the stricter of these terms and its own matter's. Empty, null
    # and false for any other file.
    matters: list[str] = []
    matter_minimum_inference_tier: int | None = None
    matter_privileged: bool = False


class RunKnowledgeBase(BaseModel):
    knowledge_base_id: uuid.UUID
    name: str


class RunDocumentsRead(BaseModel):
    chat_id: uuid.UUID
    # Null for a chat outside any matter: only named candidates are listed.
    project_id: uuid.UUID | None
    max_documents: int
    documents: list[RunDocument]
    # The knowledge bases a task of a run from this chat could search: the
    # owner's own, not archived, attached to the chat's matter. Empty for a
    # chat outside any matter, and where the offered profile searches none.
    # They are not picked: a run lists all of them, and its plan names them.
    knowledge_bases: list[RunKnowledgeBase] = []
    # How many more are attached than one run lists. Those are not searched.
    knowledge_bases_omitted: int = 0
    # The documents the last run in this chat read that can still be read, in
    # that run's order. A follow-up starts from them, so it does not lose its
    # documents when the page is reloaded. A suggestion only: nothing is
    # selected until the owner sends the request with these ids.
    suggested_file_ids: list[uuid.UUID] = []


class ChatRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: uuid.UUID
    """Client-generated. A repeated send with the same id returns the same run."""
    profile: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    goal: TaskText
    file_ids: Annotated[list[uuid.UUID], Field(max_length=MAX_SELECTED_DOCUMENTS)] = []
    """Documents the run may read, in the owner's order. A profile says whether
    it needs at least one, takes none to eight, or reads a fixed one and
    refuses any. In a matter, a file not yet attached to the matter is attached
    when the run is accepted, with an audit row (ADR 0038 D5), and a file that
    another matter holds through a knowledge base puts the run under the
    stricter of the two matters' terms. Outside a matter nothing is attached,
    and a file that a matter holds puts the run under that matter's inference
    tier floor and privilege flag."""


async def _owned_chat(runtime: DemonstrationService, chat_id: uuid.UUID, user: User) -> Chat:
    async with runtime.store.sessions() as db:
        chat = await db.scalar(
            select(Chat).where(
                Chat.id == chat_id,
                Chat.owner_id == user.id,
                Chat.autonomous_session_id.is_(None),
            )
        )
        if chat is not None:
            if chat.project_id is not None:
                await require_matter(db, chat.project_id, user, include_archived=True)
            await require_chat_run_access(db, chat.id, user)
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
    roles: tuple[
        tuple[Literal["orchestrator", "sub-agent"], Literal["orchestrator", "research"]], ...
    ] = (("orchestrator", "orchestrator"), ("sub-agent", "research"))
    base: dict[str, Any] = {
        "profile": profile.id,
        "title": profile.title,
        "summary": profile.summary,
        "reads": profile.reads,
        "documents": profile.documents,
        "evidence": profile.evidence,
        "planning_notice": profile.planning_notice,
        "answers_directly": profile.planning == "tool",
        "child_turn_limit": profile.limits.child_turn_limit,
        "max_documents": MAX_SELECTED_DOCUMENTS if profile.documents != "packet" else None,
        "min_documents": 1 if profile.documents == "selected" else 0,
        "tools": _tools(profile),
        "instructions": [
            InstructionsRef(role=shown, kind=kind, name=name)
            for shown, role in roles
            for kind, name in (profile.instructions(role),)
        ],
    }

    def unavailable(reason: Reason, text: str | None = None) -> ProfileAvailability:
        return ProfileAvailability(
            **base,
            available=False,
            reason=reason,
            reason_text=text or _reason_text(reason, profile),
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
    if user.role not in MUTATING_ROLES:
        # A viewer or an auditor reads; neither starts a run (ADR 0038, ruling 10).
        return unavailable("role_read_only")
    if chat.archived_at is not None:
        return unavailable("chat_archived")
    if project is None and chat.project_id is not None:
        return unavailable("project_unavailable")
    if project is None and profile.project_scope != "any":
        return unavailable("project_required")
    if (
        policy.demo_project_id is not None
        and project is not None
        and policy.demo_project_id != project.id
    ):
        return unavailable("project_not_permitted")
    routes = model.effects().inference
    assert routes is not None and policy.inference is not None
    try:
        quote, binding = await quote_intake(
            profile,
            settings=model.settings,
            skills=model.skills,
            policy=policy,
            routes=routes,
            root_id=uuid.uuid4(),
            owner_id=user.id,
            project_id=project.id if project is not None else None,
            goal="Readiness quote",
            # Outside a matter the chat alone sets no privilege flag or tier
            # floor. A run that selects a matter's file takes that matter's on;
            # this quote is made before any selection and does not show that.
            privileged=project.privileged if project is not None else False,
            minimum_inference_tier=(project.minimum_inference_tier or 5)
            if project is not None
            else 5,
        )
    except LQAIError as exc:
        return unavailable("route_unavailable", exc.message)
    pins = {selection.profile: selection.pin for selection in policy.skills}
    versions = {"orchestrator": quote.root_skill_version, "research": quote.child_skill_version}
    priced: dict[str, Any] = {
        "model": policy.inference.model_key,
        "budget_usd": quote.budget_usd,
        "planning_allowance_usd": quote.planning_allowance_usd,
        "root_allowance_usd": quote.root_allowance_usd,
        "child_allowance_usd": child_allowance(profile, quote),
        "max_children": quote.max_children,
        "attempt_timeout_seconds": quote.attempt_timeout_seconds,
        "routed_tier": binding.routed_tier,
        "pseudonymized": binding.anonymization_expected,
        "reasoning_effort": policy.inference.reasoning_effort,
        "instructions": [
            InstructionsRef(
                role=shown,
                kind=pins[role].kind,
                name=pins[role].name,
                version=versions[role],
                digest=pins[role].digest,
            )
            for shown, role in roles
        ],
    }
    if active is not None:
        return ProfileAvailability(
            **{**base, **priced},
            available=False,
            reason="active_run",
            reason_text=_reason_text("active_run", profile),
        )
    return ProfileAvailability(**{**base, **priced}, available=True)


async def _chat_project(db: Any, chat: Chat, user: User) -> Project | None:
    """The chat's matter while the owner still owns it and it is not archived."""
    if chat.project_id is None:
        return None
    project: Project | None = await db.scalar(
        select(Project).where(
            Project.id == chat.project_id,
            Project.owner_id == user.id,
            Project.archived_at.is_(None),
        )
    )
    return project


@router.get(
    "/{chat_id}/run-profiles",
    response_model=RunProfilesRead,
    summary="Run profiles available to this chat's composer",
)
async def run_profiles(chat_id: uuid.UUID, user: ActiveUser, runtime: Service) -> RunProfilesRead:
    """Each registry profile's availability here, and why when it is not.

    Reports the allowances a run would be quoted before any planning is paid
    for, the inference tier its pinned route resolves to, and whether message
    text on that route is pseudonymized. Makes no model call. ``active_run`` names the
    owner's run that is holding the single active-run allowance, in any chat,
    so the composer can say which one is blocking and offer to close it when it
    is uncertain.
    """
    chat = await _owned_chat(runtime, chat_id, user)
    async with runtime.store.sessions() as db:
        project = await _chat_project(db, chat, user)
        row = (
            await db.execute(
                select(OrchestrationRoot, Message.chat_id, Message.id, Chat.title)
                .outerjoin(Message, Message.autonomous_session_id == OrchestrationRoot.session_id)
                .outerjoin(Chat, Chat.id == Message.chat_id)
                .where(
                    OrchestrationRoot.owner_id == user.id,
                    OrchestrationRoot.status.in_(_ACTIVE),
                    OrchestrationRoot.project_id.is_(None)
                    | OrchestrationRoot.project_id.in_(
                        select(Project.id).where(matter_scope_filter(user))
                    ),
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
    """The files a run from this chat could read, with whether each can be.

    Also the knowledge bases a task could search: those attached to the chat's
    matter, where the composer's profile grants the search. None outside a
    matter.

    In a matter: the matter's files, plus named candidates. Selecting a
    candidate attaches it to the matter when the run is accepted. A file that
    another matter holds through a knowledge base is listed with that matter's
    name, floor and privilege flag; a run that reads it takes the stricter of
    those terms and its own matter's. Outside a
    matter: named candidates only. One that a matter holds is listed with that
    matter's name, floor and privilege flag, which a run that reads it takes
    on. The documents the last run in this chat read are always
    listed, and are returned as the suggested selection while they can still be
    read.

    A file that cannot be read is listed with its reason and is not selectable;
    it is never silently omitted (ADR 0038 D5).
    """
    chat = await _owned_chat(runtime, chat_id, user)
    async with runtime.store.sessions() as db:
        project = await _chat_project(db, chat, user)
        if chat.project_id is not None and project is None:
            raise NotFound(message="Project not found")
        previous = await db.scalar(
            select(OrchestrationRoot.planning_snapshot)
            .join(Message, Message.autonomous_session_id == OrchestrationRoot.session_id)
            .where(Message.chat_id == chat.id, OrchestrationRoot.owner_id == user.id)
            .order_by(OrchestrationRoot.created_at.desc())
            .limit(1)
        )
        earlier: list[uuid.UUID] = []
        for entry in (previous or {}).get("documents") or ():
            try:
                earlier.append(uuid.UUID(str(entry["file_id"])))
            except (KeyError, TypeError, ValueError):
                continue
        listed = await list_documents(
            db,
            owner_id=user.id,
            project_id=chat.project_id,
            candidate_file_ids=tuple(dict.fromkeys([*(file_id or ()), *earlier])),
        )
        offered = composer_profile()
        searched, omitted = (
            await list_knowledge_bases(db, owner_id=user.id, project_id=chat.project_id)
            if offered is not None and searches_knowledge(offered)
            else ((), 0)
        )
    selectable = {d.file_id for d in listed if d.selectable}
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
                matters=list(d.matters),
                matter_minimum_inference_tier=d.matter_minimum_inference_tier,
                matter_privileged=d.matter_privileged,
            )
            for d in listed
        ],
        suggested_file_ids=[f for f in earlier if f in selectable][:MAX_SELECTED_DOCUMENTS],
        knowledge_bases=[
            RunKnowledgeBase(knowledge_base_id=k.knowledge_base_id, name=k.name) for k in searched
        ],
        knowledge_bases_omitted=omitted,
    )


@router.post(
    "/{chat_id}/runs",
    response_model=ChatRunRead,
    status_code=202,
    summary="Start a governed run as a turn in this chat",
)
async def start_run(
    chat_id: uuid.UUID, body: ChatRunRequest, user: RunActor, runtime: Service
) -> ChatRunRead:
    """Accept one planning request and write its two messages.

    The request becomes an ordinary user message. The reply is one assistant
    message of kind ``run`` linked to the run's root session; it carries the
    answer once the root delivers one, and stays empty otherwise. Accepting the
    request authorizes one planning call within the disclosed allowance. Child
    work needs the owner's approval of the exact plan on the existing route.

    What the planning call receives is the profile's to say and is in its
    ``planning_notice``: the request only, or the request with the chat's
    recent messages. What it received is kept with the run.

    The chat may be outside any matter where the profile allows it.
    """
    chat = await _owned_chat(runtime, chat_id, user)
    if chat.archived_at is not None:
        raise NotFound(f"Chat {chat_id} not found.", details={"chat_id": str(chat_id)})
    return await begin_run(
        runtime.for_profile(body.profile),
        user=user,
        request_id=body.request_id,
        project_id=chat.project_id,
        goal=body.goal,
        chat_id=chat.id,
        file_ids=tuple(body.file_ids),
    )
