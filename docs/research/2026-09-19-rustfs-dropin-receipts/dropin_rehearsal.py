"""Throwaway rehearsal: is RustFS a data-level drop-in for a MinIO-written volume?

Not project code. Drives api/app/storage.py (unmodified) plus a raw aioboto3
client against whichever store S3_ENDPOINT_URL points at.

Modes:
  seed    - create the bucket, write a realistic object set, record a manifest
            (key -> sha256, size, etag, content-type) to MANIFEST
  verify  - list the bucket and read every manifest object back; compare bytes,
            etag, content-type; report extra/missing keys
  mutate  - write two new objects and delete one seeded object; update MANIFEST
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import uuid

sys.path.insert(0, os.environ["LQ_API_DIR"])

from app import storage
from app.config import get_settings

MANIFEST = os.environ["MANIFEST"]


async def _chunks(data: bytes, size: int = 1_000_000):
    for i in range(0, len(data), size):
        yield data[i : i + size]


async def _download(key: str) -> bytes:
    buf = bytearray()
    async with storage.stream_download(storage_path=key) as it:
        async for c in it:
            buf.extend(c)
    return bytes(buf)


async def _head(s3, bucket: str, key: str) -> dict:
    r = await s3.head_object(Bucket=bucket, Key=key)
    return {
        "etag": r.get("ETag"),
        "content_type": r.get("ContentType"),
        "size": r.get("ContentLength"),
    }


async def _list_keys(s3, bucket: str) -> list[str]:
    keys: list[str] = []
    token = None
    while True:
        kw = {"Bucket": bucket}
        if token:
            kw["ContinuationToken"] = token
        r = await s3.list_objects_v2(**kw)
        keys += [o["Key"] for o in r.get("Contents", [])]
        if not r.get("IsTruncated"):
            return keys
        token = r.get("NextContinuationToken")


def _record(manifest: dict, key: str, data: bytes, head: dict, ct: str) -> None:
    manifest[key] = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "etag": head["etag"],
        "content_type": head["content_type"],
        "declared_content_type": ct,
    }


async def seed() -> None:
    settings = get_settings()
    bucket = settings.s3_bucket
    await storage.ensure_bucket()
    manifest: dict = {}
    rng = os.urandom
    async with storage.s3_client() as s3:
        # One large multipart object (3 parts), like a scanned contract PDF.
        big = rng(20 * 1024 * 1024 + 3)
        keys = {}
        k_big = str(uuid.uuid4())
        await storage.stream_upload(
            storage_path=k_big,
            chunks=_chunks(big),
            content_type="application/pdf",
            max_size_bytes=100 << 20,
        )
        keys[k_big] = (big, "application/pdf")
        # Forty small "documents" with bare-UUID keys (ADR 0005), mixed types.
        for i in range(40):
            k = str(uuid.uuid4())
            data = rng(1024 * (i + 1))
            ct = [
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "text/plain",
            ][i % 3]
            await storage.stream_upload(
                storage_path=k, chunks=_chunks(data, 777), content_type=ct, max_size_bytes=100 << 20
            )
            keys[k] = (data, ct)
        # An empty upload and a 12-byte one.
        k_empty = str(uuid.uuid4())
        await storage.stream_upload(
            storage_path=k_empty,
            chunks=_chunks(b""),
            content_type="text/plain",
            max_size_bytes=1024,
        )
        keys[k_empty] = (b"", "text/plain")
        k_small = str(uuid.uuid4())
        await storage.stream_upload(
            storage_path=k_small,
            chunks=_chunks(b"hello minio!", 4),
            content_type="text/plain",
            max_size_bytes=1024,
        )
        keys[k_small] = (b"hello minio!", "text/plain")
        # Two export bundles via put_object.
        for _j in range(2):
            k = f"exports/{uuid.uuid4()}/{uuid.uuid4()}.zip"
            data = b"PK\x05\x06" + rng(5000)
            await storage.upload_bytes(storage_path=k, body=data, content_type="application/zip")
            keys[k] = (data, "application/zip")
        for k, (data, ct) in keys.items():
            _record(manifest, k, data, await _head(s3, bucket, k), ct)
        listed = await _list_keys(s3, bucket)
    # The very first big upload has an unrecorded random key; drop it so the
    # manifest is the full truth. (It is deleted below.)
    stray = [k for k in listed if k not in manifest]
    async with storage.s3_client() as s3:
        for k in stray:
            await s3.delete_object(Bucket=bucket, Key=k)
    with open(MANIFEST, "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    print(
        f"seeded {len(manifest)} objects into {bucket}; total {sum(v['size'] for v in manifest.values()) / 1e6:.1f} MB"
    )


async def verify() -> int:
    settings = get_settings()
    bucket = settings.s3_bucket
    with open(MANIFEST) as f:
        manifest = json.load(f)
    failures: list[str] = []
    async with storage.s3_client() as s3:
        try:
            await s3.head_bucket(Bucket=bucket)
            print(f"bucket {bucket}: present")
        except Exception as exc:
            print(f"bucket {bucket}: MISSING ({exc})")
            return 1
        listed = set(await _list_keys(s3, bucket))
        expected = set(manifest)
        missing = sorted(expected - listed)
        extra = sorted(listed - expected)
        print(
            f"listed {len(listed)} keys; expected {len(expected)}; missing {len(missing)}; extra {len(extra)}"
        )
        for k in missing:
            failures.append(f"missing: {k}")
        for k in extra:
            failures.append(f"extra: {k}")
        for k, rec in sorted(manifest.items()):
            try:
                data = await _download(k)
            except Exception as exc:
                failures.append(f"read failed: {k}: {exc}")
                continue
            if hashlib.sha256(data).hexdigest() != rec["sha256"] or len(data) != rec["size"]:
                failures.append(f"bytes differ: {k}")
            head = await _head(s3, bucket, k)
            if head["etag"] != rec["etag"]:
                failures.append(f"etag differs: {k}: {rec['etag']} -> {head['etag']}")
            if head["content_type"] != rec["content_type"]:
                failures.append(
                    f"content-type differs: {k}: {rec['content_type']} -> {head['content_type']}"
                )
    bad_keys = {f.split(": ", 1)[1].split(":")[0] for f in failures if not f.startswith("extra")}
    print(
        f"objects fully intact (bytes+etag+content-type): {len(manifest) - len(bad_keys)}/{len(manifest)}"
    )
    for f in failures:
        print("  FAIL", f)
    return 1 if failures else 0


async def mutate() -> None:
    settings = get_settings()
    bucket = settings.s3_bucket
    with open(MANIFEST) as f:
        manifest = json.load(f)
    async with storage.s3_client() as s3:
        k1 = str(uuid.uuid4())
        d1 = os.urandom(9 * 1024 * 1024)  # 2 parts
        await storage.stream_upload(
            storage_path=k1,
            chunks=_chunks(d1),
            content_type="application/pdf",
            max_size_bytes=100 << 20,
        )
        _record(manifest, k1, d1, await _head(s3, bucket, k1), "application/pdf")
        k2 = f"exports/{uuid.uuid4()}/{uuid.uuid4()}.zip"
        d2 = b"PK\x05\x06" + os.urandom(100)
        await storage.upload_bytes(storage_path=k2, body=d2, content_type="application/zip")
        _record(manifest, k2, d2, await _head(s3, bucket, k2), "application/zip")
        victim = sorted(
            k for k in manifest if not k.startswith("exports/") and manifest[k]["size"] < 100_000
        )[0]
        await storage.delete_object(storage_path=victim)
        del manifest[victim]
    with open(MANIFEST, "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    print(
        f"mutated: +{k1[:8]}… (9 MiB, 2 parts) +{k2[:16]}… -{victim[:8]}… ; manifest now {len(manifest)} objects"
    )


if __name__ == "__main__":
    mode = sys.argv[1]
    rc = asyncio.run({"seed": seed, "verify": verify, "mutate": mutate}[mode]())
    sys.exit(rc or 0)
