"""tabular_cell_citations — offset-bearing cell provenance rows (DE-309)

Adds:
- tabular_cell_citations  (one row per (cell, cited chunk) pair whose
  extracted value was deterministically located in the chunk's canonical
  text; carries chunk-local char offsets + the verification method /
  confidence that established them. Fail-closed: rows exist only for
  successful matches — there is no unverified state in this table, so
  verification_method is NOT NULL.)

Keyed to a cell by (execution_id, document_id, column_name) — matching
how cells are keyed in tabular_executions.results (rows by document_id,
cells by column_name). document_id / chunk_id are intentionally not FKs
(snapshot/audit posture, mirroring tabular_executions.document_ids);
execution_id cascades with its parent execution row.

Revision ID: 0066
Revises: 0065
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0066"
down_revision: str | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tabular_cell_citations",
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
                name="fk_tabular_cell_citations_execution_id",
            ),
            nullable=False,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("column_name", sa.Text(), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_offset_start", sa.Integer(), nullable=False),
        sa.Column("source_offset_end", sa.Integer(), nullable=False),
        sa.Column("verification_method", sa.Text(), nullable=False),
        sa.Column("verification_confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_offset_start >= 0",
            name="chk_tabular_cell_citations_offset_start_nonneg",
        ),
        sa.CheckConstraint(
            "source_offset_end > source_offset_start",
            name="chk_tabular_cell_citations_offset_end_gt_start",
        ),
        sa.CheckConstraint(
            "verification_method IN "
            "('exact_match', 'tolerant_match', 'paraphrase_judge', "
            "'ensemble_strict', 'ensemble_majority')",
            name="chk_tabular_cell_citations_method_values",
        ),
        sa.CheckConstraint(
            "verification_confidence IS NULL OR "
            "(verification_confidence >= 0 AND verification_confidence <= 1)",
            name="chk_tabular_cell_citations_confidence_range",
        ),
    )
    op.create_index(
        "ix_tabular_cell_citations_execution_id",
        "tabular_cell_citations",
        ["execution_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tabular_cell_citations_execution_id",
        table_name="tabular_cell_citations",
    )
    op.drop_table("tabular_cell_citations")
