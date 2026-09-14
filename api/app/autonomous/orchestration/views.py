"""Owner-scoped plan, progress and receipts, readable after opt-out or halt."""

import json
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.autonomous.orchestration.contracts import PreparedPlan
from app.autonomous.orchestration.outcomes import DemonstrationResult, TopicOutcome
from app.errors import NotFound
from app.models.autonomous import AutonomousSession
from app.models.orchestration import (
    OrchestrationAccount as Account,
    OrchestrationEffect as Effect,
    OrchestrationPlan as PlanRow,
    OrchestrationRoot as Root,
)
from app.schemas.autonomous import Phase


class EffectRead(BaseModel):
    effect_key: str
    status: str
    reserved_usd: Decimal
    charged_usd: Decimal | None


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


class TreeRead(BaseModel):
    root_id: UUID
    status: str
    stop_reason: str | None
    plan: PreparedPlan
    plan_hash: str
    approved: bool
    mode: Literal["demonstration"] = "demonstration"
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
                    effects=[
                        EffectRead(
                            effect_key=e.effect_key,
                            status=e.status,
                            reserved_usd=e.reserved_usd,
                            charged_usd=e.charged_usd,
                        )
                        for e in receipts
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
        if root.status in {"halted", "expired", "uncertain", "rejected"}:
            partial = (
                "Orchestration demonstration stopped. Sample findings are unverified.\n\n"
                + "\n".join(
                    f"{child.task.topic}: {run.outcome.summary if run.outcome else 'No delivered outcome.'}"
                    for child, run in zip(plan.children, runs[1:], strict=True)
                )
            )
        return TreeRead(
            root_id=root_id,
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
