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
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    field_serializer,
    field_validator,
    model_serializer,
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
    """Pinned instructions for one session: a name and the digest of its bytes.

    ``kind`` says where the name resolves: an installed skill, or one of the
    engine's own versioned prompt files (ADR 0038 D3). A prompt name is never
    looked up in the skill library, and a skill name never among the prompts.
    A skill pin serializes without ``kind``, as it did before prompts existed,
    so a retained plan keeps the hash its approval is bound to.
    """

    name: ShortText
    digest: Digest
    kind: Literal["skill", "prompt"] = "skill"

    @model_serializer(mode="wrap")
    def serialize_pin(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        value = handler(self)
        if self.kind == "skill":
            value.pop("kind", None)
        return value


MAX_KNOWLEDGE_BASES = 16


class ResourceScope(Snapshot):
    """Selected document IDs and configured source names, including empty scope.

    The resolver must check adapter-specific operations at call time; a source
    name never grants every operation offered by that provider.

    ``knowledge_base_ids`` are the knowledge bases a run may search (ADR 0038
    D5): the ones attached to its matter when the request was accepted. Being
    listed grants no search. Each call rechecks that the knowledge base is
    still the owner's, not archived and still attached to the run's matter.
    """

    document_ids: Annotated[tuple[UUID, ...], Field(max_length=128)]
    source_names: Annotated[tuple[ShortText, ...], Field(max_length=32)]
    knowledge_base_ids: Annotated[tuple[UUID, ...], Field(max_length=MAX_KNOWLEDGE_BASES)] = ()

    @field_validator("document_ids", "source_names", "knowledge_base_ids")
    @classmethod
    def unique_selections(cls, value: tuple) -> tuple:
        if len(set(value)) != len(value):
            raise ValueError("duplicate selected resource")
        return tuple(sorted(value))

    @model_serializer(mode="wrap")
    def serialize_scope(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        value = handler(self)
        if not self.knowledge_base_ids:
            # A scope without knowledge bases keeps the form it had before they
            # existed. This dump is part of every plan's and intake's hash.
            value.pop("knowledge_base_ids", None)
        return value

    def contains(self, other: ResourceScope) -> bool:
        return (
            set(other.document_ids) <= set(self.document_ids)
            and set(other.source_names) <= set(self.source_names)
            and set(other.knowledge_base_ids) <= set(self.knowledge_base_ids)
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


class PhaseTools(Snapshot):
    """Registry tool names a model may be offered in each phase (ADR 0038 D3, D4).

    Names, not authority. Every call still needs the matching intent in
    ``PhaseGrants``, current operator policy and durable effect admission. The
    plan carries this list so approval of the exact plan is consent for it.
    """

    intake: tuple[ShortText, ...] = ()
    analysis: tuple[ShortText, ...] = ()
    drafting: tuple[ShortText, ...] = ()
    ethics_review: tuple[ShortText, ...] = ()
    delivery: tuple[ShortText, ...] = ()

    @field_validator("*")
    @classmethod
    def unique_tools(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate tool")
        return tuple(sorted(value))

    def for_phase(self, phase: Phase) -> tuple[str, ...]:
        return getattr(self, phase.value)

    def contains(self, other: PhaseTools) -> bool:
        return all(set(other.for_phase(p)) <= set(self.for_phase(p)) for p in Phase)

    def names(self) -> frozenset[str]:
        return frozenset(name for p in Phase for name in self.for_phase(p))


class DocumentRef(Snapshot):
    """One owner-selected document, numbered in selection order (ADR 0038 D5).

    The number is what a child cites and what the read tool accepts. The file
    name is display data from the owner's own record. Neither grants a read:
    the boundary rechecks selection, ownership and project attachment.
    """

    number: Annotated[int, Field(ge=1, le=128)]
    document_id: UUID
    file_id: UUID
    filename: ShortText
    attached_for_run: bool = False


class KnowledgeBaseRef(Snapshot):
    """One knowledge base a run's tasks may search, as the plan lists it (ADR 0038 D5).

    The name is display data from the owner's own record, taken when the
    request was accepted. Neither field grants a search: the boundary rechecks
    ownership, archival and attachment to the run's matter at every call.
    """

    knowledge_base_id: UUID
    name: ShortText


def _numbered_selection(documents: tuple[DocumentRef, ...], resources: ResourceScope) -> None:
    if [d.number for d in documents] != list(range(1, len(documents) + 1)):
        raise ValueError("selected documents must be numbered in order")
    if len({d.file_id for d in documents}) != len(documents) or {
        d.document_id for d in documents
    } != set(resources.document_ids):
        raise ValueError("selected documents differ from the root resource scope")


def _listed_knowledge_bases(
    knowledge_bases: tuple[KnowledgeBaseRef, ...], resources: ResourceScope
) -> None:
    ids = [k.knowledge_base_id for k in knowledge_bases]
    if len(set(ids)) != len(ids) or set(ids) != set(resources.knowledge_base_ids):
        raise ValueError("listed knowledge bases differ from the root resource scope")


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
    # Contract version 3 (ADR 0038 D4). Omitted from earlier plans' canonical
    # form by PreparedPlan's serializer, so retained approvals keep their hash.
    tools: PhaseTools = PhaseTools()
    turn_limit: Annotated[int, Field(ge=0, le=16)] = 0

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

    contract_version: Literal[1, 2, 3] = 1
    planning_digest: Digest | None = None
    # Contract version 3 (ADR 0038): the registry profile and the numbered
    # document selection are part of what the owner approves.
    profile: ShortText | None = None
    documents: Annotated[tuple[DocumentRef, ...], Field(max_length=128)] = ()
    # The knowledge bases the tasks may search, named so that approving the
    # plan is consent to it. Version 3 only; left out of the canonical form
    # when there are none.
    knowledge_bases: Annotated[
        tuple[KnowledgeBaseRef, ...], Field(max_length=MAX_KNOWLEDGE_BASES)
    ] = ()
    plan_id: UUID
    revision: Annotated[int, Field(ge=1)]
    root_id: UUID
    # None for a run started from a chat outside any matter (ADR 0038 D1).
    # Required, never defaulted: a plan always states which it is.
    project_id: UUID | None
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
        if (self.contract_version >= 2) != (self.planning_digest is not None):
            raise ValueError("model plans require their planning scope digest")
        if self.project_id is None and self.contract_version != 3:
            raise ValueError("only a registry plan can run outside a matter")
        if self.contract_version == 3:
            if self.profile is None:
                raise ValueError("registry plans name their profile")
            _numbered_selection(self.documents, self.root.resources)
            _listed_knowledge_bases(self.knowledge_bases, self.root.resources)
            if self.knowledge_bases and self.project_id is None:
                raise ValueError("a run outside a matter searches no knowledge base")
        elif (
            self.profile is not None
            or self.documents
            or self.knowledge_bases
            or self.root.resources.knowledge_base_ids
            or any(child.tools.names() or child.turn_limit for child in self.children)
        ):
            raise ValueError("profiles, documents and tools require contract version 3")
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
            if scope.minimum_inference_tier > self.root.minimum_inference_tier:
                raise ValueError("child weakens minimum inference tier")
            if scope.maximum_egress_tier > self.root.maximum_egress_tier:
                raise ValueError("child weakens maximum egress tier")
            if self.root.privileged and not scope.privileged:
                raise ValueError("child drops privileged classification")
            if self.root.anonymize and not scope.anonymize:
                raise ValueError("child disables required anonymization")
            if bool(child.tools.names()) != bool(child.turn_limit):
                raise ValueError("a tool grant and a turn limit are set together")
        return self

    @model_serializer(mode="wrap")
    def serialize_plan(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        value = handler(self)
        if self.contract_version == 1:
            value.pop("planning_digest", None)
        if self.contract_version < 3:
            # Fields added for version 3 must not enter an earlier plan's
            # canonical form: its stored hash is the owner's consent binding.
            value.pop("profile", None)
            value.pop("documents", None)
            for child in value["children"]:
                child.pop("tools", None)
                child.pop("turn_limit", None)
        if not self.knowledge_bases:
            # Likewise a plan with no knowledge bases, of any version.
            value.pop("knowledge_bases", None)
        return value

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


@dataclass(frozen=True)
class RunCorrelation:
    """The chat turn a run is bound to (ADR 0038 D1, D2).

    Resolved by the server from the message's link to the run's root session,
    never from model output. It labels routing-log and tool-call-log rows so a
    run is found through the same channels as an ordinary chat turn. It is not
    part of an effect's identity and grants nothing.
    """

    chat_id: UUID
    message_id: UUID


class ApprovalBinding(Snapshot):
    """Consent evidence read from server-owned storage; never a bearer token."""

    plan_id: UUID
    root_id: UUID
    project_id: UUID | None
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
