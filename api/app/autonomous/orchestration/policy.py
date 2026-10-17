"""Current, local authority checks for the accepted ADR 0035 pilot.

The caller supplies the operator's current snapshot, never model-authored data.
There is no default enabled policy and no gateway/cache I/O under store locks.
Worker bootstrap must provide a consistently refreshed snapshot before enabling
dispatch. Skill instructions are pinned filesystem artifacts, not slug lookups
through the chat catalog (which can resolve a different user/team fork).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.contracts import (
    EgressTier,
    InferenceTier,
    PhaseGrants,
    PhaseTools,
    PreparedPlan,
    ShortText,
    SkillPin,
    Snapshot,
)
from app.autonomous.orchestration.planning import PlanningSnapshot
from app.autonomous.orchestration.prompts import load_prompt
from app.autonomous.orchestration.reading import read_locks, readable_documents
from app.autonomous.orchestration.tools import get_tool
from app.errors import Forbidden
from app.models.document import Document
from app.research.registry import SOURCE_REGISTRY
from app.schemas.autonomous import Phase
from app.skills.loader import LoaderError, _load_one
from app.skills.registry import MutableSkillRegistry, SkillRecord, SkillRegistry

_RESEARCH_INTENTS = frozenset(
    {
        ToolIntent.retrieve_chunks,
        ToolIntent.run_skill,
        ToolIntent.plan,
        ToolIntent.retrieve_caselaw,
        ToolIntent.retrieve_authority,
        ToolIntent.emit_finding,
        ToolIntent.workspace_read,
        ToolIntent.workspace_write,
        ToolIntent.workspace_share,
        ToolIntent.skill_workspace_list,
        ToolIntent.skill_workspace_read,
        ToolIntent.skill_workspace_write,
        ToolIntent.run_bundled_script,
        ToolIntent.skill_reference_read,
    }
)


class SourcePolicy(Snapshot):
    """Enabled configured provider with explicitly supported source operations."""

    name: ShortText
    source_type: ShortText
    egress_tier: EgressTier
    operations: tuple[ShortText, ...]

    @model_validator(mode="after")
    def supported_operations(self) -> SourcePolicy:
        spec = SOURCE_REGISTRY.get(self.source_type)
        if (
            spec is None
            or not self.operations
            or len(set(self.operations)) != len(self.operations)
            or not set(self.operations) <= set(spec.ops)
        ):
            raise ValueError("source operations must be supported by a registered adapter")
        return self


class SkillPolicy(Snapshot):
    """Explicit operator selection for a closed profile, bound to an artifact.

    Source types restrict the reviewed skill's coverage; they do not establish
    that arbitrary task prose is within its jurisdiction or substantive remit.
    The plan builder must check that separately before offering approval.
    """

    pin: SkillPin
    profile: Literal["orchestrator", "research"]
    grants: PhaseGrants
    source_types: tuple[ShortText, ...]


ReasoningEffort = Literal["none", "minimal", "low", "medium", "high"]


class InferencePolicy(Snapshot):
    """Explicit direct route and input/output limits, included in approval."""

    provider: ShortText
    native_model: ShortText
    # A profile sets this (ADR 0038 D5). A run that reads documents re-sends
    # what a child has read on each turn, so its ceiling is above one packet.
    max_input_bytes: Annotated[int, Field(ge=1, le=1_048_576)]
    max_output_tokens: Annotated[int, Field(ge=1, le=8192)]
    # How much hidden reasoning to ask the model for, where the route's adapter
    # can set it. Hidden reasoning counts against ``max_output_tokens``, so on a
    # reasoning model this decides how much of that limit is left for the
    # answer. None sends nothing and leaves the model's own default.
    reasoning_effort: ReasoningEffort | None = None

    @model_validator(mode="after")
    def direct_route(self) -> InferencePolicy:
        if "/" in self.provider or len(self.model_key) > 256:
            raise ValueError("inference requires a bounded direct provider/model route")
        return self

    @model_serializer(mode="wrap")
    def serialize_policy(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        value = handler(self)
        if self.reasoning_effort is None:
            # This dump is part of the operator policy's version and of every
            # effect's identity. A route that sets no effort keeps both as they
            # were before the field existed.
            value.pop("reasoning_effort", None)
        return value

    @property
    def model_key(self) -> str:
        return f"{self.provider}/{self.native_model}"


class OperatorPolicy(Snapshot):
    """No implicit skill, source, tier, grant or anonymization defaults."""

    demo_project_id: UUID | None = None
    skills: tuple[SkillPolicy, ...]
    sources: tuple[SourcePolicy, ...]
    grants: PhaseGrants
    minimum_inference_tier: InferenceTier
    maximum_egress_tier: EgressTier
    require_anonymization: bool
    inference: InferencePolicy | None = None
    deployment_children: Annotated[int, Field(ge=1, le=32)] | None = None
    # ADR 0038 D4: registry tools a research child may be offered, per phase,
    # and how many model turns may use them. None means no tool loop.
    tools: PhaseTools | None = None
    turn_limit: Annotated[int, Field(ge=1, le=16)] | None = None

    @model_validator(mode="after")
    def unique_catalog(self) -> OperatorPolicy:
        if (self.tools is None) != (self.turn_limit is None):
            raise ValueError("a tool grant and a turn limit are set together")
        if len({(s.pin.name, s.profile) for s in self.skills}) != len(self.skills):
            raise ValueError("duplicate skill profile")
        if len({s.name for s in self.sources}) != len(self.sources):
            raise ValueError("duplicate source name")
        for skill in self.skills:
            if len(set(skill.source_types)) != len(skill.source_types) or any(
                name not in SOURCE_REGISTRY for name in skill.source_types
            ):
                raise ValueError("skill source types must be unique registered adapters")
        return self

    def version(self) -> str:
        """Bind approval to the entire operator policy, including provider tiers."""
        value = self.model_dump(mode="json")
        if self.demo_project_id is None:
            # Existing sample approvals predate the optional project allowlist.
            value.pop("demo_project_id")
        if self.tools is None:
            # Likewise the tool grant: a policy without one keeps its version.
            value.pop("tools")
            value.pop("turn_limit")
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True)
class PinnedSkill:
    pin: SkillPin
    instructions: str
    bundle_digest: str | None = None
    reference_contents: tuple[tuple[str, str], ...] = field(default=(), repr=False, compare=False)


def on_demand_index(paths: list[str]) -> str:
    """The prompt block that names a skill's on-demand reference files."""
    return (
        "## Reference files available on request\n\n"
        "These files belong to this skill and are not included here. When the task calls "
        "for one, read it with the `skill_reference_read` tool (in chat the tool's name "
        "carries a prefix and ends in `skill_reference_read`). If no such tool is offered, "
        "say which file you could not read; do not guess its contents.\n\n"
        + "\n".join(f"- {path}" for path in paths)
    )


def load_pinned_skill(record: SkillRecord) -> PinnedSkill:
    """Hash exactly the loaded instructions, metadata and all supporting files.

    Re-read the main artifact to detect disk changes even before SIGHUP. Unlike
    public materialise(), missing supporting files are a refusal, never skipped.
    The executor must use this same artifact, not ask the gateway to resolve a
    mutable skill slug after admission.
    """
    from app.skills.references import read_reference_snapshot

    try:
        current = _load_one(record.folder, source=record.source, quiet=True)
        if current != record:
            raise ValueError("registry and disk differ")
        files = []
        for path in sorted(
            (
                *record.reference_paths,
                *record.example_paths,
                *record.script_paths,
                *record.on_demand_paths,
            )
        ):
            if not path.resolve().is_relative_to(record.folder.resolve()):
                raise ValueError("supporting file outside skill folder")
            content = (
                read_reference_snapshot(record.folder, path)
                if path in record.on_demand_paths
                else path.read_text("utf-8")
            )
            files.append((path.relative_to(record.folder).as_posix(), content))
        artifact = (record.name, record.source, record.raw_yaml, record.body, files)
        digest = hashlib.sha256(
            json.dumps(artifact, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
    except (LoaderError, OSError, UnicodeError, ValueError):
        raise Forbidden(message="Pinned skill artifact is unavailable or changed") from None
    # Build the prompt from the same bytes that were hashed. Do not materialise
    # or ask the gateway to resolve this slug again after authority checks.
    instructions = f"---\n{record.raw_yaml}\n---\n{record.body}"
    # ``references/`` files are hashed above, so a read returns pinned bytes,
    # but only their names enter the prompt: the model reads one on request.
    on_demand = {path.relative_to(record.folder).as_posix() for path in record.on_demand_paths}
    for relative_path, content in files:
        if relative_path.startswith("scripts/") or relative_path in on_demand:
            continue
        instructions += f"\n\n## Supporting file: {relative_path}\n\n{content}"
    if on_demand:
        instructions += "\n\n" + on_demand_index(sorted(on_demand))
    scripts = [(p, c) for p, c in files if p.startswith("scripts/")]
    bundle_digest = (
        hashlib.sha256(
            json.dumps(scripts, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        if scripts
        else None
    )
    return PinnedSkill(
        SkillPin(name=record.name, digest=digest),
        instructions,
        bundle_digest,
        tuple((path, content) for path, content in files if path in on_demand),
    )


def skill_pin(record: SkillRecord) -> SkillPin:
    return load_pinned_skill(record).pin


@dataclass(frozen=True)
class PinnedInstructions:
    """A session's system message as it is now, with the pin its bytes produce."""

    pin: SkillPin
    instructions: str
    version: str
    # A skill may declare its own inference-tier floor. An engine prompt has none.
    minimum_inference_tier: int = 5


def load_instructions(
    registry: SkillRegistry, kind: Literal["skill", "prompt"], name: str
) -> PinnedInstructions:
    """Read the current text for a pin's name, from the place its kind names.

    A prompt name is read only from the engine's prompt files and a skill name
    only from the installed skills, so neither can stand in for the other. The
    caller compares the returned pin with the one it holds: a different digest
    means the text changed after it was approved.
    """
    if kind == "prompt":
        prompt = load_prompt(name)
        return PinnedInstructions(prompt.pin, prompt.text, str(prompt.version))
    record = registry.get(name)
    if record is None:
        raise Forbidden(message="Pinned skill is unavailable")
    loaded = load_pinned_skill(record)
    return PinnedInstructions(
        loaded.pin,
        loaded.instructions,
        record.frontmatter.lq_ai.version or "",
        record.frontmatter.lq_ai.minimum_inference_tier or 5,
    )


class CurrentPolicy:
    """Store policy callback using current project attachments and local catalogs.

    Owner/project opt-in, archival, privilege and tier checks live in the store.
    Resource rows are share-locked only for its short transaction. A subsequent
    tool read must enforce the selected subset again in its own transaction.
    """

    def __init__(
        self,
        *,
        skills: MutableSkillRegistry,
        operator: Callable[[], OperatorPolicy | None],
    ) -> None:
        self.skills = skills
        self.operator = operator

    async def __call__(self, db: AsyncSession, plan: PreparedPlan | PlanningSnapshot) -> None:
        policy = self.operator()
        if policy is None or policy.version() != plan.policy_version:
            raise Forbidden(message="Orchestration operator policy is disabled or changed")
        if policy.demo_project_id is not None and plan.project_id != policy.demo_project_id:
            raise Forbidden(message="Project is outside the enabled demonstration")
        registry = self.skills.current()
        sources = {source.name: source for source in policy.sources}
        selections: dict[tuple[str, str], SkillPolicy] = {
            (s.pin.name, s.profile): s for s in policy.skills
        }
        pins: dict[tuple[str, str], PinnedInstructions] = {}
        for scope, profile in (
            (plan.root, "orchestrator"),
            *((child.execution, child.profile) for child in plan.children),
        ):
            selected = selections.get((scope.skill.name, profile))
            if selected is None or (
                scope.skill.kind == "skill" and registry.get(scope.skill.name) is None
            ):
                raise Forbidden(message="Skill is not enabled for the execution profile")
            # A pin's kind decides where its name is read from. Equality below
            # includes the kind, so a prompt pin never matches a skill pin.
            key = (scope.skill.kind, scope.skill.name)
            if key not in pins:
                pins[key] = load_instructions(registry, scope.skill.kind, scope.skill.name)
            current = pins[key]
            if scope.skill != selected.pin or scope.skill != current.pin:
                raise Forbidden(message="Approved skill artifact has changed")
            if (
                scope.minimum_inference_tier
                > min(policy.minimum_inference_tier, current.minimum_inference_tier)
                or scope.maximum_egress_tier > policy.maximum_egress_tier
                or (policy.require_anonymization and not scope.anonymize)
                or not policy.grants.contains(scope.grants)
                or not selected.grants.contains(scope.grants)
            ):
                raise Forbidden(message="Execution scope exceeds current data or grant policy")
            if profile == "research" and any(
                intent not in _RESEARCH_INTENTS
                for phase in Phase
                for intent in getattr(scope.grants, phase.value)
            ):
                raise Forbidden(message="Intent is outside the closed research profile")
            for name in scope.resources.source_names:
                source = sources.get(name)
                if (
                    source is None
                    or source.source_type not in selected.source_types
                    or source.egress_tier > scope.maximum_egress_tier
                ):
                    raise Forbidden(
                        message="Selected source is unavailable or outside skill policy"
                    )

        for child in plan.children:
            # The approved tool list is rechecked against what the operator
            # allows now, so removing a tool or lowering the limit stops a run.
            if not child.tools.names() and not child.turn_limit:
                continue
            if (
                policy.tools is None
                or policy.turn_limit is None
                or not policy.tools.contains(child.tools)
                or child.turn_limit > policy.turn_limit
            ):
                raise Forbidden(message="Approved tools exceed current operator policy")
            for phase in Phase:
                for name in child.tools.for_phase(phase):
                    tool = get_tool(name)
                    if (
                        tool is None
                        or tool.destructive
                        or tool.requires_confirmation
                        or tool.intent not in child.execution.grants.for_phase(phase)
                    ):
                        raise Forbidden(message="Approved tool is unavailable or not granted")

        selected_ids = set(plan.root.resources.document_ids)
        if selected_ids:
            # One query for a matter and for a run outside any matter; see
            # ``reading``. The same query guards each read at the boundary. The
            # terms a run outside a matter takes on from its documents' matters
            # are checked by the store, at this same admission.
            rows = await db.scalars(
                readable_documents(
                    owner_id=plan.owner_id,
                    project_id=plan.project_id,
                    document_ids=selected_ids,
                )
                .order_by(Document.id)
                .with_for_update(read=True, of=read_locks(plan.project_id))
            )
            if set(rows) != selected_ids:
                raise Forbidden(message="Selected documents are no longer available to this run")
