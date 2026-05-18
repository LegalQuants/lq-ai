"""add inference_routing_log.purpose — M2-E2

Adds a nullable ``purpose`` column to ``inference_routing_log`` so
the api/ side can disambiguate judge calls (Citation Engine Stage 3
and Stage 4) from regular chat completions and embeddings when
computing per-model cost calibration.

Per the M2 plan §M2-E2, the cost pre-flight in ``api/app/api/chats.py``
previously used a single hard-coded conservative constant
(``FLAT_PER_JUDGE_USD = 0.005``). That constant is 5-8x off for some
judge-model choices (haiku → 0.001/call; opus → 0.04/call), which
either causes unnecessary ensemble fallbacks (cost overestimate) or
risks runaway spend (cost underestimate when operators select
larger judge models). The fix replaces the constant with a per-model
rolling average computed from this log — which requires being able
to filter rows down to judge calls only.

Schema change:

* ``inference_routing_log.purpose: varchar(32) NULL`` — values used in
  application code: ``'chat'`` (default for chat completions),
  ``'judge_paraphrase'`` (Citation Engine Stage 3/4 calls),
  ``'embedding'`` (embeddings calls). Nullable for backwards
  compatibility with pre-migration rows; downstream code treats NULL
  the same as ``'chat'`` for cost-calibration purposes (the
  conservative interpretation).
* New composite index ``idx_inference_log_model_purpose_timestamp``
  on ``(routed_model, purpose, timestamp DESC)`` to make the
  per-model rolling-average query for the cost pre-flight cheap. The
  existing ``idx_inference_log_timestamp`` covers other access
  patterns.

Revision ID: 0029
Revises: 0028
Create Date: 2026-05-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "inference_routing_log",
        sa.Column("purpose", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        CREATE INDEX idx_inference_log_model_purpose_timestamp
            ON inference_routing_log (routed_model, purpose, timestamp DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_inference_log_model_purpose_timestamp")
    op.drop_column("inference_routing_log", "purpose")
