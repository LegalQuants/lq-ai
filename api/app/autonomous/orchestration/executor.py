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
from app.autonomous.orchestration import assembly
from app.autonomous.orchestration.chat_demo import FICTIONAL_PROFILE, contract_qa_outcome
from app.autonomous.orchestration.checkpoints import CheckpointRuntime
from app.autonomous.orchestration.contracts import PreparedPlan
from app.autonomous.orchestration.effects import GuardedEffects
from app.autonomous.orchestration.intake import UnfundedPlan, packet, prepare_model_plan
from app.autonomous.orchestration.loop import run_child_loop
from app.autonomous.orchestration.outcomes import (
    PlanCarriesPlaceholders,
    PlanWrittenAsText,
    TopicOutcome,
    arguments_carry_placeholder,
    cut_to_limit,
    direct_answer,
    general_outcome,
    topic_coverage,
)
from app.autonomous.orchestration.planning import PlanningSnapshot
from app.autonomous.orchestration.policy import OperatorPolicy
from app.autonomous.orchestration.profiles import RunProfile, run_terms
from app.autonomous.orchestration.store import OrchestrationStore, WorkerClaim
from app.autonomous.orchestration.tools import StepNote
from app.autonomous.orchestration.workspace import WorkspaceContent, WorkspaceRef
from app.errors import Conflict, Forbidden, NotFound, ValidationError
from app.graph_types import AsyncStateNode
from app.models.autonomous import AutonomousSession
from app.models.orchestration import OrchestrationRoot as Root
from app.observability_helpers import get_tracer, quiet_span, record_attributes
from app.schemas.autonomous import Phase

_tracer = get_tracer(__name__)


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
    profile: RunProfile | None = None,
) -> Any:
    profile = profile or FICTIONAL_PROFILE

    async def answer_limit() -> int:
        # The run's own terms, frozen at intake, not the profile as it is now.
        view = await store.execution_view(claim)
        return run_terms(profile, view.planning).task_answer_chars

    def wrapped(limit: int) -> Callable[[str, str], TopicOutcome]:
        def answer(content: str, finish_reason: str) -> TopicOutcome:
            # A prompt-pinned profile takes any task; its answer is plain Markdown.
            wrap = general_outcome if profile.prompted else contract_qa_outcome
            return wrap(content, finish_reason, limit=limit)

        return answer

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
            step=StepNote(kind="notes_started"),
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
            step=StepNote(kind="notes_read"),
            params={"name": "notes.md", "revision": 1},
        )
        if notes.outcome == "workspace_refused":
            raise Conflict(message="Working notes are unavailable")
        view = await store.execution_view(claim)
        task = next(c for c in view.plan.children if c.dispatch_id == claim.session_id)
        answer = wrapped(await answer_limit())
        if model_demo and task.turn_limit:
            # ADR 0038 D4: native tool calls within the plan's granted set.
            outcome = await run_child_loop(
                store,
                effects,
                claim,
                profile=profile,
                notes=notes.data["content"],
                answer=answer,
            )
        else:
            inputs = {"operation": "sample_topic", "working_notes": notes.data["content"]}
            if model_demo:
                # A plan approved before tools existed: one call, the packet in
                # the prompt. Kept so such a plan is never run under new rules.
                inputs = {
                    "operation": "answer_contract_question",
                    "document": packet(effects.skills, profile),
                    "question": task.task.question,
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
                step=StepNote(kind="model_turn"),
            )
            try:
                content = result.data.get("content")
                if not isinstance(content, str) or len(content.encode("utf-8")) > 65536:
                    raise ValueError("invalid output")
                if model_demo:
                    outcome = answer(content, result.data.get("finish_reason"))
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
        for key, kind, name, revision, body in (
            (
                "demo:findings:write:v1",
                "findings_saved",
                "findings.json",
                0,
                outcome.model_dump_json(),
            ),
            (
                "demo:notes:update:v1",
                "notes_updated",
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
                step=StepNote(kind=kind),
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
            step=StepNote(kind="findings_read"),
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
            step=StepNote(kind="findings_shared"),
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
    profile: RunProfile | None = None,
) -> Any:
    profile = profile or FICTIONAL_PROFILE

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
        # The run's own terms, frozen at intake, not the profile as it is now.
        limit = run_terms(profile, (await store.execution_view(claim)).planning).answer_chars
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
                step=StepNote(kind="findings_collected"),
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
            inputs: dict[str, Any] = {
                "operation": "synthesize_answers" if model_demo else "sample_synthesis",
                "topics": [topic.model_dump(mode="json") for topic in topics],
            }
            if model_demo and profile.evidence == "citations" and not profile.prompted:
                inputs["citation_contract"] = (
                    "Keep every quotation exactly as the child wrote it, with its marker, in "
                    'the form "quoted words" (Source: [N]). Do not alter, merge or add '
                    "quotations. Each is checked against document N after delivery."
                )
            result = await effects.infer(
                claim,
                effect_key="demo:synthesis:v1",
                phase=Phase.drafting,
                inputs=inputs,
                step=StepNote(kind="synthesis"),
            )
            summary = result.data.get("content")
            if (
                profile.prompted
                and isinstance(summary, str)
                and result.data.get("finish_reason") == "stop"
            ):
                # A complete answer that runs past the limit is kept up to it
                # and marked as cut, rather than discarded with the tasks' work.
                summary = cut_to_limit(summary.strip(), limit)
            if model_demo and (
                result.data.get("finish_reason") != "stop"
                or not isinstance(summary, str)
                or not 1 <= len(summary) <= limit
            ):
                await store.fail_synthesis(claim)
                raise Conflict(message="Model synthesis is incomplete; child work is retained")
            if not isinstance(summary, str) or not 1 <= len(summary) <= limit:
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
        profile: RunProfile | None = None,
    ) -> None:
        self.store, self.effects, self.checkpoints = store, effects, checkpoints
        # A registry profile is always model-backed. Without one, the executor
        # runs the test-only sample graph and accepts only ``demonstration`` roots.
        self.profile = profile or (FICTIONAL_PROFILE if model_demo else None)
        self.model_demo, self.policy = self.profile is not None, policy

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
            expected = self.profile.id if self.profile is not None else "demonstration"
            if root.profile != expected:
                raise Forbidden(message="Executor does not match the retained run profile")
            if session.status != "running":
                return "completed"
            plan = await self.store._stored_plan(db, root)
        with quiet_span(_tracer, "orchestration.run") as span:
            # Identifiers and labels only (ADR 0038 D2): one span per worker
            # invocation, under the trace carried from the request that queued it.
            record_attributes(
                span,
                **{
                    "orchestration.root_id": str(root_id),
                    "orchestration.session_id": str(session_id),
                    "orchestration.profile": expected,
                    "orchestration.role": "root" if root_id == session_id else "child",
                    "orchestration.stage": "planning"
                    if isinstance(plan, PlanningSnapshot)
                    else "execution",
                },
            )
            outcome = await self._run_claimed(root_id, session_id, plan)
            record_attributes(span, **{"orchestration.outcome": outcome})
            return outcome

    async def _run_claimed(
        self, root_id: UUID, session_id: UUID, plan: PreparedPlan | PlanningSnapshot
    ) -> Literal["waiting_children", "completed", "busy", "stopped"]:
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
                    self.store, self.effects, claim, saver, self.model_demo, self.profile
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
        profile = self.profile
        if profile is None or policy is None:
            raise Forbidden(message="Model planning is disabled")
        # For a prompt-pinned profile the opening message is assembled from the
        # intake itself, and the step's name is all this caller supplies.
        inputs: dict[str, Any] = {"operation": assembly.PLAN}
        if profile.prompted:
            return await self._settle_plan(claim, snapshot, profile, policy, inputs)
        if profile.documents == "packet":
            inputs["document"] = packet(self.effects.skills, profile)
            inputs["redaction_handling"] = (
                "Gateway pseudonym tokens represent supplied values, not missing terms. "
                "Ask clause-based questions without guessing redacted values or asking "
                "children to describe supplied values as absent."
            )
        else:
            # The planner sees which documents were selected, not their text.
            inputs["documents"] = [
                {"number": d.number, "filename": d.filename} for d in snapshot.documents
            ]
        if snapshot.contract_version >= 2:
            inputs["max_tasks"] = snapshot.max_children
        return await self._settle_plan(claim, snapshot, profile, policy, inputs)

    async def _settle_plan(
        self,
        claim: WorkerClaim,
        snapshot: PlanningSnapshot,
        profile: RunProfile,
        policy: OperatorPolicy,
        inputs: dict[str, Any],
    ) -> Literal["completed"]:
        """Make the one planning call and promote, deliver or fail its result.

        Where the profile hands its plan over by tool call (ADR 0038 D1), the
        call is offered ``propose_plan`` and nothing else. Exactly one call to
        it is a plan, read from the call's arguments. A complete reply with no
        call is the orchestrator's own answer: it is delivered, and the run
        ends with no plan and no approval. Anything else fails the plan. No
        tool result is ever sent back, so planning stays one model call.
        """
        terms = run_terms(profile, snapshot)
        offered = assembly.planning_tools(profile, snapshot)
        result = await self.effects.infer(
            claim,
            effect_key="chat:plan:v1",
            phase=Phase.analysis,
            intent=ToolIntent.plan,
            inputs=inputs,
            tools=offered or None,
            step=StepNote(kind="planning"),
        )
        plan = answer = None
        failure = "invalid_proposal"
        try:
            content, finish = result.data.get("content"), result.data.get("finish_reason")
            calls = result.data.get("tool_calls") or []
            if offered and calls:
                # More than one call, or a call to anything else, is not a plan.
                if len(calls) != 1 or calls[0].get("name") != assembly.PLAN:
                    raise ValueError("not one call to the plan tool")
                arguments = calls[0].get("arguments") or ""
                accounting = result.data.get("accounting") or {}
                # Anything but a recorded False counts as pseudonymized, so a
                # result without the flag fails closed.
                pseudonymized = accounting.get("anonymization_applied") is not False
                if pseudonymized and arguments_carry_placeholder(arguments):
                    # The gateway was asked to restore this call's arguments.
                    # What is still shaped like a placeholder is one it did not
                    # assign (the model altered or invented it), and no later
                    # call could restore it.
                    raise PlanCarriesPlaceholders("the plan carries a placeholder")
                plan = prepare_model_plan(profile, snapshot, arguments, policy, arguments=True)
            elif offered:
                answer = direct_answer(content, finish, limit=terms.answer_chars)
            else:
                if not isinstance(content, str) or finish != "stop":
                    raise ValueError("incomplete proposal")
                plan = prepare_model_plan(profile, snapshot, content, policy)
        except UnfundedPlan:
            failure = "unfunded_plan"
        except PlanWrittenAsText:
            failure = "plan_not_handed_over"
        except PlanCarriesPlaceholders:
            failure = "plan_has_placeholders"
        except (ValidationError, SchemaError, ValueError):
            pass
        await self.store.finish_planning(claim, plan, failure=failure, answer=answer)
        return "completed"
