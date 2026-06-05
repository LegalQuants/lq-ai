"""Pydantic schemas + shared enums for the Autonomous layer — M4-A1, M4-A3.2.

Wire shapes and the canonical ``StrEnum`` definitions for the per-user
autonomous agent ([PRD §3.10](docs/PRD.md#310-autonomous-layer-m4),
[ADR-0013](docs/adr/0013-autonomous-layer-design-influences.md)). The
ORM models live in :mod:`app.models.autonomous`; this module is the
read/response surface plus the single source of truth for the enums so
models, the executor (later M4 tasks), and future endpoints all share
one definition.

The enums are ``StrEnum`` so their members serialize to the plain
string the CHECK constraints in migrations ``0039_autonomous_layer.py``
and ``0040_autonomous_notifications.py`` enforce — ``Phase.intake ==
"intake"`` etc. Request schemas for the API surfaces land with their
respective API tasks; M4-A1 only adds the enums plus ORM-read models
the migration/models justify. M4-A3.2 adds :class:`NotificationChannel`
and :class:`AutonomousNotificationRead`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


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


class ProposalState(StrEnum):
    """Lifecycle state of a project-context promotion proposal.

    Matches the CHECK constraint on ``project_context_proposals.state``
    (migration ``0041_project_context_proposals.py``).
    """

    proposed = "proposed"
    accepted = "accepted"
    rejected = "rejected"


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
    params: dict[str, Any] = {}
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
    max_cost_usd: Decimal | None = None
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AutonomousScheduleCreate(BaseModel):
    """Request body for ``POST /autonomous/schedules`` (M4-B3).

    ``cron_expr`` is required and validated by
    :func:`app.autonomous.cron.validate_cron_expr` (invalid → 422). The
    target (``playbook_id`` / ``skill_ref`` / ``target_kb_id``) and
    ``project_id`` are optional; ``enabled`` defaults to True.
    ``max_cost_usd`` is the per-schedule spend cap (NULL = fall back to
    ``settings.autonomous_default_max_cost_usd`` at spawn time).
    """

    cron_expr: str
    name: str | None = None
    playbook_id: uuid.UUID | None = None
    skill_ref: str | None = None
    target_kb_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    enabled: bool = True
    max_cost_usd: Decimal | None = None


class AutonomousScheduleUpdate(BaseModel):
    """Request body for ``PATCH /autonomous/schedules/{id}`` (M4-B3).

    All fields optional — a partial update. If ``cron_expr`` is provided
    it is re-validated (invalid → 422) and ``next_run_at`` is recomputed.
    Toggling ``enabled`` is allowed. ``max_cost_usd`` may be edited
    (NULL clears the per-schedule cap → fall back to global default).
    The matter (``project_id``) may be reassigned; an explicit ``null``
    clears it (unassign). A non-null ``project_id`` the caller does not
    own is rejected (404, id-probing-safe).
    """

    name: str | None = None
    cron_expr: str | None = None
    enabled: bool | None = None
    playbook_id: uuid.UUID | None = None
    skill_ref: str | None = None
    target_kb_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    max_cost_usd: Decimal | None = None


class AutonomousManualRunRequest(BaseModel):
    """Request body for ``POST /autonomous/run-now`` (Phase 1, §4.4).

    Spawns a single one-off autonomous session (``trigger_kind='manual'``)
    so a user can test what a skill/playbook does — and inspect the
    resulting receipt — before arming it as a schedule or watch. Exactly
    one of ``playbook_id`` / ``skill_ref`` must be set (the agent runs an
    existing artifact; custom-task authoring is out of scope for Phase 1).
    ``target_kb_id`` and ``project_id`` are optional scope. ``max_cost_usd``
    is the per-run cap (NULL = fall back to
    ``settings.autonomous_default_max_cost_usd`` at spawn time, so R4 always
    trips).
    """

    playbook_id: uuid.UUID | None = None
    skill_ref: str | None = None
    target_kb_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    max_cost_usd: Decimal | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> AutonomousManualRunRequest:
        if (self.playbook_id is None) == (self.skill_ref is None):
            raise ValueError("exactly one of playbook_id or skill_ref must be set")
        return self


class AutonomousScheduleListResponse(BaseModel):
    """Paginated list of :class:`AutonomousScheduleRead` items (M4-B3).

    Mirrors ``AutonomousMemoryListResponse`` — total_count / limit /
    offset envelope. Excludes soft-deleted schedules (``deleted_at IS
    NULL``).
    """

    schedules: list[AutonomousScheduleRead]
    total_count: int
    limit: int
    offset: int


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
    max_cost_usd: Decimal | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AutonomousWatchCreate(BaseModel):
    """Request body for ``POST /autonomous/watches`` (M4-B4).

    ``knowledge_base_id`` is required — the KB whose document arrivals
    trigger a session. The caller must own that KB (404 otherwise;
    KB-sharing is out of scope). The target (``playbook_id`` /
    ``skill_ref``) and ``project_id`` are optional; ``enabled`` defaults
    to True. The watch is bound to its KB — there is no
    ``knowledge_base_id`` on the update schema (create a new watch for a
    different KB). ``max_cost_usd`` is the per-watch spend cap (NULL =
    fall back to ``settings.autonomous_default_max_cost_usd`` at spawn
    time).
    """

    knowledge_base_id: uuid.UUID
    playbook_id: uuid.UUID | None = None
    skill_ref: str | None = None
    project_id: uuid.UUID | None = None
    enabled: bool = True
    max_cost_usd: Decimal | None = None


class AutonomousWatchUpdate(BaseModel):
    """Request body for ``PATCH /autonomous/watches/{id}`` (M4-B4).

    All fields optional — a partial update. Toggling ``enabled`` is
    allowed; ``playbook_id`` / ``skill_ref`` may be retargeted. The
    watch's ``knowledge_base_id`` is immutable (not present here) — a
    watch is bound to its KB. ``max_cost_usd`` may be edited (NULL clears
    the per-watch cap → fall back to global default). The matter
    (``project_id``) may be reassigned; an explicit ``null`` clears it
    (unassign). A non-null ``project_id`` the caller does not own is
    rejected (404, id-probing-safe).
    """

    enabled: bool | None = None
    playbook_id: uuid.UUID | None = None
    skill_ref: str | None = None
    project_id: uuid.UUID | None = None
    max_cost_usd: Decimal | None = None


class AutonomousWatchListResponse(BaseModel):
    """Paginated list of :class:`AutonomousWatchRead` items (M4-B4).

    Mirrors ``AutonomousScheduleListResponse`` — total_count / limit /
    offset envelope. Excludes soft-deleted watches (``deleted_at IS
    NULL``).
    """

    watches: list[AutonomousWatchRead]
    total_count: int
    limit: int
    offset: int


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


class PrecedentEntryListResponse(BaseModel):
    """Paginated list of :class:`PrecedentEntryRead` items (M4-B2).

    Mirrors ``AutonomousMemoryListResponse`` — total_count / limit /
    offset envelope. Excludes dismissed entries (``dismissed_at IS NULL``).
    """

    entries: list[PrecedentEntryRead]
    total_count: int
    limit: int
    offset: int


class ProjectContextProposalRead(BaseModel):
    """ORM-read view of a :class:`~app.models.autonomous.ProjectContextProposal`.

    A proposal to promote a precedent into a Project's context document.
    ``state`` walks ``proposed → accepted | rejected``; only the user
    accepting a proposal writes ``projects.context_md`` (ADR 0013 D5).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    precedent_id: uuid.UUID
    project_id: uuid.UUID
    suggested_md: str
    state: ProposalState
    accepted_at: datetime | None = None
    rejected_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProjectContextProposalListResponse(BaseModel):
    """Paginated list of :class:`ProjectContextProposalRead` items (M4-B2).

    Mirrors ``AutonomousMemoryListResponse`` — total_count / limit /
    offset envelope.
    """

    proposals: list[ProjectContextProposalRead]
    total_count: int
    limit: int
    offset: int


class PromotePrecedentRequest(BaseModel):
    """Request body for ``POST /autonomous/precedents/{id}/promote``.

    ``project_id`` is the target Project; the caller must own it (404
    otherwise). The ``suggested_md`` snippet is derived server-side from
    the precedent's ``summary`` — the client does not supply it.
    """

    project_id: uuid.UUID


class NotificationChannel(StrEnum):
    """Delivery channel for an autonomous notification.

    Matches the CHECK constraint on ``autonomous_notifications.channel``
    (migration ``0040_autonomous_notifications.py``). ``webhook`` is
    RESERVED — present in the enum so M4-C1's fold-in is purely additive,
    but not dispatched until DE-312 (Decision M4-8).
    """

    in_app = "in_app"
    email = "email"
    webhook = "webhook"  # RESERVED — dispatch lands in M4-C1 (DE-312)


class MemoryKeepRequest(BaseModel):
    """Optional request body for ``POST /autonomous/memory/{id}/keep``.

    If ``content`` is provided, the memory entry's text is overwritten on
    keep (edit-on-keep).  Omitting the body entirely (or sending ``{}``
    or ``{"content": null}``) leaves the existing content unchanged.
    """

    content: str | None = None


class AutonomousMemoryListResponse(BaseModel):
    """Paginated list of :class:`AutonomousMemoryRead` items (M4-B1).

    Mirrors ``AutonomousSessionListResponse`` — total_count / limit /
    offset envelope for consistent pagination conventions across the API.
    Excludes soft-deleted entries (``deleted_at IS NULL``).
    """

    entries: list[AutonomousMemoryRead]
    total_count: int
    limit: int
    offset: int


class AutonomousSessionListResponse(BaseModel):
    """Paginated list of :class:`AutonomousSessionRead` items.

    Mirrors ``AdminUserListResponse`` (total_count / limit / offset
    envelope) for consistent pagination conventions across the API.
    """

    sessions: list[AutonomousSessionRead]
    total_count: int
    limit: int
    offset: int


class AutonomousSessionDetailResponse(BaseModel):
    """Session detail view including the live-reconstructed receipt.

    ``receipt`` is built by :func:`~app.autonomous.receipt.build_receipt`
    on every request — it works for running and completed sessions alike.
    A completed session also has the receipt persisted in ``result``.
    """

    session: AutonomousSessionRead
    receipt: dict[str, Any]


class AutonomousNotificationRead(BaseModel):
    """ORM-read view of an :class:`~app.models.autonomous.AutonomousNotification`.

    Written by the ``notify`` chokepoint handler (A3.3). ``read_at`` IS
    NULL = unread. The read/dismiss API that marks this column, plus email
    transport and webhook dispatch, land in M4-C1.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    session_id: uuid.UUID
    channel: NotificationChannel
    title: str
    body: str
    payload: dict[str, Any] | None = None
    read_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AutonomousNotificationListResponse(BaseModel):
    """Paginated list of :class:`AutonomousNotificationRead` items (M4-C1).

    Mirrors ``AutonomousMemoryListResponse`` — total_count / limit /
    offset envelope. ``read_at IS NULL`` = unread; the ``?unread=true``
    filter on ``GET /autonomous/notifications`` narrows to unread rows.
    """

    notifications: list[AutonomousNotificationRead]
    total_count: int
    limit: int
    offset: int
