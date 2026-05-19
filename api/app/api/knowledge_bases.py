"""Knowledge-base endpoints — Task C6 (Knowledge Service).

Surface (per ``docs/api/backend-openapi.yaml``):

* ``POST   /api/v1/knowledge-bases``                   — create.
* ``GET    /api/v1/knowledge-bases?archived=true|false`` — list.
* ``GET    /api/v1/knowledge-bases/{kb_id}``           — fetch single.
* ``PATCH  /api/v1/knowledge-bases/{kb_id}``           — partial update.
* ``DELETE /api/v1/knowledge-bases/{kb_id}``           — soft-delete.
* ``POST   /api/v1/knowledge-bases/{kb_id}/files``     — attach a file.
* ``GET    /api/v1/knowledge-bases/{kb_id}/files``     — list attached files.
* ``DELETE /api/v1/knowledge-bases/{kb_id}/files/{file_id}`` — detach.
* ``POST   /api/v1/knowledge-bases/{kb_id}/query``     — hybrid search.

All endpoints inherit auth + must-change-password gate from the router-
level ``Depends(get_active_user)`` in :mod:`app.api.__init__`. Per-user
isolation 404 (matches C4 / C7 / chats posture).

The query endpoint runs the C6 hybrid retrieval per ADR 0008:

1. Embed the query string via the gateway's ``/v1/embeddings``.
2. Run pgvector cosine + Postgres FTS in parallel.
3. Min-max normalize; linear-combine with ``hybrid_alpha``.
4. Return top-k.

Embedding-on-write trigger: ``POST /files`` enqueues an embed job so
chunks land in the vector index without the user having to wait. The
query handler also runs embed-on-read for any matched chunks that
still have NULL embeddings (the worker hasn't caught up yet) before
returning results.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.audit import audit_action
from app.clients.gateway import GatewayClient, get_gateway_client
from app.db.session import get_db
from app.errors import Conflict, LQAIError, NotFound, ValidationError
from app.knowledge.embed import (
    DEFAULT_EMBEDDING_MODEL,
    request_embedding_vector,
)
from app.knowledge.retrieval import hybrid_search
from app.models.chat import Chat
from app.models.document import Document, DocumentChunk
from app.models.file import File as FileModel
from app.models.knowledge import KnowledgeBase, KnowledgeBaseFile
from app.models.project import Project
from app.schemas.knowledge import (
    AttachFileRequest,
    KBFileResponse,
    KBQueryRequest,
    KBQueryResponse,
    KnowledgeBaseCreateRequest,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdateRequest,
    SearchResult,
    SearchResultChunk,
    SearchResultScores,
)

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_kb_id(kb_id: str) -> uuid.UUID:
    """Reject non-UUID kb ids per the OpenAPI sketch's ``{kb_id}: uuid``."""

    try:
        return uuid.UUID(kb_id)
    except ValueError as exc:
        raise ValidationError(
            "kb_id must be a UUID",
            details={"kb_id": kb_id},
        ) from exc


async def _load_visible_kb(
    db: AsyncSession,
    kb_id: uuid.UUID,
    owner_id: uuid.UUID,
    *,
    include_archived: bool = False,
) -> KnowledgeBase:
    """Load a KB scoped to the caller; 404 on miss / cross-user / archived."""

    stmt = select(KnowledgeBase).where(
        KnowledgeBase.id == kb_id,
        KnowledgeBase.owner_id == owner_id,
    )
    if not include_archived:
        stmt = stmt.where(KnowledgeBase.archived_at.is_(None))
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise NotFound(
            f"Knowledge base {kb_id} not found.",
            details={"kb_id": str(kb_id)},
        )
    return row


async def _load_visible_file_for_kb(
    db: AsyncSession,
    file_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> FileModel:
    """Load a file scoped to the caller; 404 on miss / cross-user.

    ``ingestion_status='ready'`` is enforced by the attachment handler
    explicitly so the message can say "the file isn't ready yet" rather
    than the more generic 404.
    """

    stmt = select(FileModel).where(
        FileModel.id == file_id,
        FileModel.owner_id == owner_id,
        FileModel.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise NotFound(
            f"File {file_id} not found.",
            details={"file_id": str(file_id)},
        )
    return row


async def _load_visible_project_for_kb(
    db: AsyncSession,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> Project:
    """Validate that ``project_id`` is owned by the caller (active) before
    accepting it as the KB's project association."""

    stmt = select(Project).where(
        Project.id == project_id,
        Project.owner_id == owner_id,
        Project.archived_at.is_(None),
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise NotFound(
            f"Project {project_id} not found.",
            details={"project_id": str(project_id)},
        )
    return row


async def _kb_counts(db: AsyncSession, kb_id: uuid.UUID) -> tuple[int, int]:
    """Return ``(file_count, chunk_count)`` for a KB.

    Two cheap aggregates; the chunk count joins through documents so
    the count reflects "chunks searchable inside this KB," not just
    rows in a table somewhere.
    """

    file_count_stmt = (
        select(func.count())
        .select_from(KnowledgeBaseFile)
        .where(
            KnowledgeBaseFile.kb_id == kb_id,
        )
    )
    chunk_count_stmt = (
        select(func.count())
        .select_from(DocumentChunk)
        .join(Document, DocumentChunk.document_id == Document.id)
        .join(KnowledgeBaseFile, KnowledgeBaseFile.file_id == Document.file_id)
        .where(KnowledgeBaseFile.kb_id == kb_id)
    )
    file_count = (await db.execute(file_count_stmt)).scalar_one()
    chunk_count = (await db.execute(chunk_count_stmt)).scalar_one()
    return int(file_count), int(chunk_count)


async def _serialize_kb(db: AsyncSession, kb: KnowledgeBase) -> KnowledgeBaseResponse:
    """Build a :class:`KnowledgeBaseResponse` from a row + counts."""

    file_count, chunk_count = await _kb_counts(db, kb.id)
    return KnowledgeBaseResponse(
        id=kb.id,
        owner_id=kb.owner_id,
        project_id=kb.project_id,
        name=kb.name,
        description=kb.description,
        hybrid_alpha=float(kb.hybrid_alpha),
        file_count=file_count,
        chunk_count=chunk_count,
        archived_at=kb.archived_at,
        created_at=kb.created_at,
        updated_at=kb.updated_at,
    )


async def _file_has_null_embedding_chunks(db: AsyncSession, file_id: uuid.UUID) -> bool:
    """Quick check: does this file have any chunks with NULL embeddings?

    Used after attach to decide whether to enqueue an embed-job. The
    query is a single-row EXISTS so it doesn't scan the whole table.
    """

    stmt = (
        select(DocumentChunk.id)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.file_id == file_id)
        .where(DocumentChunk.tokens.is_(None))  # NULL tokens implies NULL embedding (we set both)
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a knowledge base",
)
async def create_kb(
    payload: KnowledgeBaseCreateRequest,
    user: ActiveUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeBaseResponse:
    if payload.project_id is not None:
        await _load_visible_project_for_kb(db, payload.project_id, user.id)

    kb = KnowledgeBase(
        owner_id=user.id,
        project_id=payload.project_id,
        name=payload.name,
        description=payload.description,
        hybrid_alpha=float(payload.hybrid_alpha),
    )
    db.add(kb)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict(
            "Knowledge base creation failed due to a constraint violation.",
            details={"name": payload.name},
        ) from exc

    await audit_action(
        db,
        user_id=user.id,
        action="kb.created",
        resource_type="knowledge_base",
        resource_id=str(kb.id),
        project_id=kb.project_id,
        request=request,
        details={"name": kb.name, "hybrid_alpha": kb.hybrid_alpha},
    )
    await db.commit()
    await db.refresh(kb)

    log.info(
        "kb created",
        extra={
            "event": "kb_created",
            "user_id": str(user.id),
            "kb_id": str(kb.id),
            "project_id": str(kb.project_id) if kb.project_id else None,
        },
    )
    return await _serialize_kb(db, kb)


@router.get(
    "",
    response_model=list[KnowledgeBaseResponse],
    summary="List the caller's knowledge bases",
)
async def list_kbs(
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    archived: Annotated[
        bool | None,
        Query(description="When true, return only archived KBs."),
    ] = None,
    project_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by project association."),
    ] = None,
) -> list[KnowledgeBaseResponse]:
    stmt = select(KnowledgeBase).where(KnowledgeBase.owner_id == user.id)
    if archived is True:
        stmt = stmt.where(KnowledgeBase.archived_at.is_not(None))
    else:
        stmt = stmt.where(KnowledgeBase.archived_at.is_(None))
    if project_id is not None:
        stmt = stmt.where(KnowledgeBase.project_id == project_id)
    stmt = stmt.order_by(KnowledgeBase.created_at.desc())

    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    return [await _serialize_kb(db, row) for row in rows]


@router.get(
    "/{kb_id}",
    response_model=KnowledgeBaseResponse,
    summary="Fetch a single knowledge base",
)
async def get_kb(
    kb_id: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeBaseResponse:
    kid = _validate_kb_id(kb_id)
    kb = await _load_visible_kb(db, kid, user.id, include_archived=True)
    return await _serialize_kb(db, kb)


@router.patch(
    "/{kb_id}",
    response_model=KnowledgeBaseResponse,
    summary="Partial update of a knowledge base",
)
async def update_kb(
    kb_id: str,
    payload: KnowledgeBaseUpdateRequest,
    user: ActiveUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeBaseResponse:
    kid = _validate_kb_id(kb_id)
    kb = await _load_visible_kb(db, kid, user.id, include_archived=True)
    update_fields = payload.model_dump(exclude_unset=True)

    if "name" in update_fields:
        kb.name = update_fields["name"]
    if "description" in update_fields:
        kb.description = update_fields["description"]
    if "hybrid_alpha" in update_fields:
        kb.hybrid_alpha = float(update_fields["hybrid_alpha"])
    if "project_id" in update_fields:
        new_project_id = update_fields["project_id"]
        if new_project_id is not None:
            await _load_visible_project_for_kb(db, new_project_id, user.id)
        kb.project_id = new_project_id

    if "archived" in update_fields:
        archived_flag = update_fields["archived"]
        if archived_flag is True and kb.archived_at is None:
            kb.archived_at = datetime.now(tz=UTC)
        elif archived_flag is False and kb.archived_at is not None:
            kb.archived_at = None

    try:
        await db.flush()
        await audit_action(
            db,
            user_id=user.id,
            action="kb.updated",
            resource_type="knowledge_base",
            resource_id=str(kb.id),
            project_id=kb.project_id,
            request=request,
            details={"fields": sorted(update_fields.keys())},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict(
            "Knowledge base update conflicted with current state.",
            details={"kb_id": str(kb.id)},
        ) from exc

    await db.refresh(kb)
    log.info(
        "kb updated",
        extra={
            "event": "kb_updated",
            "user_id": str(user.id),
            "kb_id": str(kb.id),
            "fields": sorted(update_fields.keys()),
        },
    )
    return await _serialize_kb(db, kb)


@router.delete(
    "/{kb_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a knowledge base",
    response_class=Response,
)
async def delete_kb(
    kb_id: str,
    user: ActiveUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    kid = _validate_kb_id(kb_id)
    kb = await _load_visible_kb(db, kid, user.id, include_archived=False)
    kb.archived_at = datetime.now(tz=UTC)
    await audit_action(
        db,
        user_id=user.id,
        action="kb.deleted",
        resource_type="knowledge_base",
        resource_id=str(kb.id),
        project_id=kb.project_id,
        request=request,
        details={"name": kb.name},
    )
    await db.commit()
    log.info(
        "kb archived",
        extra={"event": "kb_archived", "user_id": str(user.id), "kb_id": str(kid)},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# File attachment
# ---------------------------------------------------------------------------


@router.post(
    "/{kb_id}/files",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Attach a file to a knowledge base",
    description=(
        "The file must be owned by the caller and have completed the C5 "
        "ingest pipeline (``ingestion_status='ready'``). Files in any "
        "other state return 422. After successful attach, an embed job is "
        "enqueued so chunks with NULL embeddings get vectors written; "
        "the query path also covers this lazily via embed-on-read."
    ),
    response_class=Response,
)
async def attach_file(
    kb_id: str,
    payload: AttachFileRequest,
    user: ActiveUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    kid = _validate_kb_id(kb_id)
    kb = await _load_visible_kb(db, kid, user.id)
    file_row = await _load_visible_file_for_kb(db, payload.file_id, user.id)

    if file_row.ingestion_status != "ready":
        raise ValidationError(
            f"File {payload.file_id} is not ready for KB attachment "
            f"(ingestion_status={file_row.ingestion_status!r}).",
            details={
                "file_id": str(payload.file_id),
                "ingestion_status": file_row.ingestion_status,
            },
        )

    kb_uuid = kb.id
    file_uuid = file_row.id

    join = KnowledgeBaseFile(kb_id=kb_uuid, file_id=file_uuid)
    db.add(join)
    try:
        await db.flush()
        await audit_action(
            db,
            user_id=user.id,
            action="kb.file_attached",
            resource_type="knowledge_base",
            resource_id=str(kb_uuid),
            project_id=kb.project_id,
            request=request,
            details={"file_id": str(file_uuid), "filename": file_row.filename},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict(
            "File is already attached to this knowledge base.",
            details={"kb_id": str(kb_uuid), "file_id": str(file_uuid)},
        ) from exc

    log.info(
        "kb file attached",
        extra={
            "event": "kb_file_attached",
            "user_id": str(user.id),
            "kb_id": str(kb_uuid),
            "file_id": str(file_uuid),
        },
    )

    # Eagerly enqueue an embed job if any chunks lack embeddings.
    # Best-effort — failure is non-fatal (embed-on-read covers).
    if await _file_has_null_embedding_chunks(db, file_uuid):
        try:
            from app.workers.queue import enqueue_embed_job

            await enqueue_embed_job(file_uuid)
        except Exception as exc:
            log.warning(
                "kb attach: embed-job enqueue failed (embed-on-read will cover)",
                extra={
                    "event": "kb_attach_embed_enqueue_failed",
                    "kb_id": str(kb_uuid),
                    "file_id": str(file_uuid),
                    "error": str(exc),
                },
            )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{kb_id}/files",
    response_model=list[KBFileResponse],
    summary="List the files attached to a knowledge base",
    description=(
        "Returns the files currently attached to the KB (the ``File`` "
        "shape from ``GET /files/{id}`` plus the ``attached_at`` "
        "timestamp from the join). Owner-scoped — cross-user / unknown "
        "KB id returns 404. Soft-deleted files are excluded; an "
        "attachment that points at a deleted file is filtered out at "
        "the join. Sorted by ``attached_at DESC`` so the most recent "
        "uploads surface first."
    ),
)
async def list_kb_files(
    kb_id: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[KBFileResponse]:
    """Enumerate the files attached to ``kb_id``.

    The detail page (Wave C) needs per-doc rows with ingestion status
    so the UI can render the ``✓`` / ``⏳`` / ``⚠`` indicator next to
    each filename. Backed by the ``knowledge_base_files`` join joined
    to ``files`` — both ends scoped to the caller (the KB by
    ``owner_id``; the file by ``deleted_at IS NULL`` to drop tombstones
    that may still carry a join row mid-cascade).
    """

    from sqlalchemy.orm import aliased

    kid = _validate_kb_id(kb_id)
    # Owner-scope check — cross-user / unknown / archived → 404. We
    # allow archived KBs here so the detail page can render a
    # post-archive view (matches the ``get_kb`` posture).
    await _load_visible_kb(db, kid, user.id, include_archived=True)

    # Left-join to ``documents`` so ``page_count`` / ``character_count``
    # come from the C5-pipeline row when present. A file in
    # ``ingestion_status='pending' | 'processing'`` has no document row
    # yet — those columns serialize as null until the pipeline finishes.
    doc = aliased(Document)
    stmt = (
        select(
            FileModel,
            KnowledgeBaseFile.attached_at,
            doc.id,
            doc.page_count,
            doc.character_count,
            doc.ingest_status,
            doc.ingest_failure_reason,
        )
        .join(KnowledgeBaseFile, KnowledgeBaseFile.file_id == FileModel.id)
        .outerjoin(doc, doc.file_id == FileModel.id)
        .where(
            KnowledgeBaseFile.kb_id == kid,
            FileModel.deleted_at.is_(None),
        )
        .order_by(KnowledgeBaseFile.attached_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    out: list[KBFileResponse] = []
    for (
        file_row,
        attached_at,
        document_id,
        page_count,
        character_count,
        ingest_status,
        ingest_failure_reason,
    ) in rows:
        out.append(
            KBFileResponse(
                id=file_row.id,
                owner_id=file_row.owner_id,
                project_id=file_row.project_id,
                filename=file_row.filename,
                mime_type=file_row.mime_type,
                size_bytes=file_row.size_bytes,
                hash_sha256=file_row.hash_sha256,
                ingestion_status=file_row.ingestion_status,
                ingestion_error=file_row.ingestion_error,
                ingest_status=ingest_status,
                ingest_failure_reason=ingest_failure_reason,
                page_count=page_count,
                character_count=character_count,
                document_id=document_id,
                created_at=file_row.created_at,
                attached_at=attached_at,
            )
        )
    return out


@router.delete(
    "/{kb_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach a file from a knowledge base",
    response_class=Response,
)
async def detach_file(
    kb_id: str,
    file_id: str,
    user: ActiveUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    kid = _validate_kb_id(kb_id)
    try:
        fid = uuid.UUID(file_id)
    except ValueError as exc:
        raise ValidationError(
            "file_id must be a UUID",
            details={"file_id": file_id},
        ) from exc

    kb = await _load_visible_kb(db, kid, user.id)

    stmt = select(KnowledgeBaseFile).where(
        and_(
            KnowledgeBaseFile.kb_id == kid,
            KnowledgeBaseFile.file_id == fid,
        )
    )
    result = await db.execute(stmt)
    join = result.scalar_one_or_none()
    if join is None:
        raise NotFound(
            "File is not attached to this knowledge base.",
            details={"kb_id": str(kid), "file_id": str(fid)},
        )

    await db.delete(join)
    await audit_action(
        db,
        user_id=user.id,
        action="kb.file_detached",
        resource_type="knowledge_base",
        resource_id=str(kid),
        project_id=kb.project_id,
        request=request,
        details={"file_id": str(fid)},
    )
    await db.commit()
    log.info(
        "kb file detached",
        extra={
            "event": "kb_file_detached",
            "user_id": str(user.id),
            "kb_id": str(kid),
            "file_id": str(fid),
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


@router.post(
    "/{kb_id}/query",
    response_model=KBQueryResponse,
    summary="Hybrid (vector + FTS) search over the knowledge base",
)
async def query_kb(
    kb_id: str,
    payload: KBQueryRequest,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> KBQueryResponse:
    kid = _validate_kb_id(kb_id)
    kb = await _load_visible_kb(db, kid, user.id)

    alpha = payload.hybrid_alpha if payload.hybrid_alpha is not None else float(kb.hybrid_alpha)

    # Embed the query string for the vector side, unless alpha=1
    # (FTS-only). Failures here downgrade to FTS-only ranking — the
    # user still gets results, just on one side of the score.
    query_embedding: list[float] | None = None
    if alpha < 1.0:
        try:
            gateway: GatewayClient = get_gateway_client()
            query_embedding = await request_embedding_vector(
                payload.query,
                model=DEFAULT_EMBEDDING_MODEL,
                gateway=gateway,
                request_id=request.headers.get("x-request-id"),
            )
        except LQAIError as exc:
            log.warning(
                "kb query: query-embedding fetch failed; falling back to FTS-only",
                extra={
                    "event": "kb_query_embed_fetch_failed",
                    "kb_id": str(kid),
                    "error_code": exc.effective_code,
                },
            )
            query_embedding = None

    raw_results = await hybrid_search(
        db,
        kb_id=kid,
        query=payload.query,
        query_embedding=query_embedding,
        top_k=payload.top_k,
        alpha=alpha,
    )

    # Wave D.1 T7: write a `inference.kb_chunks_retrieved` audit row when
    # the query is chat-initiated and returned at least one chunk. The
    # row is scoped to the chat (resource_type='chat') so the Receipts
    # endpoint (T5/T6) can render it as a "📎 KB retrieval" event.
    # We require the chat to be owner-visible — same posture as the
    # chat surface itself (404 leaks no existence info).
    if payload.chat_id is not None and raw_results:
        chat_stmt = select(Chat).where(
            and_(
                Chat.id == payload.chat_id,
                Chat.owner_id == user.id,
                Chat.archived_at.is_(None),
            )
        )
        chat_row = (await db.execute(chat_stmt)).scalar_one_or_none()
        if chat_row is not None:
            await audit_action(
                db,
                user_id=user.id,
                action="inference.kb_chunks_retrieved",
                resource_type="chat",
                resource_id=str(payload.chat_id),
                project_id=chat_row.project_id,
                request=request,
                details={
                    "kb_ids": [str(kid)],
                    "chunk_count": len(raw_results),
                    "chunk_ids": [str(r.chunk_id) for r in raw_results],
                    "query_token_estimate": len(payload.query.split()),
                },
            )
            await db.commit()

    return KBQueryResponse(
        results=[
            SearchResult(
                chunk=SearchResultChunk(
                    id=r.chunk_id,
                    document_id=r.document_id,
                    file_id=r.file_id,
                    file_name=r.file_name,
                    content=r.content,
                    page_start=r.page_start,
                    page_end=r.page_end,
                    char_offset_start=r.char_offset_start,
                    char_offset_end=r.char_offset_end,
                ),
                score=r.hybrid_score,
                score_components=SearchResultScores(
                    vector=r.vector_score,
                    fts=r.fts_score,
                ),
            )
            for r in raw_results
        ],
        hybrid_alpha=alpha,
    )


__all__ = [
    "attach_file",
    "create_kb",
    "delete_kb",
    "detach_file",
    "get_kb",
    "list_kb_files",
    "list_kbs",
    "query_kb",
    "router",
    "update_kb",
]
