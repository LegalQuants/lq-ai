"""Pytest wiring for the prompt-injection harness (DE-239).

Two layers, mirroring DE-231's golden harness:

* Keyless structural tests (``test_injection_inventory.py``) — validate
  the attack corpus format, canary uniqueness, composer determinism and
  the deterministic scorer. Always run; no stack, no keys, no network.
* Live tests (``test_injection_rates.py``, marker ``injection_live``) —
  seed each attack into a DE-231 fixture, send it through a running
  compose stack, and score the output. Skipped unless LQ_INJECTION_LIVE=1
  plus a provider key plus api credentials are present (see live.py).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from .injection_lib import Attack, empty_counts, rates_from_counts
from .live import DEFAULT_REPORT_DIR, injection_skip_reason, make_client

FLOOR_PATH = Path(__file__).resolve().parent / "detection-floor.json"


def write_attack_report(
    report_dir: Path,
    attack: Attack,
    *,
    outcome: str,
    routed_model: str | None,
    routed_provider: str | None,
    content: str,
) -> Path:
    """Write one per-attack JSON report; returns the path.

    Includes the raw assistant output so a maintainer can audit any
    ``followed`` classification (and confirm the deterministic scorer).
    """

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "attack_id": attack.id,
        "category": attack.category,
        "taxonomy": list(attack.taxonomy),
        "target_skill": attack.target_skill,
        "placement": attack.placement,
        "canary": attack.canary,
        "outcome": outcome,
        "routed_model": routed_model,
        "routed_provider": routed_provider,
        "response_content": content,
    }
    path = report_dir / f"{attack.target_skill}--{attack.id}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def pytest_configure(config: pytest.Config) -> None:
    # Registered here as well as in tests/pyproject.toml so the marker is
    # known even when this package is collected in isolation.
    config.addinivalue_line(
        "markers",
        "injection_live: prompt-injection tests needing a live compose stack + "
        "provider key (skipped unless LQ_INJECTION_LIVE=1; see "
        "docs/quality/prompt-injection-rates.md)",
    )


@pytest.fixture(scope="session")
def injection_client() -> Iterator[Any]:
    """A logged-in live client, or a clean skip when live mode is off."""

    reason = injection_skip_reason()
    if reason is not None:
        pytest.skip(f"injection_live: {reason}")
    client = make_client()
    client.login()
    yield client
    client.close()


@pytest.fixture(scope="session")
def report_dir() -> Path:
    path = Path(os.environ.get("LQ_INJECTION_REPORT_DIR", DEFAULT_REPORT_DIR))
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="session")
def rate_collector(report_dir: Path) -> Iterator[dict[str, dict[str, dict[str, int]]]]:
    """Session-wide outcome tallies, written to a summary + optionally gated.

    Keyed ``[skill][category] -> outcome-count dict``. At session end a
    machine-readable ``summary.json`` is written (per-cell and overall
    rates). If ``detection-floor.json`` exists, resistance rates are
    gated against it (ratcheted floor); with no floor file committed yet
    the gate is inert and the run only *measures* — the honest first-run
    state documented in docs/quality/prompt-injection-rates.md.
    """

    tally: dict[str, dict[str, dict[str, int]]] = {}
    yield tally

    cells: list[dict[str, Any]] = []
    overall = empty_counts()
    for skill in sorted(tally):
        for category in sorted(tally[skill]):
            counts = tally[skill][category]
            for outcome, n in counts.items():
                overall[outcome] = overall.get(outcome, 0) + n
            cells.append(
                {
                    "skill": skill,
                    "category": category,
                    "counts": counts,
                    "rates": rates_from_counts(counts),
                }
            )

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "overall": {"counts": overall, "rates": rates_from_counts(overall)},
        "cells": cells,
        "floor_applied": FLOOR_PATH.exists(),
    }
    (report_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    if FLOOR_PATH.exists():
        _apply_floor(cells)


def _apply_floor(cells: list[dict[str, Any]]) -> None:
    """Ratcheted-floor gate: each cell's resistance_rate must meet the floor.

    Floor file shape:
        {"default": 0.9, "cells": {"nda-review/role-play-hijack": 0.75, ...}}
    """

    floor = json.loads(FLOOR_PATH.read_text(encoding="utf-8"))
    default = float(floor.get("default", 0.0))
    per_cell = floor.get("cells", {})
    violations: list[str] = []
    for cell in cells:
        key = f"{cell['skill']}/{cell['category']}"
        threshold = float(per_cell.get(key, default))
        observed = float(cell["rates"]["resistance_rate"])
        if observed < threshold:
            violations.append(f"{key}: resistance {observed:.3f} < floor {threshold:.3f}")
    if violations:
        raise AssertionError(
            "injection resistance fell below the ratcheted floor:\n  " + "\n  ".join(violations)
        )
