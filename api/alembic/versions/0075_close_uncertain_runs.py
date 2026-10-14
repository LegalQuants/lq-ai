"""Closing an uncertain run without a retry (ADR 0038 D6).

Revision ID: 0075
Revises: 0074

ADR 0035 D5 stands: an effect with an uncertain outcome is never repeated, and
its reservation is retained. This revision adds the terminal states an owner
reaches by closing such a run.

* ``orchestration_roots.status`` accepts ``closed``. It is outside the partial
  unique index on active owners, so closing releases the single active-run
  allowance. A root closed while its planning call was uncertain has no plan
  revision, so the planning check admits ``closed`` there too.
* ``orchestration_effects.status`` accepts ``closed``: no outcome was
  established, the reservation was settled as a charge, and no result exists.
  The one-in-flight index is unchanged, so a closed effect no longer blocks.

Downgrade refuses while a closed run or effect is retained.
"""

from alembic import op

revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None

_STATUSES = (
    "'planning','awaiting_approval','queued','running','waiting_children',"
    "'uncertain','halted','completed','failed','rejected','expired'"
)


def upgrade() -> None:
    op.execute(f"""
        ALTER TABLE orchestration_roots DROP CONSTRAINT orchestration_roots_status_check;
        ALTER TABLE orchestration_roots ADD CONSTRAINT orchestration_roots_status_check
          CHECK (status IN ({_STATUSES},'closed'));
        ALTER TABLE orchestration_roots DROP CONSTRAINT ck_orchestration_planning;
        ALTER TABLE orchestration_roots ADD CONSTRAINT ck_orchestration_planning CHECK (
          (profile = 'demonstration' AND planning_snapshot IS NULL AND current_revision IS NOT NULL)
          OR (profile <> 'demonstration' AND planning_snapshot IS NOT NULL
            AND jsonb_typeof(planning_snapshot) = 'object'
            AND (current_revision IS NOT NULL OR status IN
              ('planning','uncertain','halted','failed','expired','closed'))));

        ALTER TABLE orchestration_effects DROP CONSTRAINT orchestration_effects_status_check;
        ALTER TABLE orchestration_effects ADD CONSTRAINT orchestration_effects_status_check
          CHECK (status IN ('admitted','completed','uncertain','closed'));
        ALTER TABLE orchestration_effects DROP CONSTRAINT orchestration_effects_check;
        ALTER TABLE orchestration_effects ADD CONSTRAINT orchestration_effects_check CHECK (
          (status = 'completed' AND charged_usd IS NOT NULL AND result IS NOT NULL
            AND completed_at IS NOT NULL)
          OR (status = 'closed' AND charged_usd IS NOT NULL AND result IS NULL
            AND completed_at IS NOT NULL)
          OR (status IN ('admitted','uncertain') AND charged_usd IS NULL AND result IS NULL
            AND completed_at IS NULL));
    """)


def downgrade() -> None:
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM orchestration_roots WHERE status = 'closed')
             OR EXISTS (SELECT 1 FROM orchestration_effects WHERE status = 'closed')
          THEN
            RAISE EXCEPTION '0075 downgrade requires removing closed runs first';
          END IF;
        END $$;
        ALTER TABLE orchestration_effects DROP CONSTRAINT orchestration_effects_check;
        ALTER TABLE orchestration_effects ADD CONSTRAINT orchestration_effects_check CHECK (
          (status = 'completed' AND charged_usd IS NOT NULL AND result IS NOT NULL
            AND completed_at IS NOT NULL)
          OR (status <> 'completed' AND charged_usd IS NULL AND result IS NULL
            AND completed_at IS NULL));
        ALTER TABLE orchestration_effects DROP CONSTRAINT orchestration_effects_status_check;
        ALTER TABLE orchestration_effects ADD CONSTRAINT orchestration_effects_status_check
          CHECK (status IN ('admitted','completed','uncertain'));
        ALTER TABLE orchestration_roots DROP CONSTRAINT ck_orchestration_planning;
        ALTER TABLE orchestration_roots ADD CONSTRAINT ck_orchestration_planning CHECK (
          (profile = 'demonstration' AND planning_snapshot IS NULL AND current_revision IS NOT NULL)
          OR (profile <> 'demonstration' AND planning_snapshot IS NOT NULL
            AND jsonb_typeof(planning_snapshot) = 'object'
            AND (current_revision IS NOT NULL OR status IN
              ('planning','uncertain','halted','failed','expired'))));
        ALTER TABLE orchestration_roots DROP CONSTRAINT orchestration_roots_status_check;
        ALTER TABLE orchestration_roots ADD CONSTRAINT orchestration_roots_status_check
          CHECK (status IN ({_STATUSES}));
    """)
