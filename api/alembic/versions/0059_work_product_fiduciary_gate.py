"""work_product_fiduciary_gate — fiduciary-grade verdict (ADR 0018 D3)

Revision ID: 0059
Revises: 0058
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "work_product_fiduciary_gate",
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
                "messages.id",
                ondelete="CASCADE",
                name="fk_work_product_fiduciary_gate_message",
            ),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "chat_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "chats.id", ondelete="CASCADE", name="fk_work_product_fiduciary_gate_chat"
            ),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "projects.id",
                ondelete="SET NULL",
                name="fk_work_product_fiduciary_gate_project",
            ),
            nullable=True,
        ),
        sa.Column("gate_status", sa.Text(), nullable=False),
        sa.Column("pass_count", sa.Integer(), nullable=False),
        sa.Column("supported_count", sa.Integer(), nullable=False),
        sa.Column("fail_count", sa.Integer(), nullable=False),
        sa.Column("total_assertions", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "gate_status IN ('fiduciary_grade', 'supported_only', 'flagged')",
            name="chk_work_product_fiduciary_gate_status_values",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="chk_work_product_fiduciary_gate_confidence_range",
        ),
        sa.CheckConstraint(
            "pass_count >= 0 AND supported_count >= 0 AND fail_count >= 0 "
            "AND total_assertions >= 0",
            name="chk_work_product_fiduciary_gate_counts_nonneg",
        ),
    )
    op.create_index(
        "ix_work_product_fiduciary_gate_chat_id",
        "work_product_fiduciary_gate",
        ["chat_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_work_product_fiduciary_gate_chat_id", table_name="work_product_fiduciary_gate"
    )
    op.drop_table("work_product_fiduciary_gate")
