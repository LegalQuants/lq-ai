"""Autonomous sessions + memory + precedent board API — M4-A4-i, M4-B1, M4-B2.

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
from app.models.autonomous import (
    AutonomousMemory,
    AutonomousSession,
    PrecedentEntry,
    ProjectContextProposal,
)
from app.models.project import Project
from app.schemas.autonomous import (
    AutonomousMemoryListResponse,
    AutonomousMemoryRead,
    AutonomousSessionDetailResponse,
    AutonomousSessionListResponse,
    AutonomousSessionRead,
    MemoryKeepRequest,
    MemoryState,
    PrecedentEntryListResponse,
    PrecedentEntryRead,
    ProjectContextProposalListResponse,
    ProjectContextProposalRead,
    PromotePrecedentRequest,
    ProposalState,
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
    user: ActiveUser,
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
    user: ActiveUser,
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
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectContextProposalRead:
    """POST /api/v1/autonomous/project-context-proposals/{proposal_id}/accept

    **The user-authorized write (ADR 0013 D5):** appends the proposal's
    ``suggested_md`` to the target Project's ``context_md`` (initializing
    it if NULL), sets ``state='accepted'`` and ``accepted_at=now(UTC)``.

    **Idempotent on re-accept:** if already ``accepted``, returns the
    current state without re-appending (guards against double-append).
    A ``rejected`` proposal MAY be accepted (rejected→accepted) and the
    append occurs.

    Another user's ``proposal_id`` returns 404.  Audited.
    """
    proposal = await _load_owned_proposal(db, proposal_id=proposal_id, user_id=user.id)

    if proposal.state != str(ProposalState.accepted):
        # The authorized append — load the target project (must still be the
        # caller's; 404 if it vanished or ownership changed).
        project = await _load_owned_project(db, project_id=proposal.project_id, user_id=user.id)
        if project.context_md is None:
            project.context_md = proposal.suggested_md
        else:
            project.context_md = f"{project.context_md}\n{proposal.suggested_md}"
        project.updated_at = datetime.now(UTC)

        proposal.state = str(ProposalState.accepted)
        proposal.accepted_at = datetime.now(UTC)
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
    user: ActiveUser,
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
