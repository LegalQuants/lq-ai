"""create citation_treatment (WS-G PR1 citation-graph signal)

Revision ID: 0061
Revises: 0060
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "citation_treatment",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("cluster_id", sa.BigInteger(), nullable=False),
        sa.Column("opinion_id", sa.BigInteger(), nullable=True),
        sa.Column("cited_by_count", sa.Integer(), nullable=False),
        sa.Column("citing_opinions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("derived_method", sa.Text(), nullable=False),
        sa.Column(
            "as_of", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_citation_treatment"),
        sa.UniqueConstraint("cluster_id", name="uq_citation_treatment_cluster_id"),
        sa.CheckConstraint("cited_by_count >= 0", name="chk_citation_treatment_count_nonneg"),
        sa.CheckConstraint(
            "derived_method IN ('citation_graph')", name="chk_citation_treatment_method_values"
        ),
    )
    op.create_index("ix_citation_treatment_cluster_id", "citation_treatment", ["cluster_id"])


def downgrade() -> None:
    op.drop_index("ix_citation_treatment_cluster_id", table_name="citation_treatment")
    op.drop_table("citation_treatment")
