"""Explicit local sample provider and plan builder; no network/provider fallback.

The demonstration is a technical workflow, not a research product. The provider
consumes the actual pinned skill request through GuardedEffects and returns
synthetic outcomes. It cannot retrieve documents, contact sources or incur fees.
Live inference/source bindings remain separate and are not enabled here.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.contracts import (
    ChildAssignment,
    ExecutionScope,
    PhaseGrants,
    PreparedPlan,
    ResearchTask,
    ResourceScope,
)
from app.autonomous.orchestration.effects import CostQuote, GuardedEffects
from app.autonomous.orchestration.outcomes import CollectedTopic, TopicOutcome
from app.autonomous.orchestration.policy import (
    OperatorPolicy,
    SkillPolicy,
    skill_pin,
)
from app.autonomous.orchestration.store import OrchestrationStore
from app.errors import Forbidden
from app.schemas.gateway import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
)
from app.skills.registry import MutableSkillRegistry

ROOT_SKILL = "orchestrator-harness"
CHILD_SKILL = "orchestration-topic-demo"
DEMO_MODEL = "local/orchestration-sample-v1"


def demonstration_policy(
    skills: MutableSkillRegistry, *, deployment_children: int
) -> OperatorPolicy:
    grants = PhaseGrants(
        intake=(),
        analysis=(ToolIntent.run_skill,),
        drafting=(ToolIntent.run_skill,),
        ethics_review=(),
        delivery=(),
    )
    selections = []
    profiles: tuple[tuple[str, Literal["orchestrator", "research"]], ...] = (
        (ROOT_SKILL, "orchestrator"),
        (CHILD_SKILL, "research"),
    )
    for name, profile in profiles:
        record = skills.current().get(name)
        if record is None or record.source != "built-in":
            raise Forbidden(message="Built-in demonstration skills are unavailable")
        selections.append(
            SkillPolicy(pin=skill_pin(record), profile=profile, grants=grants, source_types=())
        )
    return OperatorPolicy(
        skills=tuple(selections),
        sources=(),
        grants=grants,
        minimum_inference_tier=1,
        maximum_egress_tier=0,
        require_anonymization=False,
        deployment_children=deployment_children,
    )


def prepare_demo_plan(
    *,
    policy: OperatorPolicy,
    owner_id: UUID,
    project_id: UUID,
    goal: str,
    topics: tuple[str, ...],
    now: datetime,
    privileged: bool,
    minimum_inference_tier: int,
    max_active_children: int = 2,
) -> PreparedPlan:
    """Deterministic zero-cost planning; server alone selects executable scope."""
    root_skill = next(s for s in policy.skills if s.profile == "orchestrator")
    child_skill = next(s for s in policy.skills if s.profile == "research")
    scope = ExecutionScope(
        resources=ResourceScope(document_ids=(), source_names=()),
        grants=policy.grants,
        skill=root_skill.pin,
        minimum_inference_tier=min(1, minimum_inference_tier),
        maximum_egress_tier=0,
        privileged=privileged,
        anonymize=False,
    )
    return PreparedPlan(
        plan_id=uuid4(),
        revision=1,
        root_id=uuid4(),
        owner_id=owner_id,
        project_id=project_id,
        goal=goal,
        policy_version=policy.version(),
        root=scope,
        delegation_grants=policy.grants,
        children=tuple(
            ChildAssignment(
                dispatch_id=uuid4(),
                profile="research",
                execution=scope.model_copy(update={"skill": child_skill.pin}),
                task=ResearchTask(
                    topic=topic,
                    question=f"Demonstrate a bounded sample outcome for {topic}.",
                    boundaries="Synthetic demonstration only; no live sources or legal conclusions.",
                    output_contract="A bounded sample summary and findings, explicitly unverified.",
                    stopping_condition="Return one sample topic outcome, then stop.",
                ),
                budget_usd=Decimal("0"),
            )
            for topic in topics
        ),
        budget_usd=Decimal("0"),
        root_allowance_usd=Decimal("0"),
        max_active_children=max_active_children,
        deadline=now + timedelta(hours=1),
        attempt_timeout_seconds=60,
    )


class SampleGateway:
    """Fixed sample responses for this closed demo model; never performs I/O."""

    delay_seconds = 0.0

    def __init__(self, *, delay_seconds: float = 0.0) -> None:
        self.delay_seconds = delay_seconds

    async def chat_completion(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        # A short local pause makes actual parallel progress observable in the
        # demonstration UI. Test subclasses use zero delay and explicit barriers.
        await asyncio.sleep(self.delay_seconds)
        if request.model != DEMO_MODEL or len(request.messages) != 2:
            raise Forbidden(message="Only the local orchestration sample model is supported")
        payload = json.loads(request.messages[1].content or "{}")
        operation = payload["inputs"]["operation"]
        if operation == "sample_topic":
            task = ResearchTask.model_validate_json(json.dumps(payload["task"]))
            content = TopicOutcome(
                status="completed",
                summary=f"Sample outcome for {task.topic}.",
                findings=(f"This sample demonstrates independent work on {task.topic}.",),
            ).model_dump_json()
        elif operation == "sample_synthesis":
            topics = tuple(
                CollectedTopic.model_validate_json(json.dumps(item))
                for item in payload["inputs"]["topics"]
            )
            content = "Orchestration demonstration — sample findings, unverified.\n\n" + "\n".join(
                f"- {topic.topic}: {topic.outcome.status}. {topic.outcome.summary}"
                for topic in topics
            )
        else:
            raise Forbidden(message="Unsupported demonstration operation")
        return ChatCompletionResponse(
            id="local-orchestration-sample",
            created=0,
            model=DEMO_MODEL,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionMessage(role="assistant", content=content),
                    finish_reason="stop",
                )
            ],
            usage=ChatCompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


def demo_effects(
    store: OrchestrationStore, skills: MutableSkillRegistry, gateway: SampleGateway | None = None
) -> GuardedEffects:
    return GuardedEffects(
        store,
        skills=skills,
        gateway=gateway if gateway is not None else SampleGateway(delay_seconds=2),
        quote=lambda intent, params, scope: CostQuote(
            amount_usd=Decimal("0"), pricing_version="local-sample-free-v1"
        ),
        model=DEMO_MODEL,
        max_tokens=4096,
    )
