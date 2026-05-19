"""create playbooks, playbook_positions, playbook_executions — M3-A1

Substrate for the Playbook engine ([PRD §3.7](docs/PRD.md#37-playbooks))
that ships in M3. A playbook codifies an organization's standard
positions and fallback positions on common contract issues; when
applied to a contract, the LangGraph executor (M3-A2) produces a
per-position assessment (matches / deviates / missing) with redline
suggestions.

Schema overview
---------------

* ``playbooks`` — header row per playbook (name, contract_type, version,
  author). Positions live in a child table.
* ``playbook_positions`` — one row per issue in a playbook
  (severity, detection keywords + examples, standard language,
  fallback tiers as JSONB, redline strategy). Ordered by
  ``position_order``.
* ``playbook_executions`` — one row per execution of a playbook
  against a target document. Status flows ``running`` → ``completed``
  or ``error``; ``results`` is JSONB shaped per the M3-A2 executor.

Fallback tiers are stored as a JSONB array on each position rather
than as a separate ``playbook_fallback_tiers`` table — the per-position
list is small (typically 2-3 ranked alternatives), fetched together
with the position, and modelled as a single unit in the Pydantic
``Position`` wire shape. The JSONB column keeps the schema readable
and avoids a third join on the hot read path.

Indexes
-------

* ``(playbook_id, position_order)`` on ``playbook_positions`` — the
  executor walks a playbook's positions in order; an ordered index
  makes the per-playbook fetch a single B-tree range scan.
* ``(user_id, created_at DESC)`` on ``playbook_executions`` — the UI's
  "my recent executions" view sorts by recency.
* ``(target_document_id)`` on ``playbook_executions`` — the document
  detail view answers "what playbooks have been run against this
  document?" without scanning the table.

CHECK constraints pin two enums at the storage layer: ``severity_if_missing``
on ``playbook_positions`` (critical / high / medium / low per PRD §3.7)
and ``status`` on ``playbook_executions`` (the M3-A2 executor lifecycle).

Revision ID: 0031
Revises: 0030
Create Date: 2026-05-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playbooks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("contract_type", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Text(), nullable=False, server_default="1.0.0"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_playbooks_created_by"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "playbook_positions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "playbook_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "playbooks.id",
                ondelete="CASCADE",
                name="fk_playbook_positions_playbook_id",
            ),
            nullable=False,
        ),
        sa.Column("issue", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("standard_language", sa.Text(), nullable=False),
        sa.Column(
            "fallback_tiers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("redline_strategy", sa.Text(), nullable=False, server_default=""),
        sa.Column("severity_if_missing", sa.Text(), nullable=False),
        sa.Column(
            "detection_keywords",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "detection_examples",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("position_order", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "severity_if_missing IN ('critical','high','medium','low')",
            name="ck_playbook_positions_severity",
        ),
    )
    # Ordered fetch — the executor walks a playbook's positions in
    # ``position_order`` ASC. Single B-tree range scan.
    op.create_index(
        "idx_playbook_positions_playbook_order",
        "playbook_positions",
        ["playbook_id", "position_order"],
    )

    op.create_table(
        "playbook_executions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "playbook_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "playbooks.id",
                ondelete="CASCADE",
                name="fk_playbook_executions_playbook_id",
            ),
            nullable=False,
        ),
        sa.Column(
            "target_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "documents.id",
                ondelete="CASCADE",
                name="fk_playbook_executions_target_document_id",
            ),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="fk_playbook_executions_user_id",
            ),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "projects.id",
                ondelete="SET NULL",
                name="fk_playbook_executions_project_id",
            ),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "results",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','error')",
            name="ck_playbook_executions_status",
        ),
    )
    # "My recent executions" view for the UI.
    op.create_index(
        "idx_playbook_executions_user_created",
        "playbook_executions",
        ["user_id", sa.text("created_at DESC")],
    )
    # "What playbooks have been run against this document?" — drives the
    # document-detail view's playbook-history surface (M3-A4).
    op.create_index(
        "idx_playbook_executions_target_document",
        "playbook_executions",
        ["target_document_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_playbook_executions_target_document",
        table_name="playbook_executions",
    )
    op.drop_index(
        "idx_playbook_executions_user_created",
        table_name="playbook_executions",
    )
    op.drop_table("playbook_executions")
    op.drop_index(
        "idx_playbook_positions_playbook_order",
        table_name="playbook_positions",
    )
    op.drop_table("playbook_positions")
    op.drop_table("playbooks")
