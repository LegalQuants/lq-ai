"""Validate a completed DE-229 mutation run before publishing a scoped score."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

COUNT_KEYS = (
    "killed",
    "survived",
    "no_tests",
    "skipped",
    "suspicious",
    "timeout",
    "check_was_interrupted_by_user",
    "segfault",
)


def validate_stats(stats: dict[str, Any]) -> None:
    """Reject empty, malformed, interrupted or incomplete measurements."""
    for key in ("total", *COUNT_KEYS):
        value = stats.get(key)
        if type(value) is not int or value < 0:
            raise ValueError(f"{key} must be a non-negative integer")
    if stats["total"] == 0 or stats["total"] == stats["skipped"]:
        raise ValueError("no measured mutants")
    if sum(stats[key] for key in COUNT_KEYS) != stats["total"]:
        raise ValueError("mutant counts do not account for a completed run")
    for key in ("check_was_interrupted_by_user", "segfault", "suspicious"):
        if stats[key]:
            raise ValueError(f"run contains {key} outcomes")


def locked_version(lock_bytes: bytes, name: str = "mutmut") -> str:
    """Return the single version of ``name`` that a uv.lock pins."""
    packages = tomllib.loads(lock_bytes.decode()).get("package", [])
    versions = {entry.get("version") for entry in packages if entry.get("name") == name}
    if len(versions) != 1 or not all(isinstance(v, str) and v for v in versions):
        raise ValueError(f"uv.lock must pin exactly one {name} version")
    return versions.pop()


def build_report(
    *,
    package: str,
    stats_path: Path,
    test_stats_path: Path,
    config_path: Path,
    lock_path: Path,
    commit: str,
    run_url: str,
    run_outcome: str,
    tool_version: str,
    duration_seconds: str,
    origin: str = "local-validation",
) -> dict[str, Any]:
    """Return valid evidence or an unavailable record, never a partial score."""
    report: dict[str, Any] = {
        "schema_version": 1,
        "measurement_origin": origin,
        "status": "unavailable",
        "package": package,
        "commit": commit,
        "run_url": run_url,
        "run_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "tool": "mutmut",
        "tool_version": tool_version,
        "duration_seconds": duration_seconds,
        "mutation_score_percent": None,
        "score_definition": "killed / (total - skipped)",
    }
    try:
        if run_outcome != "success":
            raise ValueError(f"mutation execution did not succeed: {run_outcome}")
        lock_bytes = lock_path.read_bytes()
        # The installed tool must be the one the reviewed lock pins.
        locked = locked_version(lock_bytes)
        if tool_version != locked:
            raise ValueError(f"expected locked mutmut {locked}, found {tool_version}")
        config_bytes = config_path.read_bytes()
        config = tomllib.loads(config_bytes.decode())["tool"]["mutmut"]
        stats = json.loads(stats_path.read_text())
        if not isinstance(stats, dict):
            raise ValueError("mutation stats must be an object")
        # Preserve evidence even when its validation fails.
        report["counts"] = stats
        validate_stats(stats)
        test_stats = json.loads(test_stats_path.read_text())
        if not test_stats.get("duration_by_test"):
            raise ValueError("no test execution recorded")
        report.update(
            status="valid",
            mutation_score_percent=round(
                100 * stats["killed"] / (stats["total"] - stats["skipped"]), 2
            ),
            modules=config["only_mutate"],
            test_selection=config["pytest_add_cli_args_test_selection"],
            pytest_args=config.get("pytest_add_cli_args", []),
            config_sha256=hashlib.sha256(config_bytes).hexdigest(),
            lock_sha256=hashlib.sha256(lock_bytes).hexdigest(),
            tests_recorded=len(test_stats["duration_by_test"]),
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        report["reason"] = str(exc)
    return report


def write_summary(report: dict[str, Any], path: Path) -> None:
    """Append a human-readable status without claiming an unavailable score."""
    with path.open("a") as stream:
        stream.write(f"## Mutation testing — {report['package']}\n\n")
        if report["status"] != "valid":
            stream.write("**Score unavailable:** the run did not yield valid evidence.\n\n")
            stream.write("See the diagnostic artifact for the reason and any raw counts.\n")
            return
        counts = report["counts"]
        stream.write(
            f"**{report['mutation_score_percent']}%** on the configured scope "
            f"({counts['killed']}/{counts['total'] - counts['skipped']} killed).\n\n"
        )
        stream.write(
            f"{counts['survived']} survived; {counts['no_tests']} have no covering tests; "
            f"{counts['timeout']} timed out; {counts['skipped']} skipped.\n\n"
        )
        stream.write(
            f"Measured commit: `{report['commit']}`. "
            "This is a scoped test-quality measure, not whole-product assurance.\n"
        )


def main() -> int:
    """Write a report on both success and failure; invalid evidence exits nonzero."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, choices=("api", "gateway"))
    parser.add_argument("--run-outcome", required=True)
    parser.add_argument("--duration-seconds", default="")
    parser.add_argument("--output", type=Path, default=Path("mutation-score.json"))
    args = parser.parse_args()
    try:
        version = importlib.metadata.version("mutmut")
    except importlib.metadata.PackageNotFoundError:
        version = "unavailable"
    report = build_report(
        package=args.package,
        stats_path=Path("mutants/mutmut-cicd-stats.json"),
        test_stats_path=Path("mutants/mutmut-stats.json"),
        config_path=Path("pyproject.toml"),
        lock_path=Path("uv.lock"),
        commit=os.environ.get("GITHUB_SHA", ""),
        run_url=(
            f"{os.environ.get('GITHUB_SERVER_URL', '')}/"
            f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/"
            f"{os.environ.get('GITHUB_RUN_ID', '')}"
            if os.environ.get("GITHUB_RUN_ID")
            else ""
        ),
        run_outcome=args.run_outcome,
        tool_version=version,
        duration_seconds=args.duration_seconds,
        origin="github-actions"
        if os.environ.get("GITHUB_ACTIONS") == "true"
        else "local-validation",
    )
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        write_summary(report, Path(summary))
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "valid" else 1


if __name__ == "__main__":
    sys.exit(main())
