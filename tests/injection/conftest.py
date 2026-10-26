"""Pytest integration: opted-in live runs always get a complete/invalid report."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from .injection_lib import Attack, Observation, load_corpus
from .live import DEFAULT_REPORT_DIR, injection_skip_reason, make_client
from .reporting import RunLedger, provenance

FLOOR_PATH = Path(__file__).resolve().parent / "detection-floor.json"
LEDGER = pytest.StashKey[RunLedger]()


def write_attack_report(
    report_dir: Path,
    attack: Attack,
    *,
    observation: Observation,
    routed_model: str | None,
    routed_provider: str | None,
    content: str,
) -> Path:
    """Synthetic outputs only; no credentials or raw transport errors."""
    payload = {
        "schema_version": 2,
        "generated_at": datetime.now(UTC).isoformat(),
        "attack_id": attack.id,
        "category": attack.category,
        "taxonomy": list(attack.taxonomy),
        "target_skill": attack.target_skill,
        "placement": attack.placement,
        "canary": attack.canary,
        "outcome": observation.outcome,
        "canary_present": observation.canary_present,
        "injection_mentioned": observation.injection_mentioned,
        "task_preservation_proxy": observation.task_preserved,
        "structural_result": observation.structure.to_dict(),
        "routed_model": routed_model,
        "routed_provider": routed_provider,
        "response_content": content,
    }
    path = report_dir / f"{attack.target_skill}--{attack.id}.json"
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return path


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "injection_live: opt-in live injection measurement")
    if os.environ.get("LQ_INJECTION_LIVE") == "1":
        attacks = load_corpus()
        config.stash[LEDGER] = RunLedger(attacks, provenance(attacks))


@pytest.fixture(scope="session")
def injection_client() -> Iterator[Any]:
    reason = injection_skip_reason()
    if reason is not None:
        pytest.skip(f"injection_live: {reason}")
    client = make_client()
    try:
        client.login()
        yield client
    finally:
        client.close()


@pytest.fixture(scope="session")
def injection_report_dir() -> Path:
    path = Path(os.environ.get("LQ_INJECTION_REPORT_DIR", DEFAULT_REPORT_DIR))
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="session")
def injection_run(pytestconfig: pytest.Config) -> RunLedger:
    return pytestconfig.stash[LEDGER]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]) -> Iterator[Any]:
    result = yield
    report = result.get_result()
    ledger = item.config.stash.get(LEDGER, None)
    callspec = getattr(item, "callspec", None)
    attack = callspec.params.get("attack") if callspec is not None else None
    if ledger is None or "injection_live" not in item.keywords or not isinstance(attack, Attack):
        return
    if report.when == "setup":
        ledger.attempted.add(attack.id)
    if report.failed:
        ledger.failed.add(attack.id)
    if report.skipped:
        ledger.skipped.add(attack.id)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    ledger = session.config.stash.get(LEDGER, None)
    if ledger is None:
        return
    summary = ledger.summary(int(exitstatus), FLOOR_PATH)
    if not summary["run"]["publishable"] and session.exitstatus == 0:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
    summary["run"]["pytest_exit_status"] = int(session.exitstatus)
    path = Path(os.environ.get("LQ_INJECTION_REPORT_DIR", DEFAULT_REPORT_DIR))
    path.mkdir(parents=True, exist_ok=True)
    (path / "summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    if not summary["run"]["publishable"]:
        reporter = session.config.pluginmanager.getplugin("terminalreporter")
        if reporter is not None:
            reporter.write_sep("=", "Injection measurement INVALID — do not publish these rates")
            for violation in summary["floor"]["violations"]:
                reporter.write_line(violation)
