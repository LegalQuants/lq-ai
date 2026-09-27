"""Owner-scoped plan, progress and receipts, readable after opt-out or halt."""

import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.autonomous.orchestration.contracts import PreparedPlan
from app.autonomous.orchestration.outcomes import DemonstrationResult, TopicOutcome
from app.autonomous.orchestration.planning import PlanningSnapshot
from app.autonomous.orchestration.workspace import (
    WorkspaceContent,
    WorkspaceFileRead,
    file_metadata,
)
from app.errors import Conflict, NotFound
from app.models.autonomous import AutonomousSession
from app.models.orchestration import (
    OrchestrationAccount as Account,
    OrchestrationEffect as Effect,
    OrchestrationFile,
    OrchestrationPlan as PlanRow,
    OrchestrationRoot as Root,
)
from app.schemas.autonomous import Phase


class EffectRead(BaseModel):
    effect_key: str
    status: str
    reserved_usd: Decimal
    charged_usd: Decimal | None
    intent: str = ""
    created_at: datetime | None = None
    completed_at: datetime | None = None
    skill: dict[str, str] | None = None
    accounting: dict[str, Any] | None = None


class RunRead(BaseModel):
    session_id: UUID
    status: str
    phase: Phase
    allocation_usd: Decimal
    spent_usd: Decimal
    reserved_usd: Decimal
    updated_at: datetime | None
    outcome: TopicOutcome | None = None
    effects: list[EffectRead]
    files: list[WorkspaceFileRead] = []


class TreeRead(BaseModel):
    root_id: UUID
    status: str
    stop_reason: str | None
    plan: PreparedPlan
    plan_hash: str
    approved: bool
    mode: Literal["demonstration", "model_demo_v1"] = "demonstration"
    verification: Literal["unverified"] = "unverified"
    root: RunRead
    children: list[RunRead]
    spent_usd: Decimal
    reserved_usd: Decimal
    result: DemonstrationResult | None
    partial_summary: str | None


async def read_tree(
    sessions: async_sessionmaker[AsyncSession], root_id: UUID, actor_id: UUID
) -> TreeRead:
    async with sessions() as db:
        root = await db.scalar(
            select(Root).where(Root.session_id == root_id, Root.owner_id == actor_id)
        )
        if root is None:
            raise NotFound(message="Orchestration root not found")
        if root.current_revision is None:
            raise Conflict(message="The model is still preparing a plan; use the chat run view")
        row = await db.get(PlanRow, (root_id, root.current_revision))
        assert row is not None
        plan = PreparedPlan.model_validate_json(json.dumps(row.snapshot))
        runs = []
        # Approved plan order includes children that have not yet been admitted.
        for session_id, allocation in (
            (root_id, plan.root_allowance_usd),
            *((child.dispatch_id, child.budget_usd) for child in plan.children),
        ):
            session = await db.get(AutonomousSession, session_id)
            account = await db.get(Account, session_id)
            receipts = list(
                await db.scalars(
                    select(Effect)
                    .where(Effect.session_id == session_id)
                    .order_by(Effect.created_at, Effect.effect_key)
                )
            )
            runs.append(
                RunRead(
                    session_id=session_id,
                    status=(
                        session.status
                        if session.status != "running"
                        else "stopped"
                        if root.status in {"uncertain", "halted", "expired", "rejected"}
                        else "running"
                        if account and account.worker_id
                        else "queued"
                    )
                    if session
                    else "pending",
                    phase=Phase(session.current_phase) if session else Phase.intake,
                    allocation_usd=allocation,
                    spent_usd=account.spent_usd if account else Decimal("0"),
                    reserved_usd=account.reserved_usd if account else Decimal("0"),
                    updated_at=session.last_activity_at if session else None,
                    outcome=TopicOutcome.model_validate_json(json.dumps(session.result))
                    if session and session.result and session_id != root_id
                    else None,
                    effects=[effect_read(e) for e in receipts],
                    files=[
                        file_metadata(file)
                        for file in await db.scalars(
                            select(OrchestrationFile)
                            .where(OrchestrationFile.session_id == session_id)
                            .order_by(OrchestrationFile.name)
                            .limit(8)
                        )
                    ],
                )
            )
        root_session = await db.get(AutonomousSession, root_id)
        assert root_session is not None
        result = (
            DemonstrationResult.model_validate_json(json.dumps(root_session.result))
            if root_session.result
            else None
        )
        partial = None
        if root.status in {"halted", "expired", "uncertain", "rejected", "failed"} and not result:
            partial = (
                "Orchestration demonstration stopped. Findings are unverified.\n\n"
                + "\n".join(
                    f"{child.task.topic}: {run.outcome.summary if run.outcome else 'No delivered outcome.'}"
                    for child, run in zip(plan.children, runs[1:], strict=True)
                )
            )
        return TreeRead(
            root_id=root_id,
            mode="model_demo_v1" if root.profile == "model_demo_v1" else "demonstration",
            status=root.status,
            stop_reason=root.stop_reason,
            plan=plan,
            plan_hash=row.plan_hash,
            approved=row.status == "approved",
            root=runs[0],
            children=runs[1:],
            spent_usd=sum((run.spent_usd for run in runs), Decimal("0")),
            reserved_usd=sum((run.reserved_usd for run in runs), Decimal("0")),
            result=result,
            partial_summary=partial,
        )


async def read_workspace_file(
    sessions: async_sessionmaker[AsyncSession],
    root_id: UUID,
    actor_id: UUID,
    session_id: UUID,
    name: str,
) -> WorkspaceContent:
    """Owner receipt access includes private WIP after execution stops."""
    async with sessions() as db:
        row = await db.scalar(
            select(OrchestrationFile)
            .join(Account)
            .join(Root)
            .where(
                Root.session_id == root_id,
                Root.owner_id == actor_id,
                Account.session_id == session_id,
                OrchestrationFile.name == name,
            )
        )
        if row is None:
            raise NotFound(message="Workspace file not found")
        return WorkspaceContent(**file_metadata(row).model_dump(), content=row.content)


def effect_read(effect: Effect) -> EffectRead:
    """Expose only safe provenance, never raw provider responses or prompts."""
    data = (effect.result or {}).get("data", {})
    return EffectRead(
        effect_key=effect.effect_key,
        status=effect.status,
        intent=effect.intent,
        reserved_usd=effect.reserved_usd,
        charged_usd=effect.charged_usd,
        created_at=effect.created_at,
        completed_at=effect.completed_at,
        skill=data.get("skill"),
        accounting=data.get("accounting"),
    )


class ChatRunRead(BaseModel):
    root_id: UUID
    status: str
    stop_reason: str | None
    planning: PlanningSnapshot
    effects: list[EffectRead]
    spent_usd: Decimal
    reserved_usd: Decimal
    tree: TreeRead | None


async def read_chat_run(
    sessions: async_sessionmaker[AsyncSession], root_id: UUID, actor_id: UUID
) -> ChatRunRead:
    """Owner-only durable conversation, including pre-plan terminal outcomes."""
    async with sessions() as db:
        root = await db.scalar(
            select(Root).where(
                Root.session_id == root_id,
                Root.owner_id == actor_id,
                Root.profile == "model_demo_v1",
            )
        )
        if root is None:
            raise NotFound(message="Orchestration chat not found")
        snapshot = PlanningSnapshot.model_validate_json(json.dumps(root.planning_snapshot))
        account = await db.get(Account, root_id)
        assert account is not None
        effects = [
            effect_read(e)
            for e in await db.scalars(
                select(Effect).where(Effect.session_id == root_id).order_by(Effect.created_at)
            )
        ]
        revision, status, reason = root.current_revision, root.status, root.stop_reason
        spent, reserved = account.spent_usd, account.reserved_usd
    tree = await read_tree(sessions, root_id, actor_id) if revision else None
    return ChatRunRead(
        root_id=root_id,
        status=tree.status if tree else status,
        stop_reason=tree.stop_reason if tree else reason,
        planning=snapshot,
        effects=effects,
        spent_usd=tree.spent_usd if tree else spent,
        reserved_usd=tree.reserved_usd if tree else reserved,
        tree=tree,
    )
