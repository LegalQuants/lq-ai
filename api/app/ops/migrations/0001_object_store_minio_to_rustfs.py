"""Migration 0001: snapshot a MinIO volume for RustFS's in-place import."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import socket
import tarfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aioboto3
from botocore.config import Config as BotocoreConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.ops.models import Check, Detection, JournalEntry, Marker
from app.ops.state import (
    COMPONENT,
    MIGRATION_ID,
    MIGRATION_TITLE,
    TOOL_VERSION,
    Journal,
    OpsPaths,
    inspect_object_store,
    sha256_file,
    utc_now,
)

id = MIGRATION_ID
title = MIGRATION_TITLE
introduced_in = "0.8.0"
component = COMPONENT
irreversible = False


def detect(paths: OpsPaths) -> Detection:
    return inspect_object_store(paths.object_store)


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql+asyncpg://lq_ai:lq_ai@postgres:5432/lq_ai")


def _endpoint_url() -> str:
    return os.environ.get("S3_ENDPOINT_URL", "http://object-store:9000").rstrip("/")


def _store_is_stopped(endpoint: str) -> tuple[bool, str]:
    parsed = urlparse(endpoint)
    if not parsed.hostname:
        return False, f"invalid S3 endpoint: {endpoint!r}"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=1):
            return False, f"object store is accepting connections at {parsed.hostname}:{port}"
    except (OSError, TimeoutError):
        return True, "object store is stopped"


async def _database_checks() -> tuple[Check, Check]:
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            floor_ok = str(revision).isdigit() and int(str(revision)) >= 38
            tables = await connection.execute(
                text("SELECT to_regclass('public.files'), to_regclass('public.user_export_jobs')")
            )
            files_table, exports_table = tables.one()
            readable = files_table is not None and exports_table is not None
            if readable:
                await connection.execute(
                    text("SELECT storage_path, hash_sha256 FROM files LIMIT 1")
                )
                await connection.execute(text("SELECT storage_key FROM user_export_jobs LIMIT 1"))
        return (
            Check(
                "supported-floor",
                floor_ok,
                f"alembic revision {revision}; supported floor is v0.3.0 (0038)",
            ),
            Check(
                "storage-ledger-readable",
                readable,
                "files and user_export_jobs are readable"
                if readable
                else "files or user_export_jobs is missing",
            ),
        )
    except Exception as exc:
        message = f"Postgres preflight failed: {exc}"
        return Check("supported-floor", False, message), Check(
            "storage-ledger-readable", False, message
        )
    finally:
        await engine.dispose()


def _free_space_check(paths: OpsPaths, volume_bytes: int) -> Check:
    paths.snapshots.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(paths.snapshots).free
    required = (volume_bytes * 11 + 9) // 10
    return Check(
        "snapshot-space",
        free >= required,
        f"{paths.snapshots}: {free} bytes free; {required} bytes required (110% of {volume_bytes})",
    )


async def preflight(paths: OpsPaths, detection: Detection) -> tuple[Check, ...]:
    checks: list[Check] = []
    checks.append(
        Check(
            "supported-layout",
            detection.kind == "applies" and detection.layout in {"xl", "xl-single"},
            detection.reason,
        )
    )
    volume_bytes = int(detection.facts.get("volume_bytes", 0))
    checks.append(_free_space_check(paths, volume_bytes))
    stopped, stopped_message = await asyncio.to_thread(_store_is_stopped, _endpoint_url())
    checks.append(Check("store-stopped", stopped, stopped_message))
    checks.extend(await _database_checks())
    return tuple(checks)


def _snapshot_name(deployment_id: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{MIGRATION_ID}-{deployment_id}-{stamp}.tar"


def _snapshot_volume(source: Path, destination: Path) -> None:
    temporary = destination.with_suffix(".tar.partial")
    temporary.unlink(missing_ok=True)
    try:
        with tarfile.open(temporary, "w") as archive:
            for child in sorted(source.iterdir(), key=lambda path: path.name):
                archive.add(child, arcname=child.name, recursive=True)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _chown_tree(root: Path, uid: int, gid: int) -> None:
    os.chown(root, uid, gid)
    for current, dirs, files in os.walk(root):
        for name in dirs:
            os.chown(Path(current) / name, uid, gid)
        for name in files:
            os.chown(Path(current) / name, uid, gid)


def _completed_snapshot(
    paths: OpsPaths, journal: Journal, deployment_id: str
) -> tuple[Path, str, int] | None:
    """Return a durable prior snapshot so interrupted apply can resume safely."""

    for entry in reversed(journal.entries()):
        if (
            entry.migration_id != MIGRATION_ID
            or entry.deployment_id != deployment_id
            or entry.phase != "snapshot"
            or entry.state != "applied"
        ):
            continue
        raw_path = entry.receipt.get("snapshot_path")
        expected_digest = entry.receipt.get("snapshot_sha256")
        if not raw_path or not expected_digest:
            raise RuntimeError("completed snapshot receipt is missing its path or SHA-256")
        snapshot = Path(str(raw_path)).resolve()
        snapshots_root = paths.snapshots.resolve()
        if snapshot == snapshots_root or snapshots_root not in snapshot.parents:
            raise RuntimeError("snapshot receipt points outside the configured snapshot directory")
        if not snapshot.is_file():
            raise RuntimeError(f"journalled snapshot is missing: {snapshot}")
        actual_digest = sha256_file(snapshot)
        if actual_digest != expected_digest:
            raise RuntimeError("journalled snapshot SHA-256 does not match its receipt")
        return snapshot, actual_digest, snapshot.stat().st_size
    return None


def apply(
    paths: OpsPaths,
    journal: Journal,
    detection: Detection,
    *,
    actor: str,
) -> Marker:
    """Snapshot, change ownership, and write the pre-start witness."""

    if detection.kind != "applies" or detection.deployment_id is None:
        raise RuntimeError(f"migration {MIGRATION_ID} does not apply: {detection.reason}")
    paths.snapshots.mkdir(parents=True, exist_ok=True)
    completed_snapshot = _completed_snapshot(paths, journal, detection.deployment_id)
    if completed_snapshot is None:
        started = time.monotonic()
        snapshot = paths.snapshots / _snapshot_name(detection.deployment_id)
        _snapshot_volume(paths.object_store, snapshot)
        snapshot_digest = sha256_file(snapshot)
        snapshot_size = snapshot.stat().st_size
        journal.append(
            JournalEntry(
                timestamp=utc_now(),
                migration_id=MIGRATION_ID,
                component=COMPONENT,
                phase="snapshot",
                state="applied",
                actor=actor,
                tool_version=TOOL_VERSION,
                deployment_id=detection.deployment_id,
                layout=detection.layout,
                receipt={
                    "snapshot_path": str(snapshot),
                    "snapshot_bytes": snapshot_size,
                    "snapshot_sha256": snapshot_digest,
                    "duration_seconds": round(time.monotonic() - started, 3),
                },
            )
        )
    else:
        snapshot, snapshot_digest, snapshot_size = completed_snapshot

    ownership_started = time.monotonic()
    uid = int(os.environ.get("LQ_AI_OBJECTSTORE_UID", "10001"))
    gid = int(os.environ.get("LQ_AI_OBJECTSTORE_GID", "10001"))
    _chown_tree(paths.object_store, uid, gid)
    marker = Marker(
        migration_id=MIGRATION_ID,
        component=COMPONENT,
        deployment_id=detection.deployment_id,
        state="applied",
        snapshot_path=str(snapshot),
        snapshot_sha256=snapshot_digest,
        updated_at=utc_now(),
    )
    journal.write_marker(marker)
    journal.append(
        JournalEntry(
            timestamp=utc_now(),
            migration_id=MIGRATION_ID,
            component=COMPONENT,
            phase="apply",
            state="applied",
            actor=actor,
            tool_version=TOOL_VERSION,
            deployment_id=detection.deployment_id,
            layout=detection.layout,
            receipt={
                "snapshot_path": str(snapshot),
                "snapshot_bytes": snapshot_size,
                "snapshot_sha256": snapshot_digest,
                "target_uid": uid,
                "target_gid": gid,
                "object_count_before": detection.facts.get("object_count"),
                "volume_bytes_before": detection.facts.get("volume_bytes"),
                "duration_seconds": round(time.monotonic() - ownership_started, 3),
            },
        )
    )
    return marker


async def _read_expected_objects() -> tuple[dict[str, str], set[str]]:
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            file_rows = await connection.execute(
                text("SELECT storage_path, hash_sha256 FROM files")
            )
            export_rows = await connection.execute(
                text(
                    "SELECT storage_key FROM user_export_jobs "
                    "WHERE storage_key IS NOT NULL "
                    "AND (expires_at IS NULL OR expires_at > now())"
                )
            )
            files = {str(row.storage_path): str(row.hash_sha256) for row in file_rows}
            exports = {str(row.storage_key) for row in export_rows}
            return files, exports
    finally:
        await engine.dispose()


def _s3_credentials() -> tuple[str | None, str | None]:
    access = (
        os.environ.get("S3_ACCESS_KEY")
        or os.environ.get("OBJECT_STORE_ACCESS_KEY")
        or os.environ.get("MINIO_ROOT_USER")
    )
    secret = (
        os.environ.get("S3_SECRET_KEY")
        or os.environ.get("OBJECT_STORE_SECRET_KEY")
        or os.environ.get("MINIO_ROOT_PASSWORD")
    )
    return access, secret


def _readiness_check(endpoint: str) -> Check:
    url = f"{endpoint.rstrip('/')}/health/ready"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            passed = response.status == 200
            return Check("rustfs-ready", passed, f"GET {url} returned {response.status}")
    except (OSError, urllib.error.URLError) as exc:
        return Check("rustfs-ready", False, f"GET {url} failed: {exc}")


async def _list_objects(client: Any, bucket: str) -> dict[str, int]:
    objects: dict[str, int] = {}
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket}
        if token:
            kwargs["ContinuationToken"] = token
        response = await client.list_objects_v2(**kwargs)
        for item in response.get("Contents", []):
            objects[str(item["Key"])] = int(item.get("Size", 0))
        if not response.get("IsTruncated"):
            return objects
        token = response.get("NextContinuationToken")
        if not token:
            raise RuntimeError("S3 listing was truncated without a continuation token")


async def _object_sha256(client: Any, bucket: str, key: str) -> str:
    response = await client.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    digest = hashlib.sha256()
    try:
        while True:
            chunk = await body.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        body.close()
    return digest.hexdigest()


async def verify(
    paths: OpsPaths,
    journal: Journal,
    detection: Detection,
    *,
    actor: str,
) -> tuple[Marker, tuple[Check, ...]]:
    """Verify readiness, key reconciliation, and every document digest."""

    started = time.monotonic()
    endpoint = _endpoint_url()
    checks: list[Check] = [await asyncio.to_thread(_readiness_check, endpoint)]
    if not checks[0].passed:
        raise RuntimeError(checks[0].message)

    expected_files, expected_exports = await _read_expected_objects()
    expected_keys = set(expected_files) | expected_exports
    access, secret = _s3_credentials()
    session = aioboto3.Session(
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name=os.environ.get("S3_REGION", "us-east-1"),
    )
    bucket = os.environ.get("S3_BUCKET", "lq-ai-files")
    async with session.client(
        "s3",
        endpoint_url=endpoint,
        config=BotocoreConfig(s3={"addressing_style": "path"}),
    ) as client:
        await client.head_bucket(Bucket=bucket)
        actual = await _list_objects(client, bucket)
        actual_keys = set(actual)
        missing = sorted(expected_keys - actual_keys)
        unexpected = sorted(actual_keys - expected_keys)
        keys_match = not missing and not unexpected
        checks.append(
            Check(
                "object-key-reconciliation",
                keys_match,
                f"expected {len(expected_keys)}, found {len(actual_keys)}; "
                f"missing={missing[:10]}, unexpected={unexpected[:10]}",
            )
        )
        mismatches: list[str] = []
        if keys_match:
            for key, expected_digest in sorted(expected_files.items()):
                actual_digest = await _object_sha256(client, bucket, key)
                if actual_digest.lower() != expected_digest.lower():
                    mismatches.append(key)
        checks.append(
            Check(
                "document-digests",
                not mismatches,
                f"verified {len(expected_files)} document digests; mismatches={mismatches[:10]}",
            )
        )

    failed = [check.message for check in checks if not check.passed]
    if failed:
        raise RuntimeError("; ".join(failed))

    post_detection = inspect_object_store(paths.object_store)
    deployment_id = post_detection.deployment_id or detection.deployment_id
    if post_detection.layout != "rustfs" or deployment_id is None:
        raise RuntimeError("RustFS format witness was not found after the store became ready")
    prior_marker = journal.read_marker(deployment_id)
    if (
        prior_marker is None
        and detection.deployment_id
        and detection.deployment_id != deployment_id
    ):
        prior_marker = journal.read_marker(detection.deployment_id)
    marker = Marker(
        migration_id=MIGRATION_ID,
        component=COMPONENT,
        deployment_id=deployment_id,
        state="verified",
        snapshot_path=prior_marker.snapshot_path if prior_marker else None,
        snapshot_sha256=prior_marker.snapshot_sha256 if prior_marker else None,
        updated_at=utc_now(),
    )
    journal.write_marker(marker)
    journal.append(
        JournalEntry(
            timestamp=utc_now(),
            migration_id=MIGRATION_ID,
            component=COMPONENT,
            phase="verify",
            state="verified",
            actor=actor,
            tool_version=TOOL_VERSION,
            deployment_id=deployment_id,
            layout="rustfs",
            receipt={
                "snapshot_path": marker.snapshot_path,
                "snapshot_sha256": marker.snapshot_sha256,
                "object_count": len(actual_keys),
                "object_bytes": sum(actual.values()),
                "document_digests_verified": len(expected_files),
                "digest_comparison": "matched",
                "duration_seconds": round(time.monotonic() - started, 3),
            },
        )
    )
    return marker, tuple(checks)


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    root = destination.resolve()
    for member in archive.getmembers():
        target = (destination / member.name).resolve()
        if target != root and root not in target.parents:
            raise RuntimeError(f"snapshot contains an unsafe path: {member.name}")
    archive.extractall(destination, filter="data")


def rollback(paths: OpsPaths, journal: Journal, *, actor: str) -> Path:
    entries = journal.entries()
    candidates = [
        entry
        for entry in entries
        if entry.migration_id == MIGRATION_ID
        and entry.phase == "snapshot"
        and entry.state == "applied"
        and entry.receipt.get("snapshot_path")
    ]
    if not candidates:
        raise RuntimeError("no snapshot receipt exists for migration 0001")
    latest = candidates[-1]
    snapshot = Path(str(latest.receipt["snapshot_path"])).resolve()
    snapshots_root = paths.snapshots.resolve()
    if snapshot != snapshots_root and snapshots_root not in snapshot.parents:
        raise RuntimeError("snapshot receipt points outside the configured snapshot directory")
    if not snapshot.is_file():
        raise RuntimeError(f"snapshot is missing: {snapshot}")
    expected_digest = latest.receipt.get("snapshot_sha256")
    if expected_digest and sha256_file(snapshot) != expected_digest:
        raise RuntimeError("snapshot SHA-256 does not match its journal receipt")
    stopped, message = _store_is_stopped(_endpoint_url())
    if not stopped:
        raise RuntimeError(message)

    paths.object_store.mkdir(parents=True, exist_ok=True)
    for child in paths.object_store.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    with tarfile.open(snapshot, "r") as archive:
        _safe_extract(archive, paths.object_store)

    if latest.deployment_id:
        journal.remove_marker(latest.deployment_id)
    restored = inspect_object_store(paths.object_store)
    if restored.kind != "applies":
        raise RuntimeError(f"restored snapshot is not a supported MinIO volume: {restored.reason}")
    journal.append(
        JournalEntry(
            timestamp=utc_now(),
            migration_id=MIGRATION_ID,
            component=COMPONENT,
            phase="rollback",
            state="rolled_back",
            actor=actor,
            tool_version=TOOL_VERSION,
            deployment_id=latest.deployment_id,
            layout=restored.layout,
            receipt={"snapshot_path": str(snapshot), "snapshot_sha256": sha256_file(snapshot)},
        )
    )
    return snapshot
