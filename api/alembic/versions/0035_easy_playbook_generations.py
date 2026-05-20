"""create easy_playbook_generations table — M3-A6 Phase 5

The Easy Playbook generation pipeline (M3-A6) is async — the API's
``POST /api/v1/playbooks/easy`` endpoint returns 202 immediately with
a generation-row id, and the ARQ worker on the ``arq:m3a6`` queue
runs the extract → cluster → assemble pipeline against the supplied
documents and writes its progress back to this row.

Schema
------

* ``id`` — UUID PK.
* ``user_id`` — caller's user id; nullable + ``ON DELETE SET NULL``
  so historical generations survive operator deletion (matches the
  ``playbook_executions.user_id`` posture from migration 0031).
* ``contract_type`` — the playbook's target contract family
  ("NDA", "MSA-SaaS", etc.); free-form text per PRD §3.7.
* ``status`` — lifecycle ``pending → running → completed | error``.
  CHECK-constrained at the storage layer.
* ``document_ids`` — array of source document UUIDs from the
  upload corpus. NOT a foreign key (documents can be soft-deleted
  after generation completes; we preserve the row for audit).
* ``draft_playbook`` — JSONB; the assembled :class:`PlaybookCreate`
  shape. Populated only on ``status='completed'``; the Phase 6
  wizard's Step 3 inline editor consumes this.
* ``error_message`` — text; populated on ``status='error'``.
* ``created_at`` / ``started_at`` / ``completed_at`` — lifecycle
  timestamps. ``started_at`` set on ``pending → running``;
  ``completed_at`` set on either terminal state.

Indexes
-------

* ``(user_id, created_at DESC)`` — the wizard's history view sorts
  the caller's recent generations by recency.

Revision ID: 0035
Revises: 0034
Create Date: 2026-05-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "easy_playbook_generations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="fk_easy_playbook_generations_user_id",
            ),
            nullable=True,
        ),
        sa.Column("contract_type", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "document_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column(
            "draft_playbook",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','error')",
            name="chk_easy_playbook_generations_status",
        ),
    )

    op.execute(
        """
        CREATE INDEX idx_easy_playbook_generations_user_recent
            ON easy_playbook_generations (user_id, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_easy_playbook_generations_user_recent")
    op.drop_table("easy_playbook_generations")
