"""mcp tool-discovery cache (WS2/PR4b)

One row per (mcp provider, tool). Discovered through the gateway; ``enabled``
is the operator toggle. MCP servers come from gateway config, not stored here.

Revision ID: 0050
Revises: 0049
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_tools",
        sa.Column("provider_name", sa.String(), primary_key=True),
        sa.Column("tool_name", sa.String(), primary_key=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("read_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("destructive", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "requires_confirmation", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("mcp_tools")
