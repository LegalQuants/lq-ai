"""S3-compatible async client for the api/ service.

Uses ``aioboto3`` so file uploads, downloads, and metadata operations stay
on the asyncio event loop. The full upload/download surface lands in Task
C4 (this module); A4's prerequisites (session-builder, ``ensure_bucket``,
``check_storage``) are unchanged.

We use path-style addressing because it works consistently across the bundled
RustFS service and operator-supplied S3-compatible endpoints.

Streaming I/O
-------------

C4 requires streaming uploads (no full-body buffering) for the documented
100MB-per-request size cap. ``stream_upload`` consumes an
``AsyncIterator[bytes]`` (the FastAPI request stream), incrementally
SHA-256s every chunk, enforces the size cap, and pushes parts to S3 via
the multipart-upload protocol so we never need to know the body length up
front.

Streaming downloads use ``get_object``'s response body directly; we yield
chunks and the caller's ``StreamingResponse`` flushes them out.

Object key
----------

Per ADR 0005 we use the bare file UUID as the object key. Callers
pass the key in (the handler computes it as ``str(file.id)``); this module
does not synthesize keys.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import aioboto3
from botocore.config import Config as BotocoreConfig

from app.config import get_settings
from app.errors import InternalError, PayloadTooLarge

log = logging.getLogger(__name__)

# Multipart-upload part size. S3 requires every part except the last to
# be at least 5 MiB. We use 8 MiB which gives us a comfortable margin
# above the floor and keeps the maximum number of parts well within the
# 10,000-part S3 ceiling for our 100 MB default cap (≈12.5 parts) and
# any realistic operator override (a 50 GB cap → 6,250 parts).
MULTIPART_PART_SIZE = 8 * 1024 * 1024  # 8 MiB

# Streaming-download chunk size. Big enough that small files come out in
# one or two chunks; small enough that a slow consumer can backpressure
# without blowing memory.
DOWNLOAD_CHUNK_SIZE = 64 * 1024  # 64 KiB


@dataclass(slots=True, frozen=True)
class StreamUploadResult:
    """Outcome of a streaming upload.

    Attributes:
        size_bytes: The total number of bytes that flowed past.
        sha256_hex: Hex-encoded SHA-256 of the bytes (lowercase).
        storage_path: The S3 object key the bytes were written to.
    """

    size_bytes: int
    sha256_hex: str
    storage_path: str


def _build_session() -> aioboto3.Session:
    settings = get_settings()
    return aioboto3.Session(
        aws_access_key_id=settings.s3_access_key or None,
        aws_secret_access_key=settings.s3_secret_key or None,
        region_name=settings.s3_region,
    )


@asynccontextmanager
async def s3_client() -> AsyncIterator[Any]:
    """Yield an aioboto3 S3 client configured for our endpoint.

    Use as::

        async with s3_client() as s3:
            await s3.head_bucket(Bucket=...)
    """
    settings = get_settings()
    session = _build_session()
    async with session.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url or None,
        config=BotocoreConfig(s3={"addressing_style": "path"}),
    ) as client:
        yield client


async def ensure_bucket() -> None:
    """Create the configured bucket if it does not exist.

    Called from the FastAPI lifespan on startup. A 404 from HeadBucket means
    "create it"; anything else (403, network error) propagates.
    """
    settings = get_settings()
    bucket = settings.s3_bucket
    async with s3_client() as s3:
        try:
            await s3.head_bucket(Bucket=bucket)
            return
        except Exception as exc:
            # Botocore raises ClientError with response['Error']['Code'] == '404'
            # for bucket-not-found. Anything else, re-raise. We catch the bare
            # Exception because botocore's ClientError is the dominant case but
            # endpoint-misconfiguration also surfaces socket errors here.
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if code not in {"404", "NoSuchBucket"}:
                raise
        # Create the bucket. CreateBucketConfiguration is region-specific:
        # for us-east-1 it MUST be omitted; for any other region it MUST be
        # provided. We honour both.
        kwargs: dict[str, Any] = {"Bucket": bucket}
        if settings.s3_region and settings.s3_region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {
                "LocationConstraint": settings.s3_region,
            }
        await s3.create_bucket(**kwargs)
        log.info("Created S3 bucket: %s", bucket)


async def check_storage() -> bool:
    """Readiness check: returns True if the configured bucket is reachable."""
    settings = get_settings()
    try:
        async with s3_client() as s3:
            await s3.head_bucket(Bucket=settings.s3_bucket)
        return True
    except Exception as exc:
        # Readiness probes never raise; report failure in the response body.
        log.warning("Storage readiness check failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Streaming upload
# ---------------------------------------------------------------------------


async def stream_upload(
    *,
    storage_path: str,
    chunks: AsyncIterator[bytes],
    content_type: str,
    max_size_bytes: int,
) -> StreamUploadResult:
    """Stream chunks from ``chunks`` to S3-compatible storage at ``storage_path``.

    Builds parts of ``MULTIPART_PART_SIZE`` from the inbound chunk
    iterator and pushes them as a multipart upload. Computes SHA-256
    over the byte stream as it flows past — we never re-read the
    object after upload.

    Raises :class:`app.errors.PayloadTooLarge` the instant the running
    byte count exceeds ``max_size_bytes``. The in-progress multipart
    upload is aborted in that case so the object store does not retain orphan
    parts.

    Args:
        storage_path: S3 object key (per ADR 0005 this is the bare
            file UUID).
        chunks: Async iterator yielding ``bytes`` of arbitrary size; an
            empty iteration is allowed (the resulting object is empty).
        content_type: ``Content-Type`` to record on the S3 object. The
            handler trusts the user-stated MIME (we never preview the
            file based on it; just store and serve).
        max_size_bytes: Hard ceiling on the total bytes streamed. The
            ``size_bytes >= 0`` check on the column rejects negatives;
            this enforces the upper bound.

    Returns:
        :class:`StreamUploadResult` with the byte count, SHA-256 hex,
        and storage path.

    Raises:
        :class:`PayloadTooLarge`: Stream exceeded ``max_size_bytes``.
        :class:`InternalError`: the S3-compatible store returned an unexpected error.
    """

    if max_size_bytes <= 0:
        raise InternalError(
            "stream_upload called with non-positive max_size_bytes",
            details={"max_size_bytes": max_size_bytes},
        )

    settings = get_settings()
    bucket = settings.s3_bucket

    sha = hashlib.sha256()
    total_bytes = 0
    buffer = bytearray()
    part_number = 1
    parts: list[dict[str, Any]] = []
    upload_id: str | None = None

    async with s3_client() as s3:
        try:
            create_resp = await s3.create_multipart_upload(
                Bucket=bucket,
                Key=storage_path,
                ContentType=content_type,
            )
            upload_id = create_resp["UploadId"]

            async for chunk in chunks:
                if not chunk:
                    continue
                total_bytes += len(chunk)
                if total_bytes > max_size_bytes:
                    # Abort and surface the typed error. We carry the
                    # received-bytes count even though it's "the limit
                    # plus one chunk" for debugging visibility.
                    await _abort_multipart_safe(s3, bucket, storage_path, upload_id)
                    raise PayloadTooLarge(
                        message=(
                            f"Uploaded file exceeds the {max_size_bytes // (1024 * 1024)} MB "
                            "per-request limit."
                        ),
                        details={
                            "limit_bytes": max_size_bytes,
                            "received_bytes": total_bytes,
                        },
                    )
                sha.update(chunk)
                buffer.extend(chunk)

                while len(buffer) >= MULTIPART_PART_SIZE:
                    part_body = bytes(buffer[:MULTIPART_PART_SIZE])
                    del buffer[:MULTIPART_PART_SIZE]
                    part_resp = await s3.upload_part(
                        Bucket=bucket,
                        Key=storage_path,
                        PartNumber=part_number,
                        UploadId=upload_id,
                        Body=part_body,
                    )
                    parts.append({"PartNumber": part_number, "ETag": part_resp["ETag"]})
                    part_number += 1

            # Upload the trailing partial part (if any). S3 requires at
            # least one part on CompleteMultipartUpload; if the body was
            # empty, we send an explicit zero-length final part rather
            # than rely on S3's behavior with zero parts.
            if buffer or not parts:
                final_body = bytes(buffer)
                buffer.clear()
                part_resp = await s3.upload_part(
                    Bucket=bucket,
                    Key=storage_path,
                    PartNumber=part_number,
                    UploadId=upload_id,
                    Body=final_body,
                )
                parts.append({"PartNumber": part_number, "ETag": part_resp["ETag"]})

            await s3.complete_multipart_upload(
                Bucket=bucket,
                Key=storage_path,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
            upload_id = None  # Don't abort on the way out of the try.
        except PayloadTooLarge:
            # Already aborted above; re-raise unchanged.
            raise
        except Exception as exc:
            # Best-effort abort, then surface as InternalError so the
            # FastAPI handler returns a 500 with the typed envelope
            # (rather than a botocore stack trace leaking to the user).
            if upload_id is not None:
                await _abort_multipart_safe(s3, bucket, storage_path, upload_id)
            log.exception(
                "stream_upload failed",
                extra={
                    "event": "storage_stream_upload_failed",
                    "bucket": bucket,
                    "storage_path": storage_path,
                },
            )
            raise InternalError(
                "Failed to write uploaded file to object storage",
                details={"storage_path": storage_path},
            ) from exc

    return StreamUploadResult(
        size_bytes=total_bytes,
        sha256_hex=sha.hexdigest(),
        storage_path=storage_path,
    )


async def _abort_multipart_safe(
    s3: Any,
    bucket: str,
    key: str,
    upload_id: str,
) -> None:
    """Abort an in-progress multipart upload; never raise.

    AbortMultipartUpload deletes any parts that have been uploaded so
    far. We log on failure but do not propagate — the caller is
    already in the middle of handling another error.
    """

    try:
        await s3.abort_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
        )
    except Exception as exc:
        log.warning(
            "abort_multipart_upload failed (orphan parts may linger): %s",
            exc,
            extra={
                "event": "storage_abort_multipart_failed",
                "bucket": bucket,
                "key": key,
                "upload_id": upload_id,
            },
        )


# ---------------------------------------------------------------------------
# Streaming download
# ---------------------------------------------------------------------------


@asynccontextmanager
async def stream_download(*, storage_path: str) -> AsyncIterator[AsyncIterator[bytes]]:
    """Open a streaming GET from object storage; yield an async byte-iterator.

    The yielded iterator must be consumed within the ``async with`` block
    — the underlying S3 client and HTTP response are scoped to it.

    Usage::

        async with stream_download(storage_path=key) as chunks:
            async for chunk in chunks:
                ...

    Raises:
        :class:`InternalError`: object missing or S3-compatible store error.
    """

    settings = get_settings()
    bucket = settings.s3_bucket

    async with s3_client() as s3:
        try:
            response = await s3.get_object(Bucket=bucket, Key=storage_path)
        except Exception as exc:
            log.warning(
                "stream_download get_object failed",
                extra={
                    "event": "storage_get_object_failed",
                    "bucket": bucket,
                    "storage_path": storage_path,
                    "error": str(exc),
                },
            )
            raise InternalError(
                "Failed to read uploaded file from object storage",
                details={"storage_path": storage_path},
            ) from exc

        body = response["Body"]

        async def _iterate() -> AsyncIterator[bytes]:
            try:
                async for chunk in body.iter_chunks(DOWNLOAD_CHUNK_SIZE):
                    if chunk:
                        yield chunk
            finally:
                # `body` is the StreamingBody; close releases the
                # underlying connection back to the pool.
                close = getattr(body, "close", None)
                if close is not None:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result

        try:
            yield _iterate()
        finally:
            close = getattr(body, "close", None)
            if close is not None:
                try:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Delete (hard delete of the object-store object)
# ---------------------------------------------------------------------------


async def delete_object(*, storage_path: str) -> None:
    """Hard-delete the object-store object at ``storage_path``.

    Per ADR 0005, the user-facing DELETE endpoint flips ``deleted_at``
    on the row and does NOT call this function — the bytes outlive the
    soft-delete and are reaped later. This helper is exposed for D6
    (per-user export+delete) and for failure-path cleanup in the
    upload handler (e.g., we wrote the object but the row insert
    failed).

    A best-effort delete: 404 is treated as success (idempotent).
    """

    settings = get_settings()
    bucket = settings.s3_bucket

    async with s3_client() as s3:
        try:
            await s3.delete_object(Bucket=bucket, Key=storage_path)
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchKey"}:
                return  # Already gone; idempotent success.
            log.warning(
                "delete_object failed",
                extra={
                    "event": "storage_delete_failed",
                    "bucket": bucket,
                    "storage_path": storage_path,
                    "error": str(exc),
                },
            )
            raise


# ---------------------------------------------------------------------------
# Bytes-in / presigned-URL-out (D6 GDPR export)
# ---------------------------------------------------------------------------


async def upload_bytes(*, storage_path: str, body: bytes, content_type: str) -> None:
    """Single-shot upload of an in-memory blob to ``storage_path``.

    Counterpart to :func:`stream_upload` for callers that already hold
    the full bytes (e.g., the D6 export worker, which buffers a
    completed ZIP in a NamedTemporaryFile and reads it back at the
    end). For multi-megabyte inputs this is fine; the multipart path
    is reserved for files coming off a streaming request body whose
    size is not known up front.
    """

    settings = get_settings()
    bucket = settings.s3_bucket

    async with s3_client() as s3:
        await s3.put_object(
            Bucket=bucket,
            Key=storage_path,
            Body=body,
            ContentType=content_type,
        )


async def presigned_get_url(*, storage_path: str, expires_in_seconds: int) -> str:
    """Return a presigned GET URL for ``storage_path``.

    Used by D6's status-poll endpoint to hand the caller a time-bounded
    download link without proxying bytes through the API process. The
    URL is signed with the same S3 credentials the API uses for direct
    operations; recipients need no auth beyond the URL itself.

    ``expires_in_seconds`` is the validity window (S3 max is 7 days).
    The D6 endpoint uses 24h.
    """

    settings = get_settings()
    bucket = settings.s3_bucket

    async with s3_client() as s3:
        url: str = await s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": storage_path},
            ExpiresIn=expires_in_seconds,
        )
        return url
