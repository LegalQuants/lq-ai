"""Pytest wiring for the skill golden harness (DE-231).

Two test layers live in this directory:

* Keyless structural tests (``test_golden_inventory.py``) — validate
  that every starter skill ships well-formed acceptance fixtures and
  snapshots, and that the extraction heuristics behave. Always run;
  no stack, no keys, no network.
* Live golden tests (``test_skill_goldens.py``, marker ``golden_live``)
  — execute each fixture through a running compose stack. Skipped
  unless ``LQ_GOLDEN_LIVE=1`` plus a provider key plus api credentials
  are present (see live_client.live_skip_reason).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from .live_client import GoldenClient, live_config, live_skip_reason

DEFAULT_REPORT_DIR = "golden-report"


@pytest.fixture(scope="session")
def golden_client() -> Iterator[GoldenClient]:
    """A logged-in live client, or a clean skip when live mode is off."""

    reason = live_skip_reason()
    if reason is not None:
        pytest.skip(f"golden_live: {reason}")
    client = GoldenClient(live_config())
    client.login()
    yield client
    client.close()


@pytest.fixture(scope="session")
def report_dir() -> Path:
    """Directory for machine-readable per-fixture reports (gitignored)."""

    path = Path(os.environ.get("LQ_GOLDEN_REPORT_DIR", DEFAULT_REPORT_DIR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_report(report_dir: Path, name: str, payload: dict[str, Any]) -> Path:
    """Write one JSON report; returns the path (used in failure messages)."""

    payload = {"generated_at": datetime.now(UTC).isoformat(), **payload}
    path = report_dir / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path
