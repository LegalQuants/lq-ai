"""Deployment forwarding for #593's operator tool-egress ceiling.

Compose configuration checks do not start services or need a Docker daemon.
The static wiring regression runs even where the Compose CLI is unavailable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
CEILING_ENV = "LQ_AI_TOOL_MAX_EGRESS_TIER"
RECIPES = ("docker-compose.yml", "docker-compose.release.yml")
SERVICES = ("api", "arq-worker")
pytestmark = pytest.mark.unit


@pytest.mark.parametrize("alias", [CEILING_ENV, "TOOL_MAX_EGRESS_TIER"])
def test_setting_blank_means_unset(monkeypatch: pytest.MonkeyPatch, alias: str) -> None:
    monkeypatch.delenv(CEILING_ENV, raising=False)
    monkeypatch.delenv("TOOL_MAX_EGRESS_TIER", raising=False)
    monkeypatch.setenv(alias, "")
    assert Settings(_env_file=None).tool_max_egress_tier is None  # type: ignore[call-arg]


@pytest.mark.parametrize("recipe", RECIPES)
@pytest.mark.parametrize("service", SERVICES)
def test_compose_forwards_operator_ceiling(recipe: str, service: str) -> None:
    config = yaml.safe_load((REPO_ROOT / recipe).read_text())
    assert config["services"][service]["environment"].get(CEILING_ENV) == (
        "${LQ_AI_TOOL_MAX_EGRESS_TIER:-}"
    ), f"{recipe}: {service} must forward the optional operator ceiling"


@pytest.fixture(scope="module")
def compose_cli() -> str:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose CLI is unavailable; static forwarding check still runs")
    probe = subprocess.run([docker, "compose", "version"], capture_output=True, check=False)
    if probe.returncode:
        pytest.skip("Docker Compose CLI is unavailable; static forwarding check still runs")
    return docker


@pytest.fixture(scope="module", params=RECIPES)
def recipe(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture(scope="module", params=[None, "", "1", "5", "0", "6", "invalid"])
def rendered_environment(
    request: pytest.FixtureRequest,
    recipe: str,
    compose_cli: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[str | None, dict[str, dict[str, str]]]:
    """Use a clean interpolation environment and dummy deployment secrets."""
    value: str | None = request.param
    scratch = tmp_path_factory.mktemp("tool-egress-compose")
    env_file = scratch / "deployment.env"
    entries = [
        "POSTGRES_PASSWORD=disposable-test-password",
        "JWT_SECRET=disposable-test-jwt-secret",
        "LQ_AI_GATEWAY_KEY=disposable-test-gateway-key",
        "OBJECT_STORE_SECRET_KEY=disposable-test-object-store-key",
    ]
    if value is not None:
        entries.append(f"{CEILING_ENV}={value}")
    env_file.write_text("\n".join(entries) + "\n")
    clean_env = {"PATH": os.environ.get("PATH", ""), "HOME": str(Path.home())}
    result = subprocess.run(
        [
            compose_cli,
            "compose",
            "--project-name",
            "tool-egress-config-test",
            "--env-file",
            str(env_file),
            "-f",
            str(REPO_ROOT / recipe),
            "config",
            "--format",
            "json",
        ],
        env=clean_env,
        capture_output=True,
        text=True,
        check=True,
    )
    services = json.loads(result.stdout)["services"]
    return value, {name: services[name]["environment"] for name in SERVICES}


@pytest.mark.parametrize("service", SERVICES)
def test_compose_ceiling_reaches_settings(
    rendered_environment: tuple[str | None, dict[str, dict[str, str]]],
    service: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, environments = rendered_environment
    forwarded = environments[service][CEILING_ENV]
    assert forwarded == (value or "")
    assert environments["api"][CEILING_ENV] == environments["arq-worker"][CEILING_ENV]
    monkeypatch.delenv("TOOL_MAX_EGRESS_TIER", raising=False)
    monkeypatch.setenv(CEILING_ENV, forwarded)
    if value in ("0", "6", "invalid"):
        with pytest.raises(ValidationError, match=CEILING_ENV):
            Settings(_env_file=None)  # type: ignore[call-arg]
    else:
        assert Settings(_env_file=None).tool_max_egress_tier == (  # type: ignore[call-arg]
            int(value) if value else None
        )
