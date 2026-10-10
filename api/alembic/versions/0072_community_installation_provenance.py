"""Write-once community installation provenance.

Revision ID: 0072
Revises: 0071
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_skills", sa.Column("installation_provenance", postgresql.JSONB(), nullable=True)
    )
    op.execute("""CREATE FUNCTION protect_skill_installation_provenance()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.installation_provenance IS DISTINCT FROM OLD.installation_provenance THEN
            RAISE EXCEPTION 'Community installation provenance is write-once';
        END IF;
        RETURN NEW;
    END $$""")
    op.execute("""CREATE TRIGGER user_skill_installation_provenance_immutable
    BEFORE UPDATE OF installation_provenance ON user_skills
    FOR EACH ROW EXECUTE FUNCTION protect_skill_installation_provenance()""")


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM user_skills WHERE installation_provenance IS NOT NULL)
        THEN RAISE EXCEPTION 'Export and clear installed community skills before removing provenance';
        END IF;
    END $$""")
    op.execute("DROP TRIGGER user_skill_installation_provenance_immutable ON user_skills")
    op.execute("DROP FUNCTION protect_skill_installation_provenance()")
    op.drop_column("user_skills", "installation_provenance")
