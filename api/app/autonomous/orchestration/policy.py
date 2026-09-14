"""Current, local authority checks for the proposed ADR 0035 pilot.

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
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.contracts import (
    EgressTier,
    InferenceTier,
    PhaseGrants,
    PreparedPlan,
    ShortText,
    SkillPin,
    Snapshot,
)
from app.errors import Forbidden
from app.models.document import Document
from app.models.file import File
from app.models.project import ProjectFile
from app.research.registry import SOURCE_REGISTRY
from app.schemas.autonomous import Phase
from app.skills.loader import LoaderError, _load_one
from app.skills.registry import MutableSkillRegistry, SkillRecord

_RESEARCH_INTENTS = frozenset(
    {
        ToolIntent.retrieve_chunks,
        ToolIntent.run_skill,
        ToolIntent.plan,
        ToolIntent.retrieve_caselaw,
        ToolIntent.retrieve_authority,
        ToolIntent.emit_finding,
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


class InferencePolicy(Snapshot):
    """Explicit direct route and input/output limits, included in approval."""

    provider: ShortText
    native_model: ShortText
    max_input_bytes: Annotated[int, Field(ge=1, le=131072)]
    max_output_tokens: Annotated[int, Field(ge=1, le=8192)]

    @model_validator(mode="after")
    def direct_route(self) -> InferencePolicy:
        if "/" in self.provider or len(self.model_key) > 256:
            raise ValueError("inference requires a bounded direct provider/model route")
        return self

    @property
    def model_key(self) -> str:
        return f"{self.provider}/{self.native_model}"


class OperatorPolicy(Snapshot):
    """No implicit skill, source, tier, grant or anonymization defaults."""

    skills: tuple[SkillPolicy, ...]
    sources: tuple[SourcePolicy, ...]
    grants: PhaseGrants
    minimum_inference_tier: InferenceTier
    maximum_egress_tier: EgressTier
    require_anonymization: bool
    inference: InferencePolicy | None = None
    deployment_children: Annotated[int, Field(ge=1, le=32)] | None = None

    @model_validator(mode="after")
    def unique_catalog(self) -> OperatorPolicy:
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
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True)
class PinnedSkill:
    pin: SkillPin
    instructions: str


def load_pinned_skill(record: SkillRecord) -> PinnedSkill:
    """Hash exactly the loaded instructions, metadata and all supporting files.

    Re-read the main artifact to detect disk changes even before SIGHUP. Unlike
    public materialise(), missing supporting files are a refusal, never skipped.
    The executor must use this same artifact, not ask the gateway to resolve a
    mutable skill slug after admission.
    """
    try:
        current = _load_one(record.folder, source=record.source)
        if current != record:
            raise ValueError("registry and disk differ")
        files = []
        for path in sorted((*record.reference_paths, *record.example_paths)):
            if not path.resolve().is_relative_to(record.folder.resolve()):
                raise ValueError("supporting file outside skill folder")
            files.append((path.relative_to(record.folder).as_posix(), path.read_text("utf-8")))
        artifact = (record.name, record.source, record.raw_yaml, record.body, files)
        digest = hashlib.sha256(
            json.dumps(artifact, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
    except (LoaderError, OSError, UnicodeError, ValueError):
        raise Forbidden(message="Pinned skill artifact is unavailable or changed") from None
    # Build the prompt from the same bytes that were hashed. Do not materialise
    # or ask the gateway to resolve this slug again after authority checks.
    instructions = f"---\n{record.raw_yaml}\n---\n{record.body}"
    for relative_path, content in files:
        instructions += f"\n\n## Supporting file: {relative_path}\n\n{content}"
    return PinnedSkill(SkillPin(name=record.name, digest=digest), instructions)


def skill_pin(record: SkillRecord) -> SkillPin:
    return load_pinned_skill(record).pin


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

    async def __call__(self, db: AsyncSession, plan: PreparedPlan) -> None:
        policy = self.operator()
        if policy is None or policy.version() != plan.policy_version:
            raise Forbidden(message="Orchestration operator policy is disabled or changed")
        registry = self.skills.current()
        sources = {source.name: source for source in policy.sources}
        selections: dict[tuple[str, str], SkillPolicy] = {
            (s.pin.name, s.profile): s for s in policy.skills
        }
        pins: dict[str, SkillPin] = {}
        for scope, profile in (
            (plan.root, "orchestrator"),
            *((child.execution, child.profile) for child in plan.children),
        ):
            selected = selections.get((scope.skill.name, profile))
            record = registry.get(scope.skill.name)
            if selected is None or record is None:
                raise Forbidden(message="Skill is not enabled for the execution profile")
            if record.name not in pins:
                pins[record.name] = skill_pin(record)
            if scope.skill != selected.pin or scope.skill != pins[record.name]:
                raise Forbidden(message="Approved skill artifact has changed")
            if (
                scope.minimum_inference_tier
                > min(
                    policy.minimum_inference_tier,
                    record.frontmatter.lq_ai.minimum_inference_tier or 5,
                )
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

        selected_ids = set(plan.root.resources.document_ids)
        if selected_ids:
            rows = await db.scalars(
                select(Document.id)
                .join(File, File.id == Document.file_id)
                .join(ProjectFile, ProjectFile.file_id == File.id)
                .where(
                    Document.id.in_(selected_ids),
                    File.owner_id == plan.owner_id,
                    File.deleted_at.is_(None),
                    ProjectFile.project_id == plan.project_id,
                )
                .order_by(Document.id)
                .with_for_update(read=True, of=(Document, File, ProjectFile))
            )
            if set(rows) != selected_ids:
                raise Forbidden(
                    message="Selected documents are no longer available in this project"
                )
