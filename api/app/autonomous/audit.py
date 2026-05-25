"""Closed-enum audit wrapper for the autonomous executor (M4-A3.1).

All autonomous-session audit writes flow through :func:`autonomous_audit`
rather than calling :func:`~app.audit.audit_action` directly. This
gives us one place to:

* Enforce the closed event set (assertion at call time rather than a
  string scattered across call sites).
* Apply the canonical ``autonomous_session.<event>`` action format.
* Gate ``details`` content: counts, types, IDs, costs, and enums are
  fine; raw entity values (names, email addresses, legal text) are not.

Closed event set
-----------------
``started`` | ``phase_transition`` | ``tool_call`` | ``halted`` |
``cost_cap_reached`` | ``completed``

Any string not in this set raises :exc:`AssertionError` immediately so
call-site typos surface in tests rather than silently writing bad rows.

Usage::

    from app.autonomous.audit import autonomous_audit

    await autonomous_audit(db, session, "tool_call", tool="run_skill", phase="analysis")
    await autonomous_audit(db, session, "halted", reason="idle_timeout")
    await autonomous_audit(db, session, "completed", cost_total_usd=str(session.cost_total_usd))
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit_action
from app.models.autonomous import AutonomousSession

_ACTIONS: frozenset[str] = frozenset(
    {
        "started",
        "phase_transition",
        "tool_call",
        "halted",
        "cost_cap_reached",
        "completed",
        # M4-A4-i: user-initiated halt request via POST /sessions/{id}/halt.
        # The executor's ``halted`` event remains the actual stop written at
        # the R5 brake; ``halt_requested`` is the API-layer request that
        # precedes it.  These are logically distinct events in the audit
        # trail and in the receipt's terminal-reason chain.
        "halt_requested",
    }
)
"""Closed set of audit event names for autonomous sessions.

Any call with an ``event`` not in this set raises :exc:`AssertionError`
at call time, catching call-site typos in tests rather than writing
incorrect audit rows to the DB.
"""


async def autonomous_audit(
    db: AsyncSession,
    session: AutonomousSession,
    event: str,
    **details: Any,
) -> None:
    """Write one ``audit_log`` row for an autonomous-session event.

    Enforces the closed ``_ACTIONS`` set: an unknown ``event`` raises
    :exc:`AssertionError` immediately (no DB write). Details kwargs are
    passed through as the ``details`` dict; an empty kwargs dict produces
    ``details=None`` in the row (matching the audit-table convention for
    no-detail rows).

    Flushes but does NOT commit — the caller's outer transaction owns the
    commit boundary, per the :func:`~app.audit.audit_action` contract.

    Args:
        db: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
        session: The :class:`~app.models.autonomous.AutonomousSession`
            being audited; provides ``user_id`` and ``id``.
        event: One of the closed event names in ``_ACTIONS``
            (``"started"``, ``"phase_transition"``, ``"tool_call"``,
            ``"halted"``, ``"cost_cap_reached"``, ``"completed"``).
        **details: Structured scalar values (counts, type slugs, UUIDs,
            costs, enum strings). MUST NOT contain raw entity values
            (names, email addresses, legal text).

    Raises:
        AssertionError: If ``event`` is not a member of ``_ACTIONS``.
    """

    assert event in _ACTIONS, f"undefined autonomous audit action: {event!r}"

    await audit_action(
        db,
        user_id=session.user_id,
        action=f"autonomous_session.{event}",
        resource_type="autonomous_session",
        resource_id=str(session.id),
        details=details or None,
    )
