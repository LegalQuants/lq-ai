"""citation_treatment_signal + parent rollup columns (WS-G PR2 treatment judge)

Revision ID: 0062
Revises: 0061
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0062"
down_revision: str | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLASSES = "'followed','distinguished','criticized','questioned','overruled','superseded','neutral'"
_NEGATIVE = "'overruled','superseded','criticized','questioned','distinguished'"


def upgrade() -> None:
    op.create_table(
        "citation_treatment_signal",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("treatment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("citing_opinion_id", sa.BigInteger(), nullable=False),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["treatment_id"], ["citation_treatment.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "treatment_id", "citing_opinion_id", name="uq_treatment_signal_treatment_citing"
        ),
        sa.CheckConstraint(
            f"classification IN ({_CLASSES})", name="chk_treatment_signal_classification"
        ),
    )
    op.create_index(
        "ix_citation_treatment_signal_treatment_id", "citation_treatment_signal", ["treatment_id"]
    )

    op.add_column(
        "citation_treatment", sa.Column("strongest_negative_class", sa.Text(), nullable=True)
    )
    op.add_column("citation_treatment", sa.Column("judged_count", sa.Integer(), nullable=True))
    op.add_column(
        "citation_treatment", sa.Column("judge_as_of", sa.DateTime(timezone=True), nullable=True)
    )

    op.drop_constraint("chk_citation_treatment_method_values", "citation_treatment", type_="check")
    op.create_check_constraint(
        "chk_citation_treatment_method_values",
        "citation_treatment",
        "derived_method IN ('citation_graph', 'citation_graph+judge')",
    )
    op.create_check_constraint(
        "chk_citation_treatment_strongest_negative",
        "citation_treatment",
        f"strongest_negative_class IS NULL OR strongest_negative_class IN ({_NEGATIVE})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "chk_citation_treatment_strongest_negative", "citation_treatment", type_="check"
    )
    op.drop_constraint("chk_citation_treatment_method_values", "citation_treatment", type_="check")
    op.create_check_constraint(
        "chk_citation_treatment_method_values",
        "citation_treatment",
        "derived_method IN ('citation_graph')",
    )
    op.drop_column("citation_treatment", "judge_as_of")
    op.drop_column("citation_treatment", "judged_count")
    op.drop_column("citation_treatment", "strongest_negative_class")
    op.drop_index(
        "ix_citation_treatment_signal_treatment_id", table_name="citation_treatment_signal"
    )
    op.drop_table("citation_treatment_signal")
