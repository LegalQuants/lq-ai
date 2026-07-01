"""authority_citations_and_text_cache — fetched-authority citation tables (WS-E PR1b)

Adds:
- message_authority_citations  (one row per verbatim passage verified against a
  fetched statute/regulation/other authority source; mirrors
  message_caselaw_citations but uses string source_type/external_ref/content_kind
  instead of BigInteger opinion_id/cluster_id)
- authority_text_cache  (content cache for fetched authority source bodies;
  mirrors research_opinion_metadata shape; cache key = (source_type, external_ref))

Alters:
- citation_ledger_entry: adds message_authority_citation_id FK column and
  extends chk_citation_ledger_entry_exactly_one_source from 3-term to 4-term sum.

Revision ID: 0064
Revises: 0063
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0064"
down_revision: str | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create message_authority_citations
    # ------------------------------------------------------------------
    op.create_table(
        "message_authority_citations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "messages.id",
                ondelete="CASCADE",
                name="fk_message_authority_citations_message",
            ),
            nullable=False,
        ),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("external_ref", sa.Text(), nullable=False),
        sa.Column("content_kind", sa.Text(), nullable=False),
        sa.Column("source_offset_start", sa.Integer(), nullable=False),
        sa.Column("source_offset_end", sa.Integer(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("verification_method", sa.Text(), nullable=True),
        sa.Column("verification_confidence", sa.Float(), nullable=True),
        sa.Column("partial", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_offset_start >= 0",
            name="chk_message_authority_citations_offset_start_nonneg",
        ),
        sa.CheckConstraint(
            "source_offset_end > source_offset_start",
            name="chk_message_authority_citations_offset_end_gt_start",
        ),
        sa.CheckConstraint(
            "verification_method IS NULL OR verification_method IN "
            "('exact_match', 'tolerant_match', 'paraphrase_judge')",
            name="chk_message_authority_citations_method_values",
        ),
        sa.CheckConstraint(
            "verification_confidence IS NULL OR "
            "(verification_confidence >= 0 AND verification_confidence <= 1)",
            name="chk_message_authority_citations_confidence_range",
        ),
        sa.CheckConstraint(
            "(verified = false) OR (verification_method IS NOT NULL)",
            name="chk_message_authority_citations_verified_has_method",
        ),
    )
    op.create_index(
        "ix_message_authority_citations_message_id",
        "message_authority_citations",
        ["message_id"],
    )

    # ------------------------------------------------------------------
    # 2. Create authority_text_cache
    # ------------------------------------------------------------------
    op.create_table(
        "authority_text_cache",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("external_ref", sa.Text(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("char_length", sa.Integer(), nullable=False),
        sa.Column(
            "retrieved_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "source_type",
            "external_ref",
            name="uq_authority_text_cache_source_ref",
        ),
    )
    op.create_index(
        "ix_authority_text_cache_source_ref",
        "authority_text_cache",
        ["source_type", "external_ref"],
    )

    # ------------------------------------------------------------------
    # 3. Alter citation_ledger_entry: add FK column
    # ------------------------------------------------------------------
    op.add_column(
        "citation_ledger_entry",
        sa.Column(
            "message_authority_citation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_citation_ledger_entry_authority_citation",
        "citation_ledger_entry",
        "message_authority_citations",
        ["message_authority_citation_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ------------------------------------------------------------------
    # 4. Replace 3-term CHECK with 4-term CHECK on citation_ledger_entry
    # ------------------------------------------------------------------
    op.drop_constraint(
        "chk_citation_ledger_entry_exactly_one_source",
        "citation_ledger_entry",
        type_="check",
    )
    op.create_check_constraint(
        "chk_citation_ledger_entry_exactly_one_source",
        "citation_ledger_entry",
        "(message_citation_id IS NOT NULL)::int "
        "+ (message_caselaw_citation_id IS NOT NULL)::int "
        "+ (message_tool_source_id IS NOT NULL)::int "
        "+ (message_authority_citation_id IS NOT NULL)::int = 1",
    )


def downgrade() -> None:
    # ------------------------------------------------------------------
    # 4. Restore 3-term CHECK on citation_ledger_entry
    # ------------------------------------------------------------------
    op.drop_constraint(
        "chk_citation_ledger_entry_exactly_one_source",
        "citation_ledger_entry",
        type_="check",
    )
    op.create_check_constraint(
        "chk_citation_ledger_entry_exactly_one_source",
        "citation_ledger_entry",
        "(message_citation_id IS NOT NULL)::int "
        "+ (message_caselaw_citation_id IS NOT NULL)::int "
        "+ (message_tool_source_id IS NOT NULL)::int = 1",
    )

    # ------------------------------------------------------------------
    # 3. Drop FK column from citation_ledger_entry
    # ------------------------------------------------------------------
    op.drop_constraint(
        "fk_citation_ledger_entry_authority_citation",
        "citation_ledger_entry",
        type_="foreignkey",
    )
    op.drop_column("citation_ledger_entry", "message_authority_citation_id")

    # ------------------------------------------------------------------
    # 2. Drop authority_text_cache
    # ------------------------------------------------------------------
    op.drop_index("ix_authority_text_cache_source_ref", table_name="authority_text_cache")
    op.drop_table("authority_text_cache")

    # ------------------------------------------------------------------
    # 1. Drop message_authority_citations
    # ------------------------------------------------------------------
    op.drop_index(
        "ix_message_authority_citations_message_id",
        table_name="message_authority_citations",
    )
    op.drop_table("message_authority_citations")
