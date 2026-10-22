"""A governed run may complete without a plan (ADR 0038 D1).

Revision ID: 0077
Revises: 0076

Where a profile hands its plan over by tool call, the orchestrator may answer a
request by itself. That run ends ``completed`` with no plan row: its
``current_revision`` stays null. Until now ``ck_orchestration_planning`` let a
run without a plan end only as uncertain, halted, failed, expired or closed.
This revision adds ``completed`` to that list. Nothing else changes.

The constraint cannot say that such a run made one model call and admitted no
child. The application holds that: the planning call is the only effect a run
may admit before it has an approved plan, and children are admitted only under
one (ADR 0035 D2).

Downgrade refuses while a run that completed without a plan is retained.
"""

from alembic import op

revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None

_PLANNING = """
        ALTER TABLE orchestration_roots DROP CONSTRAINT ck_orchestration_planning;
        ALTER TABLE orchestration_roots ADD CONSTRAINT ck_orchestration_planning CHECK (
          (profile = 'demonstration' AND planning_snapshot IS NULL AND current_revision IS NOT NULL)
          OR (profile <> 'demonstration' AND planning_snapshot IS NOT NULL
            AND jsonb_typeof(planning_snapshot) = 'object'
            AND (current_revision IS NOT NULL OR status IN ({statuses}))));
"""
_BEFORE = "'planning','uncertain','halted','failed','expired','closed'"


def upgrade() -> None:
    op.execute(_PLANNING.format(statuses=f"{_BEFORE},'completed'"))


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM orchestration_roots
            WHERE status = 'completed' AND current_revision IS NULL
          ) THEN
            RAISE EXCEPTION '0077 downgrade requires removing runs answered without a plan first';
          END IF;
        END $$;
    """)
    op.execute(_PLANNING.format(statuses=_BEFORE))
