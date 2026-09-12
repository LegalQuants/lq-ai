import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def command(
    directory: Path,
    backend: str,
    action: str,
    fault: str = "none",
    expected: int = 0,
) -> dict[str, object]:
    # No LangSmith export even if the invoking shell has tracing configured.
    env = {
        **os.environ,
        "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
    }
    process = subprocess.run(
        [
            sys.executable,
            *(["-S"] if backend == "native" else []),
            str(ROOT / "demo.py"),
            backend,
            action,
            str(directory),
            "--fault",
            fault,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert process.returncode == expected, process.stdout + process.stderr
    return dict(json.loads(process.stdout)) if process.stdout else {}


def counts(directory: Path) -> dict[str, int]:
    path = directory / "provider.sqlite"
    if not path.exists():
        return {}
    with sqlite3.connect(path) as db:
        return dict(
            db.execute("SELECT topic_id, count(*) FROM calls GROUP BY topic_id")
        )


@pytest.mark.parametrize("backend", ["native", "langgraph"])
def test_approval_survives_real_process_restart(tmp_path: Path, backend: str) -> None:
    assert command(tmp_path, backend, "prepare")["status"] == "awaiting_approval"
    assert command(tmp_path, backend, "run")["status"] == "awaiting_approval"
    assert counts(tmp_path) == {}
    command(tmp_path, backend, "approve")
    assert command(tmp_path, backend, "run")["status"] == "complete"
    command(tmp_path, backend, "approve")
    command(tmp_path, backend, "run")
    assert counts(tmp_path) == {"topic-a": 1, "topic-b": 1}


@pytest.mark.parametrize("backend", ["native", "langgraph"])
@pytest.mark.parametrize("replacement", ["native", "langgraph"])
def test_receipt_survives_hard_crash_and_backend_replacement(
    tmp_path: Path, backend: str, replacement: str
) -> None:
    command(tmp_path, backend, "prepare")
    command(tmp_path, backend, "approve")
    command(tmp_path, backend, "run", "after-receipt", expected=73)
    assert counts(tmp_path) == {"topic-a": 1}
    # Explicit cutover after the old process is dead. Never concurrent coordinators.
    assert command(tmp_path, replacement, "run")["status"] == "complete"
    assert counts(tmp_path) == {"topic-a": 1, "topic-b": 1}


@pytest.mark.parametrize("backend", ["native", "langgraph"])
def test_unknown_external_outcome_is_not_blindly_retried(
    tmp_path: Path, backend: str
) -> None:
    command(tmp_path, backend, "prepare")
    command(tmp_path, backend, "approve")
    command(tmp_path, backend, "run", "after-effect", expected=74)
    result = command(tmp_path, backend, "run")
    assert result["status"] == "needs_attention"
    assert result["outcomes"][0]["status"] == "uncertain"
    command(tmp_path, backend, "run")
    assert counts(tmp_path) == {"topic-a": 1, "topic-b": 1}
