"""mcp_oauth_state: add return_url column for PR4d BFF redirect

Adds a nullable ``return_url`` column to ``mcp_oauth_state`` so the callback
handler can 302 the browser back to the BFF frontend after authorization.  The
column is populated at authorize-time after origin-allowlist validation and read
at callback-time; the callback never accepts a redirect target from its own
query string (server-side binding enforces no-open-redirect).

Revision ID: 0052
Revises: 0051
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_oauth_state",
        sa.Column("return_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_oauth_state", "return_url")
