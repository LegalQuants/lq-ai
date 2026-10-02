"""Backfill project_knowledge_bases from knowledge_bases.project_id.

Per ADR-00XX (junction as sole source of truth for project<->KB
association; to be filled once it is recorded): copy every live
primary-project link into the junction so the #442 filter change is
lossless for existing deployments. The column
itself is left in place (write-freeze and drop are the ADR's follow-up
steps, separate migrations).

Revision ID: 0066
Revises: 0065
"""

from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO project_knowledge_bases (project_id, knowledge_base_id)
        SELECT kb.project_id, kb.id
        FROM knowledge_bases kb
        WHERE kb.project_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    # Deliberately a no-op: the inserted rows are indistinguishable from
    # attach-created rows, and deleting them would destroy user data.
    # Revert of #442's filter change does not require removing them.
    pass
