"""create message_citations table — M2-A2

The Citation Engine (PRD §3.3) persists one row per model-emitted
citation alongside the assistant message. Each row carries:

* ``source_file_id`` + ``source_offset_start`` / ``source_offset_end``:
  the byte-precise span in the source document the model claims to
  be quoting. The verifier checks these against
  ``documents.normalized_content`` (added in M2-A1, migration 0024).
* ``source_text``: the exact text the model quoted.
* ``verified`` + ``verification_method`` + ``verification_confidence``:
  the verifier's verdict. ``verified=TRUE`` only when at least one
  stage passed.

The schema is built to carry every Stage's output the M2 plan
specifies, not just Stage 1's. Stages 2-4 (tolerant-match, LLM judge,
ensemble) land in later tasks but write into the same column shape;
``verification_method`` distinguishes them. Pre-emptive plumbing now
saves a follow-on migration.

This migration **promotes the table** from the forward-looking sketch
that has been in ``docs/db-schema.md`` since C3 — that sketch was
explicitly flagged as "may or may not survive the M2 citation work"
(the schema doc note at the head of the messages section). M2-A2
chose the relational path; the JSONB ``messages.citations`` column
remains in place at its ``'[]'`` default until M2-C2 (failed-citation
UI rendering) decides whether to retire it.

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_citations",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "message_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "messages.id",
                ondelete="CASCADE",
                name="fk_message_citations_message_id",
            ),
            nullable=False,
        ),
        sa.Column(
            "source_file_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "files.id",
                ondelete="CASCADE",
                name="fk_message_citations_source_file_id",
            ),
            nullable=False,
        ),
        sa.Column("source_offset_start", sa.Integer(), nullable=False),
        sa.Column("source_offset_end", sa.Integer(), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column(
            "verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("verification_method", sa.Text(), nullable=True),
        sa.Column("verification_confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "source_offset_start >= 0",
            name="chk_message_citations_offset_start_nonneg",
        ),
        sa.CheckConstraint(
            "source_offset_end > source_offset_start",
            name="chk_message_citations_offset_end_gt_start",
        ),
        sa.CheckConstraint(
            "verification_method IS NULL OR verification_method IN "
            "('exact_match', 'tolerant_match', 'llm_judge', 'ensemble', 'failed')",
            name="chk_message_citations_method_values",
        ),
        sa.CheckConstraint(
            "verification_confidence IS NULL OR "
            "(verification_confidence >= 0 AND verification_confidence <= 1)",
            name="chk_message_citations_confidence_range",
        ),
        sa.CheckConstraint(
            "(verified = false) OR (verification_method IS NOT NULL)",
            name="chk_message_citations_verified_has_method",
        ),
    )
    op.create_index(
        "idx_message_citations_message",
        "message_citations",
        ["message_id"],
    )
    op.create_index(
        "idx_message_citations_file",
        "message_citations",
        ["source_file_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_message_citations_file", table_name="message_citations")
    op.drop_index("idx_message_citations_message", table_name="message_citations")
    op.drop_table("message_citations")
