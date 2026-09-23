"""Orchestration service for the deployment-migration chain."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.ops.migrations import ordered_migrations
from app.ops.models import JournalEntry, MigrationState, Plan
from app.ops.state import Journal, OpsPaths, inspect_object_store, reconcile, utc_now


class MigrationService:
    def __init__(self, paths: OpsPaths, *, actor: str) -> None:
        self.paths = paths
        self.actor = actor
        self.journal = Journal(paths.ops)
        (self.migration,) = ordered_migrations()

    async def plan(self, *, record_baseline: bool = True) -> Plan:
        detection = self.migration.detect(self.paths)
        entries = self.journal.entries()
        marker = self.journal.read_marker(detection.deployment_id)
        plan = reconcile(detection, marker, entries)
        if record_baseline and not any(
            entry.migration_id == self.migration.id
            and entry.deployment_id == detection.deployment_id
            for entry in entries
        ):
            state: MigrationState
            if plan.action in {"apply", "verify"}:
                state = "pending"
            elif plan.action == "conflict":
                state = "failed"
            else:
                state = "not_applicable"
            self.journal.append(
                JournalEntry(
                    timestamp=utc_now(),
                    migration_id=self.migration.id,
                    component=self.migration.component,
                    phase="baseline",
                    state=state,
                    actor=self.actor,
                    tool_version="0.8.0",
                    deployment_id=detection.deployment_id,
                    layout=detection.layout,
                    receipt={"reason": detection.reason, **detection.facts},
                )
            )
        if plan.action == "apply":
            checks = await self.migration.preflight(self.paths, detection)
            plan = replace(plan, checks=checks)
        return plan

    async def apply(self) -> dict[str, Any]:
        plan = await self.plan()
        if plan.action == "conflict":
            raise RuntimeError(plan.reason)
        if plan.action == "none":
            return {"status": "nothing_pending", "plan": plan.to_dict()}
        if plan.action == "verify":
            return {"status": "already_applied", "plan": plan.to_dict()}
        if not plan.preflight_passed:
            failed = [check.message for check in plan.checks if not check.passed]
            raise RuntimeError("preflight failed: " + "; ".join(failed))
        marker = self.migration.apply(self.paths, self.journal, plan.detection, actor=self.actor)
        return {"status": "applied", "marker": marker.to_dict(), "plan": plan.to_dict()}

    async def verify(self) -> dict[str, Any]:
        detection = inspect_object_store(self.paths.object_store)
        marker, checks = await self.migration.verify(
            self.paths, self.journal, detection, actor=self.actor
        )
        return {
            "status": "verified",
            "marker": marker.to_dict(),
            "checks": [check.to_dict() for check in checks],
        }

    def rollback(self) -> dict[str, Any]:
        snapshot = self.migration.rollback(self.paths, self.journal, actor=self.actor)
        return {
            "status": "rolled_back",
            "snapshot_path": str(snapshot),
            "instruction": (
                "Check out the previous release and start it with the cached MinIO image."
            ),
        }

    def status(self) -> dict[str, Any]:
        snapshots = []
        if self.paths.snapshots.exists():
            snapshots = [
                {"path": str(path), "bytes": path.stat().st_size}
                for path in sorted(self.paths.snapshots.glob("*.tar"), reverse=True)
            ]
        return {
            "entries": [entry.to_dict() for entry in reversed(self.journal.entries())],
            "snapshots": snapshots,
        }
