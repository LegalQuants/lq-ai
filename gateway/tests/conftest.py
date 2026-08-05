"""Pytest fixtures shared across the gateway test suite.

Two fixtures matter:

* :func:`example_env` (autouse=False) — sets the env vars referenced by
  ``gateway.yaml.example`` so :func:`app.config_loader.load_config` succeeds
  in tests. Tests that need it import it explicitly.
* :func:`gateway_config_loaded_app` — yields a FastAPI ``app`` whose
  lifespan has run against the example config, so endpoints depending on
  ``app.state.config`` work. We do this by setting ``GATEWAY_CONFIG_PATH``
  to point at the committed example file and then using FastAPI's lifespan
  entry/exit explicitly via :class:`LifespanManager`.

We intentionally don't autouse the env-var fixture: the ``test_health`` and
``test_main_no_config`` paths cover behaviors that must work *without* it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = REPO_ROOT / "gateway.yaml.example"


@pytest.fixture
def example_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Satisfy the ``${VAR}`` placeholders in ``gateway.yaml.example``."""

    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AZURE_OPENAI_RESOURCE", "test-openai")
    monkeypatch.setenv("LQ_AI_VERSION", "0.1.0-test")
    monkeypatch.setenv("LOCAL_INFERENCE_ENABLED", "true")
    monkeypatch.setenv("VLLM_ENABLED", "false")
    monkeypatch.setenv("BUDGET_ALERT_EMAIL", "admin@example.com")
    monkeypatch.setenv("OTEL_ENABLED", "false")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318")
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse:3000")
    monkeypatch.setenv("LQ_AI_DEV_MODE", "false")


@asynccontextmanager
async def _run_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Drive a FastAPI app's lifespan (startup → ``yield`` → shutdown).

    FastAPI's lifespan is an async context manager attached at app
    construction time; entering it runs startup hooks, exiting runs
    shutdown hooks. We expose that here so tests can run real startup.
    """

    async with app.router.lifespan_context(app):
        yield


@pytest_asyncio.fixture
async def gateway_app(monkeypatch: pytest.MonkeyPatch, example_env: None) -> AsyncIterator[FastAPI]:
    """Yield the gateway ``app`` with its lifespan started against the example.

    Importing ``app.main`` is module-scoped on first use (FastAPI is
    idempotent), but we ensure ``GATEWAY_CONFIG_PATH`` is set *before* the
    lifespan runs by setting it inside the fixture.
    """

    monkeypatch.setenv("GATEWAY_CONFIG_PATH", str(EXAMPLE_CONFIG))

    # Import lazily so the env var is set first.
    from app.main import app

    async with _run_lifespan(app):
        yield app


@pytest_asyncio.fixture
async def client(gateway_app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An ``httpx.AsyncClient`` wired to the lifespan-started gateway app."""

    transport = ASGITransport(app=gateway_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
