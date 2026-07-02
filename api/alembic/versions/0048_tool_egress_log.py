"""tool_egress_log — per-call audit of third-party tool/data-source egress

One row per outbound tool-provider call through the gateway (ADR 0014 D3).
Mirrors ``inference_routing_log``: gateway-written, raw SQL, counts/types
only — NEVER raw payloads. Distinct table because egress has a different
access pattern and retention from inference routing.

Revision ID: 0048
Revises: 0047
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_egress_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("tool", sa.String(), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("bytes_out", sa.Integer(), nullable=True),
        sa.Column("bytes_in", sa.Integer(), nullable=True),
        sa.Column(
            "anonymization_applied",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "refused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("refusal_reason", sa.String(), nullable=True),
        sa.CheckConstraint("tier BETWEEN 0 AND 5", name="chk_tool_egress_log_tier_range"),
    )
    op.create_index("ix_tool_egress_log_provider", "tool_egress_log", ["provider"])
    op.create_index("ix_tool_egress_log_timestamp", "tool_egress_log", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_tool_egress_log_timestamp", table_name="tool_egress_log")
    op.drop_index("ix_tool_egress_log_provider", table_name="tool_egress_log")
    op.drop_table("tool_egress_log")
