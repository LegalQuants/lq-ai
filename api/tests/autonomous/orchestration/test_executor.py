"""The complete demonstration with real approvals, guards, checkpoints and joins."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text

from app.autonomous.orchestration.checkpoints import CheckpointRuntime
from app.autonomous.orchestration.demo import (
    SampleGateway,
    demo_effects,
    demonstration_policy,
    prepare_demo_plan,
)
from app.autonomous.orchestration.executor import OrchestrationExecutor
from app.autonomous.orchestration.outcomes import DemonstrationResult, TopicOutcome
from app.autonomous.orchestration.policy import CurrentPolicy
from app.autonomous.orchestration.store import OrchestrationStore
from app.errors import Conflict
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.orchestration import (
    OrchestrationAccount as Account,
    OrchestrationAdmission as Admission,
    OrchestrationEffect as Effect,
    OrchestrationRoot as Root,
)
from app.skills.loader import load_registry
from app.skills.registry import MutableSkillRegistry


class ControlledSampleGateway(SampleGateway):
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.requests = []
        self.active = self.peak = 0
        self.wait_for = 2
        self.outcomes = {}

    async def chat_completion(self, request):
        self.requests.append(request)
        payload = json.loads(request.messages[1].content)
        if payload["inputs"]["operation"] == "sample_topic":
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.active >= self.wait_for:
                self.entered.set()
            try:
                await self.release.wait()
                response = await super().chat_completion(request)
                outcome = self.outcomes.get(payload["task"]["topic"])
                if outcome is not None:
                    response.choices[0].message.content = outcome
                return response
            finally:
                self.active -= 1
        return await super().chat_completion(request)


@pytest_asyncio.fixture
async def demonstration(env, test_db_url):
    env.skills = MutableSkillRegistry(load_registry(Path(__file__).resolve().parents[4] / "skills"))
    env.policy = demonstration_policy(env.skills, deployment_children=2)
    env.store = OrchestrationStore(
        env.factory,
        check_policy=CurrentPolicy(
            skills=env.skills,
            operator=lambda: env.policy,
        ),
    )
    env.plan = prepare_demo_plan(
        policy=env.policy,
        owner_id=env.owner_id,
        project_id=env.project_id,
        goal="Demonstrate an approved workflow",
        topics=("Scope", "Findings", "Open questions"),
        now=datetime.now(UTC),
        privileged=False,
        minimum_inference_tier=1,
    ).model_copy(update={"root_id": env.root_id})
    env.gateway = ControlledSampleGateway()
    env.checkpoints = CheckpointRuntime(test_db_url, deployment_children=2)
    await env.checkpoints.setup()
    env.effects = demo_effects(env.store, env.skills, env.gateway)
    env.executor = OrchestrationExecutor(env.store, env.effects, env.checkpoints)
    await env.store.save_plan(env.plan, actor_id=env.owner_id)
    env.children = tuple(child.dispatch_id for child in env.plan.children)
    return env


async def approve(env):
    await env.store.approve(
        env.root_id, actor_id=env.owner_id, revision=1, plan_hash=env.plan.approval_hash()
    )


async def finish(env):
    for child in env.children:
        await env.executor.run_one(env.root_id, child)
    await env.executor.run_one(env.root_id, env.root_id)
    async with env.factory() as db:
        root = await db.get(Root, env.root_id)
        session = await db.get(AutonomousSession, env.root_id)
        return root.status, DemonstrationResult.model_validate_json(json.dumps(session.result))


async def test_approved_plan_overlaps_children_collects_and_synthesizes(demonstration):
    env = demonstration
    assert await env.executor.run_one(env.root_id, env.root_id) == "stopped"
    async with env.factory() as db:
        assert not await db.scalar(select(Admission.session_id))
    assert not env.gateway.requests
    await approve(env)
    assert await env.executor.run_one(env.root_id, env.root_id) == "waiting_children"
    async with env.factory() as db:
        account = await db.get(Account, env.root_id)
        assert account.worker_id is None
    env.gateway.release.clear()
    async with asyncio.TaskGroup() as group:
        first = group.create_task(env.executor.run_one(env.root_id, env.children[0]))
        second = group.create_task(env.executor.run_one(env.root_id, env.children[1]))
        try:
            await asyncio.wait_for(env.gateway.entered.wait(), 5)
            assert env.gateway.peak == 2
            assert await env.executor.run_one(env.root_id, env.children[2]) == "busy"
            assert await env.executor.run_one(env.root_id, env.children[0]) == "busy"
            assert await env.executor.run_one(env.root_id, env.root_id) == "waiting_children"
            async with env.factory() as db:
                sessions = list(
                    await db.scalars(
                        select(AutonomousSession).where(
                            AutonomousSession.parent_session_id == env.root_id
                        )
                    )
                )
                assert sum(session.current_phase == "analysis" for session in sessions) == 2
        finally:
            env.gateway.release.set()
    assert first.result() == second.result() == "completed"
    status, result = await finish(env)
    assert status == "completed" and result.coverage == "complete"
    assert result.verification == "unverified"
    assert len(result.topics) == 3 and all(
        t.outcome.verification == "unverified" for t in result.topics
    )
    assert len(env.gateway.requests) == 4  # Three children, one root synthesis.
    assert await env.executor.run_one(env.root_id, env.root_id) == "stopped"
    async with env.factory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Effect)
                .where(
                    Effect.session_id.in_((env.root_id, *env.children)),
                    Effect.intent == "run_skill",
                )
            )
            == 4
        )
        accounts = list(await db.scalars(select(Account).where(Account.root_id == env.root_id)))
        assert all(a.spent_usd == a.reserved_usd == 0 and a.worker_id is None for a in accounts)
        events = list(
            await db.scalars(
                select(AuditLog.details).where(AuditLog.resource_id == str(env.root_id))
            )
        )
        assert all("Demonstrate an approved workflow" not in json.dumps(event) for event in events)


@pytest.mark.parametrize(
    "case,coverage,status,requests",
    [
        ("empty", "empty", "completed", 4),
        ("partial", "partial", "completed", 4),
        ("failed", "failed", "failed", 3),
    ],
)
async def test_empty_and_ordinary_failed_topics_are_honest(
    demonstration, case, coverage, status, requests
):
    env = demonstration
    empty = TopicOutcome(
        status="empty", summary="No sample findings.", findings=()
    ).model_dump_json()
    env.gateway.outcomes = {
        child.task.topic: empty if case == "empty" else "malformed" for child in env.plan.children
    }
    if case == "partial":
        env.gateway.outcomes.pop("Scope")
    await approve(env)
    await env.executor.run_one(env.root_id, env.root_id)
    actual_status, result = await finish(env)
    assert actual_status == status and result.coverage == coverage
    assert len(env.gateway.requests) == requests
    assert result.verification == "unverified"


async def test_halt_blocks_join_and_synthesis_but_retains_finished_child(demonstration):
    env = demonstration
    await approve(env)
    await env.executor.run_one(env.root_id, env.root_id)
    await env.executor.run_one(env.root_id, env.children[0])
    await env.store.halt(env.root_id, actor_id=env.owner_id)
    assert await env.executor.run_one(env.root_id, env.children[1]) == "stopped"
    assert await env.executor.run_one(env.root_id, env.root_id) == "stopped"
    assert len(env.gateway.requests) == 1
    async with env.factory() as db:
        assert (await db.get(AutonomousSession, env.children[0])).result["status"] == "completed"


async def test_fresh_executor_resumes_durable_join_without_repeating_children(demonstration):
    env = demonstration
    await approve(env)
    await env.executor.run_one(env.root_id, env.root_id)
    await env.executor.run_one(env.root_id, env.children[0])
    env.executor = OrchestrationExecutor(
        env.store,
        demo_effects(env.store, env.skills, env.gateway),
        CheckpointRuntime(env.checkpoints.url, deployment_children=2),
    )
    status, result = await finish(env)
    assert status == "completed" and len(result.topics) == 3
    assert len(env.gateway.requests) == 4


async def test_uncheckpointed_topic_reuses_receipt_and_session_delete_cascades(
    demonstration, monkeypatch
):
    env = demonstration
    await approve(env)
    await env.executor.run_one(env.root_id, env.root_id)
    original = env.store.stage_topic
    fail = True

    async def stage(claim, outcome):
        nonlocal fail
        await original(claim, outcome)
        if fail:
            fail = False
            raise RuntimeError("private provider content must not enter framework error rows")

    monkeypatch.setattr(env.store, "stage_topic", stage)
    with pytest.raises(RuntimeError, match="Orchestration phase interrupted"):
        await env.executor.run_one(env.root_id, env.children[0])
    assert len(env.gateway.requests) == 1
    await env.executor.run_one(env.root_id, env.children[0])
    assert len(env.gateway.requests) == 1
    await finish(env)
    async with env.factory.begin() as db:
        assert (
            await db.scalar(text("SELECT count(*) FROM orchestration_checkpoints.checkpoints")) > 0
        )
        await db.execute(delete(AutonomousSession).where(AutonomousSession.id == env.root_id))
        for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            assert (
                await db.scalar(text(f"SELECT count(*) FROM orchestration_checkpoints.{table}"))
                == 0
            )


async def test_lost_checkpoint_connection_keeps_durable_capacity_until_old_attempt_stops(
    demonstration, monkeypatch
):
    env = demonstration
    env.store.deployment_children = 1
    await approve(env)
    await env.executor.run_one(env.root_id, env.root_id)
    acquire = env.checkpoints.acquire
    connections = []

    @asynccontextmanager
    async def capture(root_id, session_id, **kwargs):
        async with acquire(root_id, session_id, **kwargs) as saver:
            if saver and session_id == env.children[0]:
                connections.append(saver.conn)
            yield saver

    monkeypatch.setattr(env.checkpoints, "acquire", capture)
    env.gateway.wait_for = 1
    env.gateway.release.clear()
    attempt = asyncio.create_task(env.executor.run_one(env.root_id, env.children[0]))
    try:
        await asyncio.wait_for(env.gateway.entered.wait(), 5)
        await connections[0].close()
        # The PostgreSQL advisory slots are gone, but the durable claim and
        # pending effect still occupy the deployment slot until resolved.
        with pytest.raises(Conflict, match="capacity"):
            await env.executor.run_one(env.root_id, env.children[1])
        assert len(env.gateway.requests) == 1
    finally:
        env.gateway.release.set()
        result = await asyncio.gather(attempt, return_exceptions=True)
    assert isinstance(result[0], Exception)
    status, _ = await finish(env)
    assert status == "completed" and len(env.gateway.requests) == 4
