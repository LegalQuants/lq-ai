from __future__ import annotations

import importlib
import json
import shutil
from pathlib import Path

import pytest

from app.ops.gate import _validate_environment, run_gate
from app.ops.models import JournalEntry, Marker
from app.ops.state import (
    COMPONENT,
    MIGRATION_ID,
    TOOL_VERSION,
    Journal,
    OpsPaths,
    inspect_object_store,
    reconcile,
    utc_now,
)

migration = importlib.import_module("app.ops.migrations.0001_object_store_minio_to_rustfs")
DEPLOYMENT_ID = "c6125f3e-eb21-4ee3-9b32-538be1237407"
FIXTURES = Path(__file__).parent / "fixtures" / "ops"


def _paths(tmp_path: Path) -> OpsPaths:
    object_store = tmp_path / "objectstore"
    ops = tmp_path / "ops"
    object_store.mkdir()
    ops.mkdir()
    return OpsPaths(object_store, ops, ops / "snapshots")


def _format(root: Path, implementation: str, layout: str = "xl-single") -> None:
    system = root / f".{implementation}.sys"
    system.mkdir()
    (system / "format.json").write_text(
        json.dumps({"version": "1", "format": layout, "id": DEPLOYMENT_ID}),
        encoding="utf-8",
    )


def _entry(state: str) -> JournalEntry:
    return JournalEntry(
        timestamp=utc_now(),
        migration_id=MIGRATION_ID,
        component=COMPONENT,
        phase=state,
        state=state,  # type: ignore[arg-type]
        actor="cli",
        tool_version=TOOL_VERSION,
        deployment_id=DEPLOYMENT_ID,
        layout="xl-single",
    )


def _marker(state: str = "applied", snapshot_path: str = "/snapshot.tar") -> Marker:
    return Marker(
        migration_id=MIGRATION_ID,
        component=COMPONENT,
        deployment_id=DEPLOYMENT_ID,
        state=state,  # type: ignore[arg-type]
        snapshot_path=snapshot_path,
        snapshot_sha256="abc",
        updated_at=utc_now(),
    )


def test_detects_empty_volume_as_not_applicable(tmp_path: Path) -> None:
    detection = inspect_object_store(_paths(tmp_path).object_store)
    assert detection.kind == "not_applicable"
    assert detection.layout is None


def test_s3_credentials_prefer_client_then_generic_store_then_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "OBJECT_STORE_ACCESS_KEY",
        "OBJECT_STORE_SECRET_KEY",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("MINIO_ROOT_USER", "legacy-user")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "legacy-secret")
    assert migration._s3_credentials() == ("legacy-user", "legacy-secret")

    monkeypatch.setenv("OBJECT_STORE_ACCESS_KEY", "generic-user")
    monkeypatch.setenv("OBJECT_STORE_SECRET_KEY", "generic-secret")
    assert migration._s3_credentials() == ("generic-user", "generic-secret")

    monkeypatch.setenv("S3_ACCESS_KEY", "client-user")
    monkeypatch.setenv("S3_SECRET_KEY", "client-secret")
    assert migration._s3_credentials() == ("client-user", "client-secret")


def test_gate_requires_translated_object_store_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OBJECT_STORE_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="legacy MINIO_ROOT_PASSWORD"):
        _validate_environment()

    monkeypatch.setenv("OBJECT_STORE_SECRET_KEY", "translated-secret")
    _validate_environment()


def test_detects_supported_minio_volume_and_metrics(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    shutil.copytree(FIXTURES / "minio-single", paths.object_store, dirs_exist_ok=True)

    detection = inspect_object_store(paths.object_store)

    assert detection.kind == "applies"
    assert detection.layout == "xl-single"
    assert detection.deployment_id == DEPLOYMENT_ID
    assert detection.facts["object_count"] == 1


def test_rejects_unrecognised_nonempty_volume(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (paths.object_store / "mystery").write_text("data", encoding="utf-8")
    assert inspect_object_store(paths.object_store).kind == "conflict"


def test_detects_rustfs_fixture_for_adoption(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    shutil.copytree(FIXTURES / "rustfs", paths.object_store, dirs_exist_ok=True)

    detection = inspect_object_store(paths.object_store)

    assert detection.kind == "not_applicable"
    assert detection.layout == "rustfs"
    assert detection.deployment_id == DEPLOYMENT_ID


def test_reconciliation_table(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _format(paths.object_store, "minio")
    minio = inspect_object_store(paths.object_store)
    assert reconcile(minio, None, []).action == "apply"
    assert reconcile(minio, _marker(), [_entry("applied")]).action == "verify"
    assert reconcile(minio, None, [_entry("verified")]).action == "conflict"

    (paths.object_store / ".minio.sys").rename(paths.object_store / ".rustfs.sys")
    rustfs = inspect_object_store(paths.object_store)
    assert reconcile(rustfs, None, []).action == "verify"
    assert reconcile(rustfs, _marker("verified"), [_entry("verified")]).action == "none"


def test_journal_and_marker_round_trip(tmp_path: Path) -> None:
    journal = Journal(_paths(tmp_path).ops)
    entry = _entry("applied")
    marker = _marker()
    journal.append(entry)
    journal.write_marker(marker)

    assert journal.entries() == [entry]
    assert journal.read_marker(DEPLOYMENT_ID) == marker


def test_gate_refuses_unmigrated_minio_volume(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _format(paths.object_store, "minio")
    with pytest.raises(RuntimeError, match="existing MinIO volume detected"):
        run_gate(paths)


def test_gate_accepts_snapshot_backed_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    _format(paths.object_store, "minio")
    snapshot = paths.snapshots / "snapshot.tar"
    snapshot.parent.mkdir()
    snapshot.write_bytes(b"snapshot")
    Journal(paths.ops).write_marker(_marker(snapshot_path=str(snapshot)))
    monkeypatch.setattr("app.ops.gate._chown_tree", lambda *_args: None)

    assert "marker applied accepted" in run_gate(paths)


def test_gate_refuses_marker_when_snapshot_is_missing(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _format(paths.object_store, "minio")
    Journal(paths.ops).write_marker(_marker())

    with pytest.raises(RuntimeError, match="snapshot is missing"):
        run_gate(paths)


def test_apply_creates_snapshot_receipt_and_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    _format(paths.object_store, "minio")
    (paths.object_store / "lq-ai-files").mkdir()
    (paths.object_store / "lq-ai-files" / "payload").write_bytes(b"contract")
    detection = inspect_object_store(paths.object_store)
    monkeypatch.setattr(migration, "_chown_tree", lambda *_args: None)

    marker = migration.apply(paths, Journal(paths.ops), detection, actor="cli")

    assert marker.state == "applied"
    assert marker.snapshot_path is not None
    assert Path(marker.snapshot_path).is_file()
    assert len(Journal(paths.ops).entries()) == 2


def test_apply_resumes_from_completed_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    _format(paths.object_store, "minio")
    (paths.object_store / "payload").write_bytes(b"before")
    detection = inspect_object_store(paths.object_store)
    monkeypatch.setattr(migration, "_chown_tree", lambda *_args: None)
    journal = Journal(paths.ops)

    first = migration.apply(paths, journal, detection, actor="cli")
    journal.remove_marker(DEPLOYMENT_ID)
    second = migration.apply(paths, journal, detection, actor="cli")

    assert second.snapshot_path == first.snapshot_path
    assert len([entry for entry in journal.entries() if entry.phase == "snapshot"]) == 1


def test_rollback_restores_snapshot_and_clears_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    _format(paths.object_store, "minio")
    payload = paths.object_store / "payload"
    payload.write_bytes(b"before")
    detection = inspect_object_store(paths.object_store)
    monkeypatch.setattr(migration, "_chown_tree", lambda *_args: None)
    migration.apply(paths, Journal(paths.ops), detection, actor="cli")
    payload.write_bytes(b"after")
    monkeypatch.setattr(migration, "_store_is_stopped", lambda _endpoint: (True, "stopped"))

    migration.rollback(paths, Journal(paths.ops), actor="cli")

    assert payload.read_bytes() == b"before"
    assert Journal(paths.ops).read_marker(DEPLOYMENT_ID) is None
