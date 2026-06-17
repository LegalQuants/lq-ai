# PR3a — Gateway tool-call HTTP endpoint (WS3 transport) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Expose PR1's internal `Router.route_tool_call` over HTTP so the backend can invoke gateway tool-providers (CourtListener, future MCP) through the audited egress boundary — `POST /v1/tools/{provider}/{tool}`. Gateway-only; the api-side `GatewayClient.call_tool` + the `/api/v1/research` surface are PR3b.

**Architecture:** A new `gateway/app/api/tools.py` router, gated by the same `X-LQ-AI-Gateway-Key` dependency as the admin surface (it triggers credentialed third-party egress + cost — a privileged operation, unlike open inference). The handler pulls the lifespan-built `Router` off `app.state.router` (which already holds the tool adapters + egress writer from PR1), calls `route_tool_call`, and maps `ToolEgressRefused` / `ToolProviderError` subclasses to the `GatewayError` envelope + appropriate HTTP status. The audit row is written inside `route_tool_call` (PR1) — no double-logging here.

**Tech Stack:** FastAPI, Pydantic v2, httpx (test client via ASGITransport), pytest + pytest-asyncio + respx. Gateway mypy `--strict`.

**Branch:** `feat/research-subsystem` (off `main` @ `c7e9318`, which has PR1+PR2). **Security-reviewed** (`gateway/**`) → maintainer reviews + merges; do NOT self-merge.

## ⚠️ Test/lint runner (host venv, NOT docker compose)
- Gateway tests: `cd ~/Code/lq-ai/gateway && .venv/bin/pytest tests/X.py -v`
- Lint: `cd ~/Code/lq-ai/gateway && .venv/bin/ruff format <files> && .venv/bin/ruff check <files> && .venv/bin/mypy app`; whole-tree `ruff format --check .` before pushing.

## Confirmed gateway patterns (read 2026-06-16)
- Routers: `router = APIRouter(prefix="/v1", tags=[...])`; registered in `gateway/app/main.py` via `app.include_router(...)` (after `inference_router`/`admin_router`, ~line 411).
- Admin router gates with `require_gateway_key = make_require_gateway_key()` then `APIRouter(..., dependencies=[Depends(require_gateway_key)])` (`gateway/app/api/admin.py:54-59`). The **inference** router is NOT key-gated; the **tools** router SHOULD be (privileged egress) — match admin.
- `make_require_gateway_key()` (`gateway/app/api/dependencies.py`) reads the live config; when `gateway_auth.enabled` is True but the env key is empty it returns None (auth disabled — so tests that don't set `LQ_AI_GATEWAY_KEY` pass through); missing/wrong header when a key IS set → 401 with the `{"error": {...}}` envelope.
- State accessors (in `inference.py`, private): the Router is `app.state.router`; replicate a tiny local accessor rather than importing the private `_router`.
- `synthesize_request_id(provided)` lives in `app.router`; honor an inbound `X-Request-Id`/`X-Correlation-Id`.
- `Router.route_tool_call(provider_name, tool, args, *, request_id, max_allowed_tier=None) -> ToolCallRoutedResult(provider, tool, payload, tier)` (PR1). Refusals raise `ToolEgressRefused(reason)`; adapter errors raise `ToolProviderError` subclasses (`ToolProviderAuthError`, `ToolProviderInvalidRequestError(upstream_status)`, `ToolProviderHTTPError(upstream_status)`, `ToolProviderNetworkError`, base `ToolProviderError`).

## Scope — NOT in PR3a
- No `GatewayClient.call_tool` (api-side) — PR3b.
- No `/api/v1/research` surface, caching, find_in_case/read_case — PR3b.
- No tool-listing endpoint (`GET /v1/tools`) — defer to PR5 (chat tool-loop needs discovery); the api research layer calls known tools by name.

---

## Task 1: the `POST /v1/tools/{provider}/{tool}` route + error mapping

**Files:** Create `gateway/app/api/tools.py`; Test `gateway/tests/test_tools_route.py`.

- [ ] **Step 1: Failing tests** (`gateway/tests/test_tools_route.py`):

```python
import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.tools import router as tools_router
from app.config import GatewayConfig
from app.providers.tool.echo import EchoToolAdapter
from app.router import Router
from app.tool_egress_log import RecordingToolEgressLogWriter


def _make_app(monkeypatch, *, writer=None):
    monkeypatch.setattr(
        "app.providers.tool.egress._resolve_ips", lambda host: ["93.184.216.34"]
    )
    cfg = GatewayConfig.model_validate(
        {
            "tool_providers": [
                {
                    "name": "echo-test",
                    "type": "echo",
                    "base_url": "https://example.test",
                    "egress_tier": 4,
                    "allowlist": {"hosts": ["example.test"]},
                }
            ]
        }
    )
    adapter = EchoToolAdapter.from_config(cfg.tool_providers[0])
    router_obj = Router(
        config=cfg,
        adapters={},
        tool_adapters={"echo-test": adapter},
        tool_egress_log=writer or RecordingToolEgressLogWriter(),
    )
    app = FastAPI()
    app.state.config = cfg
    app.state.router = router_obj
    app.include_router(tools_router)
    return app, adapter


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.unit
async def test_tool_call_happy_path(monkeypatch) -> None:
    app, adapter = _make_app(monkeypatch)
    try:
        async with _client(app) as c:
            resp = await c.post(
                "/v1/tools/echo-test/echo", json={"args": {"msg": "hi"}}
            )
    finally:
        await adapter.aclose()
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "echo-test"
    assert body["tool"] == "echo"
    assert body["payload"] == {"echoed": {"msg": "hi"}}
    assert body["tier"] == 4


@pytest.mark.unit
async def test_tool_call_unknown_provider_403(monkeypatch) -> None:
    app, adapter = _make_app(monkeypatch)
    try:
        async with _client(app) as c:
            resp = await c.post("/v1/tools/missing/echo", json={"args": {}})
    finally:
        await adapter.aclose()
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "egress_refused"


@pytest.mark.unit
async def test_tool_call_tier_ceiling_403(monkeypatch) -> None:
    app, adapter = _make_app(monkeypatch)
    try:
        async with _client(app) as c:
            resp = await c.post(
                "/v1/tools/echo-test/echo",
                json={"args": {}, "max_allowed_tier": 3},
            )
    finally:
        await adapter.aclose()
    assert resp.status_code == 403


@pytest.mark.unit
async def test_tool_call_unknown_tool_400(monkeypatch) -> None:
    app, adapter = _make_app(monkeypatch)
    try:
        async with _client(app) as c:
            resp = await c.post("/v1/tools/echo-test/nope", json={"args": {}})
    finally:
        await adapter.aclose()
    assert resp.status_code == 400


@pytest.mark.unit
async def test_tool_call_requires_gateway_key_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("LQ_AI_GATEWAY_KEY", "secret-key")
    app, adapter = _make_app(monkeypatch)
    try:
        async with _client(app) as c:
            missing = await c.post("/v1/tools/echo-test/echo", json={"args": {}})
            ok = await c.post(
                "/v1/tools/echo-test/echo",
                json={"args": {"msg": "hi"}},
                headers={"X-LQ-AI-Gateway-Key": "secret-key"},
            )
    finally:
        await adapter.aclose()
    assert missing.status_code == 401
    assert ok.status_code == 200
```

- [ ] **Step 2: Run, confirm ModuleNotFoundError.**

- [ ] **Step 3: Implement `gateway/app/api/tools.py`:**

```python
"""``POST /v1/tools/{provider}/{tool}`` — backend → gateway tool-call transport.

Exposes the PR1 :meth:`Router.route_tool_call` egress path over HTTP so the
FastAPI backend can invoke tool-providers (CourtListener, MCP) WITHOUT calling
third parties directly (ADR 0014). Gated by the gateway-key dependency — this
triggers credentialed egress + cost, a privileged operation like admin.
The audit row is written inside ``route_tool_call``; this layer only maps
errors to the ``GatewayError`` envelope."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.dependencies import make_require_gateway_key
from app.providers.tool.base import (
    ToolProviderAuthError,
    ToolProviderError,
    ToolProviderHTTPError,
    ToolProviderInvalidRequestError,
    ToolProviderNetworkError,
)
from app.router import Router, ToolEgressRefused, synthesize_request_id

require_gateway_key = make_require_gateway_key()

router = APIRouter(prefix="/v1", tags=["tools"], dependencies=[Depends(require_gateway_key)])


class ToolCallRequest(BaseModel):
    """Body for a tool-call. ``args`` is the tool's own argument object."""

    args: dict[str, Any] = Field(default_factory=dict)
    max_allowed_tier: int | None = Field(default=None, ge=1, le=5)


def _router(request: Request) -> Router:
    pre_built: Router | None = getattr(request.app.state, "router", None)
    if pre_built is None:
        raise RuntimeError("gateway router not initialized")
    return pre_built


def _request_id(request: Request) -> str:
    for name in ("x-request-id", "x-correlation-id"):
        value = request.headers.get(name)
        if value:
            return synthesize_request_id(value)
    return synthesize_request_id(None)


def _error(status_code: int, code: str, message: str, details: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


@router.post("/tools/{provider}/{tool}")
async def call_tool(
    provider: str, tool: str, body: ToolCallRequest, request: Request
) -> JSONResponse:
    gw_router = _router(request)
    request_id = _request_id(request)
    try:
        result = await gw_router.route_tool_call(
            provider, tool, body.args,
            request_id=request_id, max_allowed_tier=body.max_allowed_tier,
        )
    except ToolEgressRefused as exc:
        return _error(403, "egress_refused", exc.reason)
    except ToolProviderAuthError:
        # Don't leak the upstream credential problem to the caller verbatim.
        return _error(502, "tool_provider_unavailable", "tool provider rejected gateway credentials")
    except ToolProviderInvalidRequestError as exc:
        return _error(400, "invalid_request", exc.message, exc.details)
    except ToolProviderHTTPError as exc:
        code = 429 if exc.upstream_status == 429 else 502
        return _error(code, "tool_provider_unavailable", exc.message, exc.details)
    except ToolProviderNetworkError as exc:
        return _error(502, "tool_provider_unavailable", exc.message)
    except ToolProviderError as exc:
        # Catch-all (e.g. unknown tool name from the adapter).
        return _error(400, exc.code, exc.message, exc.details)
    return JSONResponse(
        content={
            "provider": result.provider,
            "tool": result.tool,
            "payload": result.payload,
            "tier": result.tier,
        }
    )
```

- [ ] **Step 4: Run the 5 tests** (pass). **Step 5: lint** (ruff format, ruff check, mypy --strict — clean). **Step 6: commit:**
```bash
cd ~/Code/lq-ai && git add gateway/app/api/tools.py gateway/tests/test_tools_route.py
git commit -s -m "feat(gateway): POST /v1/tools/{provider}/{tool} egress transport (WS3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: register the router + OpenAPI doc + on-app test

**Files:** Modify `gateway/app/main.py`, `docs/api/gateway-openapi.yaml`; Test extend `gateway/tests/test_tools_route.py`.

- [ ] **Step 1: Failing test** — assert the route is registered on the real lifespan-built app. Append to `test_tools_route.py`:

```python
@pytest.mark.unit
async def test_tools_route_registered_on_app(gateway_app) -> None:
    paths = gateway_app.openapi()["paths"]
    assert "/v1/tools/{provider}/{tool}" in paths
    assert "post" in paths["/v1/tools/{provider}/{tool}"]
```

(`gateway_app` is the existing conftest fixture that runs the full lifespan against `gateway.yaml.example`.)

- [ ] **Step 2: Run, confirm it fails** (route not registered).

- [ ] **Step 3: Register the router** in `gateway/app/main.py`: add `from app.api.tools import router as tools_router` with the other route imports, and `app.include_router(tools_router)` next to the existing `app.include_router(inference_router)` / `admin_router` (~line 411).

- [ ] **Step 4: Document the endpoint** in `docs/api/gateway-openapi.yaml` — add the `/v1/tools/{provider}/{tool}` path (POST: `provider`/`tool` path params, `ToolCallRequest` body `{args, max_allowed_tier}`, 200 response `{provider, tool, payload, tier}`, and the `GatewayError`-envelope error responses 400/401/403/429/502). FIRST check whether a gateway OpenAPI conformance test exists (grep `gateway/tests` for `openapi`); if one pins a path count or set, update it. Match the file's existing style for an endpoint (model after `/v1/chat/completions`).

- [ ] **Step 5:** Run the new test + the FULL gateway suite (no regression). Whole-tree `ruff format --check .`.

- [ ] **Step 6: lint** (mypy --strict clean). **Step 7: commit:**
```bash
cd ~/Code/lq-ai && git add gateway/app/main.py docs/api/gateway-openapi.yaml gateway/tests/test_tools_route.py
git commit -s -m "feat(gateway): register tools router + OpenAPI for /v1/tools (WS3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: final gates, push, PR

- [ ] **Step 1: Full gate sweep** — gateway `ruff format --check .`, `ruff check .`, `mypy app`, `pytest -q -m "not provider and not slow"` (all green).
- [ ] **Step 2: Push both remotes** (`git push origin feat/research-subsystem && git push tucuxi feat/research-subsystem`).
- [ ] **Step 3: Open the PR** (base `main`), title `WS3/PR3a: gateway tool-call HTTP transport (legal-research milestone)`. Body: explain it exposes PR1's `route_tool_call` so the backend (PR3b) can reach tool-providers through the boundary; note it's key-gated like admin; list error mapping; flag that the api consumer + `/research` surface are PR3b; mark `gateway/**` security-reviewed. Watch CI green. **Do NOT self-merge.**

---

## Self-review (against the spec)
- **`POST /v1/tools/{provider}/{tool}` exposing `route_tool_call`** → Task 1. ✓
- **Key-gated (privileged egress, matches admin)** → Task 1 (`dependencies=[Depends(require_gateway_key)]`) + auth test. ✓
- **Error mapping to `GatewayError` envelope** (egress refusal 403, invalid 400, auth/http/network → 502, 429 passthrough, unknown tool 400) → Task 1 `call_tool`. ✓
- **Audit happens in `route_tool_call`** (no double-log) → handler just calls it. ✓
- **Registered + documented** → Task 2 (`include_router` + gateway-openapi.yaml + on-app test). ✓
- **No api-side code, no caching, no /research** (PR3b) → Scope section. ✓
- **Type consistency:** `ToolCallRequest`, `call_tool`, `_router`/`_request_id`/`_error` helpers, `route_tool_call(...)`/`ToolCallRoutedResult` fields, `ToolEgressRefused.reason`, the `ToolProvider*Error` subclasses — all referenced as defined in PR1. ✓
- **Known check:** Task 2 Step 4 must verify whether a gateway OpenAPI conformance test pins paths (the api side does; the gateway may not) — the implementer greps and updates if so.
