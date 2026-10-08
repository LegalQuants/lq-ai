"""A governed run may belong to no matter (ADR 0038 D1, D5).

Revision ID: 0072
Revises: 0071

A run started from a chat that is in no matter has no project. This revision
lets ``orchestration_roots.project_id`` be null. Nothing else changes: the
foreign key and its ``ON DELETE RESTRICT`` stay, ``autonomous_sessions.project_id``
was already nullable, and the tree trigger from 0067 compares projects with
``IS DISTINCT FROM``, so a root and its children that all have no project pass.

What such a run may read and which inference tier it may use are decided by the
application, not here: it reads only the owner's files that are filed in no
matter, it is never treated as privileged, and its tier floor is the profile's.

Downgrade refuses while a run without a matter is retained.
"""

from alembic import op

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE orchestration_roots ALTER COLUMN project_id DROP NOT NULL")


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM orchestration_roots WHERE project_id IS NULL) THEN
            RAISE EXCEPTION '0072 downgrade requires removing runs outside a matter first';
          END IF;
        END $$;
        ALTER TABLE orchestration_roots ALTER COLUMN project_id SET NOT NULL;
    """)
