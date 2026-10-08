"""Immutable pre-approval authority: one bounded root inference, no children."""

import hashlib
import json
from decimal import Decimal
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)

from app.autonomous.orchestration.contracts import (
    MAX_KNOWLEDGE_BASES,
    ChildAssignment,
    Digest,
    DocumentRef,
    ExecutionScope,
    KnowledgeBaseRef,
    Money,
    PhaseGrants,
    ShortText,
    Snapshot,
    TaskText,
    _listed_knowledge_bases,
    _numbered_selection,
)

# The thread excerpt a planning call is given (ADR 0038 D1). Bounded here so a
# retained intake can never carry more than the planning call may be sent.
MAX_THREAD_MESSAGES = 20
MAX_THREAD_MESSAGE_CHARS = 6000
MAX_THREAD_BYTES = 32768


class ThreadMessage(Snapshot):
    """One earlier message of the chat, as the planning call is shown it.

    Frozen at intake: an effect's identity covers its input, so a replay must
    read exactly what the first attempt read. ``cut`` says the text was
    shortened to fit, so the model and the owner can both see that it was.
    """

    role: Literal["user", "assistant"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=MAX_THREAD_MESSAGE_CHARS)]
    cut: bool = False


class RunTerms(Snapshot):
    """The limits a run states to its models and is held to, frozen at intake.

    Taken from the profile when the request is accepted. The run's messages
    state these numbers and the engine enforces the same ones, so a later
    change to the profile changes neither for a retained run.

    ``planning`` is how the orchestrator hands over its plan. ``text`` is a
    JSON object in the reply. ``tool`` is one call to ``propose_plan``; under
    it a reply with no call is the orchestrator's own answer, and no plan
    exists (ADR 0038 D1).

    The number of tool calls one turn may make is a constant of the engine
    (``inference.MAX_TOOL_CALLS``), not a profile's choice, and is not here.
    """

    task_turns: Annotated[int, Field(ge=0, le=16)]
    task_answer_chars: Annotated[int, Field(ge=1, le=16384)]
    answer_chars: Annotated[int, Field(ge=1, le=16384)]
    read_chars: Annotated[int, Field(ge=256, le=65536)]
    planning: Literal["text", "tool"] = "text"


class PlanningSnapshot(Snapshot):
    """Server-owned intake; deliberately cannot be used as an approved plan.

    Version 1 is the 0.8.0 fictional intake. Version 2 (ADR 0038) names the
    registry profile and carries the owner's numbered document selection, so
    the plan promoted from it must bind exactly that profile and list.
    Version 3 adds what a general request needs: the recent thread, the date
    the request was made, a run that belongs to no matter, the knowledge bases
    its tasks may search, and the run's terms.
    """

    contract_version: Literal[1, 2, 3] = 1
    plan_id: UUID
    root_id: UUID
    owner_id: UUID
    # None for a run started from a chat outside any matter. Version 3 only.
    project_id: UUID | None
    goal: TaskText
    policy_version: ShortText
    root: ExecutionScope
    delegation_grants: PhaseGrants
    budget_usd: Money
    root_allowance_usd: Money
    planning_allowance_usd: Money
    max_active_children: Annotated[int, Field(ge=1, le=4)] = 2
    deadline: AwareDatetime
    attempt_timeout_seconds: Annotated[int, Field(ge=1, le=900)] = 120
    packet_digest: Digest | None = None
    gateway_revision: Digest
    model: ShortText
    child_skill_version: ShortText
    root_skill_version: ShortText
    profile: ShortText | None = None
    documents: Annotated[tuple[DocumentRef, ...], Field(max_length=128)] = ()
    # How many tasks the total cap can fund at this profile's per-task
    # allowance. The planner is told; a larger proposal is refused as unfunded.
    max_children: Annotated[int, Field(ge=1, le=4)] = 4
    # Version 3. The chat before this request, oldest first, and the UTC date
    # of the request. Both are data for the planning call and grant nothing.
    thread: Annotated[tuple[ThreadMessage, ...], Field(max_length=MAX_THREAD_MESSAGES)] = ()
    today: Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")] | None = None
    # Version 3. The knowledge bases attached to the run's matter when the
    # request was accepted, which its tasks may search.
    knowledge_bases: Annotated[
        tuple[KnowledgeBaseRef, ...], Field(max_length=MAX_KNOWLEDGE_BASES)
    ] = ()
    # Version 3. None on an earlier version, and on a version 3 intake recorded
    # before terms were frozen; such a run reads its profile (``run_terms``).
    terms: RunTerms | None = None

    @field_validator("contract_version", mode="before")
    @classmethod
    def integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("contract version must be an integer")
        return value

    @model_validator(mode="after")
    def versioned_scope(self) -> Self:
        if self.contract_version == 1:
            if (
                self.packet_digest is None
                or self.profile is not None
                or self.documents
                or self.max_children != 4
            ):
                raise ValueError("version 1 intake is the fixed fictional packet")
        else:
            if self.profile is None:
                raise ValueError("registry intake names its profile")
            _numbered_selection(self.documents, self.root.resources)
        if self.contract_version == 3:
            if self.today is None:
                raise ValueError("version 3 intake records the date of the request")
            if sum(len(m.content.encode()) for m in self.thread) > MAX_THREAD_BYTES:
                raise ValueError("thread excerpt exceeds its bound")
            _listed_knowledge_bases(self.knowledge_bases, self.root.resources)
            if self.knowledge_bases and self.project_id is None:
                raise ValueError("a run outside a matter searches no knowledge base")
        elif (
            self.project_id is None
            or self.thread
            or self.today is not None
            or self.knowledge_bases
            or self.root.resources.knowledge_base_ids
            or self.terms is not None
        ):
            raise ValueError(
                "a thread, a date, knowledge bases, terms and a run outside a matter "
                "require version 3"
            )
        return self

    @property
    def children(self) -> tuple[ChildAssignment, ...]:
        return ()

    @property
    def revision(self) -> int:
        return 0

    @field_serializer("budget_usd", "root_allowance_usd", "planning_allowance_usd")
    def money(self, value: Decimal) -> str:
        return format(value, ".4f")

    @model_serializer(mode="wrap")
    def serialize_snapshot(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        value = handler(self)
        if self.contract_version == 1:
            # Keep a retained 0.8.0 intake's canonical form, and therefore the
            # digest its plan and planning effect are bound to, unchanged.
            value.pop("profile", None)
            value.pop("documents", None)
            value.pop("max_children", None)
        if self.contract_version < 3:
            # Likewise a version 2 intake: these fields are not part of it.
            value.pop("thread", None)
            value.pop("today", None)
        # Left out when there is nothing to say, so an intake recorded before
        # either existed keeps its digest.
        if not self.knowledge_bases:
            value.pop("knowledge_bases", None)
        if self.terms is None:
            value.pop("terms", None)
        return value

    def approval_hash(self) -> str:
        """Stable effect identity only; approval requires a PreparedPlan."""
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
