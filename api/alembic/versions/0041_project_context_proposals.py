"""project_context_proposals — promote-precedent-to-Project proposals, M4-B2

Creates the ``project_context_proposals`` table. The autonomous agent may
*propose* promoting a recurring precedent into a Project's context
document, but the agent NEVER writes ``projects.context_md`` directly
(ADR 0013 D5). This table records the proposal; the user accepting it
(``POST /autonomous/project-context-proposals/{id}/accept``) is the
authorized write that appends ``suggested_md`` to the Project's context.

Design notes:

* ``state`` carries ``('proposed','accepted','rejected')`` in the CHECK
  (constraint ``chk_project_context_proposals_state``), matching the
  ``ProposalState`` StrEnum in :mod:`app.schemas.autonomous`.
* ``suggested_md`` is the server-derived context snippet (derived from the
  precedent's ``summary`` at promote time).
* Per-user isolation: all three FKs (``user_id``, ``precedent_id``,
  ``project_id``) are ``ON DELETE CASCADE`` — the autonomous layer is hard
  per-user isolated, and a proposal is meaningless without its precedent or
  target project.
* ``idx_project_context_proposals_user_state`` on ``(user_id, state)``
  backs the ``GET /autonomous/project-context-proposals`` list query (the
  list is per-user and frequently filtered by ``state``). This is the one
  query shape we know is concrete now; following the locked Phase-A
  deferred-index pattern, no other index is added speculatively.

Revision ID: 0041
Revises: 0040
Create Date: 2026-05-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------
    # project_context_proposals — promote-precedent-to-Project proposals
    # ---------------------------------------------------------------
    op.create_table(
        "project_context_proposals",
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
                name="fk_project_context_proposals_user_id",
            ),
            nullable=False,
        ),
        sa.Column(
            "precedent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "precedent_entries.id",
                ondelete="CASCADE",
                name="fk_project_context_proposals_precedent_id",
            ),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "projects.id",
                ondelete="CASCADE",
                name="fk_project_context_proposals_project_id",
            ),
            nullable=False,
        ),
        sa.Column("suggested_md", sa.Text(), nullable=False),
        sa.Column(
            "state",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'proposed'"),
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
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
            "state IN ('proposed','accepted','rejected')",
            name="chk_project_context_proposals_state",
        ),
    )
    # (user_id, state) backs the per-user, state-filtered list query — the
    # one query shape that is concrete now. No other index is added
    # speculatively (locked Phase-A deferred-index pattern).
    op.create_index(
        "idx_project_context_proposals_user_state",
        "project_context_proposals",
        ["user_id", "state"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_project_context_proposals_user_state",
        table_name="project_context_proposals",
    )
    op.drop_table("project_context_proposals")
