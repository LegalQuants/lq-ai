"""Acceptance tests for runtime tool-provider management (Task 2, Donna #3).

Mirrors ``tests/test_provider_keys.py`` one layer down for
``/admin/v1/tool-providers``. The hard requirements verified here:

* GET always lists all four registered authority types, even when none are
  configured on disk.
* POST enables a (possibly keyless) provider and hot-applies its adapter into
  the live ``app.state.tool_adapters`` registry with no restart.
* POST with an ``api_key`` but no master key set fails 400
  ``failed_precondition`` (never falls through to an unencrypted write).
* POST/PATCH of an unknown ``type`` is 404.
* DELETE removes a configured entry (204, empty body) and retires its live
  adapter; DELETE of an absent entry is 404.
* No response body (GET, POST, or error) ever contains a plaintext key, the
  ``api_key_encrypted`` field name, or a ciphertext fragment.

``build_tool_adapter`` is stubbed (mirroring how ``test_provider_keys.py``
stubs ``app.main.build_adapter``) so these tests never make a real network
call while still exercising the hot-apply swap end-to-end.
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = REPO_ROOT / "gateway.yaml.example"


class _FakeToolAdapter:
    """Minimal stand-in identified by a label; avoids real network egress."""

    def __init__(self, label: str) -> None:
        self.label = label

    async def aclose(self) -> None:  # pragma: no cover - not exercised here
        return None


@asynccontextmanager
async def _run_lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with app.router.lifespan_context(app):
        yield


@pytest_asyncio.fixture
async def writable_config(tmp_path: Path) -> Path:
    """Copy the committed example config to a writable temp path."""

    dest = tmp_path / "gateway.yaml"
    shutil.copyfile(EXAMPLE_CONFIG, dest)
    return dest


def _stub_build_tool_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub ``app.main.build_tool_adapter`` so no real egress validation runs.

    Both the lifespan's own tool-adapter build loop and the hot-apply path in
    ``app.tool_provider_keys.apply_tool_provider`` import ``build_tool_adapter``
    from ``app.main`` at call time, so patching that one attribute covers both.
    """

    def _fake(provider: Any) -> _FakeToolAdapter:
        return _FakeToolAdapter(provider.name)

    monkeypatch.setattr("app.main.build_tool_adapter", _fake)


@pytest_asyncio.fixture
async def keyed_app(
    example_env: None, monkeypatch: pytest.MonkeyPatch, writable_config: Path
) -> AsyncIterator[FastAPI]:
    """Gateway app with a fresh master key + writable temp config."""

    monkeypatch.setenv("GATEWAY_CONFIG_PATH", str(writable_config))
    monkeypatch.setenv("LQ_AI_GATEWAY_MASTER_KEY", Fernet.generate_key().decode())
    _stub_build_tool_adapter(monkeypatch)

    from app.main import app

    async with _run_lifespan(app):
        yield app


@pytest_asyncio.fixture
async def client(keyed_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=keyed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest_asyncio.fixture
async def no_master_key_app(
    example_env: None, monkeypatch: pytest.MonkeyPatch, writable_config: Path
) -> AsyncIterator[FastAPI]:
    """Gateway app WITHOUT a master key — POST/PATCH with an api_key must 400."""

    monkeypatch.setenv("GATEWAY_CONFIG_PATH", str(writable_config))
    monkeypatch.delenv("LQ_AI_GATEWAY_MASTER_KEY", raising=False)
    _stub_build_tool_adapter(monkeypatch)

    from app.main import app

    async with _run_lifespan(app):
        yield app


@pytest_asyncio.fixture
async def no_master_key_client(no_master_key_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=no_master_key_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.mark.unit
async def test_get_lists_four_types(client: AsyncClient) -> None:
    r = await client.get("/admin/v1/tool-providers")
    assert r.status_code == 200, r.text
    types = {row["type"] for row in r.json()["tool_providers"]}
    assert types == {"courtlistener", "govinfo", "edgar", "eurlex"}


@pytest.mark.unit
async def test_post_enable_keyless_hot_applies(client: AsyncClient, keyed_app: FastAPI) -> None:
    r = await client.post("/admin/v1/tool-providers", json={"type": "edgar"})
    assert r.status_code == 200, r.text
    assert r.json()["type"] == "edgar"
    # enabled reflects the live adapter having been built + swapped in.
    g = (await client.get("/admin/v1/tool-providers")).json()["tool_providers"]
    assert next(x for x in g if x["type"] == "edgar")["enabled"] is True
    assert "edgar-prod" in keyed_app.state.tool_adapters


@pytest.mark.unit
async def test_hot_apply_reaches_router_from_zero_boot(
    client: AsyncClient, keyed_app: FastAPI
) -> None:
    """Regression: fresh boot with zero tool providers (the shipped default —
    ``gateway.yaml.example`` ships ``tool_providers:`` commented out) must not
    leave the Router holding a disconnected copy of ``app.state.tool_adapters``.

    ``Router.__init__`` used to do ``tool_adapters or {}``, which — because an
    empty dict is falsy — silently substitutes a brand-new dict literal
    whenever the gateway boots with no tool providers configured. Hot-apply
    (``_swap_in_tool_adapter``) mutates ``app.state.tool_adapters`` in place,
    so with the old code the Router never saw the swap: a fresh install could
    hot-enable a provider (200, ``enabled: true``) that then 404'd on every
    real tool call until restart.
    """

    # Precondition: boots with zero tool providers, so the Router was built
    # with an empty dict — the exact case the ``or {}`` bug mishandled.
    assert keyed_app.state.tool_adapters == {}

    # The fix requires the Router to hold the SAME dict object as app.state,
    # not an equal-but-distinct one, so in-place swaps are visible to both.
    assert keyed_app.state.router._tool_adapters is keyed_app.state.tool_adapters

    r = await client.post("/admin/v1/tool-providers", json={"type": "edgar"})
    assert r.status_code == 200, r.text

    # The live Router's dispatch dict must reflect the hot-applied adapter.
    assert "edgar-prod" in keyed_app.state.router._tool_adapters


@pytest.mark.unit
async def test_post_keyed_without_master_key_is_400(
    no_master_key_client: AsyncClient,
) -> None:
    r = await no_master_key_client.post(
        "/admin/v1/tool-providers", json={"type": "courtlistener", "api_key": "cl-token"}
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "failed_precondition"


@pytest.mark.unit
async def test_post_unknown_type_is_404(client: AsyncClient) -> None:
    r = await client.post("/admin/v1/tool-providers", json={"type": "westlaw"})
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "not_found"


@pytest.mark.unit
async def test_patch_unknown_type_is_404(client: AsyncClient) -> None:
    r = await client.patch("/admin/v1/tool-providers/westlaw", json={"api_key": "x"})
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "not_found"


@pytest.mark.unit
async def test_delete_removes_and_is_204(client: AsyncClient, keyed_app: FastAPI) -> None:
    await client.post("/admin/v1/tool-providers", json={"type": "edgar"})
    assert "edgar-prod" in keyed_app.state.tool_adapters

    r = await client.delete("/admin/v1/tool-providers/edgar")
    assert r.status_code == 204, r.text
    assert r.content == b""
    assert "edgar-prod" not in keyed_app.state.tool_adapters
    assert keyed_app.state.retired_tool_adapters


@pytest.mark.unit
async def test_delete_absent_is_404(client: AsyncClient) -> None:
    r = await client.delete("/admin/v1/tool-providers/eurlex")
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "not_found"


@pytest.mark.unit
async def test_patch_enabled_false_routes_to_delete(
    client: AsyncClient, keyed_app: FastAPI
) -> None:
    """D3: PATCH ``enabled: false`` is the disable path — same as DELETE."""

    await client.post("/admin/v1/tool-providers", json={"type": "govinfo"})
    r = await client.patch("/admin/v1/tool-providers/govinfo", json={"enabled": False})
    assert r.status_code == 204, r.text
    assert "govinfo-prod" not in keyed_app.state.tool_adapters


@pytest.mark.unit
async def test_no_response_ever_contains_ciphertext(client: AsyncClient) -> None:
    r = await client.post(
        "/admin/v1/tool-providers", json={"type": "govinfo", "api_key": "gv-secret"}
    )
    assert r.status_code == 200, r.text
    body = (await client.get("/admin/v1/tool-providers")).text
    for forbidden in ("gv-secret", "api_key_encrypted", "gAAAAAB"):
        assert forbidden not in body


@pytest.mark.unit
async def test_config_endpoint_strips_ciphertext(client: AsyncClient) -> None:
    """D7c: GET /admin/v1/config never echoes api_key_encrypted."""

    await client.post(
        "/admin/v1/tool-providers", json={"type": "govinfo", "api_key": "gv-secret-2"}
    )
    body = (await client.get("/admin/v1/config")).text
    for forbidden in ("gv-secret-2", "api_key_encrypted", "gAAAAAB"):
        assert forbidden not in body
