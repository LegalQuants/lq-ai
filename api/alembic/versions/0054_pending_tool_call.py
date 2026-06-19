"""pending_tool_call — paused human-gated chat tool calls (PR5b-ii / WS4)

One row per chat tool call awaiting approval (spec L3 persist-and-resume).
Single-use (deleted on resolve) + TTL-bounded (``expires_at``), mirroring
``mcp_oauth_state``. ``payload_cipher`` holds the Fernet-encrypted resume
payload (tool args + conversation-so-far) — NEVER plaintext, since it can
carry user content.

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
        "pending_tool_call",
        sa.Column("pending_call_id", sa.Text(), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_pending_tool_call_user"),
            nullable=False,
        ),
        sa.Column(
            "chat_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chats.id", ondelete="CASCADE", name="fk_pending_tool_call_chat"),
            nullable=False,
        ),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("destructive", sa.Boolean(), nullable=False),
        sa.Column("payload_cipher", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Resolve + ownership lookups are by (chat_id) for the resume endpoint.
    op.create_index("ix_pending_tool_call_chat_id", "pending_tool_call", ["chat_id"])


def downgrade() -> None:
    op.drop_index("ix_pending_tool_call_chat_id", table_name="pending_tool_call")
    op.drop_table("pending_tool_call")
