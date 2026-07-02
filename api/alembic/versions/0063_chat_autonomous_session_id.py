"""chats.autonomous_session_id — hidden session-owned chats (WS-D PR2).

Revision ID: 0063
Revises: 0062
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chats",
        sa.Column("autonomous_session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_chats_autonomous_session_id",
        "chats",
        "autonomous_sessions",
        ["autonomous_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_chats_autonomous_session_id",
        "chats",
        ["autonomous_session_id"],
        postgresql_where=sa.text("autonomous_session_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_chats_autonomous_session_id", table_name="chats")
    op.drop_constraint("fk_chats_autonomous_session_id", "chats", type_="foreignkey")
    op.drop_column("chats", "autonomous_session_id")
