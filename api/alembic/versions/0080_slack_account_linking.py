"""Explicit Slack account linking.

Revision ID: 0080
Revises: 0079
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0080"
down_revision = "0079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "slack_account_links",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(),
            sa.ForeignKey("slack_workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slack_user_id", sa.String(64), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("workspace_id", "slack_user_id"),
    )
    op.create_index("ix_slack_account_links_user_id", "slack_account_links", ["user_id"])
    op.create_table(
        "slack_link_requests",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(),
            sa.ForeignKey("slack_workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slack_user_id", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "slack_user_id"),
    )


def downgrade() -> None:
    op.drop_table("slack_link_requests")
    op.drop_table("slack_account_links")
