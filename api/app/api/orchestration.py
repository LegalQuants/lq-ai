"""Governed run intake, consent, closing and owner-only tree inspection.

Approval, rejection, halt, closing and inspection all live here and are the only
governance path for a run, wherever it was started (ADR 0016 P6). The chat
surface in :mod:`app.api.chat_runs` adds intake and availability reads and
reuses :func:`begin_run`.
"""

import hashlib
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.dependencies import ActiveUser, AdminUser, AutonomousEnabledUser
from app.autonomous.orchestration.chat_demo import PACKET, PROFILE, packet
from app.autonomous.orchestration.contracts import Digest, DocumentRef, TaskText
from app.autonomous.orchestration.intake import (
    ensure_packet_document,
    packet as profile_packet,
    prepare_intake,
    select_documents,
)
from app.autonomous.orchestration.profiles import registered_profiles
from app.autonomous.orchestration.service import DemonstrationService
from app.autonomous.orchestration.tools import get_tool
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
from app.errors import Conflict, Forbidden, NotFound, ValidationError
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


async def begin_run(
    runtime: DemonstrationService,
    *,
    user: User,
    request_id: UUID,
    project_id: UUID,
    goal: str,
    chat_id: UUID | None = None,
    file_ids: tuple[UUID, ...] = (),
) -> ChatRunRead:
    """Accept one planning request for ``runtime``'s profile; idempotent on its id.

    Shared by the chat intake and the retained stand-alone route, so both run
    the same checks: the profile's operator switch, an owned active project the
    profile permits, a priced route, a funded allowance, and the store's
    one-active-run rule. Planning is queued only after the root is durable.
    """
    profile = runtime.run_profile
    policy = runtime.require_policy()
    async with runtime.store.sessions() as db:
        previous = await db.get(OrchestrationRoot, request_id)
        if previous is not None:
            # Owner-only read before comparing input or exposing any state.
            retained = await _chat_read(runtime, request_id, user.id)
            if (
                retained.planning.goal != goal
                or retained.planning.project_id != project_id
                or retained.chat_id != chat_id
                or retained.profile != profile.id
            ):
                raise Conflict(message="Request identity was reused with different input")
            return retained
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
        documents: tuple[DocumentRef, ...] = ()
        attach: tuple[UUID, ...] = ()
        if profile.documents == "selected":
            if not file_ids:
                raise ValidationError(message="Select at least one document for this run")
            documents, attach = await select_documents(
                db, owner_id=user.id, project_id=project_id, file_ids=file_ids
            )
        elif file_ids:
            raise ValidationError(message="This profile reads a fixed document")
    routes = runtime.effects().inference
    assert routes is not None
    # Quote first, so a route that cannot be priced never files a document.
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
    )
    if profile.documents == "packet":
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
async def start_chat(
    body: ChatPlanRequest, user: AutonomousEnabledUser, runtime: Service
) -> ChatRunRead:
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
async def chat_run(root_id: UUID, user: ActiveUser, runtime: Service) -> ChatRunRead:
    return await _chat_read(runtime, root_id, user.id)


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


@router.get("/{root_id}/tree", response_model=TreeRead)
async def tree(root_id: UUID, user: ActiveUser, runtime: Service) -> TreeRead:
    return await read_tree(runtime.store.sessions, root_id, user.id)


@router.post("/{root_id}/approve", response_model=TreeRead)
async def approve(
    root_id: UUID, body: ApprovalRequest, user: AutonomousEnabledUser, runtime: Service
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
    return await read_workspace_file(runtime.store.sessions, root_id, user.id, session_id, name)


@router.post("/{root_id}/reject", response_model=TreeRead)
async def reject(
    root_id: UUID, body: RejectionRequest, user: AutonomousEnabledUser, runtime: Service
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
    documents: Literal["packet", "selected"]
    project_scope: Literal["dedicated", "owned"]
    evidence: Literal["unverified", "citations"]
    root_skill: str
    child_skill: str
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
