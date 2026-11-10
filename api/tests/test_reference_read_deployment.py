"""The operator's reference-read switch must reach both deployed processes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from app.config import Settings

ROOT = Path(__file__).resolve().parents[2]
SWITCH = "LQ_AI_SKILL_REFERENCE_READ_ENABLED"
RECIPES = ("docker-compose.yml", "docker-compose.release.yml")
pytestmark = pytest.mark.unit


@pytest.mark.parametrize("recipe", RECIPES)
@pytest.mark.parametrize("service", ("api", "arq-worker"))
def test_reference_read_switch_is_forwarded(recipe: str, service: str) -> None:
    config = yaml.safe_load((ROOT / recipe).read_text())
    assert config["services"][service]["environment"].get(SWITCH) == (
        "${LQ_AI_SKILL_REFERENCE_READ_ENABLED:-true}"
    )


@pytest.mark.parametrize("recipe", RECIPES)
@pytest.mark.parametrize("value", [None, "true", "false"])
def test_rendered_deployment_preserves_reference_read_policy(
    recipe: str, value: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose CLI unavailable; static forwarding checks still run")
    probe = subprocess.run([docker, "compose", "version"], capture_output=True, check=False)
    if probe.returncode:
        pytest.skip("Docker Compose CLI unavailable; static forwarding checks still run")
    env_file = tmp_path / "deployment.env"
    entries = [
        "POSTGRES_PASSWORD=disposable-password",
        "JWT_SECRET=disposable-jwt-secret",
        "LQ_AI_GATEWAY_KEY=disposable-gateway-key",
        "OBJECT_STORE_SECRET_KEY=disposable-storage-key",
    ]
    if value is not None:
        entries.append(f"{SWITCH}={value}")
    env_file.write_text("\n".join(entries) + "\n")
    result = subprocess.run(
        [
            docker,
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(ROOT / recipe),
            "config",
            "--format",
            "json",
        ],
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        check=True,
    )
    services = json.loads(result.stdout)["services"]
    monkeypatch.delenv("SKILL_REFERENCE_READ_ENABLED", raising=False)
    for service in ("api", "arq-worker"):
        forwarded = services[service]["environment"][SWITCH]
        monkeypatch.setenv(SWITCH, forwarded)
        assert Settings(_env_file=None).skill_reference_read_enabled is (value != "false")  # type: ignore[call-arg]
