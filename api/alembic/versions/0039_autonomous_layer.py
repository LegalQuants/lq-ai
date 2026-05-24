"""autonomous-layer data model — M4-A1

Creates the five tables that form the data substrate for the per-user
Autonomous agent ([PRD §3.10](docs/PRD.md#310-autonomous-layer-m4),
[ADR-0013](docs/adr/0013-autonomous-layer-design-influences.md)):

* ``autonomous_sessions`` — the brake-bearing run record (cost cap,
  halt state, idle-halt window, phase machine).
* ``autonomous_schedules`` — cron-triggered run definitions.
* ``autonomous_watches`` — KB-change-triggered run definitions.
* ``autonomous_memory`` — proposed / kept / dismissed memory notes.
* ``precedent_entries`` — observed precedent patterns.

Every table carries a non-null ``user_id`` FK with ``ON DELETE
CASCADE`` — the autonomous layer is hard per-user isolated. This
supersedes the sketched ``autonomous_tasks`` placeholder in
``docs/db-schema.md``; ``autonomous_tasks`` was a single-table sketch
that the design (ADR-0013) split into the brake-bearing
``autonomous_sessions`` plus the four primitive tables here.

No executor / API / business logic lands in this migration — only the
schema (M4-A1).

Revision ID: 0039
Revises: 0038
Create Date: 2026-05-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------
    # autonomous_sessions — the brake-bearing run record
    # ---------------------------------------------------------------
    op.create_table(
        "autonomous_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_autonomous_sessions_user_id"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "projects.id", ondelete="SET NULL", name="fk_autonomous_sessions_project_id"
            ),
            nullable=True,
        ),
        sa.Column("trigger_kind", sa.Text(), nullable=False),
        sa.Column("trigger_ref", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "current_phase",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'intake'"),
        ),
        sa.Column(
            "halt_state",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'running'"),
        ),
        sa.Column("max_cost_usd", sa.Numeric(10, 4), nullable=True),
        sa.Column(
            "cost_total_usd",
            sa.Numeric(10, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cost_cap_reached",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "idle_halt_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("5"),
        ),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'running'"),
        ),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "trigger_kind IN ('watch','schedule','suggestion','manual')",
            name="chk_autonomous_sessions_trigger_kind",
        ),
        sa.CheckConstraint(
            "current_phase IN ('intake','analysis','drafting','ethics_review','delivery')",
            name="chk_autonomous_sessions_current_phase",
        ),
        sa.CheckConstraint(
            "halt_state IN ('running','halt_requested','halted','paused')",
            name="chk_autonomous_sessions_halt_state",
        ),
        sa.CheckConstraint(
            "status IN ('running','completed','halted','failed')",
            name="chk_autonomous_sessions_status",
        ),
    )
    # "My recent sessions" view for the UI.
    op.create_index(
        "idx_autonomous_sessions_user_created",
        "autonomous_sessions",
        ["user_id", sa.text("created_at DESC")],
    )
    # The scheduler's "which running sessions need a halt/idle check?" scan.
    op.create_index(
        "idx_autonomous_sessions_active",
        "autonomous_sessions",
        ["halt_state", "last_activity_at"],
        postgresql_where=sa.text("status = 'running'"),
    )

    # ---------------------------------------------------------------
    # autonomous_schedules — cron-triggered run definitions
    # ---------------------------------------------------------------
    op.create_table(
        "autonomous_schedules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_autonomous_schedules_user_id"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "projects.id", ondelete="SET NULL", name="fk_autonomous_schedules_project_id"
            ),
            nullable=True,
        ),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("cron_expr", sa.Text(), nullable=False),
        sa.Column(
            "playbook_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "playbooks.id", ondelete="SET NULL", name="fk_autonomous_schedules_playbook_id"
            ),
            nullable=True,
        ),
        sa.Column("skill_ref", sa.Text(), nullable=True),
        sa.Column(
            "target_kb_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "knowledge_bases.id",
                ondelete="SET NULL",
                name="fk_autonomous_schedules_target_kb_id",
            ),
            nullable=True,
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Index deferred to M4-B3 (scheduler dispatcher) when the next_run_at
    # scan query shape (likely `enabled AND deleted_at IS NULL ORDER BY
    # next_run_at`) is concrete.

    # ---------------------------------------------------------------
    # autonomous_watches — KB-change-triggered run definitions
    # ---------------------------------------------------------------
    op.create_table(
        "autonomous_watches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_autonomous_watches_user_id"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "projects.id", ondelete="SET NULL", name="fk_autonomous_watches_project_id"
            ),
            nullable=True,
        ),
        sa.Column(
            "knowledge_base_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "knowledge_bases.id",
                ondelete="CASCADE",
                name="fk_autonomous_watches_knowledge_base_id",
            ),
            nullable=False,
        ),
        sa.Column(
            "playbook_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "playbooks.id", ondelete="SET NULL", name="fk_autonomous_watches_playbook_id"
            ),
            nullable=True,
        ),
        sa.Column("skill_ref", sa.Text(), nullable=True),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # The watch dispatcher's "which watches fire for this KB?" lookup —
    # only live, enabled watches matter.
    op.create_index(
        "idx_autonomous_watches_kb_enabled",
        "autonomous_watches",
        ["knowledge_base_id"],
        postgresql_where=sa.text("enabled AND deleted_at IS NULL"),
    )

    # ---------------------------------------------------------------
    # autonomous_memory — proposed / kept / dismissed memory notes
    # ---------------------------------------------------------------
    op.create_table(
        "autonomous_memory",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_autonomous_memory_user_id"),
            nullable=False,
        ),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "source_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "autonomous_sessions.id",
                ondelete="SET NULL",
                name="fk_autonomous_memory_source_session_id",
            ),
            nullable=True,
        ),
        sa.Column("kept_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "state IN ('proposed','kept','dismissed')",
            name="chk_autonomous_memory_state",
        ),
    )
    # The "show me my memory notes in state X" curation view.
    op.create_index(
        "idx_autonomous_memory_user_state",
        "autonomous_memory",
        ["user_id", "state"],
    )

    # ---------------------------------------------------------------
    # precedent_entries — observed precedent patterns
    # ---------------------------------------------------------------
    op.create_table(
        "precedent_entries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_precedent_entries_user_id"),
            nullable=False,
        ),
        sa.Column("pattern_kind", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "observed_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "source_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "autonomous_sessions.id",
                ondelete="SET NULL",
                name="fk_precedent_entries_source_session_id",
            ),
            nullable=True,
        ),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # The "my live precedents for pattern kind X" lookup — dismissed
    # precedents drop out of the index.
    op.create_index(
        "idx_precedent_entries_user_kind",
        "precedent_entries",
        ["user_id", "pattern_kind"],
        postgresql_where=sa.text("dismissed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_precedent_entries_user_kind", table_name="precedent_entries")
    op.drop_table("precedent_entries")

    op.drop_index("idx_autonomous_memory_user_state", table_name="autonomous_memory")
    op.drop_table("autonomous_memory")

    op.drop_index("idx_autonomous_watches_kb_enabled", table_name="autonomous_watches")
    op.drop_table("autonomous_watches")

    op.drop_table("autonomous_schedules")

    op.drop_index("idx_autonomous_sessions_active", table_name="autonomous_sessions")
    op.drop_index("idx_autonomous_sessions_user_created", table_name="autonomous_sessions")
    op.drop_table("autonomous_sessions")
