"""Stamp audit_log rows with the wall-clock time of the insert.

Revision ID: 0069
Revises: 0068

``audit_log.timestamp`` defaulted to ``now()``, which Postgres fixes at the
start of the transaction. Every row written inside one transaction therefore
carried the same timestamp: an autonomous session, whose executor flushes its
audit rows and commits once, produced a receipt in which every phase
transition and tool call showed the session's start time, in an order the
database was free to choose. ``clock_timestamp()`` advances within a
transaction, so each row records when it was written and ``ORDER BY
timestamp`` returns the rows in the order they happened.

Only the column default changes. Existing rows keep their timestamps.
"""

from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE audit_log ALTER COLUMN timestamp SET DEFAULT clock_timestamp()")


def downgrade() -> None:
    op.execute("ALTER TABLE audit_log ALTER COLUMN timestamp SET DEFAULT now()")
