"""Bounded session-owned working files for ADR 0035.

Revision ID: 0070
Revises: 0069
"""

from alembic import op

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE orchestration_files (
        session_id UUID NOT NULL REFERENCES orchestration_accounts(session_id) ON DELETE CASCADE,
        name TEXT NOT NULL CHECK (name ~ '^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}$'),
        content TEXT NOT NULL CHECK (octet_length(content) <= 65536),
        revision INTEGER NOT NULL CHECK (revision BETWEEN 1 AND 32),
        digest TEXT NOT NULL CHECK (digest ~ '^[0-9a-f]{64}$'),
        size_bytes INTEGER NOT NULL CHECK (size_bytes = octet_length(content)),
        shared BOOLEAN NOT NULL DEFAULT false,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (session_id, name)
    )""")


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM orchestration_files)
           OR EXISTS (SELECT 1 FROM orchestration_accounts WHERE worker_id IS NOT NULL)
        THEN RAISE EXCEPTION 'Workspace downgrade requires draining and exporting existing runs';
        END IF;
    END $$""")
    op.execute("DROP TABLE orchestration_files")
