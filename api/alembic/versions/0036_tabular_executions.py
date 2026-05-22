"""create tabular_executions table — M3-C2

The Tabular Review LangGraph workflow (M3-C2) runs as an ARQ-dispatched
async job on the existing ``arq:m3a6`` queue (Decision C-3 from the
Phase C prep doc: reuse the queue, don't add a second worker
container). Each execution walks ``documents x columns`` and produces
a row-per-document by column-per-spec grid; this table persists the
inputs + status + results so the result view can re-render the grid
a week later.

Schema
------

* ``id`` — UUID PK.
* ``user_id`` — caller's user id; nullable + ``ON DELETE SET NULL``
  so historical executions survive operator deletion (matches the
  ``easy_playbook_generations.user_id`` posture from migration 0035).
* ``parent_execution_id`` — UUID nullable self-FK; non-null on bulk-op
  sibling rows (Decision C-9: bulk ops spawn sibling
  ``tabular_executions`` rows rather than mutating the original grid,
  preserving the original's auditability). ``ON DELETE SET NULL`` so
  deleting a parent doesn't cascade-delete siblings.
* ``skill_name`` — text nullable; the source skill's ``name``
  (filesystem-canonical, not DB-backed; matches the Skill Service
  reference style elsewhere in the codebase). Null for ad-hoc
  executions where the operator typed columns directly in the
  wizard's column step.
* ``status`` — lifecycle
  ``pending -> running -> completed | failed | cancelled``.
  CHECK-constrained at the storage layer.
* ``document_ids`` — array of source document UUIDs from the
  caller's selection. NOT a foreign key (documents can be
  soft-deleted after execution completes; we preserve the row
  for audit; matches the ``easy_playbook_generations`` pattern).
* ``columns`` — JSONB; the resolved column spec at execution start
  (snapshot of the skill's ``lq_ai.columns`` block OR the operator's
  ad-hoc list). Snapshotting at execution start is the load-bearing
  invariant: re-rendering the grid later must be honest about what
  was actually run, not what the skill currently says.
* ``results`` — JSONB nullable; the assembled grid shape
  ``{rows: [{document_id, document_name, cells: {column_name:
  CellResult}}]}`` once status is ``completed``.
* ``cost_estimate_usd`` — numeric nullable; the operator-confirmed
  estimate at execution start (from ``POST /tabular/preview-cost``).
* ``cost_actual_usd`` — numeric nullable; populated incrementally
  by the worker as cells complete. Operators see drift between
  estimate and actual in the result view.
* ``error_text`` — text nullable; populated on ``status='failed'``.
* ``created_at`` / ``started_at`` / ``completed_at`` / ``deleted_at``
  — lifecycle timestamps. ``deleted_at`` enables soft delete per
  Decision C-9 (matches the M3-A6 ``playbooks.deleted_at`` pattern
  from migration 0034).

Indexes
-------

* ``(user_id, created_at DESC)`` partial index where
  ``deleted_at IS NULL`` — the list endpoint sorts the caller's
  non-deleted executions by recency.
* ``(parent_execution_id)`` — bulk-op siblings query their parent.

Revision ID: 0036
Revises: 0035
Create Date: 2026-05-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tabular_executions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="fk_tabular_executions_user_id",
            ),
            nullable=True,
        ),
        sa.Column(
            "parent_execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "tabular_executions.id",
                ondelete="SET NULL",
                name="fk_tabular_executions_parent_execution_id",
            ),
            nullable=True,
        ),
        sa.Column("skill_name", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "document_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column(
            "columns",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "results",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "cost_estimate_usd",
            sa.Numeric(10, 4),
            nullable=True,
        ),
        sa.Column(
            "cost_actual_usd",
            sa.Numeric(10, 4),
            nullable=True,
        ),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed','cancelled')",
            name="chk_tabular_executions_status",
        ),
    )

    op.execute(
        """
        CREATE INDEX idx_tabular_executions_user_recent
            ON tabular_executions (user_id, created_at DESC)
            WHERE deleted_at IS NULL
        """
    )

    op.execute(
        """
        CREATE INDEX idx_tabular_executions_parent
            ON tabular_executions (parent_execution_id)
            WHERE parent_execution_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tabular_executions_parent")
    op.execute("DROP INDEX IF EXISTS idx_tabular_executions_user_recent")
    op.drop_table("tabular_executions")
