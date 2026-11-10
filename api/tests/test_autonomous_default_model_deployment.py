"""Deployment wiring for #681's autonomous default model.

The Python settings default (``smart``) only helps deployments that forward
``LQ_AI_AUTONOMOUS_DEFAULT_MODEL`` into the containers. These checks do not
start services or need a Docker daemon: the static wiring regression runs
even where the Compose CLI is unavailable, and the rendered check verifies
the default (``smart``) and explicit overrides actually reach both the api
and the arq-worker.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_ENV = "LQ_AI_AUTONOMOUS_DEFAULT_MODEL"
DEFAULT_MODEL = "smart"
RECIPES = ("docker-compose.yml", "docker-compose.release.yml")
SERVICES = ("api", "arq-worker")
pytestmark = pytest.mark.unit


@pytest.mark.parametrize("recipe", RECIPES)
@pytest.mark.parametrize("service", SERVICES)
def test_compose_forwards_autonomous_default_model(recipe: str, service: str) -> None:
    config = yaml.safe_load((REPO_ROOT / recipe).read_text())
    assert config["services"][service]["environment"].get(MODEL_ENV) == (
        f"${{{MODEL_ENV}:-{DEFAULT_MODEL}}}"
    ), f"{recipe}: {service} must forward the autonomous default model"


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


@pytest.fixture(scope="module", params=[None, "fast"])
def rendered_environment(
    request: pytest.FixtureRequest,
    recipe: str,
    compose_cli: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[str | None, dict[str, dict[str, str]]]:
    """Use a clean interpolation environment and dummy deployment secrets."""
    value: str | None = request.param
    scratch = tmp_path_factory.mktemp("autonomous-model-compose")
    env_file = scratch / "deployment.env"
    entries = [
        "POSTGRES_PASSWORD=disposable-test-password",
        "JWT_SECRET=disposable-test-jwt-secret",
        "LQ_AI_GATEWAY_KEY=disposable-test-gateway-key",
        "OBJECT_STORE_SECRET_KEY=disposable-test-object-store-key",
    ]
    if value is not None:
        entries.append(f"{MODEL_ENV}={value}")
    env_file.write_text("\n".join(entries) + "\n")
    clean_env = {"PATH": os.environ.get("PATH", ""), "HOME": str(Path.home())}
    result = subprocess.run(
        [
            compose_cli,
            "compose",
            "--project-name",
            "autonomous-model-config-test",
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
def test_compose_model_reaches_settings(
    rendered_environment: tuple[str | None, dict[str, dict[str, str]]],
    service: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, environments = rendered_environment
    forwarded = environments[service][MODEL_ENV]
    assert forwarded == (value or DEFAULT_MODEL)
    assert environments["api"][MODEL_ENV] == environments["arq-worker"][MODEL_ENV]
    monkeypatch.setenv(MODEL_ENV, forwarded)
    assert Settings(_env_file=None).autonomous_default_model == forwarded  # type: ignore[call-arg]
