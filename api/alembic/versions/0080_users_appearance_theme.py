"""users.appearance_theme — the per-user shell theme preference (ADR 0045 §2)

Adds:
- appearance_theme  TEXT NOT NULL DEFAULT 'system'  (light | dark | system)

``system`` is "Match system": follow the device's colour scheme. Existing
users get ``system`` from the column default, which is the ADR's default for
anyone who has never chosen.

The column ships with a DB-level CHECK constraint
(``chk_users_appearance_theme_enum``) that mirrors the Pydantic Literal
enforcement in the API layer — the same defense-in-depth pattern as migration
0019's personalization preferences.

This migration only stores the value. Nothing reads it yet: the web shell
renders light until the dark theme ships.

Revision ID: 0080
Revises: 0079
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0080"
down_revision: str | None = "0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "appearance_theme",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'system'"),
        ),
    )
    op.create_check_constraint(
        "chk_users_appearance_theme_enum",
        "users",
        "appearance_theme IN ('light', 'dark', 'system')",
    )


def downgrade() -> None:
    op.drop_constraint("chk_users_appearance_theme_enum", "users", type_="check")
    op.drop_column("users", "appearance_theme")
