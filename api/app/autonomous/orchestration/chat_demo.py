"""Closed model-backed demonstration profile and server-built planning inputs."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.contracts import (
    ChildAssignment,
    ExecutionScope,
    PhaseGrants,
    PreparedPlan,
    ResourceScope,
    _unique_object,
    parse_research_proposal,
)
from app.autonomous.orchestration.inference import InferenceRoutes
from app.autonomous.orchestration.planning import PlanningSnapshot
from app.autonomous.orchestration.policy import (
    InferencePolicy,
    OperatorPolicy,
    SkillPolicy,
    skill_pin,
)
from app.config import Settings
from app.errors import Forbidden
from app.skills.registry import MutableSkillRegistry

PROFILE = "model_demo_v1"
ROOT_SKILL = "orchestration-chat-demo"
CHILD_SKILL = "contract-qa"
PACKET = "fictional-agreement-v1"


def model_json(content: str) -> str:
    """Remove one complete JSON presentation fence; never extract or repair data.

    All text must still pass the strict JSON/schema parser. Prose outside the
    fence, extra objects, duplicate keys and extra authority fields are refused.
    """
    if len(content.encode()) > 131072:
        raise ValueError("Model JSON exceeds the input limit")
    value = content.strip()
    if value.startswith("```json\n") and value.endswith("\n```"):
        value = value[8:-4]
    try:
        json.loads(value, object_pairs_hook=_unique_object)
    except (ValueError, TypeError, RecursionError):
        raise ValueError("Invalid bounded model JSON") from None
    return value


def packet(skills: MutableSkillRegistry) -> str:
    """Load a bounded installed fixture; its bytes are included in the root pin."""
    record = skills.current().get(ROOT_SKILL)
    if record is None or record.source != "built-in":
        raise Forbidden(message="Installed demonstration skill is unavailable")
    try:
        content = (record.folder / "reference" / "fictional-agreement.md").read_text("utf-8")
    except (OSError, UnicodeError):
        raise Forbidden(message="Fictional source packet is unavailable") from None
    if not 1 <= len(content.encode()) <= 8192:
        raise Forbidden(message="Fictional source packet exceeds limits")
    return content


def chat_policy(skills: MutableSkillRegistry, settings: Settings) -> OperatorPolicy:
    """Explicit installed skills, no retrieval or optional tools."""
    try:
        UUID(settings.orchestration_chat_project_id)
    except ValueError:
        raise Forbidden(message="Configure a dedicated demo project") from None
    if settings.orchestration_deployment_children is None:
        raise Forbidden(message="Configure shared child capacity")
    grants = PhaseGrants(
        intake=(),
        analysis=(
            ToolIntent.plan,
            ToolIntent.run_skill,
            ToolIntent.workspace_read,
            ToolIntent.workspace_write,
        ),
        drafting=(
            ToolIntent.run_skill,
            ToolIntent.workspace_read,
            ToolIntent.workspace_write,
            ToolIntent.workspace_share,
        ),
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
            raise Forbidden(message="Required installed demonstration skill is unavailable")
        selections.append(
            SkillPolicy(pin=skill_pin(record), profile=profile, grants=grants, source_types=())
        )
    return OperatorPolicy(
        demo_project_id=UUID(settings.orchestration_chat_project_id),
        skills=tuple(selections),
        sources=(),
        grants=grants,
        minimum_inference_tier=settings.orchestration_chat_minimum_tier,
        maximum_egress_tier=0,
        require_anonymization=True,
        deployment_children=settings.orchestration_deployment_children,
        inference=InferencePolicy(
            provider=settings.orchestration_chat_provider,
            native_model=settings.orchestration_chat_model,
            max_input_bytes=98304,
            # Reasoning models count hidden reasoning toward the same ceiling.
            # Keep room for the bounded visible plan/answer without retries.
            max_output_tokens=8192,
        ),
    )


async def prepare_intake(
    *,
    settings: Settings,
    skills: MutableSkillRegistry,
    policy: OperatorPolicy,
    routes: InferenceRoutes,
    root_id: UUID,
    owner_id: UUID,
    project_id: UUID,
    goal: str,
    privileged: bool,
    minimum_inference_tier: int,
) -> PlanningSnapshot:
    """Quote a maximum call allowance before accepting any paid planning."""
    if str(project_id) != settings.orchestration_chat_project_id:
        raise Forbidden(message="Only the configured demo project is enabled")
    root_skill = next(s for s in policy.skills if s.profile == "orchestrator")
    scope = ExecutionScope(
        resources=ResourceScope(document_ids=(), source_names=()),
        grants=PhaseGrants(
            intake=(), analysis=(ToolIntent.plan,), drafting=(), ethics_review=(), delivery=()
        ),
        skill=root_skill.pin,
        minimum_inference_tier=min(minimum_inference_tier, policy.minimum_inference_tier),
        maximum_egress_tier=0,
        privileged=privileged,
        anonymize=True,
    )
    assert policy.inference is not None
    root_record = skills.current().get(ROOT_SKILL)
    child_record = skills.current().get(CHILD_SKILL)
    assert root_record and child_record
    if not root_record.frontmatter.lq_ai.version or not child_record.frontmatter.lq_ai.version:
        raise Forbidden(message="Demo skills require declared versions")
    snapshot = PlanningSnapshot(
        plan_id=uuid4(),
        root_id=root_id,
        owner_id=owner_id,
        project_id=project_id,
        goal=goal,
        policy_version=policy.version(),
        root=scope,
        delegation_grants=policy.grants,
        budget_usd=Decimal(settings.orchestration_chat_budget_usd),
        root_allowance_usd=Decimal("0"),
        planning_allowance_usd=Decimal("0"),
        deadline=datetime.now(UTC) + timedelta(hours=1),
        attempt_timeout_seconds=settings.orchestration_chat_timeout_seconds,
        packet_digest=hashlib.sha256(packet(skills).encode()).hexdigest(),
        gateway_revision="0" * 64,
        model=policy.inference.model_key,
        root_skill_version=root_record.frontmatter.lq_ai.version,
        child_skill_version=child_record.frontmatter.lq_ai.version,
    )
    binding = await routes.bind(
        snapshot,
        scope,
        [
            {"role": "system", "content": "Quote bounded demonstration inference."},
            {"role": "user", "content": "No inference is dispatched by this readiness check."},
        ],
    )
    unit = binding.rates.cost(
        policy.inference.max_input_bytes + 96, policy.inference.max_output_tokens
    )
    if unit * 6 > snapshot.budget_usd:
        raise Forbidden(message="Demo budget cannot fund planning, four children and synthesis")
    return snapshot.model_copy(
        update={
            "root_allowance_usd": unit * 2,
            "planning_allowance_usd": unit,
            "gateway_revision": binding.gateway_revision,
        }
    )


def prepare_model_plan(
    snapshot: PlanningSnapshot, content: str, policy: OperatorPolicy
) -> PreparedPlan:
    """Model output supplies questions only; all executable choices are server-owned."""
    proposal = parse_research_proposal(model_json(content))
    child = next(s for s in policy.skills if s.profile == "research")
    scope = snapshot.root.model_copy(update={"grants": policy.grants})
    return PreparedPlan(
        contract_version=2,
        planning_digest=snapshot.approval_hash(),
        plan_id=snapshot.plan_id,
        root_id=snapshot.root_id,
        owner_id=snapshot.owner_id,
        project_id=snapshot.project_id,
        revision=1,
        goal=snapshot.goal,
        policy_version=snapshot.policy_version,
        root=scope,
        delegation_grants=policy.grants,
        children=tuple(
            ChildAssignment(
                dispatch_id=uuid4(),
                profile="research",
                task=task,
                execution=scope.model_copy(update={"skill": child.pin}),
                budget_usd=snapshot.planning_allowance_usd,
            )
            for task in proposal.tasks
        ),
        budget_usd=snapshot.budget_usd,
        root_allowance_usd=snapshot.root_allowance_usd,
        max_active_children=snapshot.max_active_children,
        deadline=snapshot.deadline,
        attempt_timeout_seconds=snapshot.attempt_timeout_seconds,
    )
