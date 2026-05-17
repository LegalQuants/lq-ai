"""add paraphrase_judge method + partial column on message_citations — M2-C1

Stage 3 of the Citation Engine cascade is the LLM paraphrase judge.
Two schema changes land here:

1. The ``verification_method`` CHECK constraint is widened from the
   M2-A2 list to also accept ``'paraphrase_judge'``. M2-A2's enum
   reserved ``'llm_judge'`` for this slot (more generic), but the M2
   plan §M2-C1 names the method ``'paraphrase_judge'`` and that's the
   semantically tighter label — only paraphrase judgments take this
   code path. We add it as a new value rather than reusing the
   generic name so future LLM-based verification stages (semantic
   matching, claim decomposition) can take ``'llm_judge'`` without
   conflating with the paraphrase verdict.

2. A ``partial`` BOOLEAN NOT NULL DEFAULT FALSE column distinguishes
   "judge says yes, this paraphrase captures the claim" from "judge
   says the claim is *partially* supported — the source supports
   part but not all of what the model cited." Both persist as
   ``verified=true``; the partial flag drives the M2-C2 UI's
   visually-distinct "verified with caveats" rendering.

The CHECK constraint replacement uses DROP + ADD because Postgres
doesn't support in-place ALTER on a named CHECK. Downgrade reverses
both.

Revision ID: 0026
Revises: 0025
Create Date: 2026-05-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


_NEW_METHOD_VALUES = (
    "exact_match",
    "tolerant_match",
    "llm_judge",
    "paraphrase_judge",
    "ensemble",
    "failed",
)

_OLD_METHOD_VALUES = (
    "exact_match",
    "tolerant_match",
    "llm_judge",
    "ensemble",
    "failed",
)


def _method_check_sql(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"verification_method IS NULL OR verification_method IN ({quoted})"


def upgrade() -> None:
    # Replace the method CHECK with the widened list.
    op.drop_constraint(
        "chk_message_citations_method_values",
        "message_citations",
        type_="check",
    )
    op.create_check_constraint(
        "chk_message_citations_method_values",
        "message_citations",
        _method_check_sql(_NEW_METHOD_VALUES),
    )

    # ``partial`` defaults False — existing rows stay strictly verified
    # or unverified; only Stage 3's 'partial' verdict sets this true.
    op.add_column(
        "message_citations",
        sa.Column(
            "partial",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("message_citations", "partial")

    op.drop_constraint(
        "chk_message_citations_method_values",
        "message_citations",
        type_="check",
    )
    op.create_check_constraint(
        "chk_message_citations_method_values",
        "message_citations",
        _method_check_sql(_OLD_METHOD_VALUES),
    )
