"""Files endpoints — Task C4 (File upload + storage).

Surface (per ``docs/api/backend-openapi.yaml``):

* ``POST   /api/v1/files``               — multipart upload; streams body to
  MinIO, computes SHA-256, persists metadata with
  ``ingestion_status='pending'`` and returns the canonical ``File`` shape.
* ``GET    /api/v1/files/{file_id}``     — file metadata; 404 if missing or
  owned by a different user (per-user isolation; we return 404 rather
  than 403 to avoid leaking existence).
* ``GET    /api/v1/files/{file_id}/content`` — streaming download of the
  original bytes; ``Content-Disposition: attachment; filename=...`` with
  RFC 5987-encoded ``filename*`` for non-ASCII filenames.
* ``DELETE /api/v1/files/{file_id}``     — soft-delete (sets ``deleted_at``);
  the MinIO bytes outlive the soft-delete per ADR 0005. The endpoint is
  idempotent: deleting an already-soft-deleted file (or a file that
  never existed) returns 404.

All four endpoints inherit the auth+gate from the router-level
``Depends(get_active_user)`` in ``app.api.__init__``; this module also
takes ``ActiveUser`` directly in handler signatures so the user object
is available for ``owner_id`` checks (FastAPI dedupes the dependency).

The C5 document pipeline picks up rows where
``ingestion_status='pending'`` and flips status through ``processing`` →
``ready`` (or ``failed``). C4 does NOT enqueue or notify — the pipeline
polls or subscribes; that's its problem.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.audit import audit_action
from app.config import get_settings
from app.db.session import get_db
from app.errors import NotFound, ValidationError
from app.models.document import Document
from app.models.file import File as FileModel
from app.models.project import Project
from app.schemas.files import FileMetadata
from app.storage import (
    StreamUploadResult,
    delete_object,
    stream_download,
    stream_upload,
)

router = APIRouter(prefix="/files", tags=["files"])
log = logging.getLogger(__name__)

# Default MIME for the rare upload that arrives with no `Content-Type` on
# the multipart part. Same fallback the IETF recommends for "we have no
# idea what kind of bytes these are."
DEFAULT_MIME = "application/octet-stream"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_file_id(file_id: str) -> uuid.UUID:
    """Reject non-UUID file ids per the OpenAPI sketch's ``{file_id}: uuid``."""

    try:
        return uuid.UUID(file_id)
    except ValueError as exc:
        # Keep the shape consistent with chats.py's _validate_chat_id —
        # 400 with code ``validation_error`` rather than a 404 (which
        # would conflate "bad input" with "no such resource").
        raise ValidationError(
            "file_id must be a UUID",
            details={"file_id": file_id},
        ) from exc


# RFC 6266 / RFC 5987: when the filename has only ascii printable chars
# we emit a plain ``filename="..."`` parameter; otherwise we add the
# UTF-8 ``filename*=UTF-8''<percent-encoded>`` form alongside an ascii
# fallback so legacy clients still get something usable.
_ASCII_PRINTABLE = re.compile(r"^[\x20-\x7E]+$")


def _content_disposition_attachment(filename: str) -> str:
    """Render an RFC 6266 ``Content-Disposition`` value for a download.

    For ASCII-only filenames the result is the simple
    ``attachment; filename="<name>"`` form. For names containing
    non-ASCII codepoints, both an ASCII fallback and the
    ``filename*=UTF-8''<percent-encoded>`` extension are emitted, in
    that order, per RFC 5987.

    Backslashes and quotes in the filename are escaped per RFC 6266
    section 4.1's quoted-string rules.
    """

    safe_ascii = _strip_for_ascii_fallback(filename) or "download"
    quoted_ascii = safe_ascii.replace("\\", "\\\\").replace('"', '\\"')

    if _ASCII_PRINTABLE.match(filename):
        return f'attachment; filename="{quoted_ascii}"'

    encoded = urllib.parse.quote(filename, safe="")
    return f"attachment; filename=\"{quoted_ascii}\"; filename*=UTF-8''{encoded}"


def _strip_for_ascii_fallback(filename: str) -> str:
    """Best-effort ASCII-fallback filename: drops non-printable codepoints.

    Used for the legacy ``filename="..."`` parameter when the canonical
    name has non-ASCII characters. The ``filename*`` parameter still
    carries the full UTF-8 form for modern clients.
    """

    return "".join(ch for ch in filename if 0x20 <= ord(ch) < 0x7F)


async def _upload_file_stream(
    upload: UploadFile,
    *,
    storage_path: str,
    max_size_bytes: int,
) -> StreamUploadResult:
    """Adapter: feed an ``UploadFile``'s spool through ``stream_upload``.

    Reads ``upload.read(MULTIPART_PART_SIZE)`` repeatedly so we never
    materialize the whole body. Starlette spools to a SpooledTemporaryFile
    on disk past 1 MB by default, so for any file larger than that the
    bytes are streaming through disk rather than RAM.
    """

    from app.storage import MULTIPART_PART_SIZE

    async def _chunks() -> AsyncIterator[bytes]:
        while True:
            chunk = await upload.read(MULTIPART_PART_SIZE)
            if not chunk:
                break
            yield chunk

    return await stream_upload(
        storage_path=storage_path,
        chunks=_chunks(),
        content_type=upload.content_type or DEFAULT_MIME,
        max_size_bytes=max_size_bytes,
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=FileMetadata,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file",
    description=(
        "Streaming multipart upload. The body is streamed to MinIO without "
        "ever loading the whole file into memory; a SHA-256 is computed as "
        "bytes flow past, and metadata is persisted with "
        "`ingestion_status='pending'`. The document pipeline (Task C5) "
        "picks the row up asynchronously and flips status through "
        "`processing` → `ready` (or `failed`).\n\n"
        "Per-request size limit: `LQ_AI_MAX_UPLOAD_SIZE_MB` (default 100). "
        "Exceeding it returns 413 with `code=payload_too_large`."
    ),
)
async def upload_file(
    user: ActiveUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File(description="The file to upload.")],
    project_id: Annotated[
        str | None,
        Form(
            description=(
                "Optional UUID of a project to attach this file to. The "
                "caller must own the project; cross-user or unknown ids "
                "return 422 (the upload is rejected before bytes touch "
                "MinIO)."
            ),
        ),
    ] = None,
) -> FileMetadata:
    """Stream the upload to MinIO; persist metadata; return the ``File`` shape.

    Order of operations:

    1. **Validate ``project_id``** if supplied. The form field is parsed
       as a UUID; the project must exist, be owned by the caller, and
       not be archived. Failures here return 422 *before* any bytes
       touch MinIO so a bad project_id doesn't leak into orphan storage.
    2. **Pre-allocate the file_id** locally so we know the storage path
       before touching MinIO. (Per ADR 0005 the storage key is the bare
       UUID.)
    3. **Stream the upload to MinIO** via ``stream_upload``. This raises
       :class:`PayloadTooLarge` if the streamed byte count exceeds the
       configured cap; on any other exception, the multipart upload is
       aborted (no orphan parts left behind).
    4. **Insert the row** in ``files`` with the streamed size and SHA-256.
       If the insert fails (e.g., the user has been deleted between
       auth and now), we hard-delete the just-uploaded MinIO object so
       we don't leak orphaned bytes.
    5. **Return the ``FileMetadata``** matching the OpenAPI ``File`` schema.
    """

    settings = get_settings()
    max_size_bytes = settings.lq_ai_max_upload_size_mb * 1024 * 1024

    # Filename is required by the OpenAPI sketch; FastAPI's UploadFile
    # always exposes `.filename` but it can be the empty string for a
    # pathologically-formed multipart. Reject those explicitly.
    filename = (file.filename or "").strip()
    if not filename:
        raise ValidationError(
            "Multipart upload missing required `filename` on the file part.",
        )

    # Resolve the project attachment up front. Anything other than
    # "owner-visible active project" → 422 (validation error). We use
    # 422 rather than 404 here because the caller is making a *create*
    # request; the project_id is request input, not a path identifier
    # whose existence is being probed.
    resolved_project_id: uuid.UUID | None = None
    if project_id is not None:
        try:
            resolved_project_id = uuid.UUID(project_id)
        except ValueError as exc:
            raise ValidationError(
                "project_id must be a UUID",
                details={"project_id": project_id},
            ) from exc

        stmt = select(Project.id).where(
            Project.id == resolved_project_id,
            Project.owner_id == user.id,
            Project.archived_at.is_(None),
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise ValidationError(
                "project_id does not reference a project owned by the caller.",
                details={"project_id": str(resolved_project_id)},
            )

    file_id = uuid.uuid4()
    storage_path = str(file_id)
    mime_type = file.content_type or DEFAULT_MIME

    log.info(
        "file upload start",
        extra={
            "event": "file_upload_start",
            "user_id": str(user.id),
            "file_id": str(file_id),
            # Use ``upload_filename`` not ``filename`` because ``filename``
            # is a reserved attribute on Python's ``LogRecord`` and
            # supplying it via ``extra`` raises a KeyError.
            "upload_filename": filename,
            "mime_type": mime_type,
            "project_id": str(resolved_project_id) if resolved_project_id else None,
        },
    )

    upload_result = await _upload_file_stream(
        file,
        storage_path=storage_path,
        max_size_bytes=max_size_bytes,
    )

    row = FileModel(
        id=file_id,
        owner_id=user.id,
        project_id=resolved_project_id,
        filename=filename,
        mime_type=mime_type,
        size_bytes=upload_result.size_bytes,
        hash_sha256=upload_result.sha256_hex,
        storage_path=upload_result.storage_path,
        ingestion_status="pending",
    )
    db.add(row)
    try:
        await db.flush()
        # Privilege propagates from the project (if any) — audit_action
        # resolves it from project_id without an extra fetch when the
        # ORM Project isn't loaded here.
        await audit_action(
            db,
            user_id=user.id,
            action="file.uploaded",
            resource_type="file",
            resource_id=str(file_id),
            project_id=resolved_project_id,
            request=request,
            details={
                "filename": filename,
                "size_bytes": upload_result.size_bytes,
                "mime_type": mime_type,
            },
        )
        await db.commit()
    except IntegrityError:
        # Failed to persist after the bytes were uploaded. Clean up the
        # MinIO object so we don't leak orphaned storage.
        await db.rollback()
        try:
            await delete_object(storage_path=storage_path)
        except Exception:
            log.warning(
                "Failed to clean up MinIO object after row-insert failure",
                extra={
                    "event": "file_upload_cleanup_failed",
                    "storage_path": storage_path,
                },
            )
        raise

    await db.refresh(row)

    log.info(
        "file upload complete",
        extra={
            "event": "file_upload_complete",
            "user_id": str(user.id),
            "file_id": str(file_id),
            "size_bytes": upload_result.size_bytes,
            "sha256": upload_result.sha256_hex,
        },
    )

    # Enqueue the ingest job for the C5 document pipeline. Failures are
    # non-fatal — the row stays at `pending` and the worker's startup
    # sweep will pick it up. We import lazily so test environments
    # that don't have arq installed (or that monkey-patch the queue)
    # don't pay an import cost on every upload.
    try:
        from app.workers.queue import enqueue_ingest_job

        await enqueue_ingest_job(file_id)
    except Exception as exc:
        # The enqueue helper itself catches exceptions and returns a
        # bool, but defensively handle any path that raises (e.g., the
        # import failed). The upload itself is committed; ingestion
        # is delayed.
        log.warning(
            "enqueue_ingest_job raised; row remains pending",
            extra={
                "event": "file_upload_enqueue_raised",
                "file_id": str(file_id),
                "error": str(exc),
            },
        )

    return FileMetadata.model_validate(row)


@router.get(
    "/{file_id}",
    response_model=FileMetadata,
    summary="Get file metadata",
)
async def get_file(
    file_id: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileMetadata:
    """Return the canonical ``File`` shape for ``file_id``.

    Returns 404 if the file does not exist, has been soft-deleted, or
    is owned by another user. (Per CLAUDE.md and the C4 brief: the
    cross-user case returns 404 rather than 403 to avoid leaking
    existence information.)
    """

    file_uuid = _validate_file_id(file_id)
    row = await _load_visible_file(db, file_uuid, user.id)
    # Outerjoin to ``documents`` so the response carries ``document_id``
    # once the C5 parse pipeline has produced the row (M3-A6 Phase 6).
    document_id_stmt = select(Document.id).where(Document.file_id == row.id)
    document_id = (await db.execute(document_id_stmt)).scalar_one_or_none()
    return FileMetadata.model_validate(row).model_copy(update={"document_id": document_id})


@router.get(
    "/{file_id}/content",
    summary="Download original file content",
    response_class=StreamingResponse,
)
async def get_file_content(
    file_id: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """Stream the original bytes from MinIO with the right headers.

    Headers set:
    * ``Content-Type``: from the stored ``mime_type``.
    * ``Content-Length``: from the stored ``size_bytes``.
    * ``Content-Disposition``: ``attachment; filename="..."`` with an
      RFC 5987 ``filename*`` for non-ASCII filenames.
    * ``X-Content-Type-Options: nosniff``: defensive — clients (esp.
      browsers) must not infer a MIME from sniffing.
    """

    file_uuid = _validate_file_id(file_id)
    row = await _load_visible_file(db, file_uuid, user.id)

    headers = {
        "Content-Length": str(row.size_bytes),
        "Content-Disposition": _content_disposition_attachment(row.filename),
        "X-Content-Type-Options": "nosniff",
    }

    async def _generator() -> AsyncIterator[bytes]:
        async with stream_download(storage_path=row.storage_path) as chunks:
            async for chunk in chunks:
                yield chunk

    return StreamingResponse(
        _generator(),
        media_type=row.mime_type or DEFAULT_MIME,
        headers=headers,
    )


@router.delete(
    "/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a file",
    description=(
        "Sets `deleted_at` on the row; the MinIO object is left in place "
        "and reaped later by D6 (per-user export+delete) or a future GC "
        "sweep, per `docs/adr/0005-file-storage-soft-delete-and-key-scheme.md`. "
        "Idempotent: deleting an already-soft-deleted file or a missing "
        "file returns 404."
    ),
    response_class=Response,
)
async def delete_file(
    file_id: str,
    user: ActiveUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Soft-delete the file by setting ``deleted_at``.

    Re-uses ``_load_visible_file`` so the cross-user case returns 404
    (no information leakage) and the already-soft-deleted case also
    returns 404 (the row is no longer visible to the user).
    """

    file_uuid = _validate_file_id(file_id)
    row = await _load_visible_file(db, file_uuid, user.id)

    from datetime import UTC, datetime

    row.deleted_at = datetime.now(tz=UTC)
    await audit_action(
        db,
        user_id=user.id,
        action="file.deleted",
        resource_type="file",
        resource_id=str(row.id),
        project_id=row.project_id,
        request=request,
        details={"filename": row.filename},
    )
    await db.commit()

    log.info(
        "file soft-deleted",
        extra={
            "event": "file_soft_deleted",
            "user_id": str(user.id),
            "file_id": str(file_uuid),
        },
    )

    # FastAPI translates `Response(status_code=204)` to a no-body 204.
    # Returning JSONResponse({}) with 204 would emit an empty body
    # which some HTTP/1.1 implementations dislike alongside a 204 (which
    # is defined as no-body). The explicit Response is correct.
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Internal: shared file-lookup
# ---------------------------------------------------------------------------


async def _load_visible_file(
    db: AsyncSession,
    file_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> FileModel:
    """Load ``files`` row by id, scoped to the owner, excluding soft-deleted rows.

    Raises :class:`NotFound` if the row does not exist, is soft-deleted,
    or is owned by a different user. The cross-user case is collapsed
    into 404 deliberately — see C4 brief and CLAUDE.md on
    information-leakage avoidance.
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


# ---------------------------------------------------------------------------
# JSONResponse wrapper for non-FastAPI callers
# ---------------------------------------------------------------------------
# Re-export under the legacy name so existing imports keep compiling. The
# tests under api/tests/test_endpoints.py read the route table from the
# app object; they do not import these handlers by name.

__all__ = [
    "delete_file",
    "get_file",
    "get_file_content",
    "router",
    "upload_file",
]
