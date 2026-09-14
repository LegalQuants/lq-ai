"""Closed demonstration intake, explicit consent and owner-only tree inspection."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.dependencies import ActiveUser, AutonomousEnabledUser
from app.autonomous.orchestration.contracts import Digest, ShortText, TaskText
from app.autonomous.orchestration.demo import prepare_demo_plan
from app.autonomous.orchestration.service import DemonstrationService
from app.autonomous.orchestration.views import TreeRead, read_tree, read_workspace_file
from app.autonomous.orchestration.workspace import WorkspaceContent
from app.config import get_settings
from app.db.session import get_session_factory
from app.errors import NotFound
from app.models.project import Project
from app.workers.queue import enqueue_orchestration_job

router = APIRouter(prefix="/autonomous/orchestration", tags=["autonomous"])


def service(request: Request) -> DemonstrationService:
    return DemonstrationService(
        get_settings(), request.app.state.skill_registry, get_session_factory()
    )


Service = Annotated[DemonstrationService, Depends(service)]


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
    runtime.require_policy()
    await read_tree(runtime.store.sessions, root_id, user.id)
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
