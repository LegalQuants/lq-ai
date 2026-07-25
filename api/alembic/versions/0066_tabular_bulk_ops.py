"""create tabular_bulk_ops table — DE-304 / ADR 0026

Bulk operations over a completed tabular execution (redline-per-row
report + summarize-column memo). Per ADR 0026 D1 these land in a
dedicated table rather than the Decision C-9 sibling-execution rows —
the outputs are not grids, so they don't fit ``tabular_executions.results``.

Schema
------

* ``id`` — UUID PK.
* ``execution_id`` — FK → ``tabular_executions.id`` ``ON DELETE CASCADE``.
  The causal-linkage column: an op cannot exist without its parent
  execution (ADR 0026 D1).
* ``user_id`` — caller; nullable + ``ON DELETE SET NULL`` so historical
  ops survive operator deletion (matches ``tabular_executions.user_id``).
* ``kind`` — ``'redline_rows' | 'summarize_column'``; CHECK-constrained.
* ``status`` — ``pending → running → completed | failed``;
  CHECK-constrained. ``completed`` includes batches with per-item
  failures (ADR 0026 D4); ``failed`` is whole-batch crashes only.
* ``params`` — JSONB; op parameters snapshotted at request time
  (e.g. ``{"column_name": "Term"}``) per the C-1 posture.
* ``results`` — JSONB nullable; ``{schema_version, items: [...],
  summary: {total_items, failed_items}}`` once terminal.
* ``confirmed_cost_usd`` — the operator-confirmed preview echo
  (Decision C-5 idiom, mirrors ``tabular_executions.cost_estimate_usd``).
* ``cost_actual_usd`` — summed per-item cost once terminal.
* ``error_text`` — populated on ``status='failed'``.
* ``created_at`` / ``started_at`` / ``completed_at`` — lifecycle
  timestamps. No soft delete: ops live and die with their parent
  execution (cascade), which itself soft-deletes.

Indexes
-------

* ``(execution_id, created_at DESC)`` — the detail read-side lists an
  execution's ops recent-first.

Revision ID: 0066
Revises: 0065
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tabular_bulk_ops",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "tabular_executions.id",
                ondelete="CASCADE",
                name="fk_tabular_bulk_ops_execution_id",
            ),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="fk_tabular_bulk_ops_user_id",
            ),
            nullable=True,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "results",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("confirmed_cost_usd", sa.Numeric(10, 4), nullable=True),
        sa.Column("cost_actual_usd", sa.Numeric(10, 4), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('redline_rows','summarize_column')",
            name="chk_tabular_bulk_ops_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed')",
            name="chk_tabular_bulk_ops_status",
        ),
    )

    op.execute(
        """
        CREATE INDEX idx_tabular_bulk_ops_execution_recent
            ON tabular_bulk_ops (execution_id, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tabular_bulk_ops_execution_recent")
    op.drop_table("tabular_bulk_ops")
