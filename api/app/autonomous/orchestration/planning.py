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
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)

from app.autonomous.orchestration.contracts import (
    ChildAssignment,
    Digest,
    DocumentRef,
    ExecutionScope,
    Money,
    PhaseGrants,
    ShortText,
    Snapshot,
    TaskText,
    _numbered_selection,
)


class PlanningSnapshot(Snapshot):
    """Server-owned intake; deliberately cannot be used as an approved plan.

    Version 1 is the 0.8.0 fictional intake. Version 2 (ADR 0038) names the
    registry profile and carries the owner's numbered document selection, so
    the plan promoted from it must bind exactly that profile and list.
    """

    contract_version: Literal[1, 2] = 1
    plan_id: UUID
    root_id: UUID
    owner_id: UUID
    project_id: UUID
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
        return value

    def approval_hash(self) -> str:
        """Stable effect identity only; approval requires a PreparedPlan."""
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
