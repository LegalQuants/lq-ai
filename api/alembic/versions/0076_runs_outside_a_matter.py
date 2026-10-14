"""A governed run may belong to no matter (ADR 0038 D1, D5).

Revision ID: 0076
Revises: 0075

A run started from a chat that is in no matter has no project. This revision
lets ``orchestration_roots.project_id`` be null. Nothing else changes: the
foreign key and its ``ON DELETE RESTRICT`` stay, ``autonomous_sessions.project_id``
was already nullable, and the tree trigger from 0067 compares projects with
``IS DISTINCT FROM``, so a root and its children that all have no project pass.

What such a run may read and which inference tier it may use are decided by the
application, not here: it reads the owner's undeleted files wherever they are
filed, and takes on the strictest floor and the privilege flag of the matters
that hold the files it selects. With none held by a matter it is not privileged
and its floor is the profile's (ADR 0038, ruling 4; ``reading.selection_terms``).

Downgrade refuses while a run without a matter is retained.
"""

from alembic import op

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE orchestration_roots ALTER COLUMN project_id DROP NOT NULL")


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM orchestration_roots WHERE project_id IS NULL) THEN
            RAISE EXCEPTION '0076 downgrade requires removing runs outside a matter first';
          END IF;
        END $$;
        ALTER TABLE orchestration_roots ALTER COLUMN project_id SET NOT NULL;
    """)
