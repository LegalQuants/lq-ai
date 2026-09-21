"""State inspection, durable journal writes, and reconciliation.

The component on disk is authoritative.  Journal entries and markers say what
the tool did, never where the component *must* be.  This distinction is the
central invariant in ADR 0037.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.ops.models import Detection, JournalEntry, Marker, Plan

MIGRATION_ID = "0001"
MIGRATION_TITLE = "Object store: MinIO to RustFS"
COMPONENT = "objectstore"
TOOL_VERSION = "0.8.0"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_deployment_id(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for char in value
    ):
        return None
    return value


def _read_format_file(system_dir: Path) -> tuple[dict[str, Any] | None, Path | None]:
    """Read a store format file without assuming an implementation sub-layout."""

    candidates = [system_dir / "format.json"]
    if system_dir.is_dir():
        candidates.extend(sorted(system_dir.glob("**/format.json")))
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen or not candidate.is_file():
            continue
        seen.add(candidate)
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value, candidate
    return None, None


def _volume_metrics(root: Path) -> tuple[int, int]:
    """Return an offline object estimate and bytes needed for a full snapshot."""

    total_bytes = 0
    xl_meta_count = 0
    plain_files = 0
    for current, _dirs, files in os.walk(root):
        relative = Path(current).relative_to(root)
        is_system = bool(relative.parts) and relative.parts[0] in {
            ".minio.sys",
            ".rustfs.sys",
        }
        for name in files:
            path = Path(current) / name
            try:
                total_bytes += path.stat().st_size
            except OSError:
                continue
            if is_system:
                continue
            if name == "xl.meta":
                xl_meta_count += 1
            else:
                plain_files += 1
    return (xl_meta_count if xl_meta_count else plain_files), total_bytes


def inspect_object_store(root: Path) -> Detection:
    """Detect the object-store layout from the mounted volume only."""

    if not root.exists():
        return Detection("not_applicable", "object-store volume is not mounted")
    rustfs_format, rustfs_path = _read_format_file(root / ".rustfs.sys")
    minio_format, minio_path = _read_format_file(root / ".minio.sys")

    if rustfs_format is not None:
        deployment_id = _safe_deployment_id(rustfs_format.get("id"))
        if deployment_id is None and minio_format is not None:
            deployment_id = _safe_deployment_id(minio_format.get("id"))
        if deployment_id is None:
            return Detection(
                "conflict",
                "RustFS format exists but has no safe deployment id",
                layout="rustfs",
                facts={"format_path": str(rustfs_path)},
            )
        count, size = _volume_metrics(root)
        return Detection(
            "not_applicable",
            "object-store volume is already RustFS",
            deployment_id=deployment_id,
            layout="rustfs",
            facts={"format_path": str(rustfs_path), "object_count": count, "volume_bytes": size},
        )

    if minio_format is not None:
        layout = minio_format.get("format")
        deployment_id = _safe_deployment_id(minio_format.get("id"))
        if layout not in {"xl", "xl-single"}:
            return Detection(
                "conflict",
                f"unsupported MinIO layout: {layout!r}",
                deployment_id=deployment_id,
                layout=str(layout) if layout is not None else None,
                facts={"format_path": str(minio_path)},
            )
        if deployment_id is None:
            return Detection(
                "conflict",
                "MinIO format exists but has no safe deployment id",
                layout=str(layout),
                facts={"format_path": str(minio_path)},
            )
        count, size = _volume_metrics(root)
        return Detection(
            "applies",
            "supported MinIO volume detected",
            deployment_id=deployment_id,
            layout=str(layout),
            facts={"format_path": str(minio_path), "object_count": count, "volume_bytes": size},
        )

    try:
        has_content = any(root.iterdir())
    except OSError as exc:
        return Detection("conflict", f"cannot inspect object-store volume: {exc}")
    if has_content:
        return Detection("conflict", "unrecognised non-empty object-store volume")
    return Detection("not_applicable", "empty object-store volume")


class Journal:
    """Append-only JSONL journal plus atomically replaced marker files."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "journal.jsonl"
        self.markers_dir = root / "markers" / COMPONENT

    def entries(self) -> list[JournalEntry]:
        if not self.path.exists():
            return []
        entries: list[JournalEntry] = []
        with self.path.open(encoding="utf-8") as handle:
            for line_number, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue
                try:
                    value = json.loads(raw)
                    entries.append(JournalEntry(**value))
                except (json.JSONDecodeError, TypeError) as exc:
                    raise RuntimeError(
                        f"invalid deployment-migration journal entry at line {line_number}: {exc}"
                    ) from exc
        return entries

    def append(self, entry: JournalEntry) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(entry.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
        descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, payload.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def marker_path(self, deployment_id: str) -> Path:
        safe_id = _safe_deployment_id(deployment_id)
        if safe_id is None:
            raise ValueError("unsafe deployment id")
        return self.markers_dir / f"{safe_id}.json"

    def read_marker(self, deployment_id: str | None) -> Marker | None:
        if deployment_id is None:
            return None
        path = self.marker_path(deployment_id)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            marker = Marker(**value)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise RuntimeError(f"invalid migration marker {path}: {exc}") from exc
        if marker.deployment_id != deployment_id or marker.migration_id != MIGRATION_ID:
            raise RuntimeError(f"migration marker identity mismatch: {path}")
        if marker.state not in {"applied", "verified"}:
            raise RuntimeError(f"migration marker has an invalid state: {path}")
        return marker

    def write_marker(self, marker: Marker) -> None:
        self.markers_dir.mkdir(parents=True, exist_ok=True)
        path = self.marker_path(marker.deployment_id)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(marker.to_dict(), sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        os.chmod(temporary, 0o600)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        temporary.replace(path)

    def remove_marker(self, deployment_id: str) -> None:
        self.marker_path(deployment_id).unlink(missing_ok=True)


def latest_entry(entries: list[JournalEntry], deployment_id: str | None) -> JournalEntry | None:
    matching = [
        entry
        for entry in entries
        if entry.migration_id == MIGRATION_ID
        and (deployment_id is None or entry.deployment_id == deployment_id)
    ]
    return matching[-1] if matching else None


def reconcile(
    detection: Detection,
    marker: Marker | None,
    entries: list[JournalEntry],
) -> Plan:
    """Reconcile component state with its witnesses without trusting either blindly."""

    current = latest_entry(entries, detection.deployment_id)
    if detection.kind == "conflict":
        return Plan(MIGRATION_ID, MIGRATION_TITLE, "conflict", detection.reason, detection)

    if detection.layout is None:
        return Plan(MIGRATION_ID, MIGRATION_TITLE, "none", detection.reason, detection)

    if detection.layout in {"xl", "xl-single"}:
        if (
            marker is not None
            and marker.state == "applied"
            and current is not None
            and current.state == "applied"
        ):
            return Plan(
                MIGRATION_ID,
                MIGRATION_TITLE,
                "verify",
                "snapshot and ownership change are applied; start RustFS, then verify",
                detection,
            )
        if marker is None and current is not None and current.state == "verified":
            return Plan(
                MIGRATION_ID,
                MIGRATION_TITLE,
                "conflict",
                "the volume is MinIO but the journal records it as verified; the volume may have been restored",
                detection,
            )
        return Plan(
            MIGRATION_ID,
            MIGRATION_TITLE,
            "apply",
            "MinIO volume requires a snapshot and ownership migration",
            detection,
        )

    if detection.layout == "rustfs":
        if (
            marker is not None
            and marker.state == "verified"
            and current is not None
            and current.state == "verified"
        ):
            return Plan(MIGRATION_ID, MIGRATION_TITLE, "none", "migration is verified", detection)
        return Plan(
            MIGRATION_ID,
            MIGRATION_TITLE,
            "verify",
            "RustFS state needs verification and adoption into the journal",
            detection,
        )

    return Plan(MIGRATION_ID, MIGRATION_TITLE, "conflict", "unrecognised state", detection)


@dataclass(slots=True, frozen=True)
class OpsPaths:
    object_store: Path
    ops: Path
    snapshots: Path

    @classmethod
    def from_environment(cls) -> OpsPaths:
        ops = Path(os.environ.get("LQ_AI_OPS_DIR", "/lq-ai/ops")).resolve()
        snapshots = Path(os.environ.get("LQ_AI_SNAPSHOT_DIR", str(ops / "snapshots"))).resolve()
        object_store = Path(
            os.environ.get("LQ_AI_OBJECTSTORE_DIR", "/lq-ai/volumes/objectstore")
        ).resolve()
        if object_store == Path("/") or ops == Path("/") or snapshots == Path("/"):
            raise RuntimeError("deployment-migration paths may not be the filesystem root")
        return cls(object_store=object_store, ops=ops, snapshots=snapshots)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
