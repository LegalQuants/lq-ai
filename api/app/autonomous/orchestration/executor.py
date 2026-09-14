"""Checkpointed root and isolated children for the orchestration demonstration.

An invocation runs one session and releases ownership before returning. The root
interrupts while waiting; arq wakes it after child delivery. Graph state contains
identifiers only. Task text, internal findings and synthesis remain in the
access-controlled application store, with durable guarded effect receipts.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import Any, Literal, TypedDict
from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from langsmith import tracing_context
from pydantic import ValidationError as SchemaError

from app.autonomous.orchestration.checkpoints import CheckpointRuntime
from app.autonomous.orchestration.effects import GuardedEffects
from app.autonomous.orchestration.outcomes import TopicOutcome, topic_coverage
from app.autonomous.orchestration.store import OrchestrationStore, WorkerClaim
from app.errors import Conflict, Forbidden, NotFound
from app.graph_types import AsyncStateNode
from app.models.autonomous import AutonomousSession
from app.models.orchestration import OrchestrationRoot as Root
from app.schemas.autonomous import Phase


class RunState(TypedDict):
    session_id: str


def _safe_node(node: AsyncStateNode[RunState]) -> AsyncStateNode[RunState]:
    async def call(state: RunState) -> dict[str, Any]:
        try:
            return await node(state)
        except (Conflict, Forbidden, NotFound, GraphInterrupt):
            raise
        except Exception:
            # Framework pending-error writes must not contain SQL parameters,
            # provider bodies or validation inputs with private task content.
            raise RuntimeError("Orchestration phase interrupted") from None

    return call


def child_graph(
    store: OrchestrationStore,
    effects: GuardedEffects,
    claim: WorkerClaim,
    saver: AsyncPostgresSaver,
) -> Any:
    async def intake(state: RunState) -> dict[str, Any]:
        await store.phase(claim, Phase.intake)
        return {}

    async def analysis(state: RunState) -> dict[str, Any]:
        await store.phase(claim, Phase.analysis)
        result = await effects.infer(
            claim,
            effect_key="demo:topic:v1",
            phase=Phase.analysis,
            inputs={"operation": "sample_topic"},
        )
        try:
            content = result.data.get("content")
            if not isinstance(content, str) or len(content.encode("utf-8")) > 65536:
                raise ValueError("invalid output")
            outcome = TopicOutcome.model_validate_json(content)
        except (SchemaError, ValueError):
            outcome = TopicOutcome(
                status="failed",
                summary="The topic returned an invalid sample outcome.",
                findings=(),
                failure_code="invalid_output",
            )
        await store.stage_topic(claim, outcome)
        return {}

    async def drafting(state: RunState) -> dict[str, Any]:
        await store.phase(claim, Phase.drafting)
        return {}

    async def ethics_review(state: RunState) -> dict[str, Any]:
        # No research-quality verdict is manufactured by traversing this phase.
        await store.phase(claim, Phase.ethics_review)
        return {}

    async def delivery(state: RunState) -> dict[str, Any]:
        await store.phase(claim, Phase.delivery)
        async with store.sessions() as db:
            session = await db.get(AutonomousSession, claim.session_id)
            assert session is not None
            outcome = TopicOutcome.model_validate_json(json.dumps(session.result))
        await store.deliver_topic(claim, failed=outcome.status == "failed")
        return {}

    builder = StateGraph(RunState)
    nodes = {
        "intake": intake,
        "analysis": analysis,
        "drafting": drafting,
        "ethics_review": ethics_review,
        "delivery": delivery,
    }
    for name, node in nodes.items():
        builder.add_node(name, _safe_node(node))
    builder.set_entry_point("intake")
    for first, second in zip(nodes, (*list(nodes)[1:], END), strict=True):
        builder.add_edge(first, second)
    return builder.compile(checkpointer=saver)


def root_graph(
    store: OrchestrationStore,
    effects: GuardedEffects,
    claim: WorkerClaim,
    saver: AsyncPostgresSaver,
) -> Any:
    async def delegate(state: RunState) -> dict[str, Any]:
        await store.phase(claim, Phase.analysis)
        await store.admit_children(claim)
        return {}

    async def collect(state: RunState) -> dict[str, Any]:
        if not await store.wait_for_children(claim):
            interrupt({"reason": "waiting_children", "root_id": str(claim.root_id)})
        # A resume payload is a wakeup hint, never authority or findings.
        await store.collect_topics(claim)
        return {}

    async def synthesize(state: RunState) -> dict[str, Any]:
        await store.phase(claim, Phase.drafting)
        topics = await store.collect_topics(claim)
        if topic_coverage(topics) == "failed":
            summary = "All demonstration topics failed. No research findings were established."
        else:
            result = await effects.infer(
                claim,
                effect_key="demo:synthesis:v1",
                phase=Phase.drafting,
                inputs={
                    "operation": "sample_synthesis",
                    "topics": [topic.model_dump(mode="json") for topic in topics],
                },
            )
            summary = result.data.get("content")
            if not isinstance(summary, str) or not 1 <= len(summary) <= 16384:
                raise Conflict(message="Synthesis output is invalid")
        await store.stage_synthesis(claim, summary)
        return {}

    async def ethics_review(state: RunState) -> dict[str, Any]:
        await store.phase(claim, Phase.ethics_review)
        return {}

    async def delivery(state: RunState) -> dict[str, Any]:
        await store.phase(claim, Phase.delivery)
        await store.deliver_root(claim)
        return {}

    builder = StateGraph(RunState)
    nodes = {
        "delegate": delegate,
        "collect": collect,
        "synthesize": synthesize,
        "ethics_review": ethics_review,
        "delivery": delivery,
    }
    for name, node in nodes.items():
        builder.add_node(name, _safe_node(node))
    builder.set_entry_point("delegate")
    for first, second in zip(nodes, (*list(nodes)[1:], END), strict=True):
        builder.add_edge(first, second)
    return builder.compile(checkpointer=saver)


class OrchestrationExecutor:
    def __init__(
        self, store: OrchestrationStore, effects: GuardedEffects, checkpoints: CheckpointRuntime
    ) -> None:
        self.store, self.effects, self.checkpoints = store, effects, checkpoints

    async def run_one(
        self, root_id: UUID, session_id: UUID
    ) -> Literal["waiting_children", "completed", "busy", "stopped"]:
        async with self.store.sessions() as db:
            root = await db.get(Root, root_id)
            session = await db.get(AutonomousSession, session_id)
            if root is None or session is None or session.root_session_id != root_id:
                raise NotFound(message="Orchestration session not found")
            if root.status not in {"queued", "running", "waiting_children"}:
                return "stopped"
            if session.status != "running":
                return "completed"
            plan = await self.store._stored_plan(db, root)
        async with self.checkpoints.acquire(
            root_id, session_id, root_children=plan.max_active_children
        ) as saver:
            if saver is None:
                return "busy"
            claim = await self.store.claim(
                root_id, session_id, worker_id=uuid4(), seconds=plan.attempt_timeout_seconds
            )
            try:
                graph = (root_graph if root_id == session_id else child_graph)(
                    self.store, self.effects, claim, saver
                )
                config: RunnableConfig = {
                    "configurable": {"thread_id": str(session_id)},
                    "callbacks": [],
                    "recursion_limit": 20,
                }
                # Disable external framework traces regardless of ambient env.
                with tracing_context(enabled=False):
                    snapshot = await graph.aget_state(config)
                    value: Any = {"session_id": str(session_id)} if not snapshot.values else None
                    if any(task.interrupts for task in snapshot.tasks):
                        if not await self.store.wait_for_children(claim):
                            return "waiting_children"
                        value = Command(resume=True)
                    async with asyncio.timeout(plan.attempt_timeout_seconds):
                        result = await graph.ainvoke(value, config, durability="sync")
                return "waiting_children" if result.get("__interrupt__") else "completed"
            finally:
                # The invocation (including saver writes) has stopped before
                # release; advisory locks remain until the saver connection closes.
                # Expired/uncertain claims are drained by the watchdog.
                with suppress(Conflict, Forbidden, NotFound):
                    await self.store.release_claim(claim)
