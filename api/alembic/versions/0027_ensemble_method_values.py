"""ensemble verification on message_citations — method enum + tier envelope (M2-D1)

The Citation Engine Stage 4 (ensemble verification) lands here. Two
changes on ``message_citations``:

1. **verification_method enum widening.** Per the M2 plan §M2-D1 the
   persisted method distinguishes the two aggregation rules:
   ``'ensemble_strict'`` (all judges must agree) and
   ``'ensemble_majority'`` (simple majority wins). M2-C1's migration
   0026 reserved a generic ``'ensemble'`` value pre-emptively; we
   replace it with the two tighter labels here so the persisted method
   always names the aggregation rule the operator chose. Stage 4 had
   not shipped before this migration so no real row should exist with
   the bare ``'ensemble'`` value; the downgrade reinstates it for
   symmetry.

2. **tier_envelope column (SMALLINT NULL).** Captures the privacy
   envelope of the ensemble that verified a citation — the maximum
   (weakest) inference tier across the judge models that ran. Per the
   M2-D1 spec, sending a citation to an n-model ensemble means the
   verification's privacy posture is the weakest tier in the set
   (e.g., one Tier 4 judge in an otherwise Tier 3 ensemble makes the
   verification a Tier 4 exposure). The column is NULL for non-
   ensemble methods (Stages 1-3 are single-tier by construction) and
   carries the integer envelope tier (1-5 per PRD §1.5.2) for
   ensemble rows. Audit-only: no behavior gates on it, but operators
   can query ``message_citations`` to surface chats whose
   verification reached weaker tiers than their primary inference.

Revision ID: 0027
Revises: 0026
Create Date: 2026-05-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


_NEW_METHOD_VALUES = (
    "exact_match",
    "tolerant_match",
    "llm_judge",
    "paraphrase_judge",
    "ensemble_strict",
    "ensemble_majority",
    "failed",
)

_OLD_METHOD_VALUES = (
    "exact_match",
    "tolerant_match",
    "llm_judge",
    "paraphrase_judge",
    "ensemble",
    "failed",
)


def _method_check_sql(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"verification_method IS NULL OR verification_method IN ({quoted})"


def upgrade() -> None:
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

    op.add_column(
        "message_citations",
        sa.Column(
            "tier_envelope",
            sa.SmallInteger(),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "chk_message_citations_tier_envelope_range",
        "message_citations",
        "tier_envelope IS NULL OR (tier_envelope BETWEEN 1 AND 5)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "chk_message_citations_tier_envelope_range",
        "message_citations",
        type_="check",
    )
    op.drop_column("message_citations", "tier_envelope")

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
