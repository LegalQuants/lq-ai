"""relax message_caselaw_citations method CHECK to allow paraphrase_judge (P1-B1b)

Revision ID: 0060
Revises: 0059
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "chk_message_caselaw_citations_method_values"
_TABLE = "message_caselaw_citations"


def upgrade() -> None:
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(
        _NAME,
        _TABLE,
        "verification_method IS NULL OR verification_method IN "
        "('exact_match', 'tolerant_match', 'paraphrase_judge')",
    )


def downgrade() -> None:
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(
        _NAME,
        _TABLE,
        "verification_method IS NULL OR verification_method IN ('exact_match', 'tolerant_match')",
    )
