"""Autonomous-layer ORM models — M4-A1, M4-A3.2.

Data substrate for the per-user Autonomous agent
([PRD §3.10](docs/PRD.md#310-autonomous-layer-m4),
[ADR-0013](docs/adr/0013-autonomous-layer-design-influences.md)). The
agent runs scheduled / triggered work under cost, halt, and phase
brakes. M4-A1 lands only the tables, models, and schemas — no executor,
no API endpoints, no business logic. M4-A3.2 adds the in-app
notification substrate (``autonomous_notifications``).

Five tables (migration ``0039_autonomous_layer.py``) + one from 0040:

* :class:`AutonomousSession` — the run record carrying the brakes
  (cost cap, halt state, idle-halt window, phase machine).
* :class:`AutonomousSchedule` — a cron-triggered run definition.
* :class:`AutonomousWatch` — a KB-change-triggered run definition.
* :class:`AutonomousMemory` — proposed / kept / dismissed memory notes
  the agent surfaces for user curation.
* :class:`PrecedentEntry` — observed precedent patterns across a user's
  sessions.
* :class:`ProjectContextProposal` — a proposal to promote a precedent
  into a Project's context (migration 0041); the user accepting it is
  the authorized ``context_md`` write (ADR 0013 D5).
* :class:`AutonomousNotification` — durable in-app notification written
  by the ``notify`` chokepoint handler (A3.3); migration 0040.

Every table carries a non-null ``user_id`` FK with ``ON DELETE
CASCADE`` — the autonomous layer is **hard per-user isolated**. A
user's deletion removes all of their autonomous state. This differs
from the playbook tables (which ``SET NULL`` to preserve shared audit
history) because autonomous sessions are private to the operator who
ran them and carry no shared work product.

The CHECK constraints on the session enums + ``autonomous_memory.state``
are enforced at the storage layer (see migration 0039); the canonical
``StrEnum`` definitions live in :mod:`app.schemas.autonomous` so models
and future code share one source of truth.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AutonomousSession(Base):
    """One run of the autonomous agent — the brake-bearing record.

    ``status`` is the lifecycle (``running → completed | halted |
    failed``); ``halt_state`` is the orthogonal brake state
    (``running``, ``halt_requested``, ``halted``, ``paused``) the
    executor checks at every step. ``current_phase`` walks the
    phase machine (``intake → analysis → drafting → ethics_review →
    delivery``).

    Cost brakes: ``max_cost_usd`` is the per-session cap (NULL = no
    cap); ``cost_total_usd`` accumulates as the executor spends;
    ``cost_cap_reached`` latches true when the cap is hit. Idle brake:
    if no activity for ``idle_halt_minutes`` past ``last_activity_at``,
    the session self-halts.

    ``params`` is the trigger→target seam (M4-B3, migration 0042): every
    trigger source populates the non-null subset of ``{"kb_id",
    "playbook_id", "skill_ref", "query"}`` and the executor reads it into
    ``initial_state`` — uniform across schedule / watch / manual triggers.
    """

    __tablename__ = "autonomous_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_autonomous_sessions_user_id"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL", name="fk_autonomous_sessions_project_id"),
        nullable=True,
    )
    trigger_kind: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_ref: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    current_phase: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'intake'")
    )
    halt_state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'running'"))
    max_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    cost_total_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, server_default=text("0")
    )
    cost_cap_reached: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    idle_halt_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5")
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'running'"))
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<AutonomousSession id={self.id} user_id={self.user_id} "
            f"phase={self.current_phase!r} halt={self.halt_state!r} status={self.status!r}>"
        )


class AutonomousSchedule(Base):
    """A cron-triggered run definition for the autonomous agent.

    ``cron_expr`` is a standard five-field cron string the scheduler
    parses. ``playbook_id`` / ``skill_ref`` / ``target_kb_id`` describe
    what the triggered session runs (a playbook, a skill, against a KB).
    Soft-deleted via ``deleted_at`` so a disabled-then-removed schedule
    keeps its audit trail.
    """

    __tablename__ = "autonomous_schedules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_autonomous_schedules_user_id"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL", name="fk_autonomous_schedules_project_id"),
        nullable=True,
    )
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    cron_expr: Mapped[str] = mapped_column(Text, nullable=False)
    playbook_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("playbooks.id", ondelete="SET NULL", name="fk_autonomous_schedules_playbook_id"),
        nullable=True,
    )
    skill_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_kb_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "knowledge_bases.id",
            ondelete="SET NULL",
            name="fk_autonomous_schedules_target_kb_id",
        ),
        nullable=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    max_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    def __repr__(self) -> str:
        return (
            f"<AutonomousSchedule id={self.id} user_id={self.user_id} "
            f"cron={self.cron_expr!r} enabled={self.enabled}>"
        )


class AutonomousWatch(Base):
    """A KB-change-triggered run definition for the autonomous agent.

    When the watched ``knowledge_base_id`` changes (a new file ingested),
    the agent starts a session running ``playbook_id`` / ``skill_ref``
    against the change. Soft-deleted via ``deleted_at``.
    """

    __tablename__ = "autonomous_watches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_autonomous_watches_user_id"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL", name="fk_autonomous_watches_project_id"),
        nullable=True,
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "knowledge_bases.id",
            ondelete="CASCADE",
            name="fk_autonomous_watches_knowledge_base_id",
        ),
        nullable=False,
    )
    playbook_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("playbooks.id", ondelete="SET NULL", name="fk_autonomous_watches_playbook_id"),
        nullable=True,
    )
    skill_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    max_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    def __repr__(self) -> str:
        return (
            f"<AutonomousWatch id={self.id} user_id={self.user_id} "
            f"kb={self.knowledge_base_id} enabled={self.enabled}>"
        )


class AutonomousMemory(Base):
    """A memory note the agent proposes for user curation.

    ``state`` walks ``proposed → kept | dismissed``. ``category`` is a
    free-form bucket (e.g. ``"drafting_preference"``). ``content`` is the
    note text. ``source_session_id`` links back to the session that
    proposed the note (NULL if the source session is later deleted via
    ``ON DELETE SET NULL``). ``kept_at`` is set when the user keeps the
    note. Soft-deleted via ``deleted_at``.
    """

    __tablename__ = "autonomous_memory"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_autonomous_memory_user_id"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "autonomous_sessions.id",
            ondelete="SET NULL",
            name="fk_autonomous_memory_source_session_id",
        ),
        nullable=True,
    )
    kept_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    def __repr__(self) -> str:
        return (
            f"<AutonomousMemory id={self.id} user_id={self.user_id} "
            f"state={self.state!r} category={self.category!r}>"
        )


class PrecedentEntry(Base):
    """An observed precedent pattern across a user's autonomous sessions.

    ``pattern_kind`` is a free-form classifier (e.g. ``"liability_cap"``);
    ``summary`` describes the pattern; ``observed_count`` increments each
    time the pattern recurs. ``source_session_id`` links to the session
    that first observed it (``ON DELETE SET NULL``). ``dismissed_at`` is
    set when the user dismisses the precedent.
    """

    __tablename__ = "precedent_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_precedent_entries_user_id"),
        nullable=False,
    )
    pattern_kind: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    observed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "autonomous_sessions.id",
            ondelete="SET NULL",
            name="fk_precedent_entries_source_session_id",
        ),
        nullable=True,
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    def __repr__(self) -> str:
        return (
            f"<PrecedentEntry id={self.id} user_id={self.user_id} "
            f"pattern_kind={self.pattern_kind!r} observed={self.observed_count}>"
        )


class ProjectContextProposal(Base):
    """A proposal to promote a precedent into a Project's context document.

    The autonomous agent (or a user) may surface "promote this recurring
    precedent into Project X's context", but the agent NEVER writes a
    Project's ``context_md`` directly (ADR 0013 D5). This row records the
    *proposal*; the user accepting it (``POST …/accept``) is the
    authorized write that appends ``suggested_md`` to
    ``projects.context_md``.

    ``state`` walks ``proposed → accepted | rejected`` (CHECK
    ``chk_project_context_proposals_state``). ``suggested_md`` is the
    server-derived context snippet. ``accepted_at`` / ``rejected_at``
    timestamp the terminal transitions.

    All three FKs (``user_id``, ``precedent_id``, ``project_id``) are
    ``ON DELETE CASCADE`` — the autonomous layer is hard per-user isolated
    and a proposal is meaningless without its precedent or target project.
    Migration ``0041_project_context_proposals.py``.
    """

    __tablename__ = "project_context_proposals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_project_context_proposals_user_id",
        ),
        nullable=False,
    )
    precedent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "precedent_entries.id",
            ondelete="CASCADE",
            name="fk_project_context_proposals_precedent_id",
        ),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "projects.id",
            ondelete="CASCADE",
            name="fk_project_context_proposals_project_id",
        ),
        nullable=False,
    )
    suggested_md: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'proposed'"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectContextProposal id={self.id} user_id={self.user_id} "
            f"project_id={self.project_id} state={self.state!r}>"
        )


class AutonomousFinding(Base):
    """A persisted analysis finding emitted by an autonomous run.

    Findings are the core work-product of a run — written by the
    ``emit_finding`` chokepoint handler each time a node emits one. Until
    now findings were echoed into transient LangGraph state and discarded
    after the run; only a count survived. This table makes a run's
    findings readable back later (read endpoint + contract follow).

    Unlike the other autonomous enum columns (which carry CHECK
    constraints — see migrations 0039/0040), ``severity`` deliberately has
    NO CHECK: it is LLM-emitted free text, so we persist whatever the model
    produces (``info`` | ``warn`` | ``critical`` are the intended values,
    but a stray ``high`` etc. must store, not reject the finding row).
    ``title`` is the short headline; ``content`` is the finding's summary
    body.

    ``session_id`` FK is ``ON DELETE CASCADE`` — a finding belongs to one
    session and is meaningless without it; deleting the session deletes its
    findings. There is no ``user_id`` column: authz is via the owning
    session (the read endpoint owner-gates by loading the owned session,
    then queries by ``session_id``).
    """

    __tablename__ = "autonomous_findings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "autonomous_sessions.id",
            ondelete="CASCADE",
            name="fk_autonomous_findings_session_id",
        ),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    def __repr__(self) -> str:
        return (
            f"<AutonomousFinding id={self.id} session_id={self.session_id} "
            f"severity={self.severity!r} title={self.title!r}>"
        )


class AutonomousNotification(Base):
    """A durable in-app notification written by the autonomous agent.

    Written by the ``notify`` chokepoint handler (A3.3) when a session
    completes or reaches a notable state. ``channel`` defaults to
    ``'in_app'``; ``'email'`` and ``'webhook'`` are in the CHECK so
    M4-C1's fold-in (email transport, webhook dispatch per DE-312) is
    purely additive. ``webhook`` is RESERVED until DE-312.

    ``body`` carries counts/types/IDs + a link to the receipt — **never
    raw entity values**. ``payload`` is optional structured JSONB the
    web renders (same constraint: no raw values).

    ``read_at`` IS NULL = unread. The read/dismiss API that marks this
    column lands in M4-C1.

    Both ``user_id`` and ``session_id`` FK with ``ON DELETE CASCADE`` —
    notifications cascade with their parent session and their owner user.
    """

    __tablename__ = "autonomous_notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_autonomous_notifications_user_id",
        ),
        nullable=False,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "autonomous_sessions.id",
            ondelete="CASCADE",
            name="fk_autonomous_notifications_session_id",
        ),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'in_app'"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    def __repr__(self) -> str:
        return (
            f"<AutonomousNotification id={self.id} user_id={self.user_id} "
            f"channel={self.channel!r} title={self.title!r}>"
        )
