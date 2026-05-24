"""Pydantic schemas + shared enums for the Autonomous layer — M4-A1.

Wire shapes and the canonical ``StrEnum`` definitions for the per-user
autonomous agent ([PRD §3.10](docs/PRD.md#310-autonomous-layer-m4),
[ADR-0013](docs/adr/0013-autonomous-layer-design-influences.md)). The
ORM models live in :mod:`app.models.autonomous`; this module is the
read/response surface plus the single source of truth for the enums so
models, the executor (later M4 tasks), and future endpoints all share
one definition.

The enums are ``StrEnum`` so their members serialize to the plain
string the CHECK constraints in migration ``0039_autonomous_layer.py``
enforce — ``Phase.intake == "intake"`` etc. Request schemas for the API
surfaces land with their respective API tasks; M4-A1 only adds the
enums plus ORM-read models the migration/models justify.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class TriggerKind(StrEnum):
    """How an autonomous session was started.

    Matches the CHECK constraint on ``autonomous_sessions.trigger_kind``.
    """

    watch = "watch"
    schedule = "schedule"
    suggestion = "suggestion"
    manual = "manual"


class Phase(StrEnum):
    """The agent's phase machine — sessions advance through these in order.

    Matches the CHECK constraint on ``autonomous_sessions.current_phase``.
    """

    intake = "intake"
    analysis = "analysis"
    drafting = "drafting"
    ethics_review = "ethics_review"
    delivery = "delivery"


class HaltState(StrEnum):
    """The brake state of a session — orthogonal to ``status``.

    Matches the CHECK constraint on ``autonomous_sessions.halt_state``.
    """

    running = "running"
    halt_requested = "halt_requested"
    halted = "halted"
    paused = "paused"


class SessionStatus(StrEnum):
    """Terminal-or-running lifecycle of a session.

    Matches the CHECK constraint on ``autonomous_sessions.status``.
    """

    running = "running"
    completed = "completed"
    halted = "halted"
    failed = "failed"


class MemoryState(StrEnum):
    """Review state of an autonomous-memory note.

    Matches the CHECK constraint on ``autonomous_memory.state``.
    """

    proposed = "proposed"
    kept = "kept"
    dismissed = "dismissed"


class AutonomousSessionRead(BaseModel):
    """ORM-read view of an :class:`~app.models.autonomous.AutonomousSession`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID | None = None
    trigger_kind: TriggerKind
    trigger_ref: uuid.UUID | None = None
    current_phase: Phase
    halt_state: HaltState
    max_cost_usd: Decimal | None = None
    cost_total_usd: Decimal
    cost_cap_reached: bool
    idle_halt_minutes: int
    last_activity_at: datetime
    status: SessionStatus
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class AutonomousScheduleRead(BaseModel):
    """ORM-read view of an :class:`~app.models.autonomous.AutonomousSchedule`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID | None = None
    name: str | None = None
    cron_expr: str
    playbook_id: uuid.UUID | None = None
    skill_ref: str | None = None
    target_kb_id: uuid.UUID | None = None
    enabled: bool
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AutonomousWatchRead(BaseModel):
    """ORM-read view of an :class:`~app.models.autonomous.AutonomousWatch`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID | None = None
    knowledge_base_id: uuid.UUID
    playbook_id: uuid.UUID | None = None
    skill_ref: str | None = None
    enabled: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AutonomousMemoryRead(BaseModel):
    """ORM-read view of an :class:`~app.models.autonomous.AutonomousMemory`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    state: MemoryState
    category: str
    content: str
    source_session_id: uuid.UUID | None = None
    kept_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PrecedentEntryRead(BaseModel):
    """ORM-read view of a :class:`~app.models.autonomous.PrecedentEntry`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    pattern_kind: str
    summary: str
    observed_count: int
    source_session_id: uuid.UUID | None = None
    dismissed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
