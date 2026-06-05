"""Autonomous sessions + memory + precedent board API — M4-A4-i, M4-B1, M4-B2.

Endpoints, all per-user isolated:

Sessions (M4-A4-i):
* ``POST /sessions/{session_id}/halt`` — idempotent halt request.
* ``GET  /sessions``                  — paginated list, newest first.
* ``GET  /sessions/{session_id}``     — detail + live receipt.
* ``GET  /sessions/{session_id}/findings`` — the run's findings, emission order.

Memory curation (M4-B1):
* ``GET  /memory``                           — list non-deleted entries.
* ``POST /memory/{memory_id}/keep``          — proposed|dismissed → kept.
* ``POST /memory/{memory_id}/dismiss``       — proposed|kept → dismissed.
* ``DELETE /memory/{memory_id}``             — soft-delete; returns 200.

Precedent board + promote-to-Project proposals (M4-B2):
* ``GET  /precedents``                       — list non-dismissed entries.
* ``POST /precedents/{precedent_id}/dismiss`` — set dismissed_at; idempotent.
* ``POST /precedents/{precedent_id}/promote`` — create a Project-context
  proposal (proposal only — never writes Project context).
* ``GET  /project-context-proposals``        — list the caller's proposals.
* ``POST /project-context-proposals/{proposal_id}/accept`` — the
  user-authorized write: append suggested_md to projects.context_md.
* ``POST /project-context-proposals/{proposal_id}/reject`` — set rejected.

Auth gating: the router is registered under the ``_active`` dep group
in :mod:`app.api` (bearer token + must-change-password gate, same as
``saved_prompts``/``playbooks``).

Cross-user probes return 404 — not 403 — to avoid existence disclosure
(same pattern as :func:`app.api.saved_prompts._load_owned`).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Mutate endpoints use AutonomousEnabledUser (opt-in required, PRD §3.10);
# read + halt endpoints use ActiveUser (always reachable for audit access).
from app.api.dependencies import ActiveUser, AutonomousEnabledUser
from app.audit import audit_action
from app.autonomous.audit import autonomous_audit
from app.autonomous.cron import next_run_after, validate_cron_expr
from app.autonomous.receipt import build_receipt
from app.config import get_settings
from app.db.session import get_db
from app.models.autonomous import (
    AutonomousFinding,
    AutonomousMemory,
    AutonomousNotification,
    AutonomousSchedule,
    AutonomousSession,
    AutonomousWatch,
    PrecedentEntry,
    ProjectContextProposal,
)
from app.models.knowledge import KnowledgeBase
from app.models.project import Project
from app.schemas.autonomous import (
    AutonomousFindingListResponse,
    AutonomousFindingRead,
    AutonomousManualRunRequest,
    AutonomousMemoryListResponse,
    AutonomousMemoryRead,
    AutonomousNotificationListResponse,
    AutonomousNotificationRead,
    AutonomousScheduleCreate,
    AutonomousScheduleListResponse,
    AutonomousScheduleRead,
    AutonomousScheduleUpdate,
    AutonomousSessionDetailResponse,
    AutonomousSessionListResponse,
    AutonomousSessionRead,
    AutonomousWatchCreate,
    AutonomousWatchListResponse,
    AutonomousWatchRead,
    AutonomousWatchUpdate,
    MemoryKeepRequest,
    MemoryState,
    PrecedentEntryListResponse,
    PrecedentEntryRead,
    ProjectContextProposalListResponse,
    ProjectContextProposalRead,
    PromotePrecedentRequest,
    ProposalState,
)
from app.workers.queue import enqueue_autonomous_session_job

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


async def _load_owned_precedent(
    db: AsyncSession,
    *,
    precedent_id: uuid.UUID,
    user_id: uuid.UUID,
) -> PrecedentEntry:
    """Fetch a precedent entry by id; 404 if missing OR owned by another user.

    Conflates "doesn't exist" and "belongs to someone else" to avoid leaking
    the existence of other users' precedents via id-probing. Mirrors
    :func:`_load_owned_memory`, but does NOT filter on a soft-delete column:
    precedents have ``dismissed_at`` (not ``deleted_at``), and a dismissed
    precedent is still loadable so dismiss is idempotent and promotion of a
    dismissed precedent remains possible.

    Raises:
        HTTPException: 404 if the row is absent or owned by a different user.
    """
    stmt = select(PrecedentEntry).where(
        PrecedentEntry.id == precedent_id,
        PrecedentEntry.user_id == user_id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="precedent entry not found",
        )
    return row


async def _load_owned_project(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Project:
    """Fetch a Project by id; 404 if missing OR not owned by the caller.

    Conflates "doesn't exist" and "belongs to someone else" to avoid
    existence disclosure — same idiom as the autonomous loaders. The
    autonomous layer never reveals another user's Projects.

    Raises:
        HTTPException: 404 if the row is absent or owned by a different user.
    """
    stmt = select(Project).where(
        Project.id == project_id,
        Project.owner_id == user_id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found",
        )
    return row


async def _load_owned_proposal(
    db: AsyncSession,
    *,
    proposal_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ProjectContextProposal:
    """Fetch a project-context proposal by id; 404 if missing OR another user's.

    Conflates "doesn't exist" and "belongs to someone else" to avoid
    existence disclosure. Mirrors :func:`_load_owned_memory`.

    Raises:
        HTTPException: 404 if the row is absent or owned by a different user.
    """
    stmt = select(ProjectContextProposal).where(
        ProjectContextProposal.id == proposal_id,
        ProjectContextProposal.user_id == user_id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project-context proposal not found",
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


async def _load_owned_schedule(
    db: AsyncSession,
    *,
    schedule_id: uuid.UUID,
    user_id: uuid.UUID,
) -> AutonomousSchedule:
    """Fetch a schedule by id; 404 if missing, soft-deleted, or another user's.

    Conflates "doesn't exist", "soft-deleted", and "belongs to someone
    else" to avoid leaking the existence of other users' schedules via
    id-probing. Mirrors :func:`_load_owned_memory` (filters
    ``deleted_at IS NULL``).

    Raises:
        HTTPException: 404 if the row is absent, soft-deleted, or owned
            by a different user.
    """
    stmt = select(AutonomousSchedule).where(
        AutonomousSchedule.id == schedule_id,
        AutonomousSchedule.user_id == user_id,
        AutonomousSchedule.deleted_at.is_(None),
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="autonomous schedule not found",
        )
    return row


async def _load_owned_watch(
    db: AsyncSession,
    *,
    watch_id: uuid.UUID,
    user_id: uuid.UUID,
) -> AutonomousWatch:
    """Fetch a watch by id; 404 if missing, soft-deleted, or another user's.

    Conflates "doesn't exist", "soft-deleted", and "belongs to someone
    else" to avoid leaking the existence of other users' watches via
    id-probing. Mirrors :func:`_load_owned_schedule` (filters
    ``deleted_at IS NULL``).

    Raises:
        HTTPException: 404 if the row is absent, soft-deleted, or owned
            by a different user.
    """
    stmt = select(AutonomousWatch).where(
        AutonomousWatch.id == watch_id,
        AutonomousWatch.user_id == user_id,
        AutonomousWatch.deleted_at.is_(None),
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="autonomous watch not found",
        )
    return row


async def _load_owned_notification(
    db: AsyncSession,
    *,
    notification_id: uuid.UUID,
    user_id: uuid.UUID,
) -> AutonomousNotification:
    """Fetch a notification by id; 404 if missing OR owned by another user.

    Conflates "doesn't exist" and "belongs to someone else" to avoid
    leaking the existence of other users' notifications via id-probing.
    Mirrors :func:`_load_owned_precedent` — there is no soft-delete column
    on notifications (``read_at`` is the dismiss action, and a read
    notification is still loadable so re-read is idempotent).

    Raises:
        HTTPException: 404 if the row is absent or owned by a different user.
    """
    stmt = select(AutonomousNotification).where(
        AutonomousNotification.id == notification_id,
        AutonomousNotification.user_id == user_id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="autonomous notification not found",
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


@router.get(
    "/sessions/{session_id}/findings",
    response_model=AutonomousFindingListResponse,
    summary="List a session's persisted findings (work-product, emission order)",
    responses={
        404: {"description": "Session not found"},
        401: {"description": "Not authenticated"},
    },
)
async def list_session_findings(
    session_id: uuid.UUID,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = _LIMIT_DEFAULT,
    offset: int = 0,
) -> AutonomousFindingListResponse:
    """GET /api/v1/autonomous/sessions/{session_id}/findings

    Returns the run's persisted findings (the ``emit_finding`` chokepoint
    work-product) ordered by ``created_at ASC`` — emission order, the run's
    output sequence. This differs intentionally from the newest-first
    autonomous lists: these are one run's sequential output, not a feed.

    Owner-gated by loading the owned session first (the findings table has
    no ``user_id`` — authz is via the parent session). Another user's
    ``session_id`` — or a missing one — returns 404 (not 403) to avoid
    existence disclosure. ``limit`` is clamped to [1, 200]; ``offset`` to
    [0, ∞).
    """
    await _load_owned_session(db, session_id=session_id, user_id=user.id)

    limit = max(1, min(limit, _LIMIT_MAX))
    offset = max(0, offset)

    base_where = [AutonomousFinding.session_id == session_id]

    count_stmt = select(func.count()).select_from(AutonomousFinding).where(*base_where)
    total_count: int = (await db.execute(count_stmt)).scalar_one()

    rows_stmt = (
        select(AutonomousFinding)
        .where(*base_where)
        .order_by(AutonomousFinding.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(rows_stmt)).scalars().all()

    return AutonomousFindingListResponse(
        findings=[AutonomousFindingRead.model_validate(r) for r in rows],
        total_count=total_count,
        limit=limit,
        offset=offset,
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
    source_session_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: int = _LIMIT_DEFAULT,
    offset: int = 0,
) -> AutonomousMemoryListResponse:
    """GET /api/v1/autonomous/memory

    Returns the caller's non-deleted memory entries ordered by
    ``created_at DESC``.  Pass ``?state=proposed|kept|dismissed`` to
    filter by review state; omitting ``state`` returns all non-deleted
    entries.  Pass ``?source_session_id=`` to narrow to the memories a
    specific run proposed (the run's "memories this run proposed" view).
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
    if source_session_id is not None:
        base_where.append(AutonomousMemory.source_session_id == source_session_id)

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
    user: AutonomousEnabledUser,
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
    user: AutonomousEnabledUser,
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
    user: AutonomousEnabledUser,
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


# ---------------------------------------------------------------------------
# Precedent board endpoints (M4-B2)
# ---------------------------------------------------------------------------


@router.get(
    "/precedents",
    response_model=PrecedentEntryListResponse,
    summary="List the calling user's precedent entries (non-dismissed, newest first)",
    responses={
        401: {"description": "Not authenticated"},
    },
)
async def list_precedents(
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    pattern_kind: Annotated[str | None, Query()] = None,
    limit: int = _LIMIT_DEFAULT,
    offset: int = 0,
) -> PrecedentEntryListResponse:
    """GET /api/v1/autonomous/precedents

    Returns the caller's non-dismissed precedent entries (``dismissed_at
    IS NULL``) ordered by ``created_at DESC``.  Pass ``?pattern_kind=`` to
    filter to one classifier; omitting it returns all non-dismissed
    entries.  ``limit`` is clamped to [1, 200]; ``offset`` to [0, ∞).
    """
    limit = max(1, min(limit, _LIMIT_MAX))
    offset = max(0, offset)

    base_where = [
        PrecedentEntry.user_id == user.id,
        PrecedentEntry.dismissed_at.is_(None),
    ]
    if pattern_kind is not None:
        base_where.append(PrecedentEntry.pattern_kind == pattern_kind)

    count_stmt = select(func.count()).select_from(PrecedentEntry).where(*base_where)
    total_count: int = (await db.execute(count_stmt)).scalar_one()

    rows_stmt = (
        select(PrecedentEntry)
        .where(*base_where)
        .order_by(PrecedentEntry.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(rows_stmt)).scalars().all()

    return PrecedentEntryListResponse(
        entries=[PrecedentEntryRead.model_validate(r) for r in rows],
        total_count=total_count,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/precedents/{precedent_id}/dismiss",
    response_model=PrecedentEntryRead,
    summary="Dismiss a precedent entry (idempotent)",
    responses={
        404: {"description": "Precedent entry not found"},
        401: {"description": "Not authenticated"},
    },
)
async def dismiss_precedent(
    precedent_id: uuid.UUID,
    request: Request,
    user: AutonomousEnabledUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PrecedentEntryRead:
    """POST /api/v1/autonomous/precedents/{precedent_id}/dismiss

    Sets ``dismissed_at=now(UTC)`` so the entry drops out of the board.

    **Idempotent:** re-dismissing leaves the original ``dismissed_at``
    untouched (the entry is still loadable — ``_load_owned_precedent``
    does not filter dismissed rows).

    Another user's ``precedent_id`` returns 404.  Audited.
    """
    precedent = await _load_owned_precedent(db, precedent_id=precedent_id, user_id=user.id)

    if precedent.dismissed_at is None:
        precedent.dismissed_at = datetime.now(UTC)
        precedent.updated_at = datetime.now(UTC)

    await audit_action(
        db,
        user_id=user.id,
        action="autonomous_precedent.dismiss",
        resource_type="precedent_entry",
        resource_id=str(precedent.id),
        request=request,
    )
    await db.commit()
    await db.refresh(precedent)

    return PrecedentEntryRead.model_validate(precedent)


@router.post(
    "/precedents/{precedent_id}/promote",
    response_model=ProjectContextProposalRead,
    status_code=status.HTTP_201_CREATED,
    summary="Propose promoting a precedent into a Project's context (proposal only)",
    responses={
        201: {"description": "Proposal created"},
        404: {"description": "Precedent or target project not found"},
        401: {"description": "Not authenticated"},
    },
)
async def promote_precedent(
    precedent_id: uuid.UUID,
    body: PromotePrecedentRequest,
    request: Request,
    user: AutonomousEnabledUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectContextProposalRead:
    """POST /api/v1/autonomous/precedents/{precedent_id}/promote

    Creates a ``proposed`` :class:`ProjectContextProposal` linking the
    precedent to ``body.project_id``.  The ``suggested_md`` snippet is
    **derived server-side** from the precedent's ``summary``.

    This endpoint does **NOT** mutate ``projects.context_md`` — promotion
    is a proposal only; the user accepting it (``…/accept``) performs the
    authorized write (ADR 0013 D5).

    Another user's ``precedent_id`` — or a ``project_id`` the caller does
    not own — returns 404.  Audited.
    """
    precedent = await _load_owned_precedent(db, precedent_id=precedent_id, user_id=user.id)
    project = await _load_owned_project(db, project_id=body.project_id, user_id=user.id)

    suggested_md = f"- Recurring precedent ({precedent.pattern_kind}): {precedent.summary}"

    proposal = ProjectContextProposal(
        user_id=user.id,
        precedent_id=precedent.id,
        project_id=project.id,
        suggested_md=suggested_md,
        state=str(ProposalState.proposed),
    )
    db.add(proposal)
    await db.flush()

    await audit_action(
        db,
        user_id=user.id,
        action="autonomous_precedent.promote",
        resource_type="precedent_entry",
        resource_id=str(precedent.id),
        project_id=project.id,
        request=request,
    )
    await db.commit()
    await db.refresh(proposal)

    return ProjectContextProposalRead.model_validate(proposal)


# ---------------------------------------------------------------------------
# Project-context proposal endpoints (M4-B2)
# ---------------------------------------------------------------------------


@router.get(
    "/project-context-proposals",
    response_model=ProjectContextProposalListResponse,
    summary="List the calling user's project-context proposals (newest first)",
    responses={
        401: {"description": "Not authenticated"},
    },
)
async def list_project_context_proposals(
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    state: Annotated[ProposalState | None, Query()] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: int = _LIMIT_DEFAULT,
    offset: int = 0,
) -> ProjectContextProposalListResponse:
    """GET /api/v1/autonomous/project-context-proposals

    Returns the caller's proposals ordered by ``created_at DESC``.  Pass
    ``?state=proposed|accepted|rejected`` and/or ``?project_id=`` to
    filter.  ``limit`` is clamped to [1, 200]; ``offset`` to [0, ∞).
    """
    limit = max(1, min(limit, _LIMIT_MAX))
    offset = max(0, offset)

    base_where = [ProjectContextProposal.user_id == user.id]
    if state is not None:
        base_where.append(ProjectContextProposal.state == str(state))
    if project_id is not None:
        base_where.append(ProjectContextProposal.project_id == project_id)

    count_stmt = select(func.count()).select_from(ProjectContextProposal).where(*base_where)
    total_count: int = (await db.execute(count_stmt)).scalar_one()

    rows_stmt = (
        select(ProjectContextProposal)
        .where(*base_where)
        .order_by(ProjectContextProposal.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(rows_stmt)).scalars().all()

    return ProjectContextProposalListResponse(
        proposals=[ProjectContextProposalRead.model_validate(r) for r in rows],
        total_count=total_count,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/project-context-proposals/{proposal_id}/accept",
    response_model=ProjectContextProposalRead,
    summary="Accept a proposal — append the suggested context to the Project (user-authorized write)",
    responses={
        404: {"description": "Proposal not found"},
        401: {"description": "Not authenticated"},
    },
)
async def accept_project_context_proposal(
    proposal_id: uuid.UUID,
    request: Request,
    user: AutonomousEnabledUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectContextProposalRead:
    """POST /api/v1/autonomous/project-context-proposals/{proposal_id}/accept

    **The user-authorized write (ADR 0013 D5):** appends the proposal's
    ``suggested_md`` to the target Project's ``context_md`` (initializing
    it if NULL), sets ``state='accepted'`` and ``accepted_at=now(UTC)``.

    **One-shot context append (guarded by ``accepted_at``):** the
    ``context_md`` write fires at most once per proposal lifetime —
    gated on whether the proposal has EVER been accepted
    (``accepted_at IS NULL``), NOT on its current ``state``. This is what
    makes accept→reject→accept safe: a ``rejected → accepted`` transition
    re-records ``state='accepted'`` but does **NOT** re-append (C1 fix).
    On a re-accept the project-ownership load is skipped because no write
    happens — there is nothing to authorize.

    **``reject`` does NOT retroactively remove already-appended context:**
    an accepted-then-rejected proposal leaves its text in ``context_md``;
    removal/undo is out of scope here.

    Another user's ``proposal_id`` returns 404.  Audited.
    """
    proposal = await _load_owned_proposal(db, proposal_id=proposal_id, user_id=user.id)

    if proposal.accepted_at is None:
        # The authorized append — fires at most once per proposal lifetime.
        # Load the target project (must still be the caller's; 404 if it
        # vanished or ownership changed).
        project = await _load_owned_project(db, project_id=proposal.project_id, user_id=user.id)
        if project.context_md is None:
            project.context_md = proposal.suggested_md
        else:
            project.context_md = f"{project.context_md}\n{proposal.suggested_md}"
        project.updated_at = datetime.now(UTC)
        proposal.accepted_at = datetime.now(UTC)

    # Always (re)record the accepted state so rejected→accepted still lands
    # on 'accepted', but the context write above fires at most once per
    # proposal lifetime (guarded by accepted_at).
    proposal.state = str(ProposalState.accepted)
    proposal.updated_at = datetime.now(UTC)

    await audit_action(
        db,
        user_id=user.id,
        action="project_context_proposal.accept",
        resource_type="project_context_proposal",
        resource_id=str(proposal.id),
        project_id=proposal.project_id,
        request=request,
    )
    await db.commit()
    await db.refresh(proposal)

    return ProjectContextProposalRead.model_validate(proposal)


@router.post(
    "/project-context-proposals/{proposal_id}/reject",
    response_model=ProjectContextProposalRead,
    summary="Reject a proposal (does not touch Project context)",
    responses={
        404: {"description": "Proposal not found"},
        401: {"description": "Not authenticated"},
    },
)
async def reject_project_context_proposal(
    proposal_id: uuid.UUID,
    request: Request,
    user: AutonomousEnabledUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectContextProposalRead:
    """POST /api/v1/autonomous/project-context-proposals/{proposal_id}/reject

    Sets ``state='rejected'`` and ``rejected_at=now(UTC)``.  Does **NOT**
    touch ``projects.context_md``.

    Another user's ``proposal_id`` returns 404.  Audited.
    """
    proposal = await _load_owned_proposal(db, proposal_id=proposal_id, user_id=user.id)

    if proposal.state != str(ProposalState.rejected):
        proposal.state = str(ProposalState.rejected)
        proposal.rejected_at = datetime.now(UTC)
        proposal.updated_at = datetime.now(UTC)

    await audit_action(
        db,
        user_id=user.id,
        action="project_context_proposal.reject",
        resource_type="project_context_proposal",
        resource_id=str(proposal.id),
        project_id=proposal.project_id,
        request=request,
    )
    await db.commit()
    await db.refresh(proposal)

    return ProjectContextProposalRead.model_validate(proposal)


# ---------------------------------------------------------------------------
# Scheduled-tasks endpoints (M4-B3)
# ---------------------------------------------------------------------------


@router.post(
    "/schedules",
    response_model=AutonomousScheduleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an autonomous schedule (cron-triggered run definition)",
    responses={
        201: {"description": "Schedule created"},
        422: {"description": "Invalid cron expression"},
        404: {"description": "Referenced project not found"},
        401: {"description": "Not authenticated"},
    },
)
async def create_schedule(
    body: AutonomousScheduleCreate,
    request: Request,
    user: AutonomousEnabledUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AutonomousScheduleRead:
    """POST /api/v1/autonomous/schedules

    Validates ``cron_expr`` via :func:`~app.autonomous.cron.validate_cron_expr`
    (invalid → 422), creates the schedule row, and seeds
    ``next_run_at = next_run_after(cron_expr, now(UTC))`` so the
    dispatcher's first eligible tick can pick it up.  Returns the created
    :class:`~app.schemas.autonomous.AutonomousScheduleRead` (201).

    Audited.
    """
    try:
        validate_cron_expr(body.cron_expr)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid cron expression: {exc}",
        ) from exc

    # Validate matter ownership — a non-null project_id the caller doesn't own
    # is rejected 404 (id-probing-safe). NULL = no matter; no check needed.
    if body.project_id is not None:
        await _load_owned_project(db, project_id=body.project_id, user_id=user.id)

    now = datetime.now(UTC)
    schedule = AutonomousSchedule(
        user_id=user.id,
        project_id=body.project_id,
        name=body.name,
        cron_expr=body.cron_expr,
        playbook_id=body.playbook_id,
        skill_ref=body.skill_ref,
        target_kb_id=body.target_kb_id,
        enabled=body.enabled,
        max_cost_usd=body.max_cost_usd,
        next_run_at=next_run_after(body.cron_expr, now),
    )
    db.add(schedule)
    await db.flush()

    await audit_action(
        db,
        user_id=user.id,
        action="autonomous_schedule.create",
        resource_type="autonomous_schedule",
        resource_id=str(schedule.id),
        request=request,
    )
    await db.commit()
    await db.refresh(schedule)

    return AutonomousScheduleRead.model_validate(schedule)


async def _spawn_manual_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    body: AutonomousManualRunRequest,
    enqueue: Callable[[uuid.UUID], Awaitable[bool]] | None = None,
) -> AutonomousSession:
    """Create + enqueue a one-off manual autonomous session.

    Mirrors the session construction in
    :func:`app.workers.autonomous_worker._run_schedule_sweep`: builds
    ``params`` carrying only the non-null target keys, sets a non-null
    ``max_cost_usd`` (per-run cap or the config default so R4 always
    arms), flushes to obtain the id, then best-effort enqueues. The
    five-phase executor + R4/R5/R6 brakes + receipt are unchanged.
    """
    enqueue_fn = enqueue if enqueue is not None else enqueue_autonomous_session_job
    settings = get_settings()

    # Validate matter ownership — a non-null project_id the caller doesn't own
    # is rejected 404 (id-probing-safe). NULL = no matter; no check needed.
    if body.project_id is not None:
        await _load_owned_project(db, project_id=body.project_id, user_id=user_id)

    params: dict[str, object] = {"since": None}
    if body.target_kb_id is not None:
        params["kb_id"] = str(body.target_kb_id)
    if body.playbook_id is not None:
        params["playbook_id"] = str(body.playbook_id)
    if body.skill_ref is not None:
        params["skill_ref"] = body.skill_ref

    session = AutonomousSession(
        user_id=user_id,
        project_id=body.project_id,
        trigger_kind="manual",
        trigger_ref=None,
        status="running",
        current_phase="intake",
        max_cost_usd=body.max_cost_usd
        if body.max_cost_usd is not None
        else settings.autonomous_default_max_cost_usd,
        params=params,
    )
    db.add(session)
    await db.flush()
    await enqueue_fn(session.id)
    return session


@router.post(
    "/run-now",
    response_model=AutonomousSessionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Run a skill or playbook once now (one-off manual autonomous session)",
    responses={
        201: {"description": "Session spawned"},
        403: {"description": "Autonomous layer not enabled for this user"},
        422: {"description": "Invalid target (need exactly one of playbook_id/skill_ref)"},
        404: {"description": "Referenced project not found"},
        401: {"description": "Not authenticated"},
    },
)
async def run_now(
    body: AutonomousManualRunRequest,
    request: Request,
    user: AutonomousEnabledUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AutonomousSessionRead:
    """POST /api/v1/autonomous/run-now

    Spawn a single ``trigger_kind='manual'`` session so the user can test
    a skill/playbook and inspect its receipt before arming a schedule or
    watch. Gated by opt-in (``AutonomousEnabledUser``); the spawned
    session runs under the same R4/R5/R6 brakes as every other session.
    Audited.
    """
    session = await _spawn_manual_session(db, user_id=user.id, body=body)
    await audit_action(
        db,
        user_id=user.id,
        action="autonomous_session.run_now",
        resource_type="autonomous_session",
        resource_id=str(session.id),
        request=request,
    )
    await db.commit()
    await db.refresh(session)
    return AutonomousSessionRead.model_validate(session)


@router.get(
    "/schedules",
    response_model=AutonomousScheduleListResponse,
    summary="List the calling user's autonomous schedules (non-deleted, newest first)",
    responses={
        401: {"description": "Not authenticated"},
    },
)
async def list_schedules(
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    enabled: Annotated[bool | None, Query()] = None,
    limit: int = _LIMIT_DEFAULT,
    offset: int = 0,
) -> AutonomousScheduleListResponse:
    """GET /api/v1/autonomous/schedules

    Returns the caller's non-deleted schedules ordered by
    ``created_at DESC``.  Pass ``?enabled=true|false`` to filter; omitting
    it returns all non-deleted schedules.  ``limit`` is clamped to
    [1, 200]; ``offset`` to [0, ∞).
    """
    limit = max(1, min(limit, _LIMIT_MAX))
    offset = max(0, offset)

    base_where = [
        AutonomousSchedule.user_id == user.id,
        AutonomousSchedule.deleted_at.is_(None),
    ]
    if enabled is not None:
        base_where.append(AutonomousSchedule.enabled.is_(enabled))

    count_stmt = select(func.count()).select_from(AutonomousSchedule).where(*base_where)
    total_count: int = (await db.execute(count_stmt)).scalar_one()

    rows_stmt = (
        select(AutonomousSchedule)
        .where(*base_where)
        .order_by(AutonomousSchedule.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(rows_stmt)).scalars().all()

    return AutonomousScheduleListResponse(
        schedules=[AutonomousScheduleRead.model_validate(r) for r in rows],
        total_count=total_count,
        limit=limit,
        offset=offset,
    )


@router.patch(
    "/schedules/{schedule_id}",
    response_model=AutonomousScheduleRead,
    summary="Partially update an autonomous schedule (edit / enable / disable)",
    responses={
        404: {"description": "Schedule or referenced project not found"},
        422: {"description": "Invalid cron expression"},
        401: {"description": "Not authenticated"},
    },
)
async def update_schedule(
    schedule_id: uuid.UUID,
    body: AutonomousScheduleUpdate,
    request: Request,
    user: AutonomousEnabledUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AutonomousScheduleRead:
    """PATCH /api/v1/autonomous/schedules/{schedule_id}

    Partial update — only the provided fields change.  If ``cron_expr``
    changes it is re-validated (invalid → 422) and ``next_run_at`` is
    recomputed from ``now(UTC)``.  Toggling ``enabled`` is allowed.

    Another user's ``schedule_id`` returns 404.  Returns the updated
    schedule (200).  Audited.
    """
    schedule = await _load_owned_schedule(db, schedule_id=schedule_id, user_id=user.id)

    fields = body.model_dump(exclude_unset=True)

    if "cron_expr" in fields:
        new_cron = fields["cron_expr"]
        try:
            validate_cron_expr(new_cron)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"invalid cron expression: {exc}",
            ) from exc
        schedule.cron_expr = new_cron
        schedule.next_run_at = next_run_after(new_cron, datetime.now(UTC))

    if "name" in fields:
        schedule.name = fields["name"]
    if "enabled" in fields:
        schedule.enabled = fields["enabled"]
    if "playbook_id" in fields:
        schedule.playbook_id = fields["playbook_id"]
    if "skill_ref" in fields:
        schedule.skill_ref = fields["skill_ref"]
    if "target_kb_id" in fields:
        schedule.target_kb_id = fields["target_kb_id"]
    if "project_id" in fields:
        new_project_id = fields["project_id"]
        if new_project_id is not None:
            await _load_owned_project(db, project_id=new_project_id, user_id=user.id)
        schedule.project_id = new_project_id  # explicit null clears the matter
    if "max_cost_usd" in fields:
        # Per design: NULL clears the per-schedule cap → fall back to global default.
        # `exclude_unset=True` makes "explicitly sent null" distinguishable from "omitted".
        schedule.max_cost_usd = fields["max_cost_usd"]

    schedule.updated_at = datetime.now(UTC)

    await audit_action(
        db,
        user_id=user.id,
        action="autonomous_schedule.update",
        resource_type="autonomous_schedule",
        resource_id=str(schedule.id),
        request=request,
    )
    await db.commit()
    await db.refresh(schedule)

    return AutonomousScheduleRead.model_validate(schedule)


@router.delete(
    "/schedules/{schedule_id}",
    response_model=AutonomousScheduleRead,
    summary="Soft-delete an autonomous schedule (returns 200 with updated entity)",
    responses={
        404: {"description": "Schedule not found"},
        401: {"description": "Not authenticated"},
    },
)
async def delete_schedule(
    schedule_id: uuid.UUID,
    request: Request,
    user: AutonomousEnabledUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AutonomousScheduleRead:
    """DELETE /api/v1/autonomous/schedules/{schedule_id}

    Soft-deletes the schedule by setting ``deleted_at=now(UTC)``.  Returns
    **200** with the updated (deleted) entity rather than 204 to avoid the
    FastAPI ``JSONResponse``/204 assertion pitfall (documented in
    CLAUDE.md).

    A subsequent GET excludes the schedule; patch/delete on a deleted
    schedule return 404 (``_load_owned_schedule`` filters
    ``deleted_at IS NULL``).  The dispatcher also skips soft-deleted rows.

    Another user's ``schedule_id`` returns 404.  Audited.
    """
    schedule = await _load_owned_schedule(db, schedule_id=schedule_id, user_id=user.id)

    schedule.deleted_at = datetime.now(UTC)
    schedule.updated_at = datetime.now(UTC)

    await audit_action(
        db,
        user_id=user.id,
        action="autonomous_schedule.delete",
        resource_type="autonomous_schedule",
        resource_id=str(schedule.id),
        request=request,
    )
    await db.commit()
    await db.refresh(schedule)

    return AutonomousScheduleRead.model_validate(schedule)


# ---------------------------------------------------------------------------
# KB-arrival watch endpoints (M4-B4)
# ---------------------------------------------------------------------------


@router.post(
    "/watches",
    response_model=AutonomousWatchRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an autonomous watch (KB-arrival-triggered run definition)",
    responses={
        201: {"description": "Watch created"},
        404: {"description": "Target knowledge base or referenced project not found"},
        401: {"description": "Not authenticated"},
    },
)
async def create_watch(
    body: AutonomousWatchCreate,
    request: Request,
    user: AutonomousEnabledUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AutonomousWatchRead:
    """POST /api/v1/autonomous/watches

    Validates the caller **owns** the target ``knowledge_base_id``
    (``KnowledgeBase.owner_id == user.id``) — a KB the caller cannot see
    returns 404 (conservative per-user isolation; KB-sharing is out of
    scope). Creates the watch row. Returns the created
    :class:`~app.schemas.autonomous.AutonomousWatchRead` (201).

    Audited.
    """
    # Validate KB ownership — 404 (not 403) on a KB the caller doesn't own,
    # same existence-disclosure posture as the autonomous loaders.
    kb_stmt = select(KnowledgeBase).where(
        KnowledgeBase.id == body.knowledge_base_id,
        KnowledgeBase.owner_id == user.id,
    )
    kb = (await db.execute(kb_stmt)).scalar_one_or_none()
    if kb is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="knowledge base not found",
        )

    # Validate matter ownership — a non-null project_id the caller doesn't own
    # is rejected 404 (id-probing-safe). NULL = no matter; no check needed.
    if body.project_id is not None:
        await _load_owned_project(db, project_id=body.project_id, user_id=user.id)

    watch = AutonomousWatch(
        user_id=user.id,
        project_id=body.project_id,
        knowledge_base_id=body.knowledge_base_id,
        playbook_id=body.playbook_id,
        skill_ref=body.skill_ref,
        enabled=body.enabled,
        max_cost_usd=body.max_cost_usd,
    )
    db.add(watch)
    await db.flush()

    await audit_action(
        db,
        user_id=user.id,
        action="autonomous_watch.create",
        resource_type="autonomous_watch",
        resource_id=str(watch.id),
        request=request,
    )
    await db.commit()
    await db.refresh(watch)

    return AutonomousWatchRead.model_validate(watch)


@router.get(
    "/watches",
    response_model=AutonomousWatchListResponse,
    summary="List the calling user's autonomous watches (non-deleted, newest first)",
    responses={
        401: {"description": "Not authenticated"},
    },
)
async def list_watches(
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    enabled: Annotated[bool | None, Query()] = None,
    knowledge_base_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: int = _LIMIT_DEFAULT,
    offset: int = 0,
) -> AutonomousWatchListResponse:
    """GET /api/v1/autonomous/watches

    Returns the caller's non-deleted watches ordered by
    ``created_at DESC``.  Pass ``?enabled=true|false`` and/or
    ``?knowledge_base_id=`` to filter; omitting them returns all
    non-deleted watches.  ``limit`` is clamped to [1, 200]; ``offset`` to
    [0, ∞).
    """
    limit = max(1, min(limit, _LIMIT_MAX))
    offset = max(0, offset)

    base_where = [
        AutonomousWatch.user_id == user.id,
        AutonomousWatch.deleted_at.is_(None),
    ]
    if enabled is not None:
        base_where.append(AutonomousWatch.enabled.is_(enabled))
    if knowledge_base_id is not None:
        base_where.append(AutonomousWatch.knowledge_base_id == knowledge_base_id)

    count_stmt = select(func.count()).select_from(AutonomousWatch).where(*base_where)
    total_count: int = (await db.execute(count_stmt)).scalar_one()

    rows_stmt = (
        select(AutonomousWatch)
        .where(*base_where)
        .order_by(AutonomousWatch.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(rows_stmt)).scalars().all()

    return AutonomousWatchListResponse(
        watches=[AutonomousWatchRead.model_validate(r) for r in rows],
        total_count=total_count,
        limit=limit,
        offset=offset,
    )


@router.patch(
    "/watches/{watch_id}",
    response_model=AutonomousWatchRead,
    summary="Partially update an autonomous watch (enable / disable / retarget)",
    responses={
        404: {"description": "Watch or referenced project not found"},
        401: {"description": "Not authenticated"},
    },
)
async def update_watch(
    watch_id: uuid.UUID,
    body: AutonomousWatchUpdate,
    request: Request,
    user: AutonomousEnabledUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AutonomousWatchRead:
    """PATCH /api/v1/autonomous/watches/{watch_id}

    Partial update — only the provided fields change (``enabled`` /
    ``playbook_id`` / ``skill_ref``). The watch's ``knowledge_base_id``
    is immutable: a watch is bound to its KB, so retargeting to a
    different KB means creating a new watch.

    Another user's ``watch_id`` returns 404.  Returns the updated watch
    (200).  Audited.
    """
    watch = await _load_owned_watch(db, watch_id=watch_id, user_id=user.id)

    fields = body.model_dump(exclude_unset=True)

    if "enabled" in fields:
        watch.enabled = fields["enabled"]
    if "playbook_id" in fields:
        watch.playbook_id = fields["playbook_id"]
    if "skill_ref" in fields:
        watch.skill_ref = fields["skill_ref"]
    if "project_id" in fields:
        new_project_id = fields["project_id"]
        if new_project_id is not None:
            await _load_owned_project(db, project_id=new_project_id, user_id=user.id)
        watch.project_id = new_project_id  # explicit null clears the matter
    if "max_cost_usd" in fields:
        # Per design: NULL clears the per-watch cap → fall back to global default.
        # `exclude_unset=True` makes "explicitly sent null" distinguishable from "omitted".
        watch.max_cost_usd = fields["max_cost_usd"]

    watch.updated_at = datetime.now(UTC)

    await audit_action(
        db,
        user_id=user.id,
        action="autonomous_watch.update",
        resource_type="autonomous_watch",
        resource_id=str(watch.id),
        request=request,
    )
    await db.commit()
    await db.refresh(watch)

    return AutonomousWatchRead.model_validate(watch)


@router.delete(
    "/watches/{watch_id}",
    response_model=AutonomousWatchRead,
    summary="Soft-delete an autonomous watch (returns 200 with updated entity)",
    responses={
        404: {"description": "Watch not found"},
        401: {"description": "Not authenticated"},
    },
)
async def delete_watch(
    watch_id: uuid.UUID,
    request: Request,
    user: AutonomousEnabledUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AutonomousWatchRead:
    """DELETE /api/v1/autonomous/watches/{watch_id}

    Soft-deletes the watch by setting ``deleted_at=now(UTC)``.  Returns
    **200** with the updated (deleted) entity rather than 204 to avoid the
    FastAPI ``JSONResponse``/204 assertion pitfall (documented in
    CLAUDE.md).

    A subsequent GET excludes the watch; patch/delete on a deleted watch
    return 404 (``_load_owned_watch`` filters ``deleted_at IS NULL``). The
    KB-arrival trigger also skips soft-deleted rows.

    Another user's ``watch_id`` returns 404.  Audited.
    """
    watch = await _load_owned_watch(db, watch_id=watch_id, user_id=user.id)

    watch.deleted_at = datetime.now(UTC)
    watch.updated_at = datetime.now(UTC)

    await audit_action(
        db,
        user_id=user.id,
        action="autonomous_watch.delete",
        resource_type="autonomous_watch",
        resource_id=str(watch.id),
        request=request,
    )
    await db.commit()
    await db.refresh(watch)

    return AutonomousWatchRead.model_validate(watch)


# ---------------------------------------------------------------------------
# Notification read/dismiss endpoints (M4-C1)
# ---------------------------------------------------------------------------


@router.get(
    "/notifications",
    response_model=AutonomousNotificationListResponse,
    summary="List the calling user's autonomous notifications (newest first)",
    responses={
        401: {"description": "Not authenticated"},
    },
)
async def list_notifications(
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    unread: Annotated[bool | None, Query()] = None,
    limit: int = _LIMIT_DEFAULT,
    offset: int = 0,
) -> AutonomousNotificationListResponse:
    """GET /api/v1/autonomous/notifications

    Returns the caller's notifications ordered by ``created_at DESC``.
    Pass ``?unread=true`` to narrow to unread rows (``read_at IS NULL``);
    omitting it returns all the caller's notifications. ``limit`` is
    clamped to [1, 200]; ``offset`` to [0, ∞).
    """
    limit = max(1, min(limit, _LIMIT_MAX))
    offset = max(0, offset)

    base_where = [AutonomousNotification.user_id == user.id]
    if unread:
        base_where.append(AutonomousNotification.read_at.is_(None))

    count_stmt = select(func.count()).select_from(AutonomousNotification).where(*base_where)
    total_count: int = (await db.execute(count_stmt)).scalar_one()

    rows_stmt = (
        select(AutonomousNotification)
        .where(*base_where)
        .order_by(AutonomousNotification.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(rows_stmt)).scalars().all()

    return AutonomousNotificationListResponse(
        notifications=[AutonomousNotificationRead.model_validate(r) for r in rows],
        total_count=total_count,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/notifications/{notification_id}/read",
    response_model=AutonomousNotificationRead,
    summary="Mark an autonomous notification read (the dismiss action; idempotent)",
    responses={
        404: {"description": "Notification not found"},
        401: {"description": "Not authenticated"},
    },
)
async def read_notification(
    notification_id: uuid.UUID,
    request: Request,
    user: AutonomousEnabledUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AutonomousNotificationRead:
    """POST /api/v1/autonomous/notifications/{notification_id}/read

    Sets ``read_at=now(UTC)`` if currently NULL. **Idempotent:** re-reading
    an already-read notification preserves the original ``read_at``. "Read"
    IS the dismiss action — the model has no ``dismissed_at``; a read
    notification drops out of the ``?unread=true`` list.

    Another user's ``notification_id`` returns 404 (not 403) to avoid
    existence disclosure. Audited.
    """
    note = await _load_owned_notification(db, notification_id=notification_id, user_id=user.id)

    if note.read_at is None:
        note.read_at = datetime.now(UTC)
        note.updated_at = datetime.now(UTC)

    await audit_action(
        db,
        user_id=user.id,
        action="autonomous_notification.read",
        resource_type="autonomous_notification",
        resource_id=str(note.id),
        request=request,
    )
    await db.commit()
    await db.refresh(note)

    return AutonomousNotificationRead.model_validate(note)
