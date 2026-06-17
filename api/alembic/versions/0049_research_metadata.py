"""research metadata — cached CourtListener cluster + opinion metadata (WS3b)

Cluster/opinion metadata for fetched case law; opinion BODIES live in object
storage (storage_path), not here. Read-through cache for GET /research/
clusters/{id}; find_in_case/read_case read from these rows.

Revision ID: 0049
Revises: 0048
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_cluster_metadata",
        sa.Column("cluster_id", sa.BigInteger(), primary_key=True),
        sa.Column("case_name", sa.String(), nullable=True),
        sa.Column("court", sa.String(), nullable=True),
        sa.Column("date_filed", sa.String(), nullable=True),
        sa.Column("absolute_url", sa.String(), nullable=True),
        sa.Column(
            "cached_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "research_opinion_metadata",
        sa.Column("opinion_id", sa.BigInteger(), primary_key=True),
        sa.Column("cluster_id", sa.BigInteger(), nullable=False),
        sa.Column("text_field_used", sa.String(), nullable=True),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("char_length", sa.Integer(), nullable=False),
        sa.Column(
            "cached_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_research_opinion_metadata_cluster_id",
        "research_opinion_metadata",
        ["cluster_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_opinion_metadata_cluster_id",
        table_name="research_opinion_metadata",
    )
    op.drop_table("research_opinion_metadata")
    op.drop_table("research_cluster_metadata")
