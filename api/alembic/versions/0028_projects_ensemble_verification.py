"""add projects.ensemble_verification — M2-D1

Adds the project-level activation flag for Citation Engine Stage 4
(ensemble verification). Per the M2 plan §M2-D1, three independent
sources can activate ensemble verification on a chat:

1. The skill's frontmatter ``ensemble_verification: true`` (per-skill).
2. The chat's project's ``ensemble_verification: true`` (per-project,
   this column).
3. The gateway's
   ``citation_engine.ensemble_verification.default_enabled: true``
   (deployment-wide default).

A chat-send computes ``any(...)`` across the three signals and passes
the resolved boolean into ``persist_citations`` → ``verify``. The
column is added as ``NOT NULL DEFAULT false`` so existing rows stay
on the deployment default — operators who want to flip an existing
matter into ensemble mode do so explicitly with a project update.

No index — the column is read per-message-send for the message's
parent project (already indexed on PK lookup) and never used as a
filter predicate.

Revision ID: 0028
Revises: 0027
Create Date: 2026-05-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "ensemble_verification",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "ensemble_verification")
