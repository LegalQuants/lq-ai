"""Closed-enum audit wrapper for privileged cross-user reads.

Every time an admin/auditor reads ANOTHER user's ledger / sources /
session-ledger / receipts, the handler records one ``audit_log`` row
through this wrapper ("audit the auditor"). Mirrors
``app/autonomous/audit.py``: a closed event set caught at call time.

NOTE: like ``audit_action``, this flushes but does NOT commit — but its
callers are GET handlers that do not otherwise commit, so each caller
MUST ``await db.commit()`` after calling this (see the endpoint tasks).
"""

from __future__ import annotations

import uuid

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit_action
from app.models.user import User

_AUDITOR_EVENTS: frozenset[str] = frozenset(
    {
        "ledger_viewed",
        "sources_viewed",
        "citations_viewed",
        "session_ledger_viewed",
        "receipts_viewed",
        "receipts_exported",
    }
)


async def auditor_audit(
    db: AsyncSession,
    *,
    user: User,
    event: str,
    resource_type: str,
    resource_id: str,
    viewed_user_id: uuid.UUID,
    request: Request | None = None,
) -> None:
    """Write one ``audit_log`` row for a privileged cross-user read.

    ``event`` must be in :data:`_AUDITOR_EVENTS` (AssertionError otherwise —
    catches call-site typos in tests). Does not commit; the caller does.

    ``request``, when provided, is forwarded to :func:`audit_action` so the
    row carries ``ip_address`` / ``user_agent`` / ``request_id`` — otherwise
    those columns are null (the handler had no request context).
    """
    assert event in _AUDITOR_EVENTS, f"unknown auditor audit event: {event!r}"
    await audit_action(
        db,
        user_id=user.id,
        action=f"auditor.{event}",
        resource_type=resource_type,
        resource_id=resource_id,
        details={"viewed_user_id": str(viewed_user_id)},
        request=request,
    )
