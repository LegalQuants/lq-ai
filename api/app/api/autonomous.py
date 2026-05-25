"""Autonomous sessions + memory curation API — M4-A4-i, M4-B1.

Endpoints, all per-user isolated:

Sessions (M4-A4-i):
* ``POST /sessions/{session_id}/halt`` — idempotent halt request.
* ``GET  /sessions``                  — paginated list, newest first.
* ``GET  /sessions/{session_id}``     — detail + live receipt.

Memory curation (M4-B1):
* ``GET  /memory``                           — list non-deleted entries.
* ``POST /memory/{memory_id}/keep``          — proposed|dismissed → kept.
* ``POST /memory/{memory_id}/dismiss``       — proposed|kept → dismissed.
* ``DELETE /memory/{memory_id}``             — soft-delete; returns 200.

Auth gating: the router is registered under the ``_active`` dep group
in :mod:`app.api` (bearer token + must-change-password gate, same as
``saved_prompts``/``playbooks``).

Cross-user probes return 404 — not 403 — to avoid existence disclosure
(same pattern as :func:`app.api.saved_prompts._load_owned`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.audit import audit_action
from app.autonomous.audit import autonomous_audit
from app.autonomous.receipt import build_receipt
from app.db.session import get_db
from app.models.autonomous import AutonomousMemory, AutonomousSession
from app.schemas.autonomous import (
    AutonomousMemoryListResponse,
    AutonomousMemoryRead,
    AutonomousSessionDetailResponse,
    AutonomousSessionListResponse,
    AutonomousSessionRead,
    MemoryKeepRequest,
    MemoryState,
)

router = APIRouter(prefix="/autonomous", tags=["autonomous"])

_LIMIT_DEFAULT = 50
_LIMIT_MAX = 200


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_owned_memory(
    db: AsyncSession,
    *,
    memory_id: uuid.UUID,
    user_id: uuid.UUID,
) -> AutonomousMemory:
    """Fetch an autonomous memory entry by id; 404 if missing, soft-deleted, or owned by another user.

    Conflates "doesn't exist", "soft-deleted", and "belongs to someone else"
    to avoid leaking the existence of other users' entries via id-probing.
    Mirrors :func:`_load_owned_session`.

    Args:
        db: Active async ORM session.
        memory_id: The :class:`~app.models.autonomous.AutonomousMemory`
            primary key to look up.
        user_id: The requesting user's id; must match the row's
            ``user_id`` column.

    Raises:
        HTTPException: 404 if the row is absent, soft-deleted, or owned
            by a different user.
    """
    stmt = select(AutonomousMemory).where(
        AutonomousMemory.id == memory_id,
        AutonomousMemory.user_id == user_id,
        AutonomousMemory.deleted_at.is_(None),
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="autonomous memory entry not found",
        )
    return row


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


# ---------------------------------------------------------------------------
# Memory curation endpoints (M4-B1)
# ---------------------------------------------------------------------------


@router.get(
    "/memory",
    response_model=AutonomousMemoryListResponse,
    summary="List the calling user's autonomous memory entries (non-deleted, newest first)",
    responses={
        401: {"description": "Not authenticated"},
    },
)
async def list_memory(
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    state: Annotated[MemoryState | None, Query()] = None,
    limit: int = _LIMIT_DEFAULT,
    offset: int = 0,
) -> AutonomousMemoryListResponse:
    """GET /api/v1/autonomous/memory

    Returns the caller's non-deleted memory entries ordered by
    ``created_at DESC``.  Pass ``?state=proposed|kept|dismissed`` to
    filter; omitting ``state`` returns all non-deleted entries.
    ``limit`` is clamped to [1, 200]; ``offset`` to [0, ∞).
    """
    limit = max(1, min(limit, _LIMIT_MAX))
    offset = max(0, offset)

    base_where = [
        AutonomousMemory.user_id == user.id,
        AutonomousMemory.deleted_at.is_(None),
    ]
    if state is not None:
        base_where.append(AutonomousMemory.state == str(state))

    count_stmt = select(func.count()).select_from(AutonomousMemory).where(*base_where)
    total_count: int = (await db.execute(count_stmt)).scalar_one()

    rows_stmt = (
        select(AutonomousMemory)
        .where(*base_where)
        .order_by(AutonomousMemory.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(rows_stmt)).scalars().all()

    return AutonomousMemoryListResponse(
        entries=[AutonomousMemoryRead.model_validate(r) for r in rows],
        total_count=total_count,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/memory/{memory_id}/keep",
    response_model=AutonomousMemoryRead,
    summary="Keep (approve) an autonomous memory entry; optional edit-on-keep",
    responses={
        404: {"description": "Memory entry not found"},
        401: {"description": "Not authenticated"},
    },
)
async def keep_memory(
    memory_id: uuid.UUID,
    request: Request,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    body: MemoryKeepRequest | None = None,
) -> AutonomousMemoryRead:
    """POST /api/v1/autonomous/memory/{memory_id}/keep

    Transitions ``proposed`` or ``dismissed`` → ``kept``.  If
    ``body.content`` is provided, overwrites the entry's text (edit-on-keep).

    **Re-keep semantics:** if the entry is already ``kept``, the action is
    allowed — content is updated if provided; ``kept_at`` is left as-is
    (preserves the original keep timestamp).

    Returns the updated entry.  Audited.
    """
    memory = await _load_owned_memory(db, memory_id=memory_id, user_id=user.id)

    if memory.state != str(MemoryState.kept):
        memory.kept_at = datetime.now(UTC)

    memory.state = str(MemoryState.kept)

    if body is not None and body.content is not None:
        memory.content = body.content

    memory.updated_at = datetime.now(UTC)

    await audit_action(
        db,
        user_id=user.id,
        action="autonomous_memory.keep",
        resource_type="autonomous_memory",
        resource_id=str(memory.id),
        request=request,
    )
    await db.commit()
    await db.refresh(memory)

    return AutonomousMemoryRead.model_validate(memory)


@router.post(
    "/memory/{memory_id}/dismiss",
    response_model=AutonomousMemoryRead,
    summary="Dismiss an autonomous memory entry",
    responses={
        404: {"description": "Memory entry not found"},
        401: {"description": "Not authenticated"},
    },
)
async def dismiss_memory(
    memory_id: uuid.UUID,
    request: Request,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AutonomousMemoryRead:
    """POST /api/v1/autonomous/memory/{memory_id}/dismiss

    Transitions ``proposed`` or ``kept`` → ``dismissed``.

    Returns the updated entry.  Audited.
    """
    memory = await _load_owned_memory(db, memory_id=memory_id, user_id=user.id)

    memory.state = str(MemoryState.dismissed)
    memory.updated_at = datetime.now(UTC)

    await audit_action(
        db,
        user_id=user.id,
        action="autonomous_memory.dismiss",
        resource_type="autonomous_memory",
        resource_id=str(memory.id),
        request=request,
    )
    await db.commit()
    await db.refresh(memory)

    return AutonomousMemoryRead.model_validate(memory)


@router.delete(
    "/memory/{memory_id}",
    response_model=AutonomousMemoryRead,
    summary="Soft-delete an autonomous memory entry (returns 200 with updated entry)",
    responses={
        404: {"description": "Memory entry not found"},
        401: {"description": "Not authenticated"},
    },
)
async def delete_memory(
    memory_id: uuid.UUID,
    request: Request,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AutonomousMemoryRead:
    """DELETE /api/v1/autonomous/memory/{memory_id}

    Soft-deletes the entry by setting ``deleted_at=now(UTC)``.  Returns
    **200** with the updated (deleted) entry rather than 204 to avoid the
    FastAPI ``JSONResponse``/204 assertion pitfall (documented in
    CLAUDE.md).

    A subsequent GET excludes the entry; keep/dismiss/delete on a deleted
    entry return 404 (``_load_owned_memory`` filters ``deleted_at IS NULL``).

    Audited.
    """
    memory = await _load_owned_memory(db, memory_id=memory_id, user_id=user.id)

    memory.deleted_at = datetime.now(UTC)
    memory.updated_at = datetime.now(UTC)

    await audit_action(
        db,
        user_id=user.id,
        action="autonomous_memory.delete",
        resource_type="autonomous_memory",
        resource_id=str(memory.id),
        request=request,
    )
    await db.commit()
    await db.refresh(memory)

    return AutonomousMemoryRead.model_validate(memory)
