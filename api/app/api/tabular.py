"""Tabular / Multi-Document Review endpoints — M3-C2.

Surface (per [PRD §3.14](docs/PRD.md#314-tabular--multi-document-review-m3)):

* ``POST   /api/v1/tabular/preview-cost`` — synchronous cost preview;
  no execution row is created. The UI calls this before showing the
  confirmation modal (Decision C-5).
* ``POST   /api/v1/tabular/execute`` — kick off a tabular execution.
  Creates a :class:`TabularExecution` row at ``status='pending'``,
  enqueues the ARQ worker job on the shared playbook queue (per
  Decision C-3 — same queue as Easy Playbook). Returns 202 + the row.
* ``GET    /api/v1/tabular/executions`` — list the caller's
  executions (paginated, recent-first, soft-deleted excluded).
* ``GET    /api/v1/tabular/executions/{id}`` — full state + grid.
* ``DELETE /api/v1/tabular/executions/{id}`` — soft delete; sets
  ``deleted_at``.
* ``POST   /api/v1/tabular/executions/{id}/cancel`` — set status to
  ``cancelled``; the worker honours this on the next cell-iteration
  boundary check.

Authorization
-------------

Router-level ``Depends(get_active_user)`` gates every endpoint.
Per-endpoint: rows are scoped to ``user_id == caller.id`` (admins
see everything). 404 collapses missing + unauthorized (no
information leakage), matching the M3-A6 Easy Playbook posture.

Column-spec resolution
----------------------

Either ``skill_name`` (resolved at execution start from the live
:class:`SkillRegistry` by reading the skill's
``lq_ai.columns``) OR ``columns`` (ad-hoc spec) is required. The
resolved column list is snapshotted onto the row at request time
(Decision C-1 snapshotting posture: re-rendering the grid a week
later must be honest about what was actually run).

Cost-preview shape
------------------

Per Decision C-5, the preview returns ``cells_count``,
``estimated_tokens``, ``estimated_cost_usd``, and a
``per_tier_breakdown`` informational map. The frontend gates the
big "Run" button behind a confirmation checkbox for previews
above ``CONFIRMATION_THRESHOLD_USD`` ($1.00 default per the prep
doc — the threshold is enforced UI-side, not server-side).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.audit import audit_action
from app.db.session import get_db
from app.models.document import Document
from app.models.tabular import TabularExecution
from app.schemas.tabular import (
    ColumnSpec,
    TabularExecutionCreate,
    TabularExecutionResponse,
    TabularExecutionSummary,
    TabularPreviewCostRequest,
    TabularPreviewCostResponse,
)
from app.skills.registry import MutableSkillRegistry
from app.tabular.cost import estimate_tabular_execution_cost
from app.workers.queue import enqueue_tabular_execution_job

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tabular"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _registry(request: Request) -> MutableSkillRegistry:
    """Return the live :class:`MutableSkillRegistry` from app state.

    Mirrors :func:`app.api.skills._registry`. The lifespan handler
    installs ``app.state.skill_registry``; if the handler is somehow
    exercised before that, surface a clear error rather than
    AttributeError.
    """

    holder: MutableSkillRegistry | None = getattr(request.app.state, "skill_registry", None)
    if holder is None:
        from app.errors import InternalError

        raise InternalError(
            message="Skill registry is not initialised; the API process is "
            "not yet ready to serve tabular requests.",
            details={"hint": "lifespan startup did not run"},
        )
    return holder


def _resolve_columns(
    request: Request,
    *,
    skill_name: str | None,
    ad_hoc: list[ColumnSpec] | None,
) -> tuple[str | None, list[ColumnSpec]]:
    """Resolve the request's column spec to (skill_name, columns).

    Either ``skill_name`` OR ``ad_hoc`` must be supplied. When
    ``skill_name`` is given, look up the registered skill's
    ``lq_ai.columns`` and snapshot the list. When ``ad_hoc`` is
    given, use it directly. Both-or-neither is a 400.

    Returns the resolved skill_name (None for ad-hoc) + a non-empty
    list of :class:`ColumnSpec`. Raises HTTPException(400) on
    validation errors and HTTPException(404) on unknown skill /
    skill-without-columns.
    """

    if skill_name and ad_hoc:
        raise HTTPException(
            status_code=400,
            detail="provide either skill_name or columns, not both",
        )
    if not skill_name and not ad_hoc:
        raise HTTPException(
            status_code=400,
            detail="provide either skill_name or columns",
        )

    if skill_name:
        record = _registry(request).current().get(skill_name)
        if record is None:
            raise HTTPException(status_code=404, detail=f"skill {skill_name!r} not found")
        skill_columns = record.frontmatter.lq_ai.columns
        if not skill_columns:
            raise HTTPException(
                status_code=400,
                detail=f"skill {skill_name!r} has no columns (not a table-mode skill)",
            )
        # Re-validate through the wire-side ColumnSpec so any
        # skill-side fields the wire schema doesn't honor are
        # stripped consistently.
        return skill_name, [ColumnSpec.model_validate(col.model_dump()) for col in skill_columns]

    # ad_hoc branch — the request-validation min_length=1 on columns
    # in TabularExecutionCreate already covers the empty case.
    assert ad_hoc is not None  # for the type checker
    return None, ad_hoc


async def _load_caller_owned_documents(
    db: AsyncSession,
    *,
    document_ids: list[uuid.UUID],
    user: ActiveUser,
) -> list[Document]:
    """Load documents the caller has access to via the file ownership chain.

    Mirrors the M3-A6 Easy Playbook helper. The visibility rule:
    each :class:`Document` has a parent :class:`File` whose
    ``owner_id`` must match the caller (admins see all) AND which
    has not been soft-deleted. Missing / cross-owner / soft-deleted
    documents collapse into "not found" at the caller — running
    tabular extraction over documents the user no longer "has"
    would surprise on the audit trail.
    """

    from app.models.file import File as FileModel

    stmt = (
        select(Document)
        .where(Document.id.in_(document_ids))
        .join(FileModel, Document.file_id == FileModel.id)
        .where(FileModel.deleted_at.is_(None))
    )
    if not user.is_admin:
        stmt = stmt.where(FileModel.owner_id == user.id)
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/tabular/preview-cost",
    response_model=TabularPreviewCostResponse,
    summary="Preview the cost of a proposed tabular execution.",
)
async def preview_tabular_cost(
    body: TabularPreviewCostRequest,
    request: Request,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TabularPreviewCostResponse:
    """Synchronous cost preview — no execution row is created.

    The UI calls this before showing the confirmation modal so the
    operator sees the cell-count + estimated cost + per-tier
    breakdown (Decision C-5). The estimator's rolling average
    (M2-E2 pattern) caches per ~5 minutes in-process; rapid re-previews
    during column-spec editing don't thrash the DB.

    Authorization is the router-level ``get_active_user`` gate — any
    authenticated caller may preview costs against their own document
    selection. The document-ownership check is enforced at execute
    time; preview doesn't load the documents.
    """

    _ = user  # gate-only; no per-user logic on preview

    _, columns = _resolve_columns(
        request,
        skill_name=body.skill_name,
        ad_hoc=body.columns,
    )

    return await estimate_tabular_execution_cost(
        db,
        document_ids=list(body.document_ids),
        columns=columns,
    )


@router.post(
    "/tabular/execute",
    response_model=TabularExecutionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a tabular execution.",
)
async def create_tabular_execution(
    body: TabularExecutionCreate,
    request: Request,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TabularExecutionResponse:
    """Kick off a tabular execution against the supplied document corpus.

    Authorization: the caller must own every document in
    ``document_ids``. Cross-user or non-existent ids collapse into a
    single 404 (no information leakage), matching the M3-A6 Easy
    Playbook posture.

    Creates a :class:`TabularExecution` row at ``status='pending'``
    and enqueues the ARQ worker job on the shared playbook queue
    (per Decision C-3). Returns 202 immediately with the row; the
    result-view polls
    ``GET /api/v1/tabular/executions/{id}`` until status reaches
    a terminal state.

    Per the M3-C2 quality bar, "execution completed" does NOT mean
    every cell is correct — the result-view's per-cell citation
    drawer is where the user-attorney validates extractions before
    relying on them.
    """

    documents = await _load_caller_owned_documents(
        db,
        document_ids=list(body.document_ids),
        user=user,
    )
    if len(documents) != len(body.document_ids):
        raise HTTPException(status_code=404, detail="one or more documents not found")

    resolved_skill_name, columns = _resolve_columns(
        request,
        skill_name=body.skill_name,
        ad_hoc=body.columns,
    )

    # Snapshot the column spec to the row's JSONB so re-rendering a
    # week later honours Decision C-1's snapshotting invariant.
    columns_json = [col.model_dump(mode="json") for col in columns]

    execution = TabularExecution(
        user_id=user.id,
        skill_name=resolved_skill_name,
        status="pending",
        document_ids=list(body.document_ids),
        columns=columns_json,
        cost_estimate_usd=body.confirmed_cost_usd,
    )
    db.add(execution)
    await db.flush()

    await audit_action(
        db,
        user_id=user.id,
        action="tabular.execution_started",
        resource_type="tabular_execution",
        resource_id=str(execution.id),
        request=request,
        details={
            "document_count": len(body.document_ids),
            "column_count": len(columns),
            "skill_name": resolved_skill_name,
            "confirmed_cost_usd": (
                str(body.confirmed_cost_usd) if body.confirmed_cost_usd is not None else None
            ),
        },
    )
    await db.commit()
    await db.refresh(execution)

    enqueued = await enqueue_tabular_execution_job(execution.id)
    logger.info(
        "tabular_execution_started",
        extra={
            "event": "tabular_execution_started",
            "user_id": str(user.id),
            "execution_id": str(execution.id),
            "enqueued": enqueued,
            "document_count": len(body.document_ids),
            "column_count": len(columns),
        },
    )

    return await _to_response(db, execution)


@router.get(
    "/tabular/executions",
    response_model=list[TabularExecutionSummary],
    summary="List the caller's tabular executions.",
)
async def list_tabular_executions(
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 50,
) -> list[TabularExecutionSummary]:
    """Return the caller's tabular executions, recent-first, soft-deleted excluded.

    Admins see all executions; non-admins see only their own
    (matches the Easy Playbook list posture).
    """

    stmt = select(TabularExecution).where(TabularExecution.deleted_at.is_(None))
    if not user.is_admin:
        stmt = stmt.where(
            or_(TabularExecution.user_id == user.id, TabularExecution.user_id.is_(None))
        )
    stmt = stmt.order_by(TabularExecution.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_summary(row) for row in rows]


@router.get(
    "/tabular/executions/{execution_id}",
    response_model=TabularExecutionResponse,
    summary="Get a tabular execution by id.",
)
async def get_tabular_execution(
    execution_id: uuid.UUID,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TabularExecutionResponse:
    """Return one tabular execution — full state + grid results.

    Authorization: caller must be the row's ``user_id`` OR an admin.
    Cross-user / missing / soft-deleted rows collapse into 404.
    """

    row = await _load_caller_execution(db, execution_id=execution_id, user=user)
    return await _to_response(db, row)


@router.delete(
    "/tabular/executions/{execution_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a tabular execution.",
    response_class=Response,
)
async def delete_tabular_execution(
    execution_id: uuid.UUID,
    user: ActiveUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Soft-delete (sets ``deleted_at``). Already-deleted rows return 404."""

    row = await _load_caller_execution(db, execution_id=execution_id, user=user)
    row.deleted_at = datetime.now(UTC)
    await audit_action(
        db,
        user_id=user.id,
        action="tabular.execution_deleted",
        resource_type="tabular_execution",
        resource_id=str(execution_id),
        request=request,
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/tabular/executions/{execution_id}/cancel",
    response_model=TabularExecutionResponse,
    summary="Cancel a pending or running tabular execution.",
)
async def cancel_tabular_execution(
    execution_id: uuid.UUID,
    user: ActiveUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TabularExecutionResponse:
    """Set status to ``cancelled``.

    The worker's per-cell loop checks the row status at each cell
    boundary; on cancellation it stops accepting new cells and the
    aggregate node writes whatever partial results landed. Already-
    terminal rows (``completed`` / ``failed`` / ``cancelled``) are
    a 409 — operators wanting a clean re-run start a new execution
    via ``POST /tabular/execute``.
    """

    row = await _load_caller_execution(db, execution_id=execution_id, user=user)
    if row.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(
            status_code=409,
            detail=f"execution already in terminal status {row.status!r}",
        )
    row.status = "cancelled"
    row.completed_at = datetime.now(UTC)
    await audit_action(
        db,
        user_id=user.id,
        action="tabular.execution_cancelled",
        resource_type="tabular_execution",
        resource_id=str(execution_id),
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return await _to_response(db, row)


# ---------------------------------------------------------------------------
# Response shaping
# ---------------------------------------------------------------------------


async def _load_caller_execution(
    db: AsyncSession,
    *,
    execution_id: uuid.UUID,
    user: ActiveUser,
) -> TabularExecution:
    """Load one execution + apply the caller-scope visibility rule.

    404 on missing / unauthorized / soft-deleted (single error
    surface; no information leakage).
    """

    row = await db.get(TabularExecution, execution_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="execution not found")
    if not user.is_admin and row.user_id != user.id:
        raise HTTPException(status_code=404, detail="execution not found")
    return row


async def _load_document_names(
    db: AsyncSession, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Return a ``{document_id: filename}`` map for the given ids.

    Joins ``documents → files.filename``. Soft-deleted files are
    excluded — the caller treats a missing id as a deleted document
    (renders as the empty string in the response, which the UI flags
    as "deleted document")."""

    from app.models.file import File as FileModel

    if not document_ids:
        return {}
    stmt = (
        select(Document.id, FileModel.filename)
        .join(FileModel, Document.file_id == FileModel.id)
        .where(Document.id.in_(document_ids), FileModel.deleted_at.is_(None))
    )
    rows = (await db.execute(stmt)).all()
    return {row.id: row.filename for row in rows}


async def _to_response(db: AsyncSession, row: TabularExecution) -> TabularExecutionResponse:
    """Convert the ORM row to the response wire shape.

    Async because the response includes a ``document_names`` field
    that requires a join on ``files`` — keeping the join inside the
    response builder means every endpoint that returns a single
    execution gets the names without duplicating the query."""

    document_ids = list(row.document_ids)
    name_by_id = await _load_document_names(db, document_ids)
    document_names = [name_by_id.get(did, "") for did in document_ids]
    return TabularExecutionResponse.model_validate(
        {
            "id": row.id,
            "user_id": row.user_id,
            "parent_execution_id": row.parent_execution_id,
            "skill_name": row.skill_name,
            "status": row.status,
            "document_ids": document_ids,
            "document_names": document_names,
            "columns": list(row.columns),
            "results": row.results,
            "cost_estimate_usd": row.cost_estimate_usd,
            "cost_actual_usd": row.cost_actual_usd,
            "error_text": row.error_text,
            "created_at": row.created_at,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
        }
    )


def _to_summary(row: TabularExecution) -> TabularExecutionSummary:
    """Compact list-endpoint projection."""

    return TabularExecutionSummary.model_validate(
        {
            "id": row.id,
            "user_id": row.user_id,
            "parent_execution_id": row.parent_execution_id,
            "skill_name": row.skill_name,
            "status": row.status,
            "document_count": len(row.document_ids),
            "column_count": len(row.columns),
            "cost_estimate_usd": row.cost_estimate_usd,
            "cost_actual_usd": row.cost_actual_usd,
            "created_at": row.created_at,
            "completed_at": row.completed_at,
        }
    )


__all__ = ["router"]
