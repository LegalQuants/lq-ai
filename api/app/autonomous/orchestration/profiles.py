"""The run profile registry: the closed set an operator can enable (ADR 0038 D3).

A profile names what instructs each role (pinned skills, or the engine's own
versioned prompt files), the tools granted in each phase, the resources a run
may read, its limits and its model route. Supporting another skill in runs
means adding an entry here, not engine or interface code.

The registry lives in code. Each entry reads its operator switch and pinned
route from settings, so an operator sees and controls every profile
(ADR 0016 P2, P8) and no profile is enabled by another profile's switch.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.contracts import PhaseGrants, PhaseTools
from app.autonomous.orchestration.planning import PlanningSnapshot, RunTerms
from app.autonomous.orchestration.policy import (
    InferencePolicy,
    OperatorPolicy,
    ReasoningEffort,
    SkillPolicy,
    skill_pin,
)
from app.autonomous.orchestration.prompts import load_prompt
from app.autonomous.orchestration.tools import get_tool
from app.config import Settings
from app.errors import Forbidden, ValidationError
from app.schemas.autonomous import Phase
from app.skills.registry import MutableSkillRegistry

_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# Intents the engine itself uses on every profile: one planning call, pinned
# skill inference, and the run's own working files. Granted tools add to these.
_ENGINE_ANALYSIS = (
    ToolIntent.plan,
    ToolIntent.run_skill,
    ToolIntent.workspace_read,
    ToolIntent.workspace_write,
)
_ENGINE_DRAFTING = (
    ToolIntent.run_skill,
    ToolIntent.workspace_read,
    ToolIntent.workspace_write,
    ToolIntent.workspace_share,
)


@dataclass(frozen=True)
class RouteSettings:
    """What the operator has configured for one profile. Read on every use."""

    enabled: bool
    provider: str
    model: str
    budget_usd: Decimal
    minimum_tier: int
    timeout_seconds: int
    dedicated_project_id: str = ""
    # None sends no reasoning effort and leaves the model's own default.
    reasoning_effort: ReasoningEffort | None = None


@dataclass(frozen=True)
class RunLimits:
    """Bounds a profile sets. Shown to the owner before planning is paid for.

    ``child_turn_limit`` is the number of model turns that may use tools. One
    further turn without tools then asks for the answer, so a child makes at
    most ``child_turn_limit + 1`` model calls.
    """

    max_input_bytes: int = 98304
    max_output_tokens: int = 8192
    # A task's answer is stored whole as one finding (``outcomes.Finding``).
    child_answer_chars: int = 4096
    combined_answer_chars: int = 16384
    deadline_seconds: int = 3600
    child_turn_limit: int = 2
    document_read_chars: int = 16000
    max_active_children: int = 2

    def __post_init__(self) -> None:
        if (
            not 1 <= self.max_input_bytes <= 1_048_576
            or not 1 <= self.max_output_tokens <= 8192
            or not 1 <= self.child_answer_chars <= 16384
            or not 1 <= self.combined_answer_chars <= 16384
            or not 60 <= self.deadline_seconds <= 86400
            or not 0 <= self.child_turn_limit <= 16
            or not 256 <= self.document_read_chars <= 65536
            or not 1 <= self.max_active_children <= 4
        ):
            raise ValidationError(message="Run profile limits are outside supported bounds")


@dataclass(frozen=True)
class RunProfile:
    id: str
    title: str
    summary: str
    reads: str
    # The installed skills that instruct each role, or "" for a profile that
    # pins prompt files instead (``root_prompt``, ``child_prompt``).
    root_skill: str
    child_skill: str
    # "packet": the installed fictional agreement, filed in the dedicated demo
    # project. "selected": one to eight documents the owner picks.
    # "optional": none to eight; a run with none reads no document.
    documents: Literal["packet", "selected", "optional"]
    # "dedicated": only the operator's configured demo project. "owned": any
    # active project the owner owns. "any": such a project, or no project at
    # all, for a chat that is in no matter.
    project_scope: Literal["dedicated", "owned", "any"]
    child_tools: PhaseTools
    limits: RunLimits
    evidence: Literal["unverified", "citations"]
    route: Callable[[Settings], RouteSettings]
    # The deployment setting an operator turns on to enable this profile.
    switch: str = ""
    # The one profile the chat composer offers, as the "New harness" model. A
    # profile that is not offered there stays startable through the API where
    # its switch is on; the fictional fixture is the case.
    composer: bool = False
    # The engine's own versioned prompt files for each role (ADR 0038 D3), as
    # ``<family>/<role>.v<N>``. Set both, and leave the two skills empty.
    root_prompt: str = ""
    child_prompt: str = ""
    # Whether the planning call is shown the chat's recent messages and the
    # date of the request. Such a run's intake is planning snapshot version 3.
    reads_thread: bool = False
    # "required": a run is refused unless the gateway pseudonymizes on its
    # route. "operator": a run follows the operator's gateway setting for the
    # routed tier, and every call's receipt records what was applied.
    pseudonymization: Literal["required", "operator"] = "required"
    # How the orchestrator hands over its plan. "text": a JSON object in its
    # reply. "tool": one call to ``propose_plan``; a reply with no call is then
    # the orchestrator's own answer and the run ends without a plan (ADR 0038
    # D1). Only a prompt-pinned profile may plan by tool.
    planning: Literal["text", "tool"] = "text"
    planning_notice: str = (
        "Sending asks the model for a plan: one model call within the displayed total cap. "
        "The planning call receives your request only, not earlier messages. "
        "Nothing else runs until you approve the plan."
    )

    @property
    def calls_per_child(self) -> int:
        return self.limits.child_turn_limit + 1 if self.child_tools.names() else 1

    @property
    def prompted(self) -> bool:
        """Whether the roles are instructed by prompt files rather than skills."""
        return bool(self.root_prompt)

    def terms(self) -> RunTerms:
        """The limits a run of this profile is given when its request is accepted."""
        return RunTerms(
            task_turns=self.limits.child_turn_limit,
            task_answer_chars=self.limits.child_answer_chars,
            answer_chars=self.limits.combined_answer_chars,
            read_chars=self.limits.document_read_chars,
            planning=self.planning,
        )

    def instructions(
        self, role: Literal["orchestrator", "research"]
    ) -> tuple[Literal["skill", "prompt"], str]:
        """What instructs one role: where its name resolves, and the name."""
        if self.prompted:
            return "prompt", self.root_prompt if role == "orchestrator" else self.child_prompt
        return "skill", self.root_skill if role == "orchestrator" else self.child_skill

    def grants(self) -> PhaseGrants:
        """Engine intents plus the intents of every granted tool, per phase."""
        extra: dict[Phase, set[ToolIntent]] = {phase: set() for phase in Phase}
        for phase in Phase:
            for name in self.child_tools.for_phase(phase):
                tool = get_tool(name)
                if tool is None:
                    raise Forbidden(message="Run profile grants an unregistered tool")
                extra[phase].add(tool.intent)
        return PhaseGrants(
            intake=tuple(extra[Phase.intake]),
            analysis=tuple({*_ENGINE_ANALYSIS, *extra[Phase.analysis]}),
            drafting=tuple({*_ENGINE_DRAFTING, *extra[Phase.drafting]}),
            ethics_review=tuple(extra[Phase.ethics_review]),
            delivery=tuple(extra[Phase.delivery]),
        )


_PROFILES: dict[str, RunProfile] = {}


def register_profile(profile: RunProfile) -> RunProfile:
    if _ID.fullmatch(profile.id) is None or profile.id in {"demonstration", "research"}:
        raise ValidationError(message="Run profile needs a bounded, unreserved identifier")
    if profile.id in _PROFILES:
        raise ValidationError(message="Run profile is already registered")
    for name in profile.child_tools.names():
        if get_tool(name) is None:
            raise ValidationError(message="Run profile grants an unregistered tool")
    if bool(profile.child_tools.names()) != bool(profile.limits.child_turn_limit):
        raise ValidationError(message="A tool grant and a turn limit are set together")
    skills = (bool(profile.root_skill), bool(profile.child_skill))
    prompts = (bool(profile.root_prompt), bool(profile.child_prompt))
    if skills[0] != skills[1] or prompts[0] != prompts[1] or skills[0] == prompts[0]:
        raise ValidationError(
            message="A run profile pins skills for both roles or prompt files for both, not a mix"
        )
    if profile.project_scope == "any" and profile.documents == "packet":
        raise ValidationError(message="The fictional packet is filed in a dedicated matter")
    if profile.planning == "tool" and not (profile.reads_thread and prompts[0]):
        # The plan tool and the direct answer are recorded in the run's terms,
        # which only a version 3 intake carries, and the tool is offered only
        # to a role that a prompt file instructs.
        raise ValidationError(
            message="A profile that plans by tool call is prompt-pinned and records its terms"
        )
    # The composer shows one model and asks for no profile choice. Which of two
    # offered profiles a request would run is a decision this registry does not
    # hold, so a second is refused instead of being picked by sort order.
    if profile.composer and composer_profile() is not None:
        raise ValidationError(message="Only one run profile is offered in the composer")
    _PROFILES[profile.id] = profile
    return profile


def run_terms(profile: RunProfile, snapshot: PlanningSnapshot | None) -> RunTerms:
    """The terms one retained run is held to.

    A version 3 intake carries them, frozen when its request was accepted. An
    intake without them is an earlier version, or a version 3 intake recorded
    before terms were frozen: it reads its profile's present limits, and its
    plan is a JSON object in the reply, which is all there was then.
    """
    if snapshot is not None and snapshot.terms is not None:
        return snapshot.terms
    return profile.terms().model_copy(update={"planning": "text"})


def composer_profile() -> RunProfile | None:
    """The profile the chat composer offers as New harness, if one is registered."""
    return next((p for p in registered_profiles() if p.composer), None)


def get_profile(profile_id: str) -> RunProfile | None:
    return _PROFILES.get(profile_id)


def require_profile(profile_id: str) -> RunProfile:
    profile = _PROFILES.get(profile_id)
    if profile is None:
        raise Forbidden(message="Unknown orchestration profile")
    return profile


def registered_profiles() -> tuple[RunProfile, ...]:
    return tuple(_PROFILES[key] for key in sorted(_PROFILES))


@contextmanager
def temporary_profile(profile: RunProfile) -> Iterator[RunProfile]:
    """Register a profile for the duration of a block. Used by the contract test."""
    register_profile(profile)
    try:
        yield profile
    finally:
        _PROFILES.pop(profile.id, None)


def dedicated_project(profile: RunProfile, settings: Settings) -> UUID | None:
    """The one project a dedicated profile may run in; refuses a bad setting."""
    if profile.project_scope != "dedicated":
        return None
    try:
        return UUID(profile.route(settings).dedicated_project_id)
    except ValueError:
        raise Forbidden(message="Configure a dedicated demo project") from None


def operator_policy(
    profile: RunProfile, skills: MutableSkillRegistry, settings: Settings
) -> OperatorPolicy | None:
    """The operator's current policy for one profile, or None when switched off.

    Explicit installed skills only. No retrieval source, optional helper or
    persistent workspace is granted here (ADR 0035 D8c, D8d).
    """
    route = profile.route(settings)
    if not route.enabled:
        return None
    project_id = dedicated_project(profile, settings)
    if settings.orchestration_deployment_children is None:
        raise Forbidden(message="Configure shared child capacity")
    grants = profile.grants()
    selections = []
    roles: tuple[Literal["orchestrator", "research"], ...] = ("orchestrator", "research")
    for role in roles:
        kind, name = profile.instructions(role)
        if kind == "prompt":
            # An engine prompt file, never looked up among installed skills.
            pin = load_prompt(name).pin
        else:
            record = skills.current().get(name)
            if record is None or record.source != "built-in":
                raise Forbidden(message="Required installed run skill is unavailable")
            pin = skill_pin(record)
        selections.append(SkillPolicy(pin=pin, profile=role, grants=grants, source_types=()))
    try:
        inference = InferencePolicy(
            provider=route.provider,
            native_model=route.model,
            max_input_bytes=profile.limits.max_input_bytes,
            # Reasoning models count hidden reasoning toward the same ceiling.
            # Keep room for the bounded visible plan/answer without retries.
            max_output_tokens=profile.limits.max_output_tokens,
            reasoning_effort=route.reasoning_effort,
        )
    except ValueError:
        raise Forbidden(message="Configure the run profile's provider and model") from None
    tooled = bool(profile.child_tools.names())
    return OperatorPolicy(
        demo_project_id=project_id,
        skills=tuple(selections),
        sources=(),
        grants=grants,
        minimum_inference_tier=route.minimum_tier,
        maximum_egress_tier=0,
        # False lets a run follow the operator's gateway setting for its routed
        # tier instead of being refused where that setting applies none.
        require_anonymization=profile.pseudonymization == "required",
        deployment_children=settings.orchestration_deployment_children,
        inference=inference,
        # Left unset for a profile without tools, so that such a policy hashes as
        # it did before tools existed. No registered profile is without tools:
        # the fictional profile gained them after 0.8.0, so its policy version
        # is not the one a 0.8.0 run was approved under, and a 0.8.0 run still
        # in flight at upgrade stops at its next admission. Settled runs are
        # read without the policy and are unaffected.
        tools=profile.child_tools if tooled else None,
        turn_limit=profile.limits.child_turn_limit if tooled else None,
    )
