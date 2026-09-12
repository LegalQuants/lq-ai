"""Internal plan/consent snapshots for ADR 0035, independent of the runtime.

Only ``parse_research_proposal`` accepts model output. Everything else is built
from authoritative server data. Frozen objects and hashes prevent accidental
scope drift, not malicious prose or revoked permissions. These contracts do not
authorize dispatch: durable approval, current-access checks and atomic admission
must still run in the caller's transaction.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from app.autonomous.enums import PHASE_GRANTS, ToolIntent
from app.errors import Conflict, ValidationError
from app.schemas.autonomous import Phase

MAX_PROPOSAL_BYTES = 131_072


def _exact_money(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            pass
    raise ValueError("money requires an exact decimal string or Decimal")


type ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
type TaskText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)
]
type Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
type Money = Annotated[
    Decimal,
    Field(ge=0, max_digits=10, decimal_places=4, allow_inf_nan=False),
    BeforeValidator(_exact_money),
]
type InferenceTier = Annotated[int, Field(ge=1, le=5)]
type EgressTier = Annotated[int, Field(ge=0, le=5)]


class Snapshot(BaseModel):
    """Strict, deeply immutable fields only; no mutable lists or dictionaries."""

    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, revalidate_instances="always"
    )


class ResearchTask(Snapshot):
    """Untrusted task data; no resource selectors or executable authority."""

    topic: ShortText
    question: TaskText
    boundaries: TaskText
    output_contract: TaskText
    stopping_condition: TaskText


class ResearchProposal(Snapshot):
    tasks: Annotated[tuple[ResearchTask, ...], Field(min_length=1, max_length=4)]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def parse_research_proposal(content: str) -> ResearchProposal:
    """Fail closed on malformed, ambiguous, oversized or authority-bearing JSON.

    Errors deliberately omit raw model content. Do not log the underlying
    Pydantic error: its input values can contain privileged matter text.
    """
    try:
        if len(content) > MAX_PROPOSAL_BYTES or len(content.encode("utf-8")) > MAX_PROPOSAL_BYTES:
            raise ValueError("oversized proposal")
        # Pydantic alone accepts duplicate keys. Check before schema parsing;
        # the second parse retains strict JSON array -> immutable tuple support.
        json.loads(content, object_pairs_hook=_unique_object)
        return ResearchProposal.model_validate_json(content)
    except (ValueError, TypeError, RecursionError):
        raise ValidationError(message="Research proposal is not valid bounded task JSON") from None


class SkillPin(Snapshot):
    name: ShortText
    digest: Digest


class ResourceScope(Snapshot):
    """Selected document IDs and configured source names, including empty scope.

    The resolver must check adapter-specific operations at call time; a source
    name never grants every operation offered by that provider.
    """

    document_ids: Annotated[tuple[UUID, ...], Field(max_length=128)]
    source_names: Annotated[tuple[ShortText, ...], Field(max_length=32)]

    @field_validator("document_ids", "source_names")
    @classmethod
    def unique_selections(cls, value: tuple) -> tuple:
        if len(set(value)) != len(value):
            raise ValueError("duplicate selected resource")
        return tuple(sorted(value))

    def contains(self, other: ResourceScope) -> bool:
        return set(other.document_ids) <= set(self.document_ids) and set(other.source_names) <= set(
            self.source_names
        )


class PhaseGrants(Snapshot):
    """Explicit grants for the whole lifecycle, not the parent's active phase."""

    intake: tuple[ToolIntent, ...]
    analysis: tuple[ToolIntent, ...]
    drafting: tuple[ToolIntent, ...]
    ethics_review: tuple[ToolIntent, ...]
    delivery: tuple[ToolIntent, ...]

    @field_validator("*")
    @classmethod
    def unique_intents(cls, value: tuple[ToolIntent, ...]) -> tuple[ToolIntent, ...]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate intent")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def legal_phases(self) -> Self:
        for phase in Phase:
            if not set(self.for_phase(phase)) <= PHASE_GRANTS[phase]:
                raise ValueError("intent is forbidden in this phase")
        return self

    def for_phase(self, phase: Phase) -> tuple[ToolIntent, ...]:
        return getattr(self, phase.value)

    def contains(self, other: PhaseGrants) -> bool:
        return all(set(other.for_phase(p)) <= set(self.for_phase(p)) for p in Phase)


class ExecutionScope(Snapshot):
    resources: ResourceScope
    grants: PhaseGrants
    skill: SkillPin
    minimum_inference_tier: InferenceTier
    maximum_egress_tier: EgressTier
    privileged: bool
    anonymize: bool


class ChildAssignment(Snapshot):
    """Server-selected research profile; the dispatch ID is not an admitted run."""

    dispatch_id: UUID
    profile: Literal["research"]
    task: ResearchTask
    execution: ExecutionScope
    budget_usd: Money

    @model_validator(mode="after")
    def internal_delivery_only(self) -> Self:
        forbidden = {
            ToolIntent.notify,
            ToolIntent.emit_artifact,
            ToolIntent.propose_memory,
            ToolIntent.propose_precedent,
        }
        if any(forbidden.intersection(self.execution.grants.for_phase(p)) for p in Phase):
            raise ValueError("research children cannot publish or curate")
        return self

    @field_serializer("budget_usd")
    def serialize_budget(self, value: Decimal) -> str:
        return format(value, ".4f")


class PreparedPlan(Snapshot):
    """Canonical executable plan built from resolved server policy, never an LLM."""

    contract_version: Literal[1] = 1
    plan_id: UUID
    revision: Annotated[int, Field(ge=1)]
    root_id: UUID
    project_id: UUID
    owner_id: UUID
    goal: TaskText
    policy_version: ShortText
    root: ExecutionScope
    delegation_grants: PhaseGrants
    children: Annotated[tuple[ChildAssignment, ...], Field(min_length=1, max_length=4)]
    budget_usd: Money
    root_allowance_usd: Money
    max_active_children: Annotated[int, Field(ge=1, le=4)]
    deadline: AwareDatetime
    attempt_timeout_seconds: Annotated[int, Field(ge=1, le=900)]

    @field_validator("contract_version", mode="before")
    @classmethod
    def integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("contract version must be an integer")
        return value

    @field_validator("deadline")
    @classmethod
    def utc_deadline(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @field_serializer("budget_usd", "root_allowance_usd")
    def serialize_budget(self, value: Decimal) -> str:
        return format(value, ".4f")

    @model_validator(mode="after")
    def bounded_delegation(self) -> Self:
        if len({child.dispatch_id for child in self.children}) != len(self.children):
            raise ValueError("duplicate dispatch identity")
        if self.root_allowance_usd + sum(c.budget_usd for c in self.children) > self.budget_usd:
            raise ValueError("root allowance and child budgets exceed total budget")
        for child in self.children:
            scope = child.execution
            if not self.root.resources.contains(scope.resources):
                raise ValueError("child resources exceed selected root scope")
            if not self.delegation_grants.contains(scope.grants):
                raise ValueError("child grants exceed delegation envelope")
            if scope.minimum_inference_tier < self.root.minimum_inference_tier:
                raise ValueError("child weakens minimum inference tier")
            if scope.maximum_egress_tier > self.root.maximum_egress_tier:
                raise ValueError("child weakens maximum egress tier")
            if self.root.privileged and not scope.privileged:
                raise ValueError("child drops privileged classification")
            if self.root.anonymize and not scope.anonymize:
                raise ValueError("child disables required anonymization")
        return self

    def approval_hash(self) -> str:
        """Bind every field; canonicalize set order, UTC and monetary precision.

        Topic order is meaningful and preserved. This digest is consent binding,
        not a signature, authorization token, or safe-content certification.
        """
        validated = PreparedPlan.model_validate(self)
        canonical = json.dumps(
            validated.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ApprovalBinding(Snapshot):
    """Consent evidence read from server-owned storage; never a bearer token."""

    plan_id: UUID
    root_id: UUID
    project_id: UUID
    revision: Annotated[int, Field(ge=1)]
    plan_hash: Digest
    approving_user_id: UUID
    approved_at: AwareDatetime
    policy_version: ShortText
    root_skill_digest: Digest

    def require_matches(self, plan: PreparedPlan, *, now: datetime) -> None:
        """Check snapshot identity/time only, before durable state/access checks.

        This cannot establish that approval was persisted, has not been rejected
        or revoked, or that the run is still active. W3 admission must check those
        conditions under the same transaction as child admission.
        """
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValidationError(message="Approval comparison requires an aware time")
        expected = (
            plan.plan_id,
            plan.root_id,
            plan.project_id,
            plan.revision,
            plan.approval_hash(),
            plan.owner_id,
            plan.policy_version,
            plan.root.skill.digest,
        )
        actual = (
            self.plan_id,
            self.root_id,
            self.project_id,
            self.revision,
            self.plan_hash,
            self.approving_user_id,
            self.policy_version,
            self.root_skill_digest,
        )
        if (
            actual != expected
            or self.approved_at > now
            or self.approved_at >= plan.deadline
            or now >= plan.deadline
        ):
            raise Conflict(message="Approval does not match the current unexpired plan")
