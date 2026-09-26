"""Tests for the admin alias-CRUD surface (D0.5).

Uses a per-test-copy of ``gateway.yaml.example`` so writes never
touch the repo's source-controlled file. The fixture builds a fresh
FastAPI app whose state is wired to a temp config + holder, bypassing
the module-level ``app.main:app`` to keep test isolation clean.
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.api import admin_router
from app.config_holder import MutableConfigHolder
from app.config_loader import load_config
from app.errors import LQAIError

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = REPO_ROOT / "gateway.yaml.example"


@pytest.fixture
def tmp_gateway_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Copy gateway.yaml.example into a tmp dir for safe mutation."""

    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AZURE_OPENAI_RESOURCE", "test-openai")
    monkeypatch.setenv("LQ_AI_VERSION", "0.1.0-test")
    target = tmp_path / "gateway.yaml"
    shutil.copy(EXAMPLE_CONFIG, target)
    return target


@pytest_asyncio.fixture
async def admin_app(tmp_gateway_config: Path) -> AsyncIterator[FastAPI]:
    """Build a minimal FastAPI app wired to a temp-config holder.

    Avoids the module-level ``app.main:app`` so tests don't share
    state and don't need to drive the full lifespan (which depends on
    Postgres / Redis / etc.). The admin router is the only piece
    under test here.
    """

    config = load_config(tmp_gateway_config)
    holder = MutableConfigHolder(config, config_path=tmp_gateway_config)

    app = FastAPI()
    app.state.config = config
    app.state.config_holder = holder
    app.include_router(admin_router)

    @app.exception_handler(LQAIError)
    async def _handler(_request, exc: LQAIError) -> JSONResponse:
        return JSONResponse(status_code=exc.effective_http_status, content=exc.to_envelope())

    yield app


@pytest_asyncio.fixture
async def admin_client(admin_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-LQ-AI-Gateway-Key": "test-gateway-key"},
    ) as http:
        yield http


# ---------------------------------------------------------------------------
# GET endpoints
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_get_config_returns_sanitized_payload(admin_client: AsyncClient) -> None:
    res = await admin_client.get("/admin/v1/config")
    assert res.status_code == 200
    body = res.json()
    assert "providers" in body
    assert "model_aliases" in body
    # Every provider has a `name` and `type` per the GatewayConfig schema.
    for provider in body["providers"]:
        assert "name" in provider
        assert "type" in provider


@pytest.mark.unit
async def test_list_aliases_returns_configured_set(admin_client: AsyncClient) -> None:
    res = await admin_client.get("/admin/v1/aliases")
    assert res.status_code == 200
    body = res.json()
    assert body["object"] == "list"
    names = {entry["name"] for entry in body["data"]}
    # gateway.yaml.example ships with these aliases.
    assert {"smart", "fast", "budget", "embedding"}.issubset(names)


@pytest.mark.unit
async def test_get_alias_includes_primary_inference_tier(
    admin_client: AsyncClient,
) -> None:
    res = await admin_client.get("/admin/v1/aliases/smart")
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "smart"
    assert body["provider"] == "anthropic-prod"
    assert body["model"] == "claude-opus-4-7"
    assert body["primary_inference_tier"] == 4  # default for anthropic


@pytest.mark.unit
async def test_get_alias_404(admin_client: AsyncClient) -> None:
    res = await admin_client.get("/admin/v1/aliases/does-not-exist")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_create_alias_persists_and_reloads(
    admin_client: AsyncClient, tmp_gateway_config: Path
) -> None:
    res = await admin_client.post(
        "/admin/v1/aliases",
        json={
            "name": "my-test-alias",
            "provider": "anthropic-prod",
            "model": "claude-opus-4-7",
            "fallback": [],
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "my-test-alias"

    # File reflects the new alias.
    on_disk = yaml.safe_load(tmp_gateway_config.read_text(encoding="utf-8"))
    assert "my-test-alias" in on_disk["model_aliases"]

    # And the live config does too.
    list_res = await admin_client.get("/admin/v1/aliases")
    names = {entry["name"] for entry in list_res.json()["data"]}
    assert "my-test-alias" in names


@pytest.mark.unit
async def test_create_alias_409_on_duplicate(admin_client: AsyncClient) -> None:
    res = await admin_client.post(
        "/admin/v1/aliases",
        json={
            "name": "smart",  # already exists in example
            "provider": "anthropic-prod",
            "model": "claude-opus-4-7",
        },
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "conflict"


@pytest.mark.unit
async def test_create_alias_422_on_unknown_provider(admin_client: AsyncClient) -> None:
    res = await admin_client.post(
        "/admin/v1/aliases",
        json={
            "name": "ghost-alias",
            "provider": "ghost-provider",
            "model": "claude-opus-4-7",
        },
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_request"


@pytest.mark.unit
async def test_create_alias_422_on_empty_model(admin_client: AsyncClient) -> None:
    res = await admin_client.post(
        "/admin/v1/aliases",
        json={"name": "x", "provider": "anthropic-prod", "model": ""},
    )
    # Pydantic-422 (the FastAPI body-level validator) catches min_length=1
    # before our custom validator runs.
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_update_alias_changes_primary(
    admin_client: AsyncClient, tmp_gateway_config: Path
) -> None:
    res = await admin_client.patch(
        "/admin/v1/aliases/fast",
        json={
            "provider": "anthropic-prod",
            "model": "claude-haiku-4-5",
            "fallback": [],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["model"] == "claude-haiku-4-5"

    # File reflects the change.
    on_disk = yaml.safe_load(tmp_gateway_config.read_text(encoding="utf-8"))
    assert on_disk["model_aliases"]["fast"]["primary"]["model"] == "claude-haiku-4-5"


@pytest.mark.unit
async def test_update_alias_404(admin_client: AsyncClient) -> None:
    res = await admin_client.patch(
        "/admin/v1/aliases/does-not-exist",
        json={"provider": "anthropic-prod", "model": "claude-opus-4-7"},
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


@pytest.mark.unit
async def test_update_with_fallback_chain(
    admin_client: AsyncClient, tmp_gateway_config: Path
) -> None:
    res = await admin_client.patch(
        "/admin/v1/aliases/budget",
        json={
            "provider": "anthropic-prod",
            "model": "claude-haiku-4-5",
            "fallback": [{"provider": "openai-prod", "model": "gpt-4o-mini"}],
        },
    )
    assert res.status_code == 200
    on_disk = yaml.safe_load(tmp_gateway_config.read_text(encoding="utf-8"))
    fallback = on_disk["model_aliases"]["budget"]["fallback"]
    assert fallback == [{"provider": "openai-prod", "model": "gpt-4o-mini"}]


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_delete_alias_removes(admin_client: AsyncClient, tmp_gateway_config: Path) -> None:
    # Create then delete.
    await admin_client.post(
        "/admin/v1/aliases",
        json={"name": "throwaway", "provider": "anthropic-prod", "model": "claude-haiku-4-5"},
    )
    res = await admin_client.delete("/admin/v1/aliases/throwaway")
    assert res.status_code == 204

    list_res = await admin_client.get("/admin/v1/aliases")
    names = {entry["name"] for entry in list_res.json()["data"]}
    assert "throwaway" not in names


@pytest.mark.unit
async def test_delete_404(admin_client: AsyncClient) -> None:
    res = await admin_client.delete("/admin/v1/aliases/does-not-exist")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Atomic-write integrity
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_atomic_write_no_temp_files_on_success(
    admin_client: AsyncClient, tmp_gateway_config: Path
) -> None:
    """After a successful write, no orphaned ``.tmp`` files remain."""

    await admin_client.post(
        "/admin/v1/aliases",
        json={"name": "tmp-test", "provider": "anthropic-prod", "model": "claude-opus-4-7"},
    )
    siblings = list(tmp_gateway_config.parent.iterdir())
    assert all(not str(p).endswith(".tmp") for p in siblings)


# ---------------------------------------------------------------------------
# Auth gate (gateway-key)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_admin_endpoint_requires_gateway_key_when_configured(
    admin_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When LQ_AI_GATEWAY_KEY is set, the X-LQ-AI-Gateway-Key header must match."""

    monkeypatch.setenv("LQ_AI_GATEWAY_KEY", "expected-key-value")
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        # No header
        no_header = await http.get("/admin/v1/aliases")
        assert no_header.status_code == 401

        # Wrong header
        wrong = await http.get(
            "/admin/v1/aliases",
            headers={"X-LQ-AI-Gateway-Key": "nope"},
        )
        assert wrong.status_code == 401

        # Right header
        ok = await http.get(
            "/admin/v1/aliases",
            headers={"X-LQ-AI-Gateway-Key": "expected-key-value"},
        )
        assert ok.status_code == 200
