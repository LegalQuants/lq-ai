"""Complete-run reports and strict floors for observable injection proxies."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .injection_lib import (
    REPO_ROOT,
    Attack,
    Observation,
    add_observation,
    base_fixture_path,
    base_snapshot_path,
    empty_counts,
    rates_from_counts,
)

METRIC = "task_preservation_proxy_rate"


def _threshold(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a numeric threshold")
    if not 0 <= value <= 1 or not math.isfinite(value):
        raise ValueError(f"{name} must be finite and within [0, 1]")
    return float(value)


def load_floor(path: Path, expected_cells: set[str]) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"nonstandard JSON constant: {value}")

    floor = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(floor, dict):
        raise ValueError("floor must be an object")
    allowed = {"schema_version", "metric", "default", "cells", "max_structural_failure_rate"}
    if set(floor) - allowed:
        raise ValueError("unknown floor fields")
    if type(floor.get("schema_version")) is not int or floor["schema_version"] != 2:
        raise ValueError("floor schema_version must be 2; recalibrate legacy resistance floors")
    if floor.get("metric") != METRIC:
        raise ValueError(f"floor metric must be {METRIC}")
    default = _threshold(floor.get("default"), "default")
    maximum = _threshold(floor.get("max_structural_failure_rate"), "max_structural_failure_rate")
    cells = floor.get("cells", {})
    if not isinstance(cells, dict) or set(cells) - expected_cells:
        raise ValueError("floor cells must be a mapping of known skill/category keys")
    return {
        **floor,
        "default": default,
        "max_structural_failure_rate": maximum,
        "cells": {key: _threshold(value, key) for key, value in cells.items()},
    }


def provenance(attacks: list[Attack]) -> dict[str, Any]:
    """Hash the checked-in inputs; never serialize environment values or keys."""
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        sha = None
    paths = set((REPO_ROOT / "tests/injection").glob("*.py"))
    paths.update((REPO_ROOT / "tests/golden").glob("*.py"))
    paths.update((REPO_ROOT / "tests/injection/corpus").glob("*.json"))
    for attack in attacks:
        paths.update(
            {
                base_fixture_path(attack.target_skill),
                base_snapshot_path(attack.target_skill),
                REPO_ROOT / "skills" / attack.target_skill / "SKILL.md",
            }
        )
    for relative in ("gateway.yaml.example", "tests/eval-requirements.txt"):
        paths.add(REPO_ROOT / relative)
    hashes = {
        str(path.relative_to(REPO_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
        if path.is_file()
    }
    return {
        "repository_sha": sha,
        "workflow_sha": os.environ.get("GITHUB_SHA"),
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
        "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "input_sha256": hashes,
        "note": "gateway.yaml.example is the seed config, not a hash of runtime overrides",
    }


class RunLedger:
    def __init__(self, attacks: list[Attack], metadata: dict[str, Any]) -> None:
        self.expected = {attack.id: attack for attack in attacks}
        self.metadata = metadata
        self.attempted: set[str] = set()
        self.failed: set[str] = set()
        self.skipped: set[str] = set()
        self.results: dict[str, dict[str, Any]] = {}

    def record(
        self,
        attack: Attack,
        observation: Observation,
        model: str | None,
        provider: str | None,
    ) -> None:
        if attack.id not in self.expected or attack != self.expected[attack.id]:
            raise ValueError("unexpected attack")
        if attack.id in self.results:
            raise ValueError("duplicate attack result")
        if not isinstance(model, str) or not model or not isinstance(provider, str) or not provider:
            raise ValueError("routed model and provider are required for comparable measurements")
        self.results[attack.id] = {
            "attack": attack,
            "observation": observation,
            "model": model,
            "provider": provider,
        }

    def summary(self, exit_status: int, floor_path: Path) -> dict[str, Any]:
        grouped: dict[tuple[str, str, str, str], dict[str, int]] = defaultdict(empty_counts)
        overall = empty_counts()
        for result in self.results.values():
            attack, observation = result["attack"], result["observation"]
            key = (attack.target_skill, attack.category, result["model"], result["provider"])
            add_observation(grouped[key], observation)
            add_observation(overall, observation)
        cells = [
            {
                "skill": key[0],
                "category": key[1],
                "routed_model": key[2],
                "routed_provider": key[3],
                "counts": counts,
                "rates": rates_from_counts(counts),
            }
            for key, counts in sorted(grouped.items())
        ]
        expected = set(self.expected)
        complete = (
            bool(expected)
            and set(self.results) == expected
            and self.attempted == expected
            and not self.failed
            and not self.skipped
        )
        floor_status = "not_configured"
        violations: list[str] = []
        floor_hash = None
        if floor_path.exists():
            try:
                floor_hash = hashlib.sha256(floor_path.read_bytes()).hexdigest()
                floor = load_floor(
                    floor_path,
                    {f"{a.target_skill}/{a.category}" for a in self.expected.values()},
                )
            except (ValueError, TypeError, OSError) as exc:
                floor_status = "invalid"
                violations.append(str(exc))
            else:
                floor_status = "not_evaluated"
                if complete and exit_status == 0:
                    for cell in cells:
                        key = f"{cell['skill']}/{cell['category']}"
                        label = f"{key} ({cell['routed_provider']}/{cell['routed_model']})"
                        minimum = floor["cells"].get(key, floor["default"])
                        if cell["rates"][METRIC] < minimum:
                            violations.append(f"{label}: {METRIC} below {minimum}")
                        maximum = floor["max_structural_failure_rate"]
                        if cell["rates"]["structural_failure_rate"] > maximum:
                            violations.append(f"{label}: structural failure rate above {maximum}")
                    floor_status = "failed" if violations else "passed"
        publishable = complete and exit_status == 0 and floor_status in {"not_configured", "passed"}
        return {
            "schema_version": 2,
            "generated_at": datetime.now(UTC).isoformat(),
            "provenance": self.metadata,
            "run": {
                "expected": len(expected),
                "attempted": len(self.attempted),
                "completed": len(self.results),
                "failed": len(self.failed),
                "skipped": len(self.skipped),
                "complete": complete,
                "pytest_exit_status": exit_status,
                "publishable": publishable,
                "missing_attack_ids": sorted(expected - set(self.results)),
                "failed_attack_ids": sorted(self.failed),
                "skipped_attack_ids": sorted(self.skipped),
            },
            "floor": {"status": floor_status, "sha256": floor_hash, "violations": violations},
            "overall": {"counts": overall, "rates": rates_from_counts(overall)},
            "cells": cells,
        }
