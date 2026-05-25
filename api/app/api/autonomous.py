"""Autonomous sessions read/halt API — M4-A4-i.

Three endpoints, all per-user isolated:

* ``POST /sessions/{session_id}/halt`` — idempotent halt request.
* ``GET  /sessions``                  — paginated list, newest first.
* ``GET  /sessions/{session_id}``     — detail + live receipt.

Auth gating: the router is registered under the ``_active`` dep group
in :mod:`app.api` (bearer token + must-change-password gate, same as
``saved_prompts``/``playbooks``).

Cross-user probes return 404 — not 403 — to avoid existence disclosure
(same pattern as :func:`app.api.saved_prompts._load_owned`).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.audit import audit_action
from app.autonomous.audit import autonomous_audit
from app.autonomous.receipt import build_receipt
from app.db.session import get_db
from app.models.autonomous import AutonomousSession
from app.schemas.autonomous import (
    AutonomousSessionDetailResponse,
    AutonomousSessionListResponse,
    AutonomousSessionRead,
)

router = APIRouter(prefix="/autonomous", tags=["autonomous"])

_LIMIT_DEFAULT = 50
_LIMIT_MAX = 200


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_owned_session(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> AutonomousSession:
    """Fetch an autonomous session by id; 404 if missing OR owned by another user.

    Conflates "doesn't exist" and "belongs to someone else" to avoid
    leaking the existence of other users' sessions via id-probing.
    Matches the :func:`~app.api.saved_prompts._load_owned` pattern.

    Args:
        db: Active async ORM session.
        session_id: The :class:`~app.models.autonomous.AutonomousSession`
            primary key to look up.
        user_id: The requesting user's id; must match the row's
            ``user_id`` column.

    Raises:
        HTTPException: 404 if the row is absent or owned by a different user.
    """
    stmt = select(AutonomousSession).where(
        AutonomousSession.id == session_id,
        AutonomousSession.user_id == user_id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="autonomous session not found",
        )
    return row


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/sessions/{session_id}/halt",
    response_model=AutonomousSessionRead,
    summary="Request an immediate halt for an autonomous session (idempotent)",
    responses={
        404: {"description": "Session not found"},
        401: {"description": "Not authenticated"},
    },
)
async def halt_session(
    session_id: uuid.UUID,
    request: Request,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AutonomousSessionRead:
    """POST /api/v1/autonomous/sessions/{session_id}/halt

    Sets ``halt_state = 'halt_requested'`` so the next
    :func:`~app.autonomous.guard.guarded_tool_call` on the session's
    R5 temporal brake trips and the executor transitions to ``halted``.

    **Idempotent:** if ``halt_state`` is already ``halt_requested`` or
    ``halted``, the endpoint returns the current session state with 200
    and writes NO duplicate audit row — callers may retry safely.

    Returns the updated :class:`~app.schemas.autonomous.AutonomousSessionRead`.
    """
    session = await _load_owned_session(db, session_id=session_id, user_id=user.id)

    # Idempotency check: if the session is already halted (in any sense),
    # return current state without a duplicate audit write.
    if session.halt_state in ("halt_requested", "halted"):
        return AutonomousSessionRead.model_validate(session)

    session.halt_state = "halt_requested"

    # Write the user-initiated request event through the closed-enum wrapper.
    await autonomous_audit(db, session, "halt_requested")

    # Also write a standard audit_action row so the audit feed reflects the
    # API call context (IP / UA / request-id) — mirrors saved_prompts pattern.
    await audit_action(
        db,
        user_id=user.id,
        action="autonomous_session.halt_requested",
        resource_type="autonomous_session",
        resource_id=str(session.id),
        request=request,
    )
    await db.commit()
    await db.refresh(session)

    return AutonomousSessionRead.model_validate(session)


@router.get(
    "/sessions",
    response_model=AutonomousSessionListResponse,
    summary="List the calling user's autonomous sessions (newest first, paginated)",
    responses={
        401: {"description": "Not authenticated"},
    },
)
async def list_sessions(
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = _LIMIT_DEFAULT,
    offset: int = 0,
) -> AutonomousSessionListResponse:
    """GET /api/v1/autonomous/sessions

    Returns the caller's sessions ordered by ``created_at DESC``.
    ``limit`` is clamped to [1, 200]; ``offset`` to [0, ∞).
    """
    limit = max(1, min(limit, _LIMIT_MAX))
    offset = max(0, offset)

    # Total count (for pagination envelope)
    count_stmt = (
        select(func.count())
        .select_from(AutonomousSession)
        .where(AutonomousSession.user_id == user.id)
    )
    total_count: int = (await db.execute(count_stmt)).scalar_one()

    rows_stmt = (
        select(AutonomousSession)
        .where(AutonomousSession.user_id == user.id)
        .order_by(AutonomousSession.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(rows_stmt)).scalars().all()

    return AutonomousSessionListResponse(
        sessions=[AutonomousSessionRead.model_validate(r) for r in rows],
        total_count=total_count,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/sessions/{session_id}",
    response_model=AutonomousSessionDetailResponse,
    summary="Fetch a single autonomous session with its full receipt",
    responses={
        404: {"description": "Session not found"},
        401: {"description": "Not authenticated"},
    },
)
async def get_session(
    session_id: uuid.UUID,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AutonomousSessionDetailResponse:
    """GET /api/v1/autonomous/sessions/{session_id}

    Returns the session plus a live-reconstructed receipt (built from
    audit rows on every request — works for running and completed
    sessions). A completed session also has the receipt persisted in
    ``result``.

    Another user's ``session_id`` returns 404 (not 403) to avoid
    existence disclosure.
    """
    session = await _load_owned_session(db, session_id=session_id, user_id=user.id)
    receipt = await build_receipt(session, db)

    return AutonomousSessionDetailResponse(
        session=AutonomousSessionRead.model_validate(session),
        receipt=receipt,
    )
