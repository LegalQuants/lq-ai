"""chat_sticky_skills — per-chat sticky-skill set for the opt-in sticky toggle

Adds ``chats.sticky_skills text[] NOT NULL DEFAULT '{}'``. The array IS the
state: empty means the sticky toggle is OFF (fail-restrictive default — a new
chat never inherits stickiness, issue #207 finding 4). A non-empty set is the
snapshot of skills the user made sticky; the chat send path unions it into each
turn's effective skills so a follow-up turn keeps applying them without the
client re-sending. Toggling off clears the set.

No raw payloads here — it holds skill *slugs* (identifiers), same sensitivity
class as ``messages.applied_skills``.

Revision ID: 0056
Revises: 0055
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chats",
        sa.Column(
            "sticky_skills",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )


def downgrade() -> None:
    op.drop_column("chats", "sticky_skills")
