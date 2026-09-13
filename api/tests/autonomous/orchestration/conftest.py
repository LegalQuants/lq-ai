"""Committed Postgres fixtures: independent transactions and actual row races."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.contracts import (
    ChildAssignment,
    ExecutionScope,
    PhaseGrants,
    PreparedPlan,
    ResearchTask,
    ResourceScope,
    SkillPin,
)
from app.autonomous.orchestration.store import OrchestrationStore
from app.errors import Forbidden
from app.models.autonomous import AutonomousSession
from app.models.project import Project
from app.models.user import User


class FixturePolicy:
    """Explicit policy stub; production resource resolution is a later W4 gate."""

    valid = True

    async def __call__(self, db, plan):
        assert db.in_transaction()
        if not self.valid:
            raise Forbidden(message="Fixture policy revoked")


@pytest_asyncio.fixture
async def env(test_engine):
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory.begin() as db:
        owner = User(
            email=f"durable-{uuid4()}@example.com",
            hashed_password="unused-test",
            autonomous_enabled=True,
        )
        db.add(owner)
        await db.flush()
        project = Project(owner_id=owner.id, name="Fixture", slug=f"fixture-{uuid4()}")
        db.add(project)
        await db.flush()
        session = AutonomousSession(
            user_id=owner.id,
            project_id=project.id,
            trigger_kind="manual",
            current_phase="analysis",
            max_cost_usd=Decimal("10"),
        )
        db.add(session)
        await db.flush()
        root_id, owner_id, project_id = session.id, owner.id, project.id
    grants = PhaseGrants(
        intake=(ToolIntent.retrieve_chunks,),
        analysis=(ToolIntent.run_skill,),
        drafting=(ToolIntent.emit_finding,),
        ethics_review=(ToolIntent.emit_finding,),
        delivery=(),
    )
    scope = ExecutionScope(
        resources=ResourceScope(document_ids=(), source_names=()),
        grants=grants,
        skill=SkillPin(name="fixture-skill", digest="a" * 64),
        minimum_inference_tier=1,
        maximum_egress_tier=0,
        privileged=False,
        anonymize=True,
    )
    task = ResearchTask(
        topic="Fixture",
        question="Exercise governance",
        boundaries="No external providers",
        output_contract="Empty result",
        stopping_condition="Two steps",
    )
    plan = PreparedPlan(
        plan_id=uuid4(),
        revision=1,
        root_id=root_id,
        project_id=project_id,
        owner_id=owner_id,
        goal="Fixture",
        policy_version="fixture-policy-1",
        root=scope,
        delegation_grants=grants,
        children=tuple(
            ChildAssignment(
                dispatch_id=uuid4(),
                profile="research",
                task=task,
                execution=scope,
                budget_usd=Decimal("2"),
            )
            for _ in range(2)
        ),
        budget_usd=Decimal("10"),
        root_allowance_usd=Decimal("2"),
        max_active_children=2,
        deadline=datetime.now(UTC) + timedelta(hours=1),
        attempt_timeout_seconds=60,
    )
    policy = FixturePolicy()
    store = OrchestrationStore(factory, check_policy=policy)
    try:
        yield SimpleNamespace(
            store=store,
            factory=factory,
            plan=plan,
            policy=policy,
            root_id=root_id,
            owner_id=owner_id,
            project_id=project_id,
        )
    finally:
        async with factory.begin() as db:
            await db.execute(delete(AutonomousSession).where(AutonomousSession.user_id == owner_id))
            await db.execute(delete(Project).where(Project.owner_id == owner_id))
            await db.execute(delete(User).where(User.id == owner_id))


@pytest_asyncio.fixture
async def ready(env):
    await env.store.save_plan(env.plan, actor_id=env.owner_id)
    await env.store.approve(
        env.root_id, actor_id=env.owner_id, revision=1, plan_hash=env.plan.approval_hash()
    )
    env.claim = await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)
    return env
