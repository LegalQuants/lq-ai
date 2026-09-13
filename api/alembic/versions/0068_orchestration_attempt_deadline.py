"""Bound renewable worker leases to a fixed per-attempt deadline.

Revision ID: 0068
Revises: 0067

Existing claims retain their current lease as their conservative attempt limit.
Drain ownership before downgrade; receipts and budget history are preserved.
"""

from alembic import op

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE orchestration_accounts ADD COLUMN attempt_deadline timestamptz;
        UPDATE orchestration_accounts SET attempt_deadline = lease_until;
        ALTER TABLE orchestration_accounts ADD CONSTRAINT ck_orchestration_attempt_lease
          CHECK (
            (worker_id IS NULL AND attempt_deadline IS NULL)
            OR (worker_id IS NOT NULL AND attempt_deadline IS NOT NULL
                AND lease_until <= attempt_deadline)
          );
    """)


def downgrade() -> None:
    op.execute("""
        LOCK TABLE orchestration_accounts IN ACCESS EXCLUSIVE MODE;
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM orchestration_accounts WHERE worker_id IS NOT NULL) THEN
            RAISE EXCEPTION '0068 downgrade requires draining worker ownership first';
          END IF;
        END $$;
        ALTER TABLE orchestration_accounts DROP CONSTRAINT ck_orchestration_attempt_lease;
        ALTER TABLE orchestration_accounts DROP COLUMN attempt_deadline;
    """)
