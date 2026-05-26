"""autonomous_notifications read-index — M4-C1

Adds the read-index that migration 0040 DEFERRED to M4-C1 (it waited for
the read-API query shape to be concrete). The shape is now known:

    GET /api/v1/autonomous/notifications
        WHERE user_id = :user_id [AND read_at IS NULL]   -- ?unread=true
        ORDER BY created_at DESC

The composite ``(user_id, read_at, created_at DESC)`` serves both the
all-notifications list (leading ``user_id`` + ``created_at DESC`` order)
and the ``?unread=true`` variant (the ``read_at`` predicate). The
``created_at DESC`` trailing column matches the newest-first sort so the
planner can read the index in order. Mirrors the
``idx_autonomous_sessions_user_created`` DESC-column idiom from migration
0039.

Revision ID: 0043
Revises: 0042
Create Date: 2026-05-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Serves GET /autonomous/notifications:
    #   WHERE user_id = :u [AND read_at IS NULL] ORDER BY created_at DESC
    op.create_index(
        "idx_autonomous_notifications_user_unread",
        "autonomous_notifications",
        ["user_id", "read_at", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_autonomous_notifications_user_unread",
        table_name="autonomous_notifications",
    )
