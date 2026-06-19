"""chat_pending_tool_call — persist-and-resume state for the chat confirmation gate

Stores the per-turn pending-tool-call payload that the backend persists when
the model proposes a destructive / requires_confirmation tool, before the user
confirms.  The row id is the ``pending_call_id`` returned in the SSE event.

Security / data-separation rationale (mirrors model docstring):
``tool_call_args`` and ``resume_state`` hold conversation/tool payloads needed
to resume the tool-loop.  They live here — deliberately NOT on
``tool_call_log`` — to preserve ``tool_call_log``'s counts/types-only
invariant (PR5a).  ``resume_state`` has the same sensitivity class as
``messages.content`` (plaintext conversation store): it MUST NEVER be emitted
to logs, tracing spans, or audit fields.  Rows are TTL-bounded by
``expires_at`` and are CASCADE-deleted when their parent chat or user is
deleted.

Revision ID: 0054
Revises: 0053
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_pending_tool_call",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "chat_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "chats.id",
                ondelete="CASCADE",
                name="fk_chat_pending_tool_call_chat",
            ),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                ondelete="CASCADE",
                name="fk_chat_pending_tool_call_user",
            ),
            nullable=False,
        ),
        sa.Column("assistant_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tool_call_log_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "tool_call_log.id",
                ondelete="SET NULL",
                name="fk_chat_pending_tool_call_log",
            ),
            nullable=True,
        ),
        sa.Column("function_name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("destructive", sa.Boolean(), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("tool_call_args", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resume_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
    op.create_index(
        "ix_chat_pending_tool_call_chat_id",
        "chat_pending_tool_call",
        ["chat_id"],
    )
    op.create_index(
        "ix_chat_pending_tool_call_user_id",
        "chat_pending_tool_call",
        ["user_id"],
    )
    op.create_index(
        "ix_chat_pending_tool_call_expires_at",
        "chat_pending_tool_call",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_pending_tool_call_expires_at", table_name="chat_pending_tool_call")
    op.drop_index("ix_chat_pending_tool_call_user_id", table_name="chat_pending_tool_call")
    op.drop_index("ix_chat_pending_tool_call_chat_id", table_name="chat_pending_tool_call")
    op.drop_table("chat_pending_tool_call")
