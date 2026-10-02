"""Checkpointed root and isolated children for the orchestration demonstration.

An invocation runs one session and releases ownership before returning. The root
interrupts while waiting; arq wakes it after child delivery. Graph state contains
identifiers only. Task text, internal findings and synthesis remain in the
access-controlled application store, with durable guarded effect receipts.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
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

from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.chat_demo import (
    contract_qa_outcome,
    packet,
    prepare_model_plan,
)
from app.autonomous.orchestration.checkpoints import CheckpointRuntime
from app.autonomous.orchestration.effects import GuardedEffects
from app.autonomous.orchestration.outcomes import TopicOutcome, topic_coverage
from app.autonomous.orchestration.planning import PlanningSnapshot
from app.autonomous.orchestration.policy import OperatorPolicy
from app.autonomous.orchestration.store import OrchestrationStore, WorkerClaim
from app.autonomous.orchestration.workspace import WorkspaceContent, WorkspaceRef
from app.errors import Conflict, Forbidden, NotFound, ValidationError
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
    model_demo: bool = False,
) -> Any:
    async def intake(state: RunState) -> dict[str, Any]:
        await store.phase(claim, Phase.intake)
        return {}

    async def prepare_notes(state: RunState) -> dict[str, Any]:
        await store.phase(claim, Phase.analysis)
        view = await store.execution_view(claim)
        topic = next(c.task.topic for c in view.plan.children if c.dispatch_id == claim.session_id)
        saved = await effects.workspace(
            claim,
            effect_key="demo:notes:create:v1",
            phase=Phase.analysis,
            intent=ToolIntent.workspace_write,
            params={
                "name": "notes.md",
                "revision": 0,
                "content": f"Work in progress: {topic}. Findings remain unverified.",
            },
        )
        if saved.outcome == "workspace_refused":
            raise Conflict(message="Working notes could not be saved")
        return {}

    async def analysis(state: RunState) -> dict[str, Any]:
        await store.phase(claim, Phase.analysis)
        notes = await effects.workspace(
            claim,
            effect_key="demo:notes:read:v1",
            phase=Phase.analysis,
            intent=ToolIntent.workspace_read,
            params={"name": "notes.md", "revision": 1},
        )
        if notes.outcome == "workspace_refused":
            raise Conflict(message="Working notes are unavailable")
        inputs = {"operation": "sample_topic", "working_notes": notes.data["content"]}
        if model_demo:
            view = await store.execution_view(claim)
            task = next(c.task for c in view.plan.children if c.dispatch_id == claim.session_id)
            inputs = {
                "operation": "answer_contract_question",
                "document": packet(effects.skills),
                "question": task.question,
                "response_contract": (
                    "Return only the Contract QA answer as Markdown, at most 4096 characters. "
                    "Lead with the answer and preserve clause quotes, citations, and limitations. "
                    "State explicitly when the agreement does not answer a part of the question. "
                    "Do not add a JSON envelope; the application records the outcome and receipt."
                ),
                "redaction_handling": (
                    "Gateway pseudonym tokens stand for supplied values and will be restored "
                    "in the answer. Preserve tokens verbatim in quotations. A pseudonym is not "
                    "a missing contractual term: do not say a number, date or amount is absent "
                    "merely because its value is represented by a token. Do not guess its value."
                ),
            }
        result = await effects.infer(
            claim,
            effect_key="demo:topic:v1",
            phase=Phase.analysis,
            inputs=inputs,
        )
        try:
            content = result.data.get("content")
            if not isinstance(content, str) or len(content.encode("utf-8")) > 65536:
                raise ValueError("invalid output")
            if model_demo:
                outcome = contract_qa_outcome(content, result.data.get("finish_reason"))
            else:
                outcome = TopicOutcome.model_validate_json(content)
                if outcome.artifact is not None:
                    raise ValueError("The application supplies artifact references")
        except (SchemaError, ValueError):
            outcome = TopicOutcome(
                status="failed",
                summary="The topic returned an invalid bounded outcome.",
                findings=(),
                failure_code="invalid_output",
            )
        for key, name, revision, body in (
            ("demo:findings:write:v1", "findings.json", 0, outcome.model_dump_json()),
            (
                "demo:notes:update:v1",
                "notes.md",
                1,
                f"Analysis saved to findings.json. {outcome.summary}",
            ),
        ):
            saved = await effects.workspace(
                claim,
                effect_key=key,
                phase=Phase.analysis,
                intent=ToolIntent.workspace_write,
                params={"name": name, "revision": revision, "content": body},
            )
            if saved.outcome == "workspace_refused":
                raise Conflict(message="Work could not be saved")
        return {}

    async def drafting(state: RunState) -> dict[str, Any]:
        await store.phase(claim, Phase.drafting)
        saved = await effects.workspace(
            claim,
            effect_key="demo:findings:read:v1",
            phase=Phase.drafting,
            intent=ToolIntent.workspace_read,
            params={"name": "findings.json", "revision": 1},
        )
        if saved.outcome == "workspace_refused":
            raise Conflict(message="Findings are unavailable")
        outcome = TopicOutcome.model_validate_json(saved.data["content"])
        shared = await effects.workspace(
            claim,
            effect_key="demo:findings:share:v1",
            phase=Phase.drafting,
            intent=ToolIntent.workspace_share,
            params={"name": "findings.json", "revision": 1},
        )
        if shared.outcome == "workspace_refused":
            raise Conflict(message="Findings could not be shared")
        reference = WorkspaceRef.model_validate_json(
            json.dumps({k: shared.data[k] for k in ("session_id", "name", "revision", "digest")})
        )
        await store.stage_topic(claim, outcome.model_copy(update={"artifact": reference}))
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
        "prepare_notes": prepare_notes,
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
    model_demo: bool = False,
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
        collected = []
        for topic in topics:
            reference = topic.outcome.artifact
            if reference is None:
                raise Conflict(message="Topic has no shared findings file")
            saved = await effects.workspace(
                claim,
                effect_key=f"demo:collect:{topic.session_id}:v1",
                phase=Phase.drafting,
                intent=ToolIntent.workspace_read,
                params={
                    "session_id": str(reference.session_id),
                    "name": reference.name,
                    "revision": reference.revision,
                },
            )
            if saved.outcome == "workspace_refused":
                raise Conflict(message="Shared topic findings are unavailable")
            file = WorkspaceContent.model_validate_json(json.dumps(saved.data))
            outcome = TopicOutcome.model_validate_json(file.content)
            if (
                file.digest != reference.digest
                or not file.shared
                or outcome.model_copy(update={"artifact": reference}) != topic.outcome
            ):
                raise Conflict(message="Shared file differs from delivered topic outcome")
            collected.append(
                topic.model_copy(
                    update={"outcome": outcome.model_copy(update={"artifact": reference})}
                )
            )
        topics = tuple(collected)
        if topic_coverage(topics) == "failed":
            summary = "All demonstration topics failed. No research findings were established."
        else:
            result = await effects.infer(
                claim,
                effect_key="demo:synthesis:v1",
                phase=Phase.drafting,
                inputs={
                    "operation": "synthesize_answers" if model_demo else "sample_synthesis",
                    "topics": [topic.model_dump(mode="json") for topic in topics],
                },
            )
            summary = result.data.get("content")
            if model_demo and (
                result.data.get("finish_reason") != "stop"
                or not isinstance(summary, str)
                or not 1 <= len(summary) <= 16384
            ):
                await store.fail_synthesis(claim)
                raise Conflict(message="Model synthesis is incomplete; child work is retained")
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
        self,
        store: OrchestrationStore,
        effects: GuardedEffects,
        checkpoints: CheckpointRuntime,
        *,
        model_demo: bool = False,
        policy: Callable[[], OperatorPolicy | None] | None = None,
    ) -> None:
        self.store, self.effects, self.checkpoints = store, effects, checkpoints
        self.model_demo, self.policy = model_demo, policy

    async def run_one(
        self, root_id: UUID, session_id: UUID
    ) -> Literal["waiting_children", "completed", "busy", "stopped"]:
        async with self.store.sessions() as db:
            root = await db.get(Root, root_id)
            session = await db.get(AutonomousSession, session_id)
            if root is None or session is None or session.root_session_id != root_id:
                raise NotFound(message="Orchestration session not found")
            if root.status not in {"planning", "queued", "running", "waiting_children"}:
                return "stopped"
            if (root.profile == "model_demo_v1") != self.model_demo:
                raise Forbidden(message="Executor does not match the retained run profile")
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
                if isinstance(plan, PlanningSnapshot):
                    return await self._plan(claim, plan)
                graph = (root_graph if root_id == session_id else child_graph)(
                    self.store, self.effects, claim, saver, self.model_demo
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

    async def _plan(self, claim: WorkerClaim, snapshot: PlanningSnapshot) -> Literal["completed"]:
        """A durable planning effect precedes the approved LangGraph batch."""
        policy = self.policy() if self.policy else None
        if not self.model_demo or policy is None:
            raise Forbidden(message="Model planning is disabled")
        result = await self.effects.infer(
            claim,
            effect_key="chat:plan:v1",
            phase=Phase.analysis,
            intent=ToolIntent.plan,
            inputs={
                "operation": "propose_plan",
                "document": packet(self.effects.skills),
                "redaction_handling": (
                    "Gateway pseudonym tokens represent supplied values, not missing terms. "
                    "Ask clause-based questions without guessing redacted values or asking "
                    "children to describe supplied values as absent."
                ),
            },
        )
        plan = None
        try:
            content = result.data.get("content")
            if not isinstance(content, str) or result.data.get("finish_reason") != "stop":
                raise ValueError("incomplete proposal")
            plan = prepare_model_plan(snapshot, content, policy)
        except (ValidationError, SchemaError, ValueError):
            pass
        await self.store.finish_planning(claim, plan)
        return "completed"
