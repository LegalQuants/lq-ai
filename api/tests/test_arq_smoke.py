"""M3-A6 Phase 1 — "ARQ is wired up" gate.

Verifies that :mod:`app.workers.arq_setup` exposes a well-formed
``WorkerSettings`` class the arq CLI can discover, and that the
registered ``noop_job`` returns the expected value when invoked.

The live "compose up + enqueue + observe execution" path is the
operator's responsibility (and the compose healthcheck on the
``arq-worker`` service). These tests are unit-scope, matching the
pattern in :mod:`tests.test_workers_queue` (the existing ingest-side
arq tests).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.workers import arq_setup
from app.workers.arq_setup import M3A6_QUEUE_NAME, WorkerSettings, noop_job


@pytest.mark.unit
def test_queue_name_is_disjoint_from_arq_default() -> None:
    """The M3-A6 queue must NOT be arq's default ``arq:queue``.

    A shared queue would let ingest-worker and arq-worker both consume
    each other's jobs and reject what they can't route. The whole
    point of running a sister worker is queue isolation.
    """

    assert M3A6_QUEUE_NAME == "arq:m3a6"
    assert M3A6_QUEUE_NAME != "arq:queue"


@pytest.mark.unit
def test_worker_settings_class_shape() -> None:
    """arq's CLI reads class attributes directly. Verify the contract."""

    assert WorkerSettings.queue_name == M3A6_QUEUE_NAME
    assert callable(WorkerSettings.on_startup)
    assert callable(WorkerSettings.on_shutdown)
    assert noop_job in WorkerSettings.functions
    # ``_populate_class_attrs`` ran at import; the redis_settings attr
    # should be present (arq is installed in the test env).
    assert hasattr(WorkerSettings, "redis_settings")


@pytest.mark.unit
async def test_noop_job_returns_ok() -> None:
    """Direct invocation: the registered job is a coroutine that returns ``"ok"``."""

    result = await noop_job({})  # ``ctx`` is whatever arq passes; unused.
    assert result == "ok"


@pytest.mark.unit
async def test_on_startup_installs_skill_registry_and_returns_none() -> None:
    """Startup hook installs the skill registry (Donna ask #9), then logs.

    skill_ref autonomous sessions resolve through
    ``app.state.skill_registry`` in whichever process runs them; the
    worker must install it exactly like the API lifespan does. The full
    resolution path is covered by
    ``tests/autonomous/test_worker_skill_registry.py``; this unit test
    pins the wiring (hook calls the shared bootstrap; returns None).
    """

    from app.skills.registry import MutableSkillRegistry, SkillRegistry

    holder = MutableSkillRegistry(SkillRegistry(records={}))
    with patch(
        "app.skills.bootstrap.install_skill_registry",
        return_value=holder,
    ) as mock_install:
        # No exception, no return value.
        assert await arq_setup.on_startup({}) is None

    mock_install.assert_called_once()


@pytest.mark.unit
async def test_on_startup_propagates_registry_failure() -> None:
    """Fail-loudly contract: a registry bootstrap failure must propagate
    so the worker process exits at startup (crash-looping container)
    instead of dying at the first scheduled tick."""

    with (
        patch(
            "app.skills.bootstrap.install_skill_registry",
            side_effect=FileNotFoundError("skills directory does not exist"),
        ),
        pytest.raises(FileNotFoundError),
    ):
        await arq_setup.on_startup({})


@pytest.mark.unit
async def test_on_shutdown_disposes_db_engine() -> None:
    """Shutdown hook calls ``dispose_engine``; failures are swallowed."""

    with patch(
        "app.workers.arq_setup.dispose_engine",
        AsyncMock(),
    ) as mock_dispose:
        await arq_setup.on_shutdown({})
        mock_dispose.assert_awaited_once()


@pytest.mark.unit
async def test_on_shutdown_swallows_dispose_failure() -> None:
    """Shutdown best-effort: a dispose_engine failure must not propagate."""

    with patch(
        "app.workers.arq_setup.dispose_engine",
        AsyncMock(side_effect=RuntimeError("engine already disposed")),
    ):
        # No exception leaks.
        await arq_setup.on_shutdown({})


@pytest.mark.unit
def test_build_redis_settings_reads_redis_url() -> None:
    """RedisSettings derives from ``Settings.redis_url`` via ``from_dsn``."""

    fake_settings = type("S", (), {"redis_url": "redis://localhost:6379/0"})()
    fake_redis_settings: Any = object()

    class _FakeRS:
        @staticmethod
        def from_dsn(url: str) -> Any:
            assert url == fake_settings.redis_url
            return fake_redis_settings

    with (
        patch("app.workers.arq_setup.get_settings", return_value=fake_settings),
        patch.dict(
            "sys.modules",
            {"arq.connections": type("M", (), {"RedisSettings": _FakeRS})()},
        ),
    ):
        result = arq_setup._build_redis_settings()

    assert result is fake_redis_settings
