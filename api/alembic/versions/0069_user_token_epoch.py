"""Access-token invalidation epoch on users.

Adds ``users.token_epoch``. Each access token carries the user's epoch at mint
time; the request path rejects any token whose epoch is below the current one.
Incremented on logout and password change so those actions invalidate
outstanding access tokens immediately (pen-test findings jwt#F-A / #F-B).

Revision ID: 0069
Revises: 0068
"""

from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN token_epoch INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN token_epoch")
