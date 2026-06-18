"""mcp_oauth_tokens + mcp_oauth_state — PR4c per-user OAuth persistence

``mcp_oauth_tokens``: Fernet-encrypted access/refresh tokens, one row per
``(user_id, provider_name)``.  Composite PK; no surrogate key.

``mcp_oauth_state``: short-lived CSRF/PKCE state bridging /authorize →
/callback.  PK is the opaque ``state`` token.  Single-use + TTL-checked by
the app; a dedicated table (not a cache) for multi-worker safety.

Revision ID: 0051
Revises: 0050
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_oauth_tokens",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_mcp_oauth_tokens_user"),
            primary_key=True,
        ),
        sa.Column("provider_name", sa.Text(), primary_key=True),
        sa.Column("access_token", sa.LargeBinary(), nullable=False),
        sa.Column("refresh_token", sa.LargeBinary(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("issuer", sa.Text(), nullable=True),
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

    op.create_table(
        "mcp_oauth_state",
        sa.Column("state", sa.Text(), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_mcp_oauth_state_user"),
            nullable=False,
        ),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("code_verifier", sa.Text(), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("token_endpoint", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("as_iss_supported", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("mcp_oauth_state")
    op.drop_table("mcp_oauth_tokens")
