"""Phase-transition helper for the autonomous executor — M4-A2.

The single public function, :func:`run_phase_transition`, updates
the session row's ``current_phase`` field and writes an
``autonomous_session.phase_transition`` audit row in the same
transaction (flush only — the caller owns the commit, per the
:func:`~app.audit.audit_action` contract).

Audit action string is part of a closed set::

    autonomous_session.{started, phase_transition, tool_call,
                        halted, cost_cap_reached, completed}

Only ``phase_transition`` (and optionally ``started`` / ``completed``
in later tasks) is in scope for M4-A2.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.audit import autonomous_audit
from app.models.autonomous import AutonomousSession
from app.schemas.autonomous import Phase


async def run_phase_transition(
    session: AutonomousSession,
    to_phase: Phase,
    db: AsyncSession,
) -> None:
    """Advance ``session`` to ``to_phase`` and write an audit row.

    Sets ``session.current_phase`` to ``to_phase`` then calls
    :func:`~app.autonomous.audit.autonomous_audit` with event
    ``"phase_transition"`` and ``to_phase`` in the details dict.
    This routes through the closed-enum audit wrapper so all autonomous
    session audit writes share one path (M4-A3.1 refactor).

    * ``action = "autonomous_session.phase_transition"``
    * ``resource_type = "autonomous_session"``
    * ``resource_id = str(session.id)``
    * ``details = {"to_phase": str(to_phase)}``
    * ``user_id = session.user_id``
    * No project context (the transition audit row is not
      privilege-bearing by itself).

    The helper flushes but does NOT commit — the executor's outer
    transaction owns the commit boundary.
    """

    session.current_phase = str(to_phase)
    await autonomous_audit(db, session, "phase_transition", to_phase=str(to_phase))
