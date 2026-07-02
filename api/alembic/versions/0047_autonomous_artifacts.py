"""autonomous_artifacts — persist document-grade artifact references

An opted-in autonomous run may persist document-grade artifacts
(markdown memos) into its target knowledge base as real documents. This
table records the *reference* per emitted artifact; the document itself
lives in ``files`` / the KB like any other upload.

``session_id`` FK is ``ON DELETE CASCADE`` — the artifact reference dies
with its session. ``file_id`` FK is ``ON DELETE SET NULL`` — the KB
document OUTLIVES the session (it is the user's deliverable); a hard
file-delete nulls the ref while the name/size metadata survives. There
is no ``user_id`` column: authz is via the owning session. An index on
``session_id`` backs the read endpoint's by-session query. ``name`` and
``mime`` are LLM-emitted free text — deliberately NO CHECK (the
``autonomous_findings.severity`` precedent).

Also adds the opt-in ``emit_artifacts`` flag to ``autonomous_schedules``
and ``autonomous_watches`` (NOT NULL, default false — existing
automations see zero behavior or cost change).

Revision ID: 0047
Revises: 0046
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "autonomous_artifacts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "autonomous_sessions.id",
                ondelete="CASCADE",
                name="fk_autonomous_artifacts_session_id",
            ),
            nullable=False,
        ),
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "files.id",
                ondelete="SET NULL",
                name="fk_autonomous_artifacts_file_id",
            ),
            nullable=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_autonomous_artifacts_session_id",
        "autonomous_artifacts",
        ["session_id"],
    )
    op.add_column(
        "autonomous_schedules",
        sa.Column(
            "emit_artifacts",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "autonomous_watches",
        sa.Column(
            "emit_artifacts",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("autonomous_watches", "emit_artifacts")
    op.drop_column("autonomous_schedules", "emit_artifacts")
    op.drop_index("ix_autonomous_artifacts_session_id", table_name="autonomous_artifacts")
    op.drop_table("autonomous_artifacts")
