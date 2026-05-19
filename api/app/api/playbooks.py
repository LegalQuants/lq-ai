"""Playbook executor + read endpoints — M3-A2 and M3-A4.

Surface (subset of [PRD §3.7](docs/PRD.md#37-playbooks); CRUD lands
in M3-A6):

* ``GET /api/v1/playbooks`` (M3-A4) — list playbooks visible to the
  caller. Built-in playbooks (``created_by IS NULL``) are visible to
  every authenticated user; non-admins additionally see their own
  authored playbooks; admins see everything. Positions are NOT
  inlined; clients fetch the detail endpoint for the position list.
* ``GET /api/v1/playbooks/{playbook_id}`` (M3-A4) — full playbook
  including positions + fallback tiers. Same visibility rule as the
  list endpoint; 404 (not 403) on unauthorized access, mirroring the
  execute endpoint.
* ``POST /api/v1/playbooks/{playbook_id}/execute`` — kick off an
  execution against a target document. Returns 202 with the new
  :class:`PlaybookExecution` row at status ``'pending'``; the
  workflow runs in a FastAPI ``BackgroundTask`` and writes its
  state to the same row as it progresses.
* ``GET /api/v1/playbook-executions/{execution_id}`` — poll the
  current state of an execution. Returns the row with the latest
  ``status`` / ``results`` / ``error`` fields.

Authorization
-------------

Both endpoints inherit the router-level ``Depends(get_active_user)``
gate. The execute endpoint additionally:

* Requires the caller to be an admin OR the playbook's ``created_by``.
  Operators ship built-in playbooks at the deployment level; per-user
  forking lands in M3-A4 + M3-A6.
* Requires the caller to own the target file (the document's parent),
  matching the per-user isolation posture for ``files`` (Task C4).
* If ``project_id`` is supplied, requires the caller to own the
  project (matches the projects-endpoint posture).

The poll endpoint requires the caller to own the execution
(``user_id`` match) OR be an admin.

Async execution model
---------------------

Per the M3-1 architectural decision the executor runs in-process
via FastAPI ``BackgroundTasks``. The executor function
(:func:`app.playbooks.executor.run_playbook_execution`) opens its
own DB session (the request-scoped session closes when the
202-returning handler exits). Operators with restart-survival
requirements can migrate the worker path to ARQ as a future
enhancement — the executor interface accepts the same shape either
way.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.clients.gateway import GatewayClient, get_gateway_client
from app.db.session import get_db, get_session_factory
from app.models.document import Document
from app.models.file import File as FileModel
from app.models.playbook import Playbook, PlaybookExecution
from app.models.project import Project
from app.playbooks.executor import PlaybookExecutorError, run_playbook_execution
from app.schemas.playbooks import (
    Playbook as PlaybookSchema,
    PlaybookExecution as PlaybookExecutionSchema,
    PlaybookExecutionCreate,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["playbooks"])


@router.get(
    "/playbooks",
    response_model=list[PlaybookSchema],
    summary="List playbooks visible to the caller.",
)
async def list_playbooks(
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PlaybookSchema]:
    """List playbooks the caller can see.

    Visibility rules (mirroring the execute endpoint):

    * Admins see all playbooks.
    * Non-admins see playbooks they authored OR built-in playbooks
      (``created_by IS NULL`` — created by the seed migration).

    Positions are NOT inlined in the list response; clients fetch the
    detail endpoint when they need them. This keeps the list response
    bounded even when a playbook has dozens of positions.
    """
    stmt = select(Playbook)
    if not user.is_admin:
        stmt = stmt.where((Playbook.created_by == user.id) | (Playbook.created_by.is_(None)))
    stmt = stmt.order_by(Playbook.name)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        PlaybookSchema(
            id=row.id,
            name=row.name,
            contract_type=row.contract_type,
            description=row.description,
            version=row.version,
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
            positions=[],
        )
        for row in rows
    ]


@router.get(
    "/playbooks/{playbook_id}",
    response_model=PlaybookSchema,
    summary="Get a playbook with its full position list.",
)
async def get_playbook(
    playbook_id: uuid.UUID,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlaybookSchema:
    """Return the playbook header + positions + fallback tiers.

    Visibility: admins see all; non-admins see playbooks they authored
    or built-in playbooks (``created_by IS NULL``). 404 (not 403) on
    unauthorized access — mirrors the playbook-execute handler.
    """
    playbook = await db.get(Playbook, playbook_id)
    if playbook is None:
        raise HTTPException(status_code=404, detail="playbook not found")
    if not user.is_admin and playbook.created_by is not None and playbook.created_by != user.id:
        raise HTTPException(status_code=404, detail="playbook not found")
    # Eager-load positions in this async context (the relationship is lazy
    # by default and would otherwise trigger an implicit I/O on access).
    await db.refresh(playbook, attribute_names=["positions"])
    return PlaybookSchema.model_validate(playbook, from_attributes=True)


@router.post(
    "/playbooks/{playbook_id}/execute",
    response_model=PlaybookExecutionSchema,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Kick off a playbook execution against a target document.",
)
async def execute_playbook(
    playbook_id: uuid.UUID,
    body: PlaybookExecutionCreate,
    user: ActiveUser,
    background: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> PlaybookExecutionSchema:
    """Create a :class:`PlaybookExecution` row and schedule the workflow.

    Returns 202 immediately with the row at status ``'pending'``. The
    workflow promotes it to ``'running'`` shortly after the response
    is sent, and to ``'completed'`` / ``'error'`` once the four-node
    graph completes.
    """

    playbook = await db.get(Playbook, playbook_id)
    if playbook is None:
        raise HTTPException(status_code=404, detail="playbook not found")

    # Per-user isolation: caller must be admin OR the playbook's
    # author. Tightens to per-user scope once user-scoped playbooks
    # land (M3-A4); for v0.3 builtins this means admin only.
    if not user.is_admin and playbook.created_by != user.id:
        raise HTTPException(status_code=404, detail="playbook not found")

    document = await db.get(Document, body.target_document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="target document not found")

    # The caller must own the file the document was parsed from
    # (admins bypass the ownership check — built-in playbooks ship at
    # the deployment level and admins act on operator-uploaded docs).
    file_row = await db.get(FileModel, document.file_id)
    file_missing_or_unowned = (
        file_row is None or file_row.deleted_at is not None or file_row.owner_id != user.id
    )
    if file_missing_or_unowned and not user.is_admin:
        raise HTTPException(status_code=404, detail="target document not found")

    if body.project_id is not None:
        project = await db.get(Project, body.project_id)
        project_missing_or_unowned = (
            project is None or project.archived_at is not None or project.owner_id != user.id
        )
        if project_missing_or_unowned and not user.is_admin:
            raise HTTPException(status_code=404, detail="project not found")

    execution = PlaybookExecution(
        playbook_id=playbook_id,
        target_document_id=body.target_document_id,
        user_id=user.id,
        project_id=body.project_id,
        status="pending",
    )
    db.add(execution)
    await db.commit()
    await db.refresh(execution)

    # Schedule the workflow. The executor opens its own DB session so
    # the per-request session can close cleanly when we return 202.
    background.add_task(
        _run_in_background,
        execution_id=execution.id,
        gateway=gateway,
    )

    return PlaybookExecutionSchema.model_validate(execution)


@router.get(
    "/playbook-executions/{execution_id}",
    response_model=PlaybookExecutionSchema,
    summary="Poll the current state of a playbook execution.",
)
async def get_playbook_execution(
    execution_id: uuid.UUID,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlaybookExecutionSchema:
    """Return the current state of one execution.

    Returns the row regardless of completion state: ``pending`` /
    ``running`` / ``completed`` / ``error``. Callers poll this
    endpoint until they see a terminal state (``completed`` or
    ``error``).
    """

    stmt = select(PlaybookExecution).where(PlaybookExecution.id == execution_id)
    execution = (await db.execute(stmt)).scalar_one_or_none()
    if execution is None:
        raise HTTPException(status_code=404, detail="execution not found")

    if not user.is_admin and execution.user_id != user.id:
        raise HTTPException(status_code=404, detail="execution not found")

    return PlaybookExecutionSchema.model_validate(execution)


async def _run_in_background(
    *,
    execution_id: uuid.UUID,
    gateway: GatewayClient,
) -> None:
    """Background-task entry point — opens a fresh session for the executor.

    FastAPI's request-scoped session closes when the kick-off handler
    returns 202; the executor needs its own session for the duration
    of the workflow. We rely on the same session factory the rest of
    the API uses, so the executor's queries flow through the same
    connection pool.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            await run_playbook_execution(
                session,
                execution_id=execution_id,
                gateway=gateway,
            )
        except PlaybookExecutorError as exc:
            # The executor already wrote status='error' before raising;
            # this catch is purely so the background task doesn't surface
            # as an unhandled exception in the logs.
            logger.warning(
                "playbook executor refused to start",
                extra={
                    "event": "playbook_executor_refused",
                    "execution_id": str(execution_id),
                    "reason": str(exc),
                },
            )
