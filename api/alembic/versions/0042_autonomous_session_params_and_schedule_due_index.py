"""autonomous_sessions.params seam + autonomous_schedules due-index — M4-B3

Two additive changes supporting scheduled autonomous tasks (M4-B3):

1. ``autonomous_sessions.params`` — a JSONB ``NOT NULL DEFAULT '{}'``
   column carrying the trigger→target seam (Decision B3-a). Every
   trigger source (the B3 schedule dispatcher, B4's watch-enqueue, any
   manual/suggestion trigger) populates the non-null subset of
   ``{"kb_id", "playbook_id", "skill_ref", "query"}``; the executor
   reads it into ``initial_state`` (replacing the hardcoded
   ``kb_id=None``/``query=None``) — uniform across all trigger kinds,
   decoupled from the schedule/watch tables.

2. ``idx_autonomous_schedules_due`` — the A1-deferred partial index
   (Decision B3-b). Serves the dispatcher scan
   ``WHERE enabled AND deleted_at IS NULL AND next_run_at <= now()``:
   the partial predicate matches the always-true filter so the planner
   reads only the live, enabled schedules ordered by ``next_run_at``.

Revision ID: 0042
Revises: 0041
Create Date: 2026-05-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------
    # autonomous_sessions.params — trigger→target seam (Decision B3-a)
    # ---------------------------------------------------------------
    op.add_column(
        "autonomous_sessions",
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # ---------------------------------------------------------------
    # autonomous_schedules due-index (A1-deferred; Decision B3-b)
    # ---------------------------------------------------------------
    # Serves the dispatcher scan:
    #   SELECT ... FROM autonomous_schedules
    #   WHERE enabled AND deleted_at IS NULL AND next_run_at <= now()
    # The partial predicate matches the always-true filter so the planner
    # reads only live, enabled schedules ordered by next_run_at.
    op.create_index(
        "idx_autonomous_schedules_due",
        "autonomous_schedules",
        ["next_run_at"],
        postgresql_where=sa.text("enabled AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_autonomous_schedules_due",
        table_name="autonomous_schedules",
    )
    op.drop_column("autonomous_sessions", "params")
