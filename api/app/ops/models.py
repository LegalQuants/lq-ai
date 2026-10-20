"""Stable data shapes used by deployment migrations and their CLI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

DetectionKind = Literal["applies", "not_applicable", "conflict"]
MigrationState = Literal[
    "baseline",
    "pending",
    "applied",
    "verified",
    "rolled_back",
    "not_applicable",
    "failed",
]


@dataclass(slots=True, frozen=True)
class Check:
    """One named preflight or verification check."""

    name: str
    passed: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class Detection:
    """What a migration found by inspecting its component's own state."""

    kind: DetectionKind
    reason: str
    deployment_id: str | None = None
    layout: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class JournalEntry:
    """One append-only event in ``journal.jsonl``."""

    timestamp: str
    migration_id: str
    component: str
    phase: str
    state: MigrationState
    actor: str
    tool_version: str
    deployment_id: str | None = None
    layout: str | None = None
    receipt: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    supersedes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class Marker:
    """Small pre-start witness stored next to the journal."""

    migration_id: str
    component: str
    deployment_id: str
    state: Literal["applied", "verified"]
    snapshot_path: str | None
    snapshot_sha256: str | None
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class Plan:
    """Reconciled action for one migration."""

    migration_id: str
    title: str
    action: Literal["none", "apply", "verify", "conflict"]
    reason: str
    detection: Detection
    checks: tuple[Check, ...] = ()

    @property
    def preflight_passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "migration_id": self.migration_id,
            "title": self.title,
            "action": self.action,
            "reason": self.reason,
            "detection": self.detection.to_dict(),
            "checks": [check.to_dict() for check in self.checks],
            "preflight_passed": self.preflight_passed,
        }
