"""The run profile registry: the closed set an operator can enable (ADR 0038 D3).

A profile names pinned skills by role, the tools granted in each phase, the
resources a run may read, its limits and its model route. Supporting another
skill in runs means adding an entry here, not engine or interface code.

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
from app.autonomous.orchestration.policy import (
    InferencePolicy,
    OperatorPolicy,
    SkillPolicy,
    skill_pin,
)
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


@dataclass(frozen=True)
class RunLimits:
    """Bounds a profile sets. Shown to the owner before planning is paid for.

    ``child_turn_limit`` is the number of model turns that may use tools. One
    further turn without tools then asks for the answer, so a child makes at
    most ``child_turn_limit + 1`` model calls.
    """

    max_input_bytes: int = 98304
    max_output_tokens: int = 8192
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
            or not 1 <= self.child_answer_chars <= 4096
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
    root_skill: str
    child_skill: str
    # "packet": the installed fictional agreement, filed in the dedicated demo
    # project. "selected": documents the owner picks from the chat's project.
    documents: Literal["packet", "selected"]
    # "dedicated": only the operator's configured demo project. "owned": any
    # active project the owner owns.
    project_scope: Literal["dedicated", "owned"]
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
    planning_notice: str = (
        "Sending asks the model for a plan: one model call within the displayed total cap. "
        "The planning call receives your request only, not earlier messages. "
        "Nothing else runs until you approve the plan."
    )

    @property
    def calls_per_child(self) -> int:
        return self.limits.child_turn_limit + 1 if self.child_tools.names() else 1

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
    # The composer shows one model and asks for no profile choice. Which of two
    # offered profiles a request would run is a decision this registry does not
    # hold, so a second is refused instead of being picked by sort order.
    if profile.composer and composer_profile() is not None:
        raise ValidationError(message="Only one run profile is offered in the composer")
    _PROFILES[profile.id] = profile
    return profile


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
    roles: tuple[tuple[str, Literal["orchestrator", "research"]], ...] = (
        (profile.root_skill, "orchestrator"),
        (profile.child_skill, "research"),
    )
    for name, role in roles:
        record = skills.current().get(name)
        if record is None or record.source != "built-in":
            raise Forbidden(message="Required installed run skill is unavailable")
        selections.append(
            SkillPolicy(pin=skill_pin(record), profile=role, grants=grants, source_types=())
        )
    try:
        inference = InferencePolicy(
            provider=route.provider,
            native_model=route.model,
            max_input_bytes=profile.limits.max_input_bytes,
            # Reasoning models count hidden reasoning toward the same ceiling.
            # Keep room for the bounded visible plan/answer without retries.
            max_output_tokens=profile.limits.max_output_tokens,
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
        require_anonymization=True,
        deployment_children=settings.orchestration_deployment_children,
        inference=inference,
        # Left unset for a profile without tools, so a policy that predates the
        # registry keeps the version its retained approvals are bound to.
        tools=profile.child_tools if tooled else None,
        turn_limit=profile.limits.child_turn_limit if tooled else None,
    )
