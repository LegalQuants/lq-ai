"""Pre-approval orchestration planning, preserving sample run identities.

Revision ID: 0069
Revises: 0068
"""

from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE orchestration_roots
          ALTER COLUMN current_revision DROP NOT NULL,
          ADD COLUMN planning_snapshot jsonb,
          ADD COLUMN profile text NOT NULL DEFAULT 'demonstration',
          DROP CONSTRAINT orchestration_roots_status_check,
          ADD CONSTRAINT orchestration_roots_status_check CHECK (status IN
            ('planning','awaiting_approval','queued','running','waiting_children',
             'uncertain','halted','completed','failed','rejected','expired')),
          ADD CONSTRAINT ck_orchestration_profile CHECK
            (profile IN ('demonstration','model_demo_v1')),
          ADD CONSTRAINT ck_orchestration_planning CHECK (
            (profile = 'demonstration' AND planning_snapshot IS NULL AND current_revision IS NOT NULL)
            OR (profile = 'model_demo_v1' AND planning_snapshot IS NOT NULL
              AND jsonb_typeof(planning_snapshot) = 'object'
              AND (current_revision IS NOT NULL OR status IN
                ('planning','uncertain','halted','failed','expired')))),
          ADD CONSTRAINT ck_orchestration_planning_revision CHECK
            (status <> 'planning' OR current_revision IS NULL);
        DROP INDEX uq_orchestration_active_owner;
        CREATE UNIQUE INDEX uq_orchestration_active_owner ON orchestration_roots(owner_id)
          WHERE status IN ('planning','awaiting_approval','queued','running','waiting_children','uncertain');
    """)


def downgrade() -> None:
    # Retained model runs require an explicit export/deletion decision; never
    # silently discard their receipts or reinterpret them as sample runs.
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM orchestration_roots WHERE profile <> 'demonstration') THEN
        RAISE EXCEPTION 'Retained model demonstration runs prevent downgrade';
      END IF;
    END $$;
    ALTER TABLE orchestration_roots
      DROP CONSTRAINT ck_orchestration_planning_revision,
      DROP CONSTRAINT ck_orchestration_planning,
      DROP CONSTRAINT ck_orchestration_profile,
      DROP CONSTRAINT orchestration_roots_status_check,
      DROP COLUMN planning_snapshot, DROP COLUMN profile,
      ALTER COLUMN current_revision SET NOT NULL,
      ADD CONSTRAINT orchestration_roots_status_check CHECK (status IN
        ('awaiting_approval','queued','running','waiting_children','uncertain',
         'halted','completed','failed','rejected','expired'));
    DROP INDEX uq_orchestration_active_owner;
    CREATE UNIQUE INDEX uq_orchestration_active_owner ON orchestration_roots(owner_id)
      WHERE status IN ('awaiting_approval','queued','running','waiting_children','uncertain');
    """)
