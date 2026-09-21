"""Fail-closed object-store init gate used before RustFS starts."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app.ops.state import Journal, OpsPaths, inspect_object_store


def _chown_tree(root: Path, uid: int, gid: int) -> None:
    os.chown(root, uid, gid)
    for current, dirs, files in os.walk(root):
        for name in dirs:
            os.chown(Path(current) / name, uid, gid)
        for name in files:
            os.chown(Path(current) / name, uid, gid)


def run_gate(paths: OpsPaths) -> str:
    """Validate migration state, then make the volume writable by uid 10001."""

    paths.object_store.mkdir(parents=True, exist_ok=True)
    detection = inspect_object_store(paths.object_store)
    unattended = os.environ.get("LQ_AI_OPS_UNATTENDED") == "1"
    if detection.kind == "conflict":
        raise RuntimeError(f"object-store init refused: {detection.reason}")
    if detection.kind == "applies":
        marker = Journal(paths.ops).read_marker(detection.deployment_id)
        if marker is None and not unattended:
            raise RuntimeError(
                "existing MinIO volume detected — run "
                "`docker compose --profile ops run --rm migrate plan` first"
            )
        if marker is None:
            message = "WARNING: LQ_AI_OPS_UNATTENDED=1 bypassed the migration marker check"
        else:
            snapshot = Path(marker.snapshot_path).resolve() if marker.snapshot_path else None
            snapshots_root = paths.snapshots.resolve()
            if (
                snapshot is None
                or snapshot == snapshots_root
                or snapshots_root not in snapshot.parents
                or not snapshot.is_file()
            ):
                raise RuntimeError(
                    "object-store init refused: the migration marker's snapshot is missing"
                )
            message = f"migration marker {marker.state} accepted for {marker.deployment_id}"
    else:
        message = detection.reason
    uid = int(os.environ.get("LQ_AI_OBJECTSTORE_UID", "10001"))
    gid = int(os.environ.get("LQ_AI_OBJECTSTORE_GID", "10001"))
    _chown_tree(paths.object_store, uid, gid)
    return f"{message}; object-store ownership set to {uid}:{gid}"


def main() -> None:
    try:
        print(run_gate(OpsPaths.from_environment()))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
