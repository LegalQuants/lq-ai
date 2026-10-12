"""Throwaway verification: drive api/app/storage.py against a live RustFS.

Not project code. Exercises exactly the S3 calls the api makes:
head_bucket/create_bucket, multipart upload (8 MiB parts + trailing partial,
and the empty-body single zero-length part), get_object streaming,
delete_object (twice, idempotent), put_object, generate_presigned_url + GET.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import urllib.request

sys.path.insert(0, os.environ["LQ_API_DIR"])

from app import storage
from app.errors import PayloadTooLarge


async def _chunks(data: bytes, size: int):
    for i in range(0, len(data), size):
        yield data[i : i + size]


async def _empty():
    if False:
        yield b""


async def main() -> None:
    results: list[tuple[str, str]] = []

    async def step(name, coro):
        try:
            out = await coro
            results.append((name, "OK"))
            return out
        except Exception as exc:
            results.append((name, f"FAIL: {type(exc).__name__}: {exc}"))
            return None

    await step("ensure_bucket (fresh bucket -> CreateBucket)", storage.ensure_bucket())
    await step("ensure_bucket (idempotent -> HeadBucket 200)", storage.ensure_bucket())
    ok = await step("check_storage", storage.check_storage())
    results.append(("check_storage returned True", "OK" if ok else "FAIL"))

    # 20 MiB + 3 bytes: 2 full 8 MiB parts + a trailing partial part.
    big = os.urandom(20 * 1024 * 1024 + 3)
    res = await step(
        "stream_upload 20MiB (3 multipart parts)",
        storage.stream_upload(
            storage_path="big-uuid",
            chunks=_chunks(big, 1_000_000),
            content_type="application/pdf",
            max_size_bytes=100 * 1024 * 1024,
        ),
    )
    if res:
        results.append(
            (
                "stream_upload sha256/size match",
                "OK"
                if res.sha256_hex == hashlib.sha256(big).hexdigest() and res.size_bytes == len(big)
                else "FAIL",
            )
        )

    async def _download(key: str) -> bytes:
        buf = bytearray()
        async with storage.stream_download(storage_path=key) as it:
            async for c in it:
                buf.extend(c)
        return bytes(buf)

    got = await step("stream_download 20MiB", _download("big-uuid"))
    results.append(("download bytes == upload bytes", "OK" if got == big else "FAIL"))

    small = b"hello rustfs"
    await step(
        "stream_upload small (single trailing part < 5MiB)",
        storage.stream_upload(
            storage_path="small-uuid",
            chunks=_chunks(small, 4),
            content_type="text/plain",
            max_size_bytes=1024,
        ),
    )
    got = await step("stream_download small", _download("small-uuid"))
    results.append(("small roundtrip", "OK" if got == small else "FAIL"))

    await step(
        "stream_upload EMPTY body (explicit zero-length part)",
        storage.stream_upload(
            storage_path="empty-uuid",
            chunks=_empty(),
            content_type="text/plain",
            max_size_bytes=1024,
        ),
    )
    got = await step("stream_download empty", _download("empty-uuid"))
    results.append(("empty roundtrip", "OK" if got == b"" else f"FAIL: {got!r}"))

    # Size-cap path: must raise PayloadTooLarge and abort the multipart upload.
    try:
        await storage.stream_upload(
            storage_path="toolarge-uuid",
            chunks=_chunks(os.urandom(9 * 1024 * 1024), 1_000_000),
            content_type="application/octet-stream",
            max_size_bytes=8 * 1024 * 1024 + 1,
        )
        results.append(("PayloadTooLarge raised + abort", "FAIL: no exception"))
    except PayloadTooLarge:
        results.append(("PayloadTooLarge raised + abort", "OK"))
    except Exception as exc:
        results.append(("PayloadTooLarge raised + abort", f"FAIL: {exc}"))

    await step(
        "upload_bytes (put_object)",
        storage.upload_bytes(
            storage_path="exports/u1/j1.zip",
            body=b"PK\x05\x06" + b"\x00" * 18,
            content_type="application/zip",
        ),
    )
    url = await step(
        "presigned_get_url",
        storage.presigned_get_url(storage_path="exports/u1/j1.zip", expires_in_seconds=600),
    )
    if url:
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                body = r.read()
            results.append(
                ("GET presigned url (no auth)", "OK" if body.startswith(b"PK") else "FAIL")
            )
        except Exception as exc:
            results.append(("GET presigned url (no auth)", f"FAIL: {exc}"))

    await step("delete_object", storage.delete_object(storage_path="small-uuid"))
    await step(
        "delete_object again (idempotent 404)", storage.delete_object(storage_path="small-uuid")
    )
    await step("delete_object never-existed key", storage.delete_object(storage_path="nope-uuid"))

    # A missing object must surface as InternalError, not hang.
    try:
        await _download("small-uuid")
        results.append(("stream_download missing -> InternalError", "FAIL: no exception"))
    except Exception as exc:
        results.append(("stream_download missing -> InternalError", f"OK ({type(exc).__name__})"))

    for name, status in results:
        print(f"{status:<8} {name}" if status in {"OK"} else f"{status}  <-  {name}")


if __name__ == "__main__":
    asyncio.run(main())
