"""autonomous_findings — persist run findings

Findings emitted via the ``emit_finding`` chokepoint were echoed into
transient LangGraph state and discarded after the run; only a count
survived. This table persists one row per finding so a run's
work-product can be read back later (read endpoint + contract follow).

``session_id`` FK is ``ON DELETE CASCADE`` — a finding belongs to one
session and is meaningless without it. There is no ``user_id`` column:
authz is via the owning session. An index on ``session_id`` backs the
read endpoint's by-session query. Unlike the other autonomous enum
columns (which carry CHECK constraints — see migrations 0039/0040),
``severity`` deliberately has NO CHECK: it is LLM-emitted free text, so
we persist whatever the model produces (``info`` | ``warn`` |
``critical`` are the intended values, but a stray ``high`` etc. must
store, not reject the finding row).

Revision ID: 0046
Revises: 0045
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "autonomous_findings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "autonomous_sessions.id",
                ondelete="CASCADE",
                name="fk_autonomous_findings_session_id",
            ),
            nullable=False,
        ),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_autonomous_findings_session_id",
        "autonomous_findings",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_autonomous_findings_session_id", table_name="autonomous_findings")
    op.drop_table("autonomous_findings")
