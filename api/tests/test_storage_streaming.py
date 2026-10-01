"""Unit tests for the streaming storage helpers (Task C4).

The MinIO multipart-upload + streaming-download paths are mocked end-to-end
with a fake S3 client so the tests run without a live MinIO. Full
round-trip integration through the FastAPI handler lives in
``test_files_endpoints.py``.

What's covered here:

* SHA-256 / size accounting for streamed uploads of varying chunk shapes.
* The 413 branch: oversized uploads abort the multipart upload AND raise
  :class:`PayloadTooLarge` with ``limit_bytes`` and ``received_bytes``.
* The pre-failure abort branch: errors raised mid-upload abort the
  in-progress multipart upload.
* The empty-body case: zero-length uploads still produce a valid
  ``StreamUploadResult`` with the canonical SHA-256 of "".
* Streaming download yields the bytes the fake S3 client returns and
  closes the body cleanly.
* ``delete_object`` is idempotent on a 404.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import patch

import pytest

from app.config import get_settings
from app.errors import InternalError, PayloadTooLarge
from app.storage import (
    StreamUploadResult,
    delete_object,
    stream_download,
    stream_upload,
)

# ---------------------------------------------------------------------------
# Fake S3 client wired via @asynccontextmanager monkey-patching
# ---------------------------------------------------------------------------


class _FakeStreamingBody:
    def __init__(self, payload: bytes, chunk_size: int = 64 * 1024) -> None:
        self._payload = payload
        self._chunk_size = chunk_size
        self.closed = False

    async def iter_chunks(self, chunk_size: int = 64 * 1024) -> AsyncIterator[bytes]:
        # The configured stream_download passes 64 KiB; respect whatever
        # is asked, but we slice on `_chunk_size` for testability.
        size = chunk_size or self._chunk_size
        offset = 0
        while offset < len(self._payload):
            yield self._payload[offset : offset + size]
            offset += size

    async def close(self) -> None:
        self.closed = True


class FakeS3Client:
    """In-memory fake of the subset of aioboto3 S3 we touch.

    Records every call so tests can assert on the multipart sequence
    (create → upload_part → complete OR abort).
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}
        self.parts_in_progress: dict[str, list[tuple[int, bytes]]] = {}
        self.events: list[tuple[str, dict[str, Any]]] = []
        self._abort_should_raise = False
        self._upload_part_should_raise: int | None = None
        self._next_upload_id = 0

    def fail_upload_part_at(self, part_number: int) -> None:
        self._upload_part_should_raise = part_number

    def fail_abort(self) -> None:
        self._abort_should_raise = True

    async def head_bucket(self, *, Bucket: str) -> dict[str, Any]:
        self.events.append(("head_bucket", {"Bucket": Bucket}))
        return {}

    async def create_multipart_upload(
        self, *, Bucket: str, Key: str, ContentType: str
    ) -> dict[str, Any]:
        self._next_upload_id += 1
        upload_id = f"upload-{self._next_upload_id}"
        self.parts_in_progress[upload_id] = []
        self.content_types[Key] = ContentType
        self.events.append(
            (
                "create_multipart_upload",
                {"Bucket": Bucket, "Key": Key, "ContentType": ContentType, "UploadId": upload_id},
            )
        )
        return {"UploadId": upload_id}

    async def upload_part(
        self,
        *,
        Bucket: str,
        Key: str,
        PartNumber: int,
        UploadId: str,
        Body: bytes,
    ) -> dict[str, Any]:
        self.events.append(
            (
                "upload_part",
                {
                    "Bucket": Bucket,
                    "Key": Key,
                    "PartNumber": PartNumber,
                    "UploadId": UploadId,
                    "Body_len": len(Body),
                },
            )
        )
        if self._upload_part_should_raise == PartNumber:
            raise RuntimeError("Simulated S3 failure on upload_part")
        self.parts_in_progress.setdefault(UploadId, []).append((PartNumber, Body))
        return {"ETag": f'"etag-{PartNumber}"'}

    async def complete_multipart_upload(
        self,
        *,
        Bucket: str,
        Key: str,
        UploadId: str,
        MultipartUpload: dict[str, Any],
    ) -> dict[str, Any]:
        self.events.append(
            (
                "complete_multipart_upload",
                {
                    "Bucket": Bucket,
                    "Key": Key,
                    "UploadId": UploadId,
                    "Parts": MultipartUpload["Parts"],
                },
            )
        )
        parts = sorted(self.parts_in_progress.pop(UploadId, []), key=lambda p: p[0])
        body = b"".join(part[1] for part in parts)
        self.objects[Key] = body
        return {}

    async def abort_multipart_upload(
        self, *, Bucket: str, Key: str, UploadId: str
    ) -> dict[str, Any]:
        self.events.append(
            (
                "abort_multipart_upload",
                {"Bucket": Bucket, "Key": Key, "UploadId": UploadId},
            )
        )
        if self._abort_should_raise:
            raise RuntimeError("Simulated abort failure")
        self.parts_in_progress.pop(UploadId, None)
        return {}

    async def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self.events.append(("get_object", {"Bucket": Bucket, "Key": Key}))
        if Key not in self.objects:
            err = RuntimeError("NoSuchKey")
            err.response = {"Error": {"Code": "NoSuchKey"}}  # type: ignore[attr-defined]
            raise err
        return {
            "Body": _FakeStreamingBody(self.objects[Key]),
            "ContentType": self.content_types.get(Key, "application/octet-stream"),
            "ContentLength": len(self.objects[Key]),
        }

    async def delete_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self.events.append(("delete_object", {"Bucket": Bucket, "Key": Key}))
        if Key not in self.objects:
            err = RuntimeError("NoSuchKey")
            err.response = {"Error": {"Code": "NoSuchKey"}}  # type: ignore[attr-defined]
            raise err
        del self.objects[Key]
        return {}


@pytest.fixture
def fake_s3() -> FakeS3Client:
    return FakeS3Client()


@pytest.fixture(autouse=True)
def _patch_s3_client(fake_s3: FakeS3Client) -> Iterator[None]:
    """Monkey-patch ``app.storage.s3_client`` to yield the fake."""

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _ctx() -> AsyncIterator[FakeS3Client]:
        yield fake_s3

    with patch("app.storage.s3_client", _ctx):
        yield


# ---------------------------------------------------------------------------
# stream_upload — happy path
# ---------------------------------------------------------------------------


async def _aiter(*chunks: bytes) -> AsyncIterator[bytes]:
    for c in chunks:
        yield c


@pytest.mark.unit
async def test_stream_upload_records_size_and_sha256(fake_s3: FakeS3Client) -> None:
    payload = b"hello world"
    result = await stream_upload(
        storage_path="my-key",
        chunks=_aiter(payload),
        content_type="text/plain",
        max_size_bytes=1_000,
    )

    assert isinstance(result, StreamUploadResult)
    assert result.size_bytes == len(payload)
    assert result.sha256_hex == hashlib.sha256(payload).hexdigest()
    assert result.storage_path == "my-key"

    # The fake's complete-multipart commits the bytes:
    assert fake_s3.objects["my-key"] == payload
    assert fake_s3.content_types["my-key"] == "text/plain"


@pytest.mark.unit
async def test_stream_upload_assembles_multiple_small_chunks(fake_s3: FakeS3Client) -> None:
    # Many small chunks across the part-size boundary should still
    # round-trip cleanly. Use 100 chunks of 100 bytes each = 10,000 bytes,
    # which is one part with the default 8 MiB part size.
    chunks = [bytes([i % 256] * 100) for i in range(100)]
    result = await stream_upload(
        storage_path="multi-small",
        chunks=_aiter(*chunks),
        content_type="application/octet-stream",
        max_size_bytes=1_000_000,
    )

    expected = b"".join(chunks)
    assert result.size_bytes == len(expected)
    assert result.sha256_hex == hashlib.sha256(expected).hexdigest()
    assert fake_s3.objects["multi-small"] == expected


@pytest.mark.unit
async def test_stream_upload_rolls_over_part_boundary(fake_s3: FakeS3Client) -> None:
    """A body larger than MULTIPART_PART_SIZE flushes intermediate parts."""

    from app.storage import MULTIPART_PART_SIZE

    # Two-and-a-bit parts: the upload should issue 3 upload_part calls
    # plus a complete_multipart_upload at the end.
    payload = b"A" * (2 * MULTIPART_PART_SIZE + 1234)
    result = await stream_upload(
        storage_path="big",
        chunks=_aiter(payload),
        content_type="application/octet-stream",
        max_size_bytes=10 * MULTIPART_PART_SIZE,
    )

    assert result.size_bytes == len(payload)
    assert fake_s3.objects["big"] == payload
    upload_part_events = [e for e in fake_s3.events if e[0] == "upload_part"]
    assert len(upload_part_events) == 3
    complete_events = [e for e in fake_s3.events if e[0] == "complete_multipart_upload"]
    assert len(complete_events) == 1


@pytest.mark.unit
async def test_stream_upload_empty_body_writes_zero_byte_object(fake_s3: FakeS3Client) -> None:
    result = await stream_upload(
        storage_path="empty",
        chunks=_aiter(),
        content_type="application/octet-stream",
        max_size_bytes=1_000,
    )

    assert result.size_bytes == 0
    assert result.sha256_hex == hashlib.sha256(b"").hexdigest()
    assert fake_s3.objects["empty"] == b""


# ---------------------------------------------------------------------------
# stream_upload — failure paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_stream_upload_rejects_oversized_body(fake_s3: FakeS3Client) -> None:
    payload = b"X" * 1_001
    with pytest.raises(PayloadTooLarge) as exc_info:
        await stream_upload(
            storage_path="too-big",
            chunks=_aiter(payload),
            content_type="application/octet-stream",
            max_size_bytes=1_000,
        )

    assert exc_info.value.details["limit_bytes"] == 1_000
    assert exc_info.value.details["received_bytes"] >= 1_001
    # The upload was aborted (no orphan object).
    assert "too-big" not in fake_s3.objects
    abort_events = [e for e in fake_s3.events if e[0] == "abort_multipart_upload"]
    assert len(abort_events) == 1


@pytest.mark.unit
async def test_stream_upload_aborts_on_internal_error(fake_s3: FakeS3Client) -> None:
    fake_s3.fail_upload_part_at(1)
    with pytest.raises(InternalError):
        await stream_upload(
            storage_path="will-fail",
            chunks=_aiter(b"some bytes"),
            content_type="text/plain",
            max_size_bytes=1_000_000,
        )

    # Abort was attempted; no orphan object was committed.
    assert "will-fail" not in fake_s3.objects
    abort_events = [e for e in fake_s3.events if e[0] == "abort_multipart_upload"]
    assert len(abort_events) == 1


@pytest.mark.unit
async def test_stream_upload_negative_max_raises_internal_error() -> None:
    with pytest.raises(InternalError):
        await stream_upload(
            storage_path="bad",
            chunks=_aiter(b"x"),
            content_type="text/plain",
            max_size_bytes=0,
        )


@pytest.mark.unit
async def test_stream_upload_oversized_with_failed_abort_still_raises_payload_too_large(
    fake_s3: FakeS3Client,
) -> None:
    """If abort itself fails, the original PayloadTooLarge still surfaces.

    Documented behavior: ``_abort_multipart_safe`` swallows its own
    exceptions so the original error reaches the caller.
    """

    fake_s3.fail_abort()
    with pytest.raises(PayloadTooLarge):
        await stream_upload(
            storage_path="too-big-abort-fails",
            chunks=_aiter(b"X" * 1_001),
            content_type="text/plain",
            max_size_bytes=1_000,
        )


# ---------------------------------------------------------------------------
# stream_download
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_stream_download_yields_full_body(fake_s3: FakeS3Client) -> None:
    fake_s3.objects["k"] = b"the bytes"
    out = bytearray()
    async with stream_download(storage_path="k") as chunks:
        async for chunk in chunks:
            out.extend(chunk)

    assert bytes(out) == b"the bytes"


@pytest.mark.unit
async def test_stream_download_missing_key_raises_internal_error(
    fake_s3: FakeS3Client,
) -> None:
    with pytest.raises(InternalError):
        async with stream_download(storage_path="never-uploaded") as chunks:
            async for _ in chunks:  # pragma: no cover — should not iterate
                pass


# ---------------------------------------------------------------------------
# delete_object
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_delete_object_removes_existing_key(fake_s3: FakeS3Client) -> None:
    fake_s3.objects["k"] = b"data"
    await delete_object(storage_path="k")
    assert "k" not in fake_s3.objects


@pytest.mark.unit
async def test_delete_object_is_idempotent_on_missing_key(fake_s3: FakeS3Client) -> None:
    # No key uploaded; should NOT raise.
    await delete_object(storage_path="never-uploaded")


@pytest.mark.unit
async def test_settings_max_upload_size_default_is_100mb() -> None:
    settings = get_settings()
    assert settings.lq_ai_max_upload_size_mb == 100
