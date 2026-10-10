"""Matter-scoped tool-egress ceiling columns (DE-358 item 6 / AG-03, issue #593).

Revision ID: 0070
Revises: 0069

Adds the nullable ceiling inputs and audit columns for the API-side
tool-egress ceiling:

- ``projects.max_egress_tier`` — per-matter ceiling, 1-5, NULL = no
  Project ceiling (composes with the operator default and any
  orchestration scope via numeric ``min()``).
- ``chat_pending_tool_call.max_egress_tier`` — the ceiling resolved at
  proposal time; the approve path re-resolves current policy and
  executes under ``min(original, current)``.
- ``tool_call_log.max_allowed_tier`` / ``tool_call_log.ceiling_source`` —
  the ceiling actually applied and which policy bound it
  (``operator`` | ``project`` | ``execution_scope`` | ``pending_original``
  | ``unresolved`` | NULL when unconstrained).

All new columns are nullable, so the upgrade is a pure DDL add with no
backfill and no data loss on downgrade beyond the new columns.
"""

from alembic import op

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE projects
          ADD COLUMN max_egress_tier SMALLINT,
          ADD CONSTRAINT chk_projects_max_egress_tier_range CHECK (
            max_egress_tier IS NULL OR (max_egress_tier BETWEEN 1 AND 5)
          );

        ALTER TABLE chat_pending_tool_call
          ADD COLUMN max_egress_tier SMALLINT,
          ADD CONSTRAINT chk_chat_pending_tool_call_max_egress_tier_range CHECK (
            max_egress_tier IS NULL OR (max_egress_tier BETWEEN 1 AND 5)
          );

        ALTER TABLE tool_call_log
          ADD COLUMN max_allowed_tier SMALLINT,
          ADD COLUMN ceiling_source TEXT,
          ADD CONSTRAINT chk_tool_call_log_max_allowed_tier_range CHECK (
            -- 0 ("no egress") is a real applied ceiling for scope-0 refusals;
            -- configured ceilings are 1-5.
            max_allowed_tier IS NULL OR (max_allowed_tier BETWEEN 0 AND 5)
          ),
          ADD CONSTRAINT chk_tool_call_log_ceiling_source CHECK (
            ceiling_source IS NULL OR (ceiling_source IN (
              'operator', 'project', 'execution_scope', 'pending_original', 'unresolved'
            ))
          );
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE tool_call_log
          DROP CONSTRAINT chk_tool_call_log_ceiling_source,
          DROP CONSTRAINT chk_tool_call_log_max_allowed_tier_range,
          DROP COLUMN ceiling_source,
          DROP COLUMN max_allowed_tier;

        ALTER TABLE chat_pending_tool_call
          DROP CONSTRAINT chk_chat_pending_tool_call_max_egress_tier_range,
          DROP COLUMN max_egress_tier;

        ALTER TABLE projects
          DROP CONSTRAINT chk_projects_max_egress_tier_range,
          DROP COLUMN max_egress_tier;
    """)
