"""The fictional Contract QA profile: the first run profile registry entry.

Release 0.8.0 shipped this profile as constants on its own page. It is now an
entry in the registry (ADR 0038 D3), hosted in the main chat (D1), and its
children read the fictional agreement through the document tool (D4) instead of
receiving it in their prompt.
"""

from typing import Any
from uuid import UUID

from app.autonomous.orchestration import intake
from app.autonomous.orchestration.contracts import PhaseTools, PreparedPlan
from app.autonomous.orchestration.inference import InferenceRoutes
from app.autonomous.orchestration.intake import model_json
from app.autonomous.orchestration.outcomes import TopicOutcome
from app.autonomous.orchestration.planning import PlanningSnapshot
from app.autonomous.orchestration.policy import OperatorPolicy
from app.autonomous.orchestration.profiles import (
    RouteSettings,
    RunLimits,
    RunProfile,
    register_profile,
)
from app.config import Settings
from app.skills.registry import MutableSkillRegistry

PROFILE = "model_demo_v1"
ROOT_SKILL = "orchestration-chat-demo"
CHILD_SKILL = "contract-qa"
PACKET = "fictional-agreement-v1"

__all__ = [
    "CHILD_SKILL",
    "FICTIONAL_PROFILE",
    "PACKET",
    "PROFILE",
    "ROOT_SKILL",
    "contract_qa_outcome",
    "model_json",
    "packet",
    "prepare_intake",
    "prepare_model_plan",
]


def _route(settings: Settings) -> RouteSettings:
    return RouteSettings(
        enabled=settings.orchestration_chat_enabled,
        provider=settings.orchestration_chat_provider,
        model=settings.orchestration_chat_model,
        budget_usd=settings.orchestration_chat_budget_usd,
        minimum_tier=settings.orchestration_chat_minimum_tier,
        timeout_seconds=settings.orchestration_chat_timeout_seconds,
        dedicated_project_id=settings.orchestration_chat_project_id,
    )


FICTIONAL_PROFILE = register_profile(
    RunProfile(
        id=PROFILE,
        title="Contract Questions Orchestrator",
        summary="Splits a request into Contract QA tasks on a fictional vendor agreement.",
        reads="The installed fictional vendor agreement only. No matter documents or live sources.",
        root_skill=ROOT_SKILL,
        child_skill=CHILD_SKILL,
        documents="packet",
        project_scope="dedicated",
        child_tools=PhaseTools(analysis=("read_document", "read_note", "save_note")),
        limits=RunLimits(child_turn_limit=2, document_read_chars=16000),
        evidence="unverified",
        route=_route,
        switch="LQ_AI_ORCHESTRATION_CHAT_ENABLED",
    )
)


def contract_qa_outcome(content: str, finish_reason: str, *, limit: int = 4096) -> TopicOutcome:
    """Wrap the skill's adaptive Markdown in a bounded, unverified result.

    Older completed effects may contain the original JSON envelope. Keep those
    readable, but never reinterpret a malformed JSON attempt as a Markdown
    answer or make another model call to repair it.
    """
    answer = content.strip()
    if finish_reason != "stop" or not answer or len(answer.encode()) > 16384:
        raise ValueError("Incomplete or oversized Contract QA answer")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in answer):
        raise ValueError("Contract QA answer contains control characters")
    if answer.startswith(("{", "```json")):
        outcome = TopicOutcome.model_validate_json(model_json(answer))
        if len(outcome.findings) > 1 or len(outcome.summary) > 512:
            raise ValueError("Invalid bounded Contract QA envelope")
    else:
        if len(answer) > limit:
            raise ValueError("Oversized Contract QA Markdown answer")
        summary = next(
            (
                line.strip()
                for line in answer.splitlines()
                if line.strip()
                and len(line.strip()) <= 512
                and not line.lstrip().startswith(("#", ">", "-", "*", "[§"))
            ),
            "Contract QA returned an answer to the approved question.",
        )
        outcome = TopicOutcome(status="completed", summary=summary, findings=(answer,))
    if outcome.artifact is not None:
        raise ValueError("The application supplies artifact references")
    return outcome


def packet(skills: MutableSkillRegistry) -> str:
    """Load a bounded installed fixture; its bytes are included in the root pin."""
    return intake.packet(skills, FICTIONAL_PROFILE)


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
    **more: Any,
) -> PlanningSnapshot:
    """Quote a maximum call allowance before accepting any paid planning."""
    return await intake.prepare_intake(
        FICTIONAL_PROFILE,
        settings=settings,
        skills=skills,
        policy=policy,
        routes=routes,
        root_id=root_id,
        owner_id=owner_id,
        project_id=project_id,
        goal=goal,
        privileged=privileged,
        minimum_inference_tier=minimum_inference_tier,
        **more,
    )


def prepare_model_plan(
    snapshot: PlanningSnapshot, content: str, policy: OperatorPolicy
) -> PreparedPlan:
    """Model output supplies questions only; all executable choices are server-owned."""
    return intake.prepare_model_plan(FICTIONAL_PROFILE, snapshot, content, policy)
