"""Per-session receipt builder — M4-A4-i.

Reconstructs a human-readable "what the agent did and why" summary from
:class:`~app.models.audit.AuditLog` rows written during the session.

**Privacy contract (critical):**
The receipt is built ONLY from audit ``details`` fields — which already
carry only counts / types / IDs / costs / enum labels (enforced in A3 by
:func:`~app.autonomous.audit.autonomous_audit`).  The builder never pulls
raw column values from :class:`~app.models.autonomous.AutonomousSession`
beyond the safe scalar fields (IDs, enums, costs, timestamps), and never
fetches document text or entity values from any other table.

The returned dict is JSON-serialisable and can be stored in
``autonomous_sessions.result`` (JSONB column).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession

log = logging.getLogger(__name__)


async def build_receipt(
    session: AutonomousSession,
    db: AsyncSession,
) -> dict[str, Any]:
    """Build a JSON-serialisable receipt for *session* from its audit rows.

    Queries all ``audit_log`` rows where ``resource_type ==
    "autonomous_session"`` and ``resource_id == str(session.id)``,
    ordered by ``timestamp``.

    The receipt contains:

    * Top-level session scalars (IDs, enums, costs, timestamps) — safe
      metadata only; no raw entity values.
    * ``phase_transitions`` — ordered list assembled from
      ``autonomous_session.phase_transition`` rows.
    * ``tool_calls`` — ordered list assembled from
      ``autonomous_session.tool_call`` rows; each entry carries the
      audit details (tool, outcome, cost_usd if present).
    * ``terminal_reason`` — string pulled from the first
      ``halted`` / ``cost_cap_reached`` / ``completed`` row, or
      ``None`` if the session is still running.

    Args:
        session: The :class:`~app.models.autonomous.AutonomousSession`
            whose receipt is being built.
        db: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.

    Returns:
        A ``dict[str, Any]`` that is JSON-serialisable (all values are
        strings, ints, floats, booleans, lists, dicts, or ``None``).
        Suitable for storing in ``autonomous_sessions.result`` (JSONB).
    """

    rows = (
        (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.resource_type == "autonomous_session")
                .where(AuditLog.resource_id == str(session.id))
                .order_by(AuditLog.timestamp)
            )
        )
        .scalars()
        .all()
    )

    phase_transitions: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    terminal_reason: str | None = None

    for row in rows:
        suffix = row.action.removeprefix("autonomous_session.")
        details: dict[str, Any] = row.details or {}

        at: str | None = row.timestamp.isoformat() if row.timestamp is not None else None

        if suffix == "phase_transition":
            phase_transitions.append(
                {
                    "to_phase": details.get("to_phase"),
                    "timestamp": at,
                }
            )

        elif suffix == "tool_call":
            entry: dict[str, Any] = {
                "tool": details.get("tool"),
                "outcome": details.get("outcome"),
                "timestamp": at,
            }
            if "cost_usd" in details:
                entry["cost_usd"] = details["cost_usd"]
            tool_calls.append(entry)

        elif suffix in ("halted", "cost_cap_reached", "completed") and terminal_reason is None:
            # Use the first terminal row to determine the terminal reason.
            if suffix == "halted":
                terminal_reason = details.get("reason", "external_halt")
            elif suffix == "cost_cap_reached":
                terminal_reason = "cost_cap_reached"
            else:
                terminal_reason = "completed"

    # Determine current status string safely.
    status_str = str(session.status) if session.status is not None else None

    # cost_total_usd may be a Decimal — convert to float for JSON safety.
    cost_total: float | None
    try:
        cost_total = float(session.cost_total_usd) if session.cost_total_usd is not None else 0.0
    except (TypeError, ValueError):
        cost_total = 0.0

    max_cost: float | None
    try:
        max_cost = float(session.max_cost_usd) if session.max_cost_usd is not None else None
    except (TypeError, ValueError):
        max_cost = None

    return {
        "session_id": str(session.id),
        "trigger_kind": str(session.trigger_kind),
        "status": status_str,
        "halt_state": str(session.halt_state) if session.halt_state is not None else None,
        "current_phase": str(session.current_phase) if session.current_phase is not None else None,
        "cost_total_usd": cost_total,
        "max_cost_usd": max_cost,
        "cost_cap_reached": bool(session.cost_cap_reached),
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "phase_transitions": phase_transitions,
        "tool_calls": tool_calls,
        "terminal_reason": terminal_reason,
    }


async def build_receipt_safe(session: AutonomousSession, db: AsyncSession) -> dict[str, Any] | None:
    """Best-effort :func:`build_receipt` — NEVER raises.

    On any failure, logs and returns ``None`` so a receipt-build error can
    neither crash the autonomous worker nor leave the session row
    non-terminal. The caller has already set the terminal status; persisting
    it (and committing) is the caller's responsibility and must proceed even
    when the receipt JSON could not be assembled. (DE-325)
    """
    try:
        return await build_receipt(session, db)
    except Exception:
        log.warning(
            "build_receipt failed; persisting terminal status without a receipt",
            extra={
                "event": "autonomous_build_receipt_failed",
                "session_id": str(session.id),
            },
            exc_info=True,
        )
        return None
