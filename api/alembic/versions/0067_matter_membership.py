"""project_members + projects.share_scope — matter-scoped collaboration

Revision ID: 0067
Revises: 0066
Create Date: 2026-08-20

PRD §3.11 lists ``share_scope`` in the Project data model and names
``POST /api/v1/projects/{id}/share``; §3.11's M1 status records
share-with-group as deferred. ADR 0020 D3 pins "matter = project — there
is no new ``Matter`` model". This migration lands the deferred half:
a membership table over ``projects`` and the ``share_scope`` column the
PRD already named.

**project_members** mirrors ``team_members`` (migration 0014) verbatim —
composite PK, the same CASCADE/RESTRICT split, and the same
``added_by_user_id`` forensic column so "who let X onto matter Y?"
survives in audit-log queries that index by actor.

The ``role`` enum extends the team model with one value: ``blocked``.
A blocked row is a **negative** grant — an ethical screen / conflict
wall — and the resolver evaluates it before every allow, so it overrides
firm-wide scope, explicit membership, and operator-admin alike. Storing
denial as a role value rather than a separate table keeps "who can see
this matter, and who explicitly cannot" answerable from one indexed
query.

**share_scope** is the ambient grant:

* ``personal`` — the owner and explicit members only (the pre-migration
  behaviour, and the default upstream).
* ``members`` — same as personal today; reserved so a deployment can
  distinguish "deliberately restricted" from "never shared" in the UI
  without a second column.
* ``org`` — every non-blocked user in the deployment gets **read**.
  Contributing still requires an explicit membership row, so the roster
  stays a truthful answer to "who worked this matter" — which is the
  question that matters for privilege and conflicts.

Sandbox matters (``is_sandbox``) are per-user scratch space and are
constrained to ``personal`` at the DB layer; sharing one would leak a
colleague's try-it space into the matter list.

**Backfill:** one ``lead`` row per existing project for its owner, so the
owner path and the membership path are structurally identical from row
one and the resolver returns exactly the pre-migration answer for every
existing row. ``projects.owner_id`` is ``ON DELETE RESTRICT`` and
non-nullable, so every project has a live owner to backfill from.

Reversible: ``downgrade()`` drops the constraint, the column, and the
table. Membership rows are lost, which is correct — without the table
there is nothing to express them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic
revision: str = "0067"
down_revision: str | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- project_members ---------------------------------------------------
    op.create_table(
        "project_members",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "projects.id",
                ondelete="CASCADE",
                name="fk_project_members_project",
            ),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                ondelete="CASCADE",
                name="fk_project_members_user",
            ),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "added_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                ondelete="RESTRICT",
                name="fk_project_members_added_by",
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("project_id", "user_id", name="pk_project_members"),
        sa.CheckConstraint(
            "role IN ('lead', 'contributor', 'reader', 'blocked')",
            name="ck_project_members_role_enum",
        ),
    )

    # Drives the "which matters can this user see" list query.
    op.create_index(
        "idx_project_members_user",
        "project_members",
        ["user_id"],
    )

    # --- projects.share_scope ----------------------------------------------
    op.add_column(
        "projects",
        sa.Column(
            "share_scope",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'personal'"),
        ),
    )
    op.create_check_constraint(
        "chk_projects_share_scope_enum",
        "projects",
        "share_scope IN ('personal', 'members', 'org')",
    )
    # A sandbox matter is per-user scratch space; sharing one would leak a
    # colleague's try-it project into the matter list.
    op.create_check_constraint(
        "chk_projects_sandbox_personal",
        "projects",
        "(is_sandbox = false) OR (share_scope = 'personal')",
    )

    # --- backfill: every existing project gets its owner as lead -----------
    op.execute(
        """
        INSERT INTO project_members (project_id, user_id, role, added_by_user_id, created_at)
        SELECT p.id, p.owner_id, 'lead', p.owner_id, p.created_at
        FROM projects AS p
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_constraint("chk_projects_sandbox_personal", "projects", type_="check")
    op.drop_constraint("chk_projects_share_scope_enum", "projects", type_="check")
    op.drop_column("projects", "share_scope")
    op.drop_index("idx_project_members_user", table_name="project_members")
    op.drop_table("project_members")
