"""Closed demonstration intake, explicit consent and owner-only tree inspection."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.dependencies import ActiveUser, AutonomousEnabledUser
from app.autonomous.orchestration.chat_demo import PACKET, PROFILE, packet, prepare_intake
from app.autonomous.orchestration.contracts import Digest, ShortText, TaskText
from app.autonomous.orchestration.demo import prepare_demo_plan
from app.autonomous.orchestration.service import DemonstrationService
from app.autonomous.orchestration.views import (
    ChatRunRead,
    TreeRead,
    read_chat_run,
    read_tree,
    read_workspace_file,
)
from app.autonomous.orchestration.workspace import WorkspaceContent
from app.config import get_settings
from app.db.session import get_session_factory
from app.errors import Conflict, NotFound
from app.models.orchestration import OrchestrationRoot
from app.models.project import Project
from app.workers.queue import enqueue_orchestration_job

router = APIRouter(prefix="/autonomous/orchestration", tags=["autonomous"])


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


@router.get("/chat-runs", response_model=ChatCapabilities, response_model_exclude_none=True)
async def chat_capabilities(user: ActiveUser, runtime: Service) -> dict:
    model = runtime.for_profile(PROFILE)
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
        "title": "Contract Questions Orchestrator",
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
        "planning_notice": "Propose plan authorizes one model call within the displayed total cap. Child work requires separate approval.",
    }


@router.post("/chat-runs", response_model=ChatRunRead, status_code=202)
async def start_chat(
    body: ChatPlanRequest, user: AutonomousEnabledUser, runtime: Service
) -> ChatRunRead:
    model = runtime.for_profile(PROFILE)
    policy = model.require_policy()
    async with model.store.sessions() as db:
        previous = await db.get(OrchestrationRoot, body.request_id)
        if previous is not None:
            # Owner-only read before comparing input or exposing any state.
            retained = await read_chat_run(model.store.sessions, body.request_id, user.id)
            if (
                retained.planning.goal != body.goal
                or retained.planning.project_id != body.project_id
            ):
                raise Conflict(message="Request identity was reused with different input")
            return retained
        project = await db.scalar(
            select(Project).where(
                Project.id == body.project_id,
                Project.owner_id == user.id,
                Project.archived_at.is_(None),
            )
        )
        if project is None:
            raise NotFound(message="Project not found")
        privileged, tier = project.privileged, project.minimum_inference_tier or 5
    routes = model.effects().inference
    assert routes is not None
    snapshot = await prepare_intake(
        settings=model.settings,
        skills=model.skills,
        policy=policy,
        routes=routes,
        root_id=body.request_id,
        owner_id=user.id,
        project_id=body.project_id,
        goal=body.goal,
        privileged=privileged,
        minimum_inference_tier=tier,
    )
    await model.store.start_planning(snapshot, actor_id=user.id)
    await enqueue_orchestration_job(snapshot.root_id, snapshot.root_id)
    return await read_chat_run(model.store.sessions, snapshot.root_id, user.id)


@router.get("/chat-runs/{root_id}", response_model=ChatRunRead)
async def chat_run(root_id: UUID, user: ActiveUser, runtime: Service) -> ChatRunRead:
    return await read_chat_run(runtime.store.sessions, root_id, user.id)


@router.post("/chat-runs/{root_id}/halt", response_model=ChatRunRead)
async def halt_chat(root_id: UUID, user: ActiveUser, runtime: Service) -> ChatRunRead:
    await read_chat_run(runtime.store.sessions, root_id, user.id)
    await runtime.store.halt(root_id, actor_id=user.id)
    return await read_chat_run(runtime.store.sessions, root_id, user.id)


class DemoPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    goal: TaskText
    topics: Annotated[list[ShortText], Field(min_length=1, max_length=4)]
    max_active_children: Annotated[int, Field(strict=True, ge=1, le=4)] = 2


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: Annotated[int, Field(strict=True, ge=1)]
    plan_hash: Digest


class RejectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: Annotated[int, Field(strict=True, ge=1)]


class DemoCapabilities(BaseModel):
    enabled: bool
    deployment_children: int | None
    max_topics: int = 4
    live_providers: bool = False


@router.get("/capabilities", response_model=DemoCapabilities)
async def capabilities(user: ActiveUser, runtime: Service) -> DemoCapabilities:
    policy = runtime.policy()
    return DemoCapabilities(
        enabled=policy is not None,
        deployment_children=policy.deployment_children if policy else None,
    )


@router.post("/plans", response_model=TreeRead, status_code=201)
async def prepare_plan(
    body: DemoPlanRequest, user: AutonomousEnabledUser, runtime: Service
) -> TreeRead:
    policy = runtime.require_policy()
    async with runtime.store.sessions() as db:
        project = await db.scalar(
            select(Project).where(
                Project.id == body.project_id,
                Project.owner_id == user.id,
                Project.archived_at.is_(None),
            )
        )
        if project is None:
            raise NotFound(message="Project not found")
        plan = prepare_demo_plan(
            policy=policy,
            owner_id=user.id,
            project_id=project.id,
            goal=body.goal,
            topics=tuple(body.topics),
            now=datetime.now(UTC),
            privileged=project.privileged,
            minimum_inference_tier=project.minimum_inference_tier or 5,
            max_active_children=body.max_active_children,
        )
    await runtime.store.save_plan(plan, actor_id=user.id, create_session=True)
    return await read_tree(runtime.store.sessions, plan.root_id, user.id)


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
    await runtime.store.halt(root_id, actor_id=user.id)
    return await read_tree(runtime.store.sessions, root_id, user.id)
