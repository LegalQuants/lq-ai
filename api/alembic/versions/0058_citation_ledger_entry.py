"""citation_ledger_entry — the Citation Ledger (ADR 0018 D1)

Revision ID: 0058
Revises: 0057
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "citation_ledger_entry",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "projects.id", ondelete="CASCADE", name="fk_citation_ledger_entry_project"
            ),
            nullable=True,
        ),
        sa.Column(
            "chat_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chats.id", ondelete="CASCADE", name="fk_citation_ledger_entry_chat"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "messages.id", ondelete="CASCADE", name="fk_citation_ledger_entry_message"
            ),
            nullable=False,
        ),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column(
            "message_citation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "message_citations.id",
                ondelete="CASCADE",
                name="fk_citation_ledger_entry_msg_citation",
            ),
            nullable=True,
        ),
        sa.Column(
            "message_caselaw_citation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "message_caselaw_citations.id",
                ondelete="CASCADE",
                name="fk_citation_ledger_entry_caselaw_citation",
            ),
            nullable=True,
        ),
        sa.Column(
            "message_tool_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "message_tool_sources.id",
                ondelete="CASCADE",
                name="fk_citation_ledger_entry_tool_source",
            ),
            nullable=True,
        ),
        sa.Column("verification_status", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("treatment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(message_citation_id IS NOT NULL)::int "
            "+ (message_caselaw_citation_id IS NOT NULL)::int "
            "+ (message_tool_source_id IS NOT NULL)::int = 1",
            name="chk_citation_ledger_entry_exactly_one_source",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="chk_citation_ledger_entry_confidence_range",
        ),
    )
    op.create_index("ix_citation_ledger_entry_chat_id", "citation_ledger_entry", ["chat_id"])
    op.create_index("ix_citation_ledger_entry_message_id", "citation_ledger_entry", ["message_id"])
    op.create_index("ix_citation_ledger_entry_project_id", "citation_ledger_entry", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_citation_ledger_entry_project_id", table_name="citation_ledger_entry")
    op.drop_index("ix_citation_ledger_entry_message_id", table_name="citation_ledger_entry")
    op.drop_index("ix_citation_ledger_entry_chat_id", table_name="citation_ledger_entry")
    op.drop_table("citation_ledger_entry")
