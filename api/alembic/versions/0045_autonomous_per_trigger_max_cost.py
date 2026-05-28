"""autonomous_watches + autonomous_schedules per-trigger max_cost_usd — M4 real executor work

Adds an optional ``max_cost_usd`` to both trigger tables so a user can cap
autonomous spend per watch / per schedule. ``NULL`` means "fall back to the
global default at spawn time" (``settings.autonomous_default_max_cost_usd``,
mirroring the gateway.yaml default of $5).

Mirrors the existing ``autonomous_sessions.max_cost_usd`` column type
(``NUMERIC(10,4)``). Spawn paths in
:func:`app.autonomous.watch_trigger.fire_watches_for_kb` and
:func:`app.workers.autonomous_worker._run_schedule_sweep` are updated in
the same PR to ALWAYS set the spawned session's ``max_cost_usd`` (per-trigger
value or global default) so R4 has teeth in production.

Revision ID: 0045
Revises: 0044
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "autonomous_watches",
        sa.Column("max_cost_usd", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "autonomous_schedules",
        sa.Column("max_cost_usd", sa.Numeric(10, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("autonomous_schedules", "max_cost_usd")
    op.drop_column("autonomous_watches", "max_cost_usd")
