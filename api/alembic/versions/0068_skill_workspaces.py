"""Persistent, optional owner/project/skill workspaces.

Revision ID: 0068
Revises: 0067
"""

from alembic import op

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE skill_workspaces (
        id UUID PRIMARY KEY,
        owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
        skill_key TEXT NOT NULL CHECK (char_length(skill_key) BETWEEN 1 AND 256),
        skill_name TEXT NOT NULL CHECK (char_length(skill_name) BETWEEN 1 AND 256),
        format_version INTEGER NOT NULL CHECK (format_version BETWEEN 1 AND 1000),
        CONSTRAINT uq_skill_workspace_scope UNIQUE NULLS NOT DISTINCT
            (owner_id, project_id, skill_key, format_version)
    )""")
    op.execute("""CREATE TABLE skill_workspace_files (
        workspace_id UUID NOT NULL REFERENCES skill_workspaces(id) ON DELETE CASCADE,
        name TEXT NOT NULL CHECK (name ~ '^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}$'),
        content TEXT NOT NULL CHECK (octet_length(content) <= 65536),
        revision UUID NOT NULL,
        size_bytes INTEGER NOT NULL CHECK (size_bytes = octet_length(content)),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (workspace_id, name)
    )""")


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM skill_workspaces)
        THEN RAISE EXCEPTION 'Skill workspace downgrade requires exporting and clearing retained work';
        END IF;
    END $$""")
    op.execute("DROP TABLE skill_workspace_files")
    op.execute("DROP TABLE skill_workspaces")
