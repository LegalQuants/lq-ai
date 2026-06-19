"""tool_call_log — per-call governance audit for chat and autonomous tool calls

One row per governed tool call (PR5a).  Records counts/types only —
NEVER raw arguments or tool results (mirrors ``tool_egress_log`` discipline).

``origin`` distinguishes chat-triggered from autonomous-triggered calls.
``user_id`` FK cascades so deleting a user erases their audit rows.
``outcome`` progresses: pending → executed | refused_tier | error | denied.

Revision ID: 0053
Revises: 0052
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_call_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_tool_call_log_user"),
            nullable=True,
        ),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column(
            "confirmation_state",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'not_required'"),
        ),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("args_digest", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_tool_call_log_user_id", "tool_call_log", ["user_id"])
    op.create_index("ix_tool_call_log_created_at", "tool_call_log", ["created_at"])
    op.create_index("ix_tool_call_log_provider", "tool_call_log", ["provider"])


def downgrade() -> None:
    op.drop_index("ix_tool_call_log_provider", table_name="tool_call_log")
    op.drop_index("ix_tool_call_log_created_at", table_name="tool_call_log")
    op.drop_index("ix_tool_call_log_user_id", table_name="tool_call_log")
    op.drop_table("tool_call_log")
