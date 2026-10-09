"""Governed run intake, consent, closing and owner-only tree inspection.

Approval, rejection, halt, closing and inspection all live here and are the only
governance path for a run, wherever it was started (ADR 0016 P6). The chat
surface in :mod:`app.api.chat_runs` adds intake and availability reads and
reuses :func:`begin_run`.
"""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.dependencies import (
    ActiveUser,
    AdminUser,
    RunActor,
    is_privileged_reader,
)
from app.auditor_audit import auditor_audit
from app.autonomous.orchestration.assembly import planning_message, planning_tools
from app.autonomous.orchestration.chat_demo import PACKET, PROFILE, packet
from app.autonomous.orchestration.contracts import (
    Digest,
    DocumentRef,
    KnowledgeBaseRef,
    TaskText,
)
from app.autonomous.orchestration.inference import conversation_identity, identity_limit
from app.autonomous.orchestration.intake import (
    ensure_packet_document,
    list_knowledge_bases,
    packet as profile_packet,
    prepare_intake,
    searches_knowledge,
    select_documents,
    thread_excerpt,
)
from app.autonomous.orchestration.planning import ThreadMessage
from app.autonomous.orchestration.profiles import registered_profiles
from app.autonomous.orchestration.prompts import load_prompt
from app.autonomous.orchestration.reading import NO_FLOOR, MatterTerms, selection_terms
from app.autonomous.orchestration.service import DemonstrationService
from app.autonomous.orchestration.tools import get_tool
from app.autonomous.orchestration.trace import SessionTraceRead, read_session_trace
from app.autonomous.orchestration.views import (
    ChatRunRead,
    ToolRead,
    TreeRead,
    read_chat_run,
    read_tree,
    read_workspace_file,
)
from app.autonomous.orchestration.workspace import WorkspaceContent
from app.config import get_settings
from app.db.session import get_session_factory
from app.errors import Conflict, Forbidden, LQAIError, NotFound, ValidationError
from app.models.orchestration import OrchestrationRoot
from app.models.project import Project
from app.models.user import User
from app.schemas.autonomous import Phase
from app.workers.queue import enqueue_orchestration_job

router = APIRouter(prefix="/autonomous/orchestration", tags=["autonomous"])
admin_router = APIRouter(prefix="/admin/orchestration", tags=["admin"])


def service(request: Request) -> DemonstrationService:
    return DemonstrationService(
        get_settings(), request.app.state.skill_registry, get_session_factory()
    )


Service = Annotated[DemonstrationService, Depends(service)]


class ChatPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    project_id: UUID
    goal: TaskText
    profile: Literal["model_demo_v1"] = "model_demo_v1"
    packet_id: Literal["fictional-agreement-v1"] = "fictional-agreement-v1"


class ChatCapabilities(BaseModel):
    enabled: bool
    profile: Literal["model_demo_v1"] | None = None
    title: str | None = None
    project_id: UUID | None = None
    project_name: str | None = None
    packet_id: str | None = None
    packet: str | None = None
    model: str | None = None
    budget_usd: Decimal | None = None
    planning_allowance_usd: Decimal | None = None
    root_allowance_usd: Decimal | None = None
    child_skill: str | None = None
    deployment_children: int | None = None
    attempt_timeout_seconds: int | None = None
    planning_notice: str | None = None


async def _chat_read(runtime: DemonstrationService, root_id: UUID, owner_id: UUID) -> ChatRunRead:
    """Attach the exact current fixture only when it matches this run's pin."""
    value = await read_chat_run(runtime.store.sessions, root_id, owner_id)
    if value.planning.packet_digest is None:
        return value
    try:
        source = packet(runtime.skills)
    except Forbidden:
        return value
    if hashlib.sha256(source.encode()).hexdigest() != value.planning.packet_digest:
        return value
    return value.model_copy(update={"packet": source})


async def owner_for_read(
    runtime: DemonstrationService,
    root_id: UUID,
    user: User,
    *,
    event: Literal["run_viewed", "run_trace_viewed"],
    request: Request,
) -> UUID:
    """Whose run this is, for a caller who may read it (ADR 0038, ruling 10).

    The owner reads their own run. An admin or an auditor
    (``is_privileged_reader``) may read another owner's run and how its
    sessions were set up, and each such read writes one ``auditor`` audit
    row before anything is returned. For anyone else, and for a run that
    does not exist, the caller's own id is returned: the read then applies
    its owner filter and answers 404 for both alike.

    This is for reads only. Approval, rejection, halt, closing and a run's
    working files stay with the owner.
    """
    async with runtime.store.sessions() as db:
        owner_id: UUID | None = await db.scalar(
            select(OrchestrationRoot.owner_id).where(OrchestrationRoot.session_id == root_id)
        )
        if owner_id is None or owner_id == user.id or not is_privileged_reader(user):
            return user.id
        await auditor_audit(
            db,
            user=user,
            event=event,
            resource_type="autonomous_session",
            resource_id=str(root_id),
            viewed_user_id=owner_id,
            request=request,
        )
        await db.commit()  # a read path: persist the audit row explicitly
        return owner_id


async def begin_run(
    runtime: DemonstrationService,
    *,
    user: User,
    request_id: UUID,
    project_id: UUID | None,
    goal: str,
    chat_id: UUID | None = None,
    file_ids: tuple[UUID, ...] = (),
) -> ChatRunRead:
    """Accept one planning request for ``runtime``'s profile; idempotent on its id.

    Shared by the chat intake and the retained stand-alone route, so both run
    the same checks: the profile's operator switch, an owned active project the
    profile permits (or none, for a profile that allows a chat outside any
    matter), a priced route, a funded allowance, and the store's one-active-run
    rule. Planning is queued only after the root is durable.

    Outside a matter the run has no terms of its own. It takes on the
    strictest terms of the matters that hold its selected documents: the
    lowest floor any of them sets, and privileged if any of them is (ADR 0038
    D5, ruling 4). With no document, or none from a matter, it is not
    privileged and its floor is the profile's own.
    """
    profile = runtime.run_profile
    policy = runtime.require_policy()
    async with runtime.store.sessions() as db:
        previous = await db.get(OrchestrationRoot, request_id)
        if previous is not None:
            # Owner-only read before comparing input or exposing any state.
            retained = await _chat_read(runtime, request_id, user.id)
            # A packet profile's document is the installed packet, not a selection.
            selects = profile.documents in ("selected", "optional")
            if (
                retained.planning.goal != goal
                or retained.planning.project_id != project_id
                or retained.chat_id != chat_id
                or retained.profile != profile.id
                or (selects and [d.file_id for d in retained.planning.documents] != list(file_ids))
            ):
                raise Conflict(message="Request identity was reused with different input")
            return retained
        privileged, tier = False, 5
        if project_id is not None:
            project = await db.scalar(
                select(Project).where(
                    Project.id == project_id,
                    Project.owner_id == user.id,
                    Project.archived_at.is_(None),
                )
            )
            if project is None:
                raise NotFound(message="Project not found")
            privileged, tier = project.privileged, project.minimum_inference_tier or 5
        elif profile.project_scope != "any":
            raise Forbidden(message="This run profile starts from a chat inside a matter")
        documents: tuple[DocumentRef, ...] = ()
        attach: tuple[UUID, ...] = ()
        if profile.documents == "packet":
            if file_ids:
                raise ValidationError(message="This profile reads a fixed document")
        else:
            if not file_ids and profile.documents == "selected":
                raise ValidationError(message="Select at least one document for this run")
            documents, attach = await select_documents(
                db, owner_id=user.id, project_id=project_id, file_ids=file_ids
            )
            if project_id is None:
                # The store works these out again at every admission and
                # holds the run to them.
                terms = await selection_terms(db, [d.document_id for d in documents])
                privileged, tier = terms.privileged, terms.minimum_inference_tier
        # Read once, here, and frozen in the intake: a replayed planning call
        # must see exactly the thread the first attempt saw.
        # An earlier answer written under stricter terms than this run's is not
        # shown to its planning call: the call goes out on this run's terms.
        thread: tuple[ThreadMessage, ...] = (
            await thread_excerpt(
                db,
                chat_id=chat_id,
                terms=MatterTerms(
                    minimum_inference_tier=min(tier, policy.minimum_inference_tier),
                    privileged=privileged,
                ),
            )
            if profile.reads_thread and chat_id is not None
            else ()
        )
        # The matter's knowledge bases as they are now. The plan names them,
        # and each search rechecks that one is still attached.
        knowledge_bases: tuple[KnowledgeBaseRef, ...] = ()
        if searches_knowledge(profile):
            knowledge_bases, _ = await list_knowledge_bases(
                db, owner_id=user.id, project_id=project_id
            )
    today = datetime.now(UTC).date().isoformat()
    routes = runtime.effects().inference
    assert routes is not None
    # Quote first, so a route that cannot be priced never files a document.
    from_matters = project_id is None and (privileged or tier < NO_FLOOR)
    try:
        await prepare_intake(
            profile,
            settings=runtime.settings,
            skills=runtime.skills,
            policy=policy,
            routes=routes,
            root_id=request_id,
            owner_id=user.id,
            project_id=project_id,
            goal=goal,
            privileged=privileged,
            minimum_inference_tier=tier,
            today=today,
        )
    except Forbidden:
        if not from_matters:
            raise
        # Quote again as the chat alone would be quoted. If that is refused
        # too, the route is unavailable whatever is selected, and that refusal
        # is the one to give. If it is accepted, the selected documents'
        # matters are the reason.
        await prepare_intake(
            profile,
            settings=runtime.settings,
            skills=runtime.skills,
            policy=policy,
            routes=routes,
            root_id=request_id,
            owner_id=user.id,
            project_id=None,
            goal=goal,
            privileged=False,
            minimum_inference_tier=NO_FLOOR,
            today=today,
        )
        raise Forbidden(
            message=(
                "A selected document belongs to a matter whose inference tier floor "
                "or privilege setting this run's route does not meet."
            ),
            details={"minimum_inference_tier": tier, "privileged": privileged},
        ) from None
    if profile.documents == "packet":
        assert project_id is not None  # a packet profile is limited to one matter
        documents = (
            await ensure_packet_document(
                runtime.store.sessions,
                owner_id=user.id,
                project_id=project_id,
                text=profile_packet(runtime.skills, profile),
            ),
        )
    snapshot = await prepare_intake(
        profile,
        settings=runtime.settings,
        skills=runtime.skills,
        policy=policy,
        routes=routes,
        root_id=request_id,
        owner_id=user.id,
        project_id=project_id,
        goal=goal,
        privileged=privileged,
        minimum_inference_tier=tier,
        documents=documents,
        thread=thread,
        today=today,
        knowledge_bases=knowledge_bases,
    )
    if profile.prompted and policy.inference is not None:
        # Refuse here, before anything is stored, a request whose planning call
        # could not be sent. Found later it would leave a run in planning that
        # nothing can advance, holding the owner's one active-run allowance.
        # Counted as the route binding counts it: both messages and, where the
        # plan is handed over by tool call, that tool's schema.
        pinned = load_prompt(profile.root_prompt)
        try:
            _, size = conversation_identity(
                [
                    {"role": "system", "content": pinned.text},
                    {"role": "user", "content": planning_message(profile, snapshot)},
                ],
                planning_tools(profile, snapshot) or None,
                max_bytes=identity_limit(policy.inference),
            )
        except LQAIError:
            size = policy.inference.max_input_bytes + 1
        if size > policy.inference.max_input_bytes:
            raise ValidationError(
                message="The request and this chat's recent messages are too long for one planning call"
            )
    await runtime.store.start_planning(
        snapshot,
        actor_id=user.id,
        profile=profile.id,
        chat_id=chat_id,
        attach_file_ids=attach,
    )
    await enqueue_orchestration_job(snapshot.root_id, snapshot.root_id)
    return await _chat_read(runtime, snapshot.root_id, user.id)


@router.get("/chat-runs", response_model=ChatCapabilities, response_model_exclude_none=True)
async def chat_capabilities(user: ActiveUser, runtime: Service) -> dict:
    model = runtime.for_profile(PROFILE)
    # A switched-on but incomplete configuration is refused here, as in 0.8.0,
    # so the operator sees the missing setting rather than "disabled".
    policy = model.policy()
    if policy is None:
        return {"enabled": False}
    async with model.store.sessions() as db:
        project = await db.scalar(
            select(Project).where(
                Project.id == UUID(model.settings.orchestration_chat_project_id),
                Project.owner_id == user.id,
                Project.archived_at.is_(None),
            )
        )
    if project is None:
        return {"enabled": False}
    routes = model.effects().inference
    assert routes is not None
    quote = await prepare_intake(
        model.run_profile,
        settings=model.settings,
        skills=model.skills,
        policy=policy,
        routes=routes,
        root_id=uuid4(),
        owner_id=user.id,
        project_id=project.id,
        goal="Readiness quote",
        privileged=project.privileged,
        minimum_inference_tier=project.minimum_inference_tier or 5,
    )
    assert policy.inference is not None
    return {
        "enabled": True,
        "profile": PROFILE,
        "title": model.run_profile.title,
        "project_id": str(project.id),
        "project_name": project.name,
        "packet_id": PACKET,
        "packet": packet(model.skills),
        "model": policy.inference.model_key,
        "budget_usd": model.settings.orchestration_chat_budget_usd,
        "planning_allowance_usd": str(quote.planning_allowance_usd),
        "root_allowance_usd": str(quote.root_allowance_usd),
        "child_skill": "contract-qa",
        "deployment_children": policy.deployment_children,
        "attempt_timeout_seconds": quote.attempt_timeout_seconds,
        "planning_notice": model.run_profile.planning_notice,
    }


@router.post("/chat-runs", response_model=ChatRunRead, status_code=202)
async def start_chat(body: ChatPlanRequest, user: RunActor, runtime: Service) -> ChatRunRead:
    """Start a fictional-profile run with no chat. Retained for existing clients.

    New runs start from a chat (``POST /chats/{chat_id}/runs``). A run started
    here has no message; its page remains its receipt view (ADR 0038 D1).
    """
    return await begin_run(
        runtime.for_profile(PROFILE),
        user=user,
        request_id=body.request_id,
        project_id=body.project_id,
        goal=body.goal,
    )


@router.get("/chat-runs/{root_id}", response_model=ChatRunRead)
async def chat_run(
    root_id: UUID, user: ActiveUser, runtime: Service, request: Request
) -> ChatRunRead:
    """A run as its owner sees it: the request, the plan, each step and the answer.

    The owner, or an admin or auditor reading another owner's run; that
    read writes one ``auditor.run_viewed`` audit row.
    """
    owner_id = await owner_for_read(runtime, root_id, user, event="run_viewed", request=request)
    return await _chat_read(runtime, root_id, owner_id)


@router.post("/chat-runs/{root_id}/halt", response_model=ChatRunRead)
async def halt_chat(root_id: UUID, user: ActiveUser, runtime: Service) -> ChatRunRead:
    await read_chat_run(runtime.store.sessions, root_id, user.id)
    await runtime.store.halt(root_id, actor_id=user.id)
    return await _chat_read(runtime, root_id, user.id)


@router.post("/chat-runs/{root_id}/close", response_model=ChatRunRead)
async def close_chat(root_id: UUID, user: ActiveUser, runtime: Service) -> ChatRunRead:
    """Close an uncertain run without a retry (ADR 0038 D6).

    Owner-only. Nothing is repeated: each unresolved effect is closed without an
    outcome and its reservation is charged. Retained work stays readable, and
    the owner's single active-run allowance is released. Like halt, this stays
    reachable after opt-out or a switched-off profile: it only narrows authority.
    """
    await read_chat_run(runtime.store.sessions, root_id, user.id)
    await runtime.store.close_uncertain(root_id, actor_id=user.id)
    return await _chat_read(runtime, root_id, user.id)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: Annotated[int, Field(strict=True, ge=1)]
    plan_hash: Digest


class RejectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: Annotated[int, Field(strict=True, ge=1)]


class PromptRead(BaseModel):
    """One of the engine's own versioned prompt files (ADR 0038 D3)."""

    name: str
    family: str
    role: str
    version: int
    digest: Digest
    text: str


@router.get("/prompts/{family}/{name}", response_model=PromptRead)
async def prompt(family: str, name: str, user: ActiveUser) -> PromptRead:
    """The text of one engine prompt, for example ``new_harness/orchestrator.v1``.

    Any signed-in user may read it, before sending anything: a prompt is open
    work product, like a skill (PRD §1.3). A released file is never edited, so
    a name and its digest always give the same text.
    """
    try:
        loaded = load_prompt(f"{family}/{name}")
    except Forbidden:
        raise NotFound(message="Prompt not found") from None
    return PromptRead(
        name=loaded.pin.name,
        family=loaded.family,
        role=loaded.role,
        version=loaded.version,
        digest=loaded.pin.digest,
        text=loaded.text,
    )


@router.get("/{root_id}/tree", response_model=TreeRead)
async def tree(root_id: UUID, user: ActiveUser, runtime: Service, request: Request) -> TreeRead:
    """A run's approved plan and its sessions.

    The owner, or an admin or auditor reading another owner's run; that
    read writes one ``auditor.run_viewed`` audit row.
    """
    owner_id = await owner_for_read(runtime, root_id, user, event="run_viewed", request=request)
    return await read_tree(runtime.store.sessions, root_id, owner_id)


@router.get("/{root_id}/sessions/{session_id}/trace", response_model=SessionTraceRead)
async def session_trace(
    root_id: UUID, session_id: UUID, user: ActiveUser, runtime: Service, request: Request
) -> SessionTraceRead:
    """How one session of a run was set up, and what its model wrote back.

    The owner, or an admin or auditor reading another owner's run; that read
    writes one ``auditor.run_trace_viewed`` audit row (ADR 0038, ruling 10).
    ``session_id`` is the run's root for the orchestrator, or one
    task's dispatch id. Gives the pinned system message, the opening message,
    the tools offered, and each turn's text and tool calls. See
    :mod:`app.autonomous.orchestration.trace` for what is rebuilt, how it is
    checked against what was sent, and what is not kept.
    """
    owner_id = await owner_for_read(
        runtime, root_id, user, event="run_trace_viewed", request=request
    )
    return await read_session_trace(
        runtime.store.sessions, runtime.skills.current(), root_id, owner_id, session_id
    )


@router.post("/{root_id}/approve", response_model=TreeRead)
async def approve(
    root_id: UUID, body: ApprovalRequest, user: RunActor, runtime: Service
) -> TreeRead:
    retained = await read_tree(runtime.store.sessions, root_id, user.id)
    runtime = runtime.for_profile(retained.mode)
    runtime.require_policy()
    await runtime.store.approve(
        root_id, actor_id=user.id, revision=body.revision, plan_hash=body.plan_hash
    )
    # Approval is durable before wakeup. The recovery sweep repairs a lost queue write.
    await enqueue_orchestration_job(root_id, root_id)
    return await read_tree(runtime.store.sessions, root_id, user.id)


@router.get("/{root_id}/files/{session_id}/{name}", response_model=WorkspaceContent)
async def workspace_file(
    root_id: UUID, session_id: UUID, name: str, user: ActiveUser, runtime: Service
) -> WorkspaceContent:
    """One of a run's working files. Owner-only: an admin or auditor is not given it."""
    return await read_workspace_file(runtime.store.sessions, root_id, user.id, session_id, name)


@router.post("/{root_id}/reject", response_model=TreeRead)
async def reject(
    root_id: UUID, body: RejectionRequest, user: RunActor, runtime: Service
) -> TreeRead:
    await read_tree(runtime.store.sessions, root_id, user.id)
    await runtime.store.reject(root_id, actor_id=user.id, revision=body.revision)
    return await read_tree(runtime.store.sessions, root_id, user.id)


@router.post("/{root_id}/halt", response_model=TreeRead)
async def halt(root_id: UUID, user: ActiveUser, runtime: Service) -> TreeRead:
    await read_tree(runtime.store.sessions, root_id, user.id)
    await runtime.store.halt(root_id, actor_id=user.id)
    return await read_tree(runtime.store.sessions, root_id, user.id)


# --- Operator view of the registry (ADR 0038 D3; ADR 0016 P2, P8) -------------


class ProfileState(BaseModel):
    """One registry profile as the operator has configured it."""

    profile: str
    title: str
    summary: str
    reads: str
    enabled: bool
    # Set when the switch is on but the profile cannot run as configured.
    problem: str | None = None
    switch: str
    # Whether the chat composer offers this profile, as the New harness model.
    composer: bool = False
    documents: Literal["packet", "selected", "optional"]
    project_scope: Literal["dedicated", "owned", "any"]
    evidence: Literal["unverified", "citations"]
    # The installed skills that instruct each role, or the engine prompt files
    # that do (ADR 0038 D3). A profile sets one pair and leaves the other empty.
    root_skill: str
    child_skill: str
    root_prompt: str = ""
    child_prompt: str = ""
    # "required": refused unless the gateway pseudonymizes on the route.
    # "operator": follows the gateway's setting for the routed tier.
    pseudonymization: Literal["required", "operator"] = "required"
    reasoning_effort: str | None = None
    provider: str | None = None
    model: str | None = None
    budget_usd: Decimal | None = None
    minimum_inference_tier: int | None = None
    attempt_timeout_seconds: int | None = None
    tools: list[ToolRead]
    limits: dict[str, Any]


class ProfileRegistryRead(BaseModel):
    profiles: list[ProfileState]
    deployment_children: int | None


@admin_router.get("/profiles", response_model=ProfileRegistryRead)
async def list_profiles(admin: AdminUser, runtime: Service) -> ProfileRegistryRead:
    """The closed set of run profiles and each one's operator state.

    Read-only. Profiles are switched on and routed through deployment
    configuration; this route reports what that configuration yields.
    """
    states = []
    for profile in registered_profiles():
        route = profile.route(runtime.settings)
        problem = None
        if route.enabled:
            try:
                runtime.for_profile(profile.id).require_policy()
            except Forbidden as exc:
                problem = exc.message
        states.append(
            ProfileState(
                profile=profile.id,
                title=profile.title,
                summary=profile.summary,
                reads=profile.reads,
                enabled=route.enabled and problem is None,
                problem=problem,
                switch=profile.switch,
                composer=profile.composer,
                documents=profile.documents,
                project_scope=profile.project_scope,
                evidence=profile.evidence,
                root_skill=profile.root_skill,
                child_skill=profile.child_skill,
                root_prompt=profile.root_prompt,
                child_prompt=profile.child_prompt,
                pseudonymization=profile.pseudonymization,
                reasoning_effort=route.reasoning_effort,
                provider=route.provider or None,
                model=route.model or None,
                budget_usd=route.budget_usd,
                minimum_inference_tier=route.minimum_tier,
                attempt_timeout_seconds=route.timeout_seconds,
                tools=[
                    ToolRead(
                        name=name,
                        label=tool.label if (tool := get_tool(name)) else name,
                        phase=phase.value,
                        registered=tool is not None,
                    )
                    for phase in Phase
                    for name in profile.child_tools.for_phase(phase)
                ],
                limits={
                    "max_input_bytes": profile.limits.max_input_bytes,
                    "max_output_tokens": profile.limits.max_output_tokens,
                    "child_answer_chars": profile.limits.child_answer_chars,
                    "combined_answer_chars": profile.limits.combined_answer_chars,
                    "deadline_seconds": profile.limits.deadline_seconds,
                    "child_turn_limit": profile.limits.child_turn_limit,
                    "document_read_chars": profile.limits.document_read_chars,
                    "max_active_children": profile.limits.max_active_children,
                },
            )
        )
    return ProfileRegistryRead(
        profiles=states, deployment_children=runtime.settings.orchestration_deployment_children
    )
