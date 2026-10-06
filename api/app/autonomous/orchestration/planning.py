"""Immutable pre-approval authority: one bounded root inference, no children."""

import hashlib
import json
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_serializer

from app.autonomous.orchestration.contracts import (
    ChildAssignment,
    Digest,
    ExecutionScope,
    Money,
    PhaseGrants,
    ShortText,
    Snapshot,
    TaskText,
)


class PlanningSnapshot(Snapshot):
    """Server-owned intake; deliberately cannot be used as an approved plan."""

    contract_version: Literal[1] = 1
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
    packet_digest: Digest
    gateway_revision: Digest
    model: ShortText
    child_skill_version: ShortText
    root_skill_version: ShortText

    @property
    def children(self) -> tuple[ChildAssignment, ...]:
        return ()

    @property
    def revision(self) -> int:
        return 0

    @field_serializer("budget_usd", "root_allowance_usd", "planning_allowance_usd")
    def money(self, value: Decimal) -> str:
        return format(value, ".4f")

    def approval_hash(self) -> str:
        """Stable effect identity only; approval requires a PreparedPlan."""
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
