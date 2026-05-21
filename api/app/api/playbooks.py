"""Playbook executor + CRUD endpoints — M3-A2 / M3-A4 / M3-A6.

Surface (per [PRD §3.7](docs/PRD.md#37-playbooks)):

* ``GET    /api/v1/playbooks`` (M3-A4) — list playbooks visible to the
  caller. Built-in playbooks (``created_by IS NULL``) are visible to
  every authenticated user; non-admins additionally see their own
  authored playbooks; admins see everything. Positions are NOT
  inlined; clients fetch the detail endpoint for the position list.
* ``GET    /api/v1/playbooks/{playbook_id}`` (M3-A4) — full playbook
  including positions + fallback tiers. Same visibility rule as the
  list endpoint; 404 (not 403) on unauthorized access, mirroring the
  execute endpoint.
* ``POST   /api/v1/playbooks`` (M3-A6) — create a new playbook owned
  by the caller. Sets ``created_by = caller.id`` unconditionally;
  the only way to mint a built-in (``created_by IS NULL``) is via
  seed migration.
* ``PATCH  /api/v1/playbooks/{playbook_id}`` (M3-A6) — update the
  header and (optionally) atomically replace the positions array.
  Built-in playbooks are 403 (operators fork-then-edit); non-builtin
  playbooks require admin OR ownership.
* ``DELETE /api/v1/playbooks/{playbook_id}`` (M3-A6) — soft-delete
  via ``deleted_at``. Same authorization as PATCH. Already-deleted
  rows are invisible to the visibility helper, so a second DELETE
  returns 404.
* ``POST   /api/v1/playbooks/easy`` (M3-A6) — kick off an Easy
  Playbook generation against an uploaded document corpus. Returns
  202 with the new :class:`EasyPlaybookGeneration` row at status
  ``'pending'``; the ARQ worker on the ``arq:m3a6`` queue runs the
  extract → cluster → assemble pipeline and writes its progress to
  the row.
* ``GET    /api/v1/playbooks/easy/{generation_id}`` (M3-A6) — poll
  the current state. The wizard's Step 2 reads ``status``; Step 3
  binds the inline editor to ``draft_playbook`` once status reaches
  ``completed``.
* ``POST   /api/v1/playbooks/{playbook_id}/execute`` — kick off an
  execution against a target document. Returns 202 with the new
  :class:`PlaybookExecution` row at status ``'pending'``; the
  workflow runs in a FastAPI ``BackgroundTask`` and writes its
  state to the same row as it progresses.
* ``GET    /api/v1/playbook-executions/{execution_id}`` — poll the
  current state of an execution. Returns the row with the latest
  ``status`` / ``results`` / ``error`` fields.

Authorization
-------------

All endpoints inherit the router-level ``Depends(get_active_user)``
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
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.audit import audit_action
from app.clients.gateway import GatewayClient, get_gateway_client
from app.db.session import get_db, get_session_factory
from app.models.document import Document
from app.models.file import File as FileModel
from app.models.playbook import (
    EasyPlaybookGeneration,
    Playbook,
    PlaybookExecution,
    PlaybookPosition,
)
from app.models.project import Project
from app.playbooks.executor import PlaybookExecutorError, run_playbook_execution
from app.schemas.playbooks import (
    EasyPlaybookGeneration as EasyPlaybookGenerationSchema,
    EasyPlaybookGenerationCreate,
    Playbook as PlaybookSchema,
    PlaybookCreate,
    PlaybookExecution as PlaybookExecutionSchema,
    PlaybookExecutionCreate,
    PlaybookUpdate,
)
from app.workers.queue import enqueue_easy_playbook_generation_job

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
    stmt = select(Playbook).where(Playbook.deleted_at.is_(None))
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
    playbook = await _load_visible_playbook(db, playbook_id, user)
    # Eager-load positions in this async context (the relationship is lazy
    # by default and would otherwise trigger an implicit I/O on access).
    await db.refresh(playbook, attribute_names=["positions"])
    return PlaybookSchema.model_validate(playbook, from_attributes=True)


@router.post(
    "/playbooks",
    response_model=PlaybookSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new playbook.",
)
async def create_playbook(
    body: PlaybookCreate,
    user: ActiveUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlaybookSchema:
    """Create a playbook owned by the caller — M3-A6 Phase 2.

    Sets ``created_by = user.id`` unconditionally. Admins do not get to
    create "built-in" playbooks (``created_by IS NULL``) through this
    endpoint — built-ins ship via seed migration only (matches the
    "admins can fork built-ins but not edit them in place" posture
    from the M3-A6 prep doc).
    """

    playbook = Playbook(
        name=body.name,
        contract_type=body.contract_type,
        description=body.description,
        version=body.version,
        created_by=user.id,
    )
    for new_pos in body.positions:
        playbook.positions.append(
            PlaybookPosition(
                issue=new_pos.issue,
                description=new_pos.description,
                standard_language=new_pos.standard_language,
                fallback_tiers=[tier.model_dump() for tier in new_pos.fallback_tiers],
                redline_strategy=new_pos.redline_strategy,
                severity_if_missing=new_pos.severity_if_missing,
                detection_keywords=list(new_pos.detection_keywords),
                detection_examples=list(new_pos.detection_examples),
                position_order=new_pos.position_order,
            )
        )
    db.add(playbook)
    await db.flush()
    # Count from the input body, not from the ORM relationship — after
    # the flush, accessing `playbook.positions` triggers a lazy-load
    # query (greenlet error in async context). The input list is what
    # we care about for the audit row anyway.
    position_count = len(body.positions)
    await audit_action(
        db,
        user_id=user.id,
        action="playbook.created",
        resource_type="playbook",
        resource_id=str(playbook.id),
        request=request,
        details={
            "name": playbook.name,
            "contract_type": playbook.contract_type,
            "version": playbook.version,
            "position_count": position_count,
        },
    )
    await db.commit()
    await db.refresh(playbook, attribute_names=["positions"])
    logger.info(
        "playbook created",
        extra={
            "event": "playbook_created",
            "user_id": str(user.id),
            "playbook_id": str(playbook.id),
            "position_count": position_count,
        },
    )
    return PlaybookSchema.model_validate(playbook, from_attributes=True)


@router.patch(
    "/playbooks/{playbook_id}",
    response_model=PlaybookSchema,
    summary="Update a playbook's header and (optionally) replace its positions.",
)
async def update_playbook(
    playbook_id: uuid.UUID,
    body: PlaybookUpdate,
    user: ActiveUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlaybookSchema:
    """Patch the playbook header; atomically replace positions if supplied — M3-A6 Phase 2.

    Authorization: built-in playbooks (``created_by IS NULL``) are
    immutable through this endpoint by anyone, including admins —
    operators ship built-ins via migration and the admin-fork-then-edit
    path is the canonical mutation route. Non-built-in playbooks can be
    edited by their author OR by an admin. Cross-user / soft-deleted
    cases return 404 (no information leakage), matching the read paths.

    Position replacement is atomic: when ``body.positions`` is supplied,
    every existing position row for this playbook is deleted and the
    body's list is inserted in a single transaction. To leave positions
    alone, omit the field (``None``); to clear all positions, send an
    empty list ``[]``.
    """

    playbook = await _load_visible_playbook(db, playbook_id, user)
    # Built-ins are immutable through the CRUD surface (the admin path
    # is to create a forked playbook then edit the fork). The check
    # comes before the owner check because the cross-user case for
    # built-ins is already collapsed into 404 by _load_visible_playbook;
    # we land here only if the caller can see the playbook.
    if playbook.created_by is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="built-in playbooks cannot be edited; fork and edit the copy instead",
        )
    # Non-admin callers must own the playbook. Cross-user for non-builtin
    # playbooks already returns 404 via the visibility helper, so this
    # check is belt-and-suspenders for any future visibility change.
    if not user.is_admin and playbook.created_by != user.id:
        raise HTTPException(status_code=404, detail="playbook not found")

    update_data = body.model_dump(exclude_unset=True)
    position_payload = update_data.pop("positions", None)

    if "name" in update_data:
        playbook.name = update_data["name"]
    if "contract_type" in update_data:
        playbook.contract_type = update_data["contract_type"]
    if "description" in update_data:
        playbook.description = update_data["description"]
    if "version" in update_data:
        playbook.version = update_data["version"]
    playbook.updated_at = datetime.now(tz=UTC)

    if position_payload is not None:
        # Atomic replace: drop the existing rows, insert the new ones.
        # The ORM relationship's cascade='all, delete-orphan' would do
        # this on a list reassignment too, but the explicit DELETE +
        # INSERT pattern is easier to reason about in the async session
        # and matches how the executor's tests already manipulate the
        # children table directly.
        await db.execute(
            delete(PlaybookPosition).where(PlaybookPosition.playbook_id == playbook.id)
        )
        # Coerce back to PositionCreate so model_dump() on the Pydantic
        # objects gives us the canonical shape. (When body is parsed by
        # FastAPI the items are already PositionCreate instances; the
        # model_dump above turned them into dicts.)
        from app.schemas.playbooks import PositionCreate

        for raw in position_payload:
            new_pos = PositionCreate.model_validate(raw)
            db.add(
                PlaybookPosition(
                    playbook_id=playbook.id,
                    issue=new_pos.issue,
                    description=new_pos.description,
                    standard_language=new_pos.standard_language,
                    fallback_tiers=[tier.model_dump() for tier in new_pos.fallback_tiers],
                    redline_strategy=new_pos.redline_strategy,
                    severity_if_missing=new_pos.severity_if_missing,
                    detection_keywords=list(new_pos.detection_keywords),
                    detection_examples=list(new_pos.detection_examples),
                    position_order=new_pos.position_order,
                )
            )

    await db.flush()
    await audit_action(
        db,
        user_id=user.id,
        action="playbook.updated",
        resource_type="playbook",
        resource_id=str(playbook.id),
        request=request,
        details={
            "fields_changed": sorted(update_data.keys()),
            "positions_replaced": position_payload is not None,
            "new_position_count": (len(position_payload) if position_payload is not None else None),
        },
    )
    await db.commit()
    await db.refresh(playbook, attribute_names=["positions"])
    logger.info(
        "playbook updated",
        extra={
            "event": "playbook_updated",
            "user_id": str(user.id),
            "playbook_id": str(playbook.id),
        },
    )
    return PlaybookSchema.model_validate(playbook, from_attributes=True)


@router.delete(
    "/playbooks/{playbook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a playbook.",
    response_class=Response,
)
async def delete_playbook(
    playbook_id: uuid.UUID,
    user: ActiveUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Soft-delete the playbook by setting ``deleted_at`` — M3-A6 Phase 2.

    Authorization mirrors :func:`update_playbook`:

    * Built-ins are immutable (403) — operators fork built-ins; they do
      not delete them.
    * Non-admin callers must own the playbook (404 otherwise).
    * Already soft-deleted rows return 404 (the row is invisible to all
      callers via :func:`_load_visible_playbook`).

    The ``playbook_positions`` rows are NOT deleted; they continue to
    reference the now-soft-deleted playbook. This preserves the
    relationship for any historical ``playbook_executions`` that
    referenced positions by id. A future hard-purge sweep can drop both
    positions and the tombstone playbook together.
    """

    playbook = await _load_visible_playbook(db, playbook_id, user)
    if playbook.created_by is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="built-in playbooks cannot be deleted",
        )
    if not user.is_admin and playbook.created_by != user.id:
        raise HTTPException(status_code=404, detail="playbook not found")

    playbook.deleted_at = datetime.now(tz=UTC)
    await audit_action(
        db,
        user_id=user.id,
        action="playbook.deleted",
        resource_type="playbook",
        resource_id=str(playbook.id),
        request=request,
        details={"name": playbook.name},
    )
    await db.commit()
    logger.info(
        "playbook soft-deleted",
        extra={
            "event": "playbook_soft_deleted",
            "user_id": str(user.id),
            "playbook_id": str(playbook.id),
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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

    # Reuse the visibility helper. Note: the execute path is stricter
    # than read — it requires admin OR explicit ownership (built-ins
    # cannot be executed by non-admins below). The helper enforces the
    # admin-OR-visible-to-caller predicate; the stricter check follows.
    playbook = await _load_visible_playbook(db, playbook_id, user)

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


@router.post(
    "/playbooks/easy",
    response_model=EasyPlaybookGenerationSchema,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start an Easy Playbook generation run.",
)
async def create_easy_playbook_generation(
    body: EasyPlaybookGenerationCreate,
    user: ActiveUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EasyPlaybookGenerationSchema:
    """Kick off an Easy Playbook generation against the supplied document corpus.

    Authorization: the caller must own every document in
    ``document_ids``. Cross-user or non-existent ids collapse into a
    single 404 (no information leakage), matching the M3-A2 executor's
    posture.

    Creates an :class:`EasyPlaybookGeneration` row at
    ``status='pending'`` and enqueues the ARQ worker job on the
    ``arq:m3a6`` queue. Returns 202 immediately with the row id; the
    wizard's Step 2 polls
    ``GET /api/v1/playbooks/easy/{generation_id}`` until status
    reaches ``completed`` or ``error``.

    Per the M3-A6 quality bar, "generation completed" does NOT mean
    the playbook is fit for use — the wizard's Step 3 inline editor
    is where the user-attorney validates and edits before the final
    save (which POSTs to ``/api/v1/playbooks`` like any other
    playbook create).
    """

    documents = await _load_caller_owned_documents(
        db,
        document_ids=body.document_ids,
        user=user,
    )
    if len(documents) != len(body.document_ids):
        # Caller asked for documents they don't own (or that don't exist).
        # 404 collapses both cases per the project's information-leakage
        # avoidance posture.
        raise HTTPException(status_code=404, detail="one or more documents not found")

    generation = EasyPlaybookGeneration(
        user_id=user.id,
        contract_type=body.contract_type,
        status="pending",
        document_ids=list(body.document_ids),
    )
    db.add(generation)
    await db.flush()

    await audit_action(
        db,
        user_id=user.id,
        action="easy_playbook.generation_started",
        resource_type="easy_playbook_generation",
        resource_id=str(generation.id),
        request=request,
        details={
            "contract_type": body.contract_type,
            "document_count": len(body.document_ids),
        },
    )
    await db.commit()
    await db.refresh(generation)

    enqueued = await enqueue_easy_playbook_generation_job(generation.id)
    logger.info(
        "easy_playbook_generation_started",
        extra={
            "event": "easy_playbook_started",
            "user_id": str(user.id),
            "generation_id": str(generation.id),
            "enqueued": enqueued,
            "document_count": len(body.document_ids),
        },
    )

    return EasyPlaybookGenerationSchema.model_validate(generation)


@router.get(
    "/playbooks/easy/{generation_id}",
    response_model=EasyPlaybookGenerationSchema,
    summary="Poll an Easy Playbook generation row.",
)
async def get_easy_playbook_generation(
    generation_id: uuid.UUID,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EasyPlaybookGenerationSchema:
    """Return the current state of one Easy Playbook generation.

    Caller must be the row's ``user_id`` OR an admin. Cross-user /
    missing rows collapse into 404. The wizard's Step 2 polls this
    endpoint every few seconds until ``status`` reaches a terminal
    state (``completed`` or ``error``).
    """

    row = await db.get(EasyPlaybookGeneration, generation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="generation not found")
    if not user.is_admin and row.user_id != user.id:
        raise HTTPException(status_code=404, detail="generation not found")
    return EasyPlaybookGenerationSchema.model_validate(row)


async def _load_caller_owned_documents(
    db: AsyncSession,
    *,
    document_ids: list[uuid.UUID],
    user: ActiveUser,
) -> list[Document]:
    """Load Documents whose parent file the caller owns; admins see all.

    Returns only the documents that pass the ownership check.
    Soft-deleted files (``files.deleted_at IS NOT NULL``) are
    excluded — generating a playbook from documents the user no
    longer "has" would surprise on the audit trail.
    """

    if not document_ids:
        return []
    stmt = select(Document).where(Document.id.in_(document_ids))
    docs = (await db.execute(stmt)).scalars().all()
    if not docs:
        return []

    file_ids = [doc.file_id for doc in docs]
    file_stmt = select(FileModel).where(
        FileModel.id.in_(file_ids),
        FileModel.deleted_at.is_(None),
    )
    files = (await db.execute(file_stmt)).scalars().all()
    file_by_id = {f.id: f for f in files}

    out: list[Document] = []
    for doc in docs:
        file_row = file_by_id.get(doc.file_id)
        if file_row is None:
            continue
        if user.is_admin or file_row.owner_id == user.id:
            out.append(doc)
    return out


async def _load_visible_playbook(
    db: AsyncSession,
    playbook_id: uuid.UUID,
    user: ActiveUser,
) -> Playbook:
    """Load a playbook by id, applying the read-visibility predicate.

    Visibility rules (matches :func:`list_playbooks` and the M3-A4
    detail endpoint):

    * Admins see every non-deleted playbook.
    * Non-admins see playbooks they authored OR built-ins
      (``created_by IS NULL``).
    * Soft-deleted rows (``deleted_at IS NOT NULL``) are invisible to
      everyone, including admins. Use a direct DB query if you need to
      reach a soft-deleted row (no such path exists today).

    Raises ``HTTPException(404)`` if the row does not exist, is
    soft-deleted, or is owned by a different non-admin user. The
    cross-user case is collapsed into 404 (not 403) to avoid
    information leakage, matching the C4 files pattern.
    """

    playbook = await db.get(Playbook, playbook_id)
    if playbook is None or playbook.deleted_at is not None:
        raise HTTPException(status_code=404, detail="playbook not found")
    if not user.is_admin and playbook.created_by is not None and playbook.created_by != user.id:
        raise HTTPException(status_code=404, detail="playbook not found")
    return playbook


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
