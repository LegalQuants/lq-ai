"""Closed-enum audit wrapper for the autonomous executor (M4-A3.1).

The autonomous-session audit writes of the engine flow through
:func:`autonomous_audit` rather than calling :func:`~app.audit.audit_action`
directly. (Two API routes, a halt request and ``run-now``, also write a row of
their own that carries the request's IP, user agent and request id; they pass
the session's project, so it is marked the same way.) This gives us one place
to:

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

import uuid
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit_action
from app.autonomous.enums import ToolIntent
from app.models.autonomous import AutonomousSession
from app.models.orchestration import OrchestrationRoot
from app.models.project import Project

OWNERSHIP_DENIED_OUTCOME: Final[str] = "ownership_denied"

# The ``privilege_basis`` of a run that is privileged because another matter
# holding one of its selected files is: a run outside any matter (ADR 0038,
# ruling 4), or a run in a matter that is not itself privileged and reads a
# file from a privileged matter's knowledge base. A privileged matter's own
# rows carry its name; such a run has none of its own to name.
RUN_PRIVILEGE_BASIS: Final[str] = "run terms: a selected file is held by a privileged matter"


def recorded_privilege(planning_snapshot: dict[str, Any] | None) -> bool:
    """Whether a governed run was accepted as privileged (``root.privileged`` of its intake)."""
    scope = planning_snapshot.get("root") if isinstance(planning_snapshot, dict) else None
    return isinstance(scope, dict) and scope.get("privileged") is True


async def run_privilege(
    db: AsyncSession, project_id: uuid.UUID | None, privileged: bool
) -> dict[str, Any]:
    """The privilege marking for the audit rows of a governed run.

    ``privileged`` is what the run's intake recorded at the start
    (:func:`recorded_privilege`); every admission holds the run to it. A run in
    a privileged matter is marked from that matter, as any row of the matter
    is. A run that is privileged without that, because a matter that holds a
    selected file is, has no matter of its own to take the basis from and is
    marked with :data:`RUN_PRIVILEGE_BASIS`. Returns the keyword arguments for
    :func:`~app.audit.audit_action`; a run that is not privileged is marked as
    any other row.
    """
    if privileged and not (
        project_id is not None
        and await db.scalar(select(Project.privileged).where(Project.id == project_id))
    ):
        return {"privilege_marked": True, "privilege_basis": RUN_PRIVILEGE_BASIS}
    return {"project_id": project_id}


class AuditedRetrievalOwnershipDenied(ValueError):
    """Retrieval refused after its closing ownership-denied audit was flushed.

    The analysis loop must preserve the nonfatal ValueError observation without
    adding a second closing row. Audit-write failures never use this signal.
    """


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

    # A session may belong to a governed run, which carries the terms it took
    # on at the start; any other is marked from its matter, or not at all.
    # Only the one recorded flag is read, not the whole snapshot, which this
    # query runs for on every row of every session.
    privileged = await db.scalar(
        select(OrchestrationRoot.planning_snapshot["root"]["privileged"].as_boolean()).where(
            OrchestrationRoot.session_id == session.root_session_id
        )
    )
    marking = await run_privilege(db, session.project_id, privileged is True)

    await audit_action(
        db,
        user_id=session.user_id,
        action=f"autonomous_session.{event}",
        resource_type="autonomous_session",
        resource_id=str(session.id),
        details=details or None,
        **marking,
    )


async def audit_retrieval_ownership_denial(db: AsyncSession, session: AutonomousSession) -> None:
    """Flush a payload-free refusal; the executor owns commit or rollback.

    Called only when a retrieval ownership predicate refuses access. Preserve
    audit failures rather than suppressing them or continuing into retrieval.
    """
    await autonomous_audit(
        db,
        session,
        "tool_call",
        tool=str(ToolIntent.retrieve_chunks),
        outcome=OWNERSHIP_DENIED_OUTCOME,
    )
