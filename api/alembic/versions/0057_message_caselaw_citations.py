"""message_caselaw_citations — quote-verified citations against external opinions

Revision ID: 0057
Revises: 0056
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "message_caselaw_citations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "messages.id", ondelete="CASCADE", name="fk_message_caselaw_citations_message"
            ),
            nullable=False,
        ),
        sa.Column("opinion_id", sa.BigInteger(), nullable=False),
        sa.Column("cluster_id", sa.BigInteger(), nullable=False),
        sa.Column("source_offset_start", sa.Integer(), nullable=False),
        sa.Column("source_offset_end", sa.Integer(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("verification_method", sa.Text(), nullable=True),
        sa.Column("verification_confidence", sa.Float(), nullable=True),
        sa.Column("partial", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_offset_start >= 0",
            name="chk_message_caselaw_citations_offset_start_nonneg",
        ),
        sa.CheckConstraint(
            "source_offset_end > source_offset_start",
            name="chk_message_caselaw_citations_offset_end_gt_start",
        ),
        sa.CheckConstraint(
            "verification_method IS NULL OR verification_method IN "
            "('exact_match', 'tolerant_match')",
            name="chk_message_caselaw_citations_method_values",
        ),
        sa.CheckConstraint(
            "verification_confidence IS NULL OR "
            "(verification_confidence >= 0 AND verification_confidence <= 1)",
            name="chk_message_caselaw_citations_confidence_range",
        ),
        sa.CheckConstraint(
            "(verified = false) OR (verification_method IS NOT NULL)",
            name="chk_message_caselaw_citations_verified_has_method",
        ),
    )
    op.create_index(
        "ix_message_caselaw_citations_message_id",
        "message_caselaw_citations",
        ["message_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_message_caselaw_citations_message_id", table_name="message_caselaw_citations")
    op.drop_table("message_caselaw_citations")
