"""Add the inactive internal workspace-event foundation (ADR PR #677 / #256).

Revision ID: 0079
Revises: 0078

Additive: no existing records, producers or configuration are changed. Normal
rollback disables callers and retains this table; downgrade drops only this new
table and is destructive to event metadata, so use it only on disposable tests
or after explicitly approved data handling. No platform/vendor is provisioned.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_workspace_events_user_id"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE", name="fk_workspace_events_project_id"),
        ),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_ref", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'recorded'")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("sensitivity", sa.Text(), nullable=False),
        sa.Column("dedupe_digest", sa.Text(), nullable=False),
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
        sa.UniqueConstraint(
            "user_id", "source_kind", "source_ref", "event_type", name="uq_workspace_events_source"
        ),
        sa.CheckConstraint("source_kind = 'internal'", name="chk_workspace_events_source_kind"),
        sa.CheckConstraint(
            "event_type = 'finding.created'", name="chk_workspace_events_event_type"
        ),
        sa.CheckConstraint("status = 'recorded'", name="chk_workspace_events_status"),
        sa.CheckConstraint(
            "sensitivity IN ('confidential', 'privileged')", name="chk_workspace_events_sensitivity"
        ),
        sa.CheckConstraint(
            "dedupe_digest ~ '^[0-9a-f]{64}$'", name="chk_workspace_events_dedupe_digest"
        ),
        sa.CheckConstraint(
            'provenance = \'{"producer": "autonomous"}\'::jsonb',
            name="chk_workspace_events_provenance",
        ),
    )
    op.create_index(
        "ix_workspace_events_owner_time", "workspace_events", ["user_id", "occurred_at", "id"]
    )
    op.create_index("ix_workspace_events_project", "workspace_events", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_workspace_events_project", table_name="workspace_events")
    op.drop_index("ix_workspace_events_owner_time", table_name="workspace_events")
    op.drop_table("workspace_events")
