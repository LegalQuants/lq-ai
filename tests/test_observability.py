"""Cross-subsystem no-telemetry-by-default contract test (M3-F3).

Per PRD §5.7, both ``api/`` and ``gateway/`` guarantee that OTel export
is **off by default** — it activates only when the operator sets one of
three well-known OTLP env vars.  This file pins that contract across
both sides so a future change to either observability module surfaces
here before landing in production.

What's verified:

1. ``_otel_enabled(env={})`` is ``False`` — no env vars, no telemetry.
2. Each of the three trigger vars individually enables telemetry.
3. Setting a trigger var to an empty string does **not** enable telemetry
   (empty string ≠ set).

The module-loading technique mirrors :mod:`test_error_code_contract`
exactly: clear ``app`` / ``app.*`` from ``sys.modules``, insert the
target subsystem dir at position 0, then use ``importlib.import_module``.
Module-scoped fixtures load each side once per test session.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
API_DIR = REPO_ROOT / "api"
GATEWAY_DIR = REPO_ROOT / "gateway"

# The three OTLP env vars that trigger OTel (per both observability modules).
TRIGGER_VARS: list[str] = [
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
]


def _load_subsystem_observability(subsystem_dir: Path) -> ModuleType:
    """Load ``<subsystem>/app/observability.py`` as a fresh module instance.

    Follows the identical technique used by ``_load_subsystem_errors`` in
    :mod:`test_error_code_contract`: evict any cached ``app`` / ``app.*``
    module from :data:`sys.modules` before loading so the two subsystems'
    ``observability`` modules do not clobber each other on the shared
    package name ``app``.
    """

    # Evict cached app namespace — ensures next import binds against
    # subsystem_dir/app/ rather than a previously-cached copy.
    for mod_name in list(sys.modules):
        if mod_name == "app" or mod_name.startswith("app."):
            del sys.modules[mod_name]

    # Put the subsystem dir at the front so its app/ wins.
    str_dir = str(subsystem_dir)
    sys.path.insert(0, str_dir)
    try:
        module = importlib.import_module("app.observability")
        return module
    finally:
        # Leave sys.path mutated — consistent with test_error_code_contract.
        # The next load will insert at position 0 and the right module wins.
        pass


@pytest.fixture(scope="module")
def api_obs() -> ModuleType:
    """Load ``api/app/observability.py``."""
    return _load_subsystem_observability(API_DIR)


@pytest.fixture(scope="module")
def gateway_obs() -> ModuleType:
    """Load ``gateway/app/observability.py``.

    Runs after ``api_obs`` (which left ``app`` cached against api/).
    The load helper evicts the cache before binding against gateway/.
    """
    return _load_subsystem_observability(GATEWAY_DIR)


# ---------------------------------------------------------------------------
# 1. No telemetry by default
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_telemetry_by_default_api(api_obs: ModuleType) -> None:
    """api/_otel_enabled returns False when env is empty."""
    assert api_obs._otel_enabled(env={}) is False


@pytest.mark.unit
def test_no_telemetry_by_default_gateway(gateway_obs: ModuleType) -> None:
    """gateway/_otel_enabled returns False when env is empty."""
    assert gateway_obs._otel_enabled(env={}) is False


# ---------------------------------------------------------------------------
# 2. Each trigger var enables telemetry (parametrized)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("var", TRIGGER_VARS)
def test_otlp_endpoint_enables_api(api_obs: ModuleType, var: str) -> None:
    """api/_otel_enabled returns True when any trigger var is set."""
    assert api_obs._otel_enabled(env={var: "http://collector:4318"}) is True


@pytest.mark.unit
@pytest.mark.parametrize("var", TRIGGER_VARS)
def test_otlp_endpoint_enables_gateway(gateway_obs: ModuleType, var: str) -> None:
    """gateway/_otel_enabled returns True when any trigger var is set."""
    assert gateway_obs._otel_enabled(env={var: "http://collector:4318"}) is True


# ---------------------------------------------------------------------------
# 3. Empty string does not count as "set"
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_empty_endpoint_value_stays_disabled_api(api_obs: ModuleType) -> None:
    """api/_otel_enabled treats an empty-string value as unset."""
    assert api_obs._otel_enabled(env={"OTEL_EXPORTER_OTLP_ENDPOINT": ""}) is False


@pytest.mark.unit
def test_empty_endpoint_value_stays_disabled_gateway(gateway_obs: ModuleType) -> None:
    """gateway/_otel_enabled treats an empty-string value as unset."""
    assert gateway_obs._otel_enabled(env={"OTEL_EXPORTER_OTLP_ENDPOINT": ""}) is False
