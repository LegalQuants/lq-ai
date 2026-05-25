"""autonomous_notifications — in-app notification substrate, M4-A3.2

Creates the ``autonomous_notifications`` table that the ``notify``
chokepoint handler (A3.3) writes a durable in-app artifact to. This
table is pulled forward from M4-C1 so A3.3 has a write target; C1 adds
the remaining pieces that depend on the read-API query shape being
concrete: email/SMTP transport, the read/dismiss API, the web surface,
and webhook dispatch.

Design notes:

* ``channel`` carries ``('in_app','email','webhook')`` in the CHECK so
  M4-C1's fold-in is purely additive. ``webhook`` is RESERVED and not
  dispatched until DE-312 (Decision M4-8).
* ``body`` carries counts/types/IDs + a link to the receipt — never raw
  entity values. ``payload`` is optional structured JSONB the web
  renders (same constraint: no raw values).
* ``read_at`` IS NULL = unread (in-app read state). The read/dismiss API
  that marks this column lands in M4-C1.
* Per-user isolation: both ``user_id`` and ``session_id`` FK on ``ON
  DELETE CASCADE`` — the autonomous layer is hard per-user isolated.
  Notifications are always session-produced; they cascade with the session.

**Read index deferred to M4-C1.** Following the locked Phase-A pattern
(see the ``autonomous_schedules`` comment in migration 0039 where the
``next_run_at`` scan index was deferred), the notifications read-index
(likely ``user_id, read_at, created_at DESC``) is deferred until the
read-API query shape (unread filter? ordering?) is concrete.

Revision ID: 0040
Revises: 0039
Create Date: 2026-05-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------
    # autonomous_notifications — in-app notification substrate
    # ---------------------------------------------------------------
    op.create_table(
        "autonomous_notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                ondelete="CASCADE",
                name="fk_autonomous_notifications_user_id",
            ),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "autonomous_sessions.id",
                ondelete="CASCADE",
                name="fk_autonomous_notifications_session_id",
            ),
            nullable=False,
        ),
        sa.Column(
            "channel",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'in_app'"),
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "channel IN ('in_app','email','webhook')",
            name="chk_autonomous_notifications_channel",
        ),
    )
    # Read index (user_id + read_at/created_at) deferred to M4-C1 when the
    # read-API query shape (unread filter? ordering?) is concrete. Following
    # the locked Phase-A pattern: don't index until the query is known.


def downgrade() -> None:
    op.drop_table("autonomous_notifications")
