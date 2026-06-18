# PR4b — api MCP registry / discovery-cache / admin (WS2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the api side of the MCP subsystem on top of the merged PR4a gateway slice: enumerate configured MCP servers, discover + DB-cache their tools through the gateway, let an operator enable/disable individual tools, and expose it all under `/api/v1/admin/mcp`. End-to-end functional for `none`/`bearer` MCP servers; per-user OAuth is PR4c.

**Architecture:** No new MCP-protocol code in the api — it brokers through PR4a's gateway endpoints. The api learns the configured servers from `GatewayClient.list_tool_providers()` filtered to `type == "mcp"` (no api-side server table). A new `GatewayClient.discover_tools()` calls PR4a's `GET /v1/tools/{provider}` and the result is upserted into a new `mcp_tools` cache table (migration 0050) carrying an operator `enabled` toggle. An admin router (`/api/v1/admin/mcp`, `AdminUser`-gated) lists servers+tools, refreshes discovery, and toggles tools.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async + asyncpg, Alembic, Pydantic v2, pytest + respx. mypy standard (api).

**Gate:** api-only (new admin endpoints reuse the existing `AdminUser` dep; new audit *calls* reuse existing audit infra — neither changes authz/audit *implementation*, so no CODEOWNERS security trigger). → **self-merge after CI green.**

**Depends on:** PR4a (merged, `main` @ `5b73e75`). Out of scope: per-user OAuth + token storage (PR4c); the chat tool-loop / `ToolIntent`s (PR5); provenance UI (PR6). Retiring the `web/` stub is PR4c.

**Pre-flight facts (verified against merged `main`):**
- PR4a discovery contract — `GET /v1/tools/{provider}` (gateway-key gated) → `{"provider": str, "tools": [{"name", "description", "parameters", "read_only", "destructive", "requires_confirmation"}]}`; optional `X-LQ-AI-User-Token` header (oauth; PR4c). 404 `unknown_provider`, 502 `tool_provider_unavailable`.
- `GatewayClient` (`api/app/clients/gateway.py`): `call_tool` (~689), `list_tool_providers()` → `[{name,type}]` (~916), `_build_headers(*, request_id)` (~1038, gateway key is set on the httpx client in `__init__`, NOT here), `_raise_for_gateway_error` (~1046), singleton `get_gateway_client()` (~1267). To send a per-call header, build the headers dict from `_build_headers` then add `X-LQ-AI-User-Token` when a token is given.
- Admin router (`api/app/api/admin.py`): `router = APIRouter(prefix="/admin", tags=["admin"])`; handlers take `_admin: AdminUser` (from `app.api.dependencies`) and inject `gateway: Annotated[GatewayClient, Depends(get_gateway_client)]` / `db: Annotated[AsyncSession, Depends(get_db)]`. Registered in `api/app/api/__init__.py` under the `_active` group. Audit pattern: `from app.audit import audit_action; await audit_action(db, user_id=admin.id, action="...", resource_type="...", resource_id="...", request=request, details={...})` then `await db.commit()`.
- Model pattern (`api/app/models/research.py`): `class X(Base)` with `Mapped[...] = mapped_column(...)`; `Base` from `app.db.base`; register in `api/app/models/__init__.py` (import + `__all__`) so Alembic sees it.
- Migration: head is **0049** (`api/alembic/versions/0049_research_metadata.py`); new file `0050_mcp_tools.py` with `revision="0050"`, `down_revision="0049"`, `op.create_table`/`op.create_index`.
- Collision guards: `api/tests/test_endpoints.py` `IMPLEMENTED_ROUTES` (add `(METHOD, path)` tuples); `api/tests/test_openapi.py` `EXPECTED_PATHS` frozenset (add path strings, **deduped by path**) + bump `assert len(actual) == 124`.
- `AdminUser` is `Annotated[User, Depends(require_admin)]`-style (read `app/api/dependencies.py` to confirm exact name) — has `.id`.

**Run/gate reminders (from the milestone handoff):**
- api tests via host venv + throwaway pgvector :15433: `cd api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest tests/<file>.py -q`. conftest auto-migrates a throwaway DB. **NEVER** host `alembic upgrade` against the dev DB.
- Gates: `cd api && .venv/bin/ruff format --check app tests && .venv/bin/ruff check app tests && .venv/bin/mypy app` (run from repo root with `api/.venv/bin/...` paths is equivalent). CI runs `ruff format --check` and `ruff check` as SEPARATE gates — run both.
- Commit `-s` + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Stage explicitly (never `git add -A`).

---

## File structure

| File | Responsibility |
|---|---|
| `api/alembic/versions/0050_mcp_tools.py` (create) | `mcp_tools` cache table |
| `api/app/models/mcp.py` (create) | `MCPToolCache` ORM model |
| `api/app/models/__init__.py` (modify) | register the model for Alembic |
| `api/app/clients/gateway.py` (modify) | `discover_tools()` calling PR4a's `GET /v1/tools/{provider}` |
| `api/app/mcp/__init__.py` (create) | package marker |
| `api/app/mcp/service.py` (create) | `list_servers`, `refresh_server`, `list_cached_tools`, `set_tool_enabled` |
| `api/app/schemas/mcp.py` (create) | request/response Pydantic models |
| `api/app/api/admin_mcp.py` (create) | `/api/v1/admin/mcp` router (3 endpoints) |
| `api/app/api/__init__.py` (modify) | register the new admin-mcp router under `_active` |
| `api/tests/test_endpoints.py` + `api/tests/test_openapi.py` (modify) | collision guards |
| `docs/api/backend-openapi.yaml` (modify) | document the 3 routes |
| `api/tests/test_mcp_*.py` (create) | model/service/endpoint tests |

---

## Task 1: `mcp_tools` cache table (model + migration)

**Files:**
- Create: `api/app/models/mcp.py`
- Modify: `api/app/models/__init__.py`
- Create: `api/alembic/versions/0050_mcp_tools.py`
- Test: `api/tests/test_mcp_models.py`

**Design:** one table, the discovery cache. Composite PK `(provider_name, tool_name)`. `enabled` is the operator toggle (authoritative for what PR5 exposes). `parameters` holds the JSON-schema. No api-side server table — servers come from gateway config at read time.

- [ ] **Step 1: Write the failing model test**

```python
# api/tests/test_mcp_models.py
import pytest

from app.models.mcp import MCPToolCache


@pytest.mark.unit
def test_mcp_tool_cache_columns() -> None:
    cols = MCPToolCache.__table__.columns.keys()
    assert set(cols) >= {
        "provider_name", "tool_name", "description", "parameters",
        "read_only", "destructive", "requires_confirmation", "enabled", "discovered_at",
    }
    pk = {c.name for c in MCPToolCache.__table__.primary_key.columns}
    assert pk == {"provider_name", "tool_name"}
```

- [ ] **Step 2: Run it (fails — module missing)**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest tests/test_mcp_models.py -q`
Expected: FAIL — `ModuleNotFoundError: app.models.mcp`.

- [ ] **Step 3: Implement the model**

```python
# api/app/models/mcp.py
"""ORM model for the MCP tool-discovery cache (WS2/PR4b).

One row per (mcp server, tool). Populated by discovering tools through the
gateway (PR4a's GET /v1/tools/{provider}); ``enabled`` is the operator toggle
that gates what PR5 exposes to the model. MCP servers themselves are NOT stored
here — they come from the gateway config (list_tool_providers, type==mcp)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MCPToolCache(Base):
    __tablename__ = "mcp_tools"

    provider_name: Mapped[str] = mapped_column(String, primary_key=True)
    tool_name: Mapped[str] = mapped_column(String, primary_key=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    read_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    destructive: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    requires_confirmation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
```
Then in `api/app/models/__init__.py` add the import (`from app.models.mcp import MCPToolCache`) and `"MCPToolCache"` to `__all__`, matching the file's existing style.

- [ ] **Step 4: Run model test (passes)**

Run the Step-2 command. Expected: 1 passed.

- [ ] **Step 5: Write the migration**

```python
# api/alembic/versions/0050_mcp_tools.py
"""mcp tool-discovery cache (WS2/PR4b)

One row per (mcp provider, tool). Discovered through the gateway; ``enabled``
is the operator toggle. MCP servers come from gateway config, not stored here.

Revision ID: 0050
Revises: 0049
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_tools",
        sa.Column("provider_name", sa.String(), primary_key=True),
        sa.Column("tool_name", sa.String(), primary_key=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("read_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("destructive", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "requires_confirmation", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("mcp_tools")
```

- [ ] **Step 6: Verify the migration on a throwaway DB (NOT the dev DB)**

The conftest auto-migrates the throwaway pgvector on :15433 when the suite runs. Confirm by running the model test again under the test DB (Step 2 command) — conftest will have applied 0050. Expected: passes (table exists). Do NOT run host `alembic upgrade` against the dev DB.

- [ ] **Step 7: Commit**

```bash
cd /Users/kevinkeller/Code/lq-ai && git add api/app/models/mcp.py api/app/models/__init__.py api/alembic/versions/0050_mcp_tools.py api/tests/test_mcp_models.py && git commit -s -m "PR4b: mcp_tools discovery-cache table (model + migration 0050)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `GatewayClient.discover_tools`

**Files:**
- Modify: `api/app/clients/gateway.py`
- Test: `api/tests/test_gateway_discover_tools.py`

- [ ] **Step 1: Write the failing test (respx)**

```python
# api/tests/test_gateway_discover_tools.py
import httpx
import pytest
import respx

from app.clients.gateway import GATEWAY_KEY_HEADER, GatewayClient

GATEWAY_BASE = "http://test-gateway"
GATEWAY_KEY = "test-secret"


def _client() -> GatewayClient:
    return GatewayClient(base_url=GATEWAY_BASE, gateway_key=GATEWAY_KEY)


@pytest.mark.asyncio
async def test_discover_tools_happy_path() -> None:
    payload = {
        "provider": "acme-mcp",
        "tools": [
            {"name": "read_doc", "description": "reads", "parameters": {"type": "object"},
             "read_only": True, "destructive": False, "requires_confirmation": False},
        ],
    }
    with respx.mock(base_url=GATEWAY_BASE) as mock:
        route = mock.get("/v1/tools/acme-mcp").mock(return_value=httpx.Response(200, json=payload))
        out = await _client().discover_tools("acme-mcp")
    assert out["provider"] == "acme-mcp"
    assert out["tools"][0]["name"] == "read_doc"
    assert route.calls.last.request.headers[GATEWAY_KEY_HEADER] == GATEWAY_KEY


@pytest.mark.asyncio
async def test_discover_tools_sends_user_token_header() -> None:
    with respx.mock(base_url=GATEWAY_BASE) as mock:
        route = mock.get("/v1/tools/acme-mcp").mock(
            return_value=httpx.Response(200, json={"provider": "acme-mcp", "tools": []})
        )
        await _client().discover_tools("acme-mcp", user_token="user-tok")
    assert route.calls.last.request.headers["X-LQ-AI-User-Token"] == "user-tok"


@pytest.mark.asyncio
async def test_discover_tools_unknown_provider_raises() -> None:
    from app.errors import LQAIError

    body = {"error": {"code": "unknown_provider", "message": "nope", "details": {}}}
    with respx.mock(base_url=GATEWAY_BASE) as mock:
        mock.get("/v1/tools/nope").mock(return_value=httpx.Response(404, json=body))
        with pytest.raises(LQAIError):
            await _client().discover_tools("nope")
```

- [ ] **Step 2: Run it (fails — no `discover_tools`)**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest tests/test_gateway_discover_tools.py -q`
Expected: FAIL — `AttributeError: 'GatewayClient' object has no attribute 'discover_tools'`.

- [ ] **Step 3: Implement the method**

Add near `call_tool` in `api/app/clients/gateway.py` (mirror `call_tool`'s structure exactly — timeout/transport/`_raise_for_gateway_error` handling):

```python
    async def discover_tools(
        self,
        provider: str,
        *,
        user_token: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """GET /v1/tools/{provider} on the gateway (PR4a discovery transport).

        Returns the gateway's ``{provider, tools:[...]}`` dict. ``user_token``
        (for ``auth: oauth`` MCP servers, PR4c) is sent in the
        ``X-LQ-AI-User-Token`` header — never a query param (it would land in
        access logs). Errors translate like ``call_tool``."""
        headers = self._build_headers(request_id=request_id)
        if user_token is not None:
            headers["X-LQ-AI-User-Token"] = user_token
        op = f"discover_tools:{provider}"
        try:
            response = await self._client.get(f"/v1/tools/{provider}", headers=headers)
        except httpx.TimeoutException as exc:
            raise GatewayTimeout(
                "Gateway did not respond within the configured timeout",
                details={"timeout_seconds": self._timeout},
            ) from exc
        except httpx.HTTPError as exc:
            raise GatewayUnreachable(
                "Could not reach the Inference Gateway",
                details={"transport_error": type(exc).__name__},
            ) from exc
        if response.status_code >= 400:
            self._raise_for_gateway_error(
                status_code=response.status_code,
                body_bytes=response.content,
                op=op,
                request_id=request_id,
            )
        try:
            payload: dict[str, Any] = response.json()
            return payload
        except json.JSONDecodeError as exc:
            raise GatewayInvalidResponse(
                "Gateway discover_tools returned a non-JSON success response",
                details={"status_code": response.status_code},
            ) from exc
```
(Confirm `GatewayTimeout`, `GatewayUnreachable`, `GatewayInvalidResponse`, `json` are already imported in the file — they are, used by `call_tool`.)

- [ ] **Step 4: Run discovery tests (pass)**

Run the Step-2 command. Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/kevinkeller/Code/lq-ai && git add api/app/clients/gateway.py api/tests/test_gateway_discover_tools.py && git commit -s -m "PR4b: GatewayClient.discover_tools (GET /v1/tools/{provider})

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `api/app/mcp/` service (registry + cache reconciliation + toggle)

**Files:**
- Create: `api/app/mcp/__init__.py` (empty package marker)
- Create: `api/app/mcp/service.py`
- Test: `api/tests/test_mcp_service.py`

**Design:** four async functions. `refresh_server` reconciles the cache: upsert returned tools (PRESERVING the existing `enabled` flag for surviving tools; new tools default `enabled=True`), and DELETE cached rows for tools the server no longer returns. `list_cached_tools` reads the cache. `list_servers` enumerates `type==mcp` providers from gateway config. `set_tool_enabled` flips the toggle (404 if the tool isn't cached).

- [ ] **Step 1: Write failing service tests**

```python
# api/tests/test_mcp_service.py
import httpx
import pytest
import respx
from sqlalchemy import select

from app.errors import NotFound
from app.mcp import service
from app.models.mcp import MCPToolCache

GW = "http://localhost:8001"  # settings.lq_ai_gateway_url default


def _tools_payload(provider, names):
    return {"provider": provider, "tools": [
        {"name": n, "description": f"{n} desc", "parameters": {"type": "object"},
         "read_only": False, "destructive": False, "requires_confirmation": True}
        for n in names
    ]}


@pytest.mark.asyncio
async def test_list_servers_filters_mcp(monkeypatch) -> None:
    async def fake_list(*, request_id=None):
        return [{"name": "acme-mcp", "type": "mcp"}, {"name": "cl", "type": "courtlistener"}]
    monkeypatch.setattr("app.mcp.service.get_gateway_client", lambda: type("C", (), {"list_tool_providers": staticmethod(fake_list)})())
    servers = await service.list_servers()
    assert [s["name"] for s in servers] == ["acme-mcp"]


@pytest.mark.asyncio
async def test_refresh_upserts_and_preserves_enabled(db_session) -> None:
    # seed a disabled tool that will survive refresh + a stale tool that won't
    db_session.add(MCPToolCache(provider_name="acme-mcp", tool_name="read_doc",
                                parameters={}, enabled=False, requires_confirmation=True))
    db_session.add(MCPToolCache(provider_name="acme-mcp", tool_name="gone",
                                parameters={}, enabled=True, requires_confirmation=True))
    await db_session.commit()
    with respx.mock(base_url=GW) as mock:
        mock.get("/v1/tools/acme-mcp").mock(
            return_value=httpx.Response(200, json=_tools_payload("acme-mcp", ["read_doc", "new_tool"]))
        )
        tools = await service.refresh_server(db_session, provider="acme-mcp")
    await db_session.commit()
    rows = {r.tool_name: r for r in (await db_session.execute(
        select(MCPToolCache).where(MCPToolCache.provider_name == "acme-mcp"))).scalars()}
    assert set(rows) == {"read_doc", "new_tool"}          # stale "gone" deleted
    assert rows["read_doc"].enabled is False               # preserved
    assert rows["new_tool"].enabled is True                # new defaults enabled
    assert {t["name"] for t in tools} == {"read_doc", "new_tool"}


@pytest.mark.asyncio
async def test_set_tool_enabled_toggles(db_session) -> None:
    db_session.add(MCPToolCache(provider_name="acme-mcp", tool_name="read_doc",
                                parameters={}, enabled=True, requires_confirmation=True))
    await db_session.commit()
    await service.set_tool_enabled(db_session, provider="acme-mcp", tool="read_doc", enabled=False)
    await db_session.commit()
    row = (await db_session.execute(select(MCPToolCache).where(
        MCPToolCache.tool_name == "read_doc"))).scalar_one()
    assert row.enabled is False


@pytest.mark.asyncio
async def test_set_tool_enabled_missing_raises(db_session) -> None:
    with pytest.raises(NotFound):
        await service.set_tool_enabled(db_session, provider="x", tool="y", enabled=True)
```
(Check `api/tests/conftest.py` for the `db_session` fixture name — match whatever the research tests use; `test_research_service.py` uses `db_session`.)

- [ ] **Step 2: Run (fails — module missing)**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest tests/test_mcp_service.py -q`
Expected: FAIL — `ModuleNotFoundError: app.mcp`.

- [ ] **Step 3: Implement the service**

Create `api/app/mcp/__init__.py` (empty). Create `api/app/mcp/service.py`:

```python
"""MCP registry + discovery-cache orchestration (WS2/PR4b).

Servers come from gateway config (type==mcp); tools are discovered through the
gateway (PR4a) and cached in ``mcp_tools`` with an operator ``enabled`` toggle.
The api never speaks MCP directly (ADR 0014)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import get_gateway_client
from app.errors import NotFound
from app.models.mcp import MCPToolCache

_MCP_TYPE = "mcp"


async def list_servers(*, request_id: str | None = None) -> list[dict[str, str]]:
    """Configured MCP servers, from gateway config (name + type)."""
    providers = await get_gateway_client().list_tool_providers(request_id=request_id)
    return [p for p in providers if p.get("type") == _MCP_TYPE]


def _tool_dict(row: MCPToolCache) -> dict[str, Any]:
    return {
        "name": row.tool_name,
        "description": row.description,
        "parameters": row.parameters,
        "read_only": row.read_only,
        "destructive": row.destructive,
        "requires_confirmation": row.requires_confirmation,
        "enabled": row.enabled,
    }


async def list_cached_tools(db: AsyncSession, *, provider: str) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(MCPToolCache)
            .where(MCPToolCache.provider_name == provider)
            .order_by(MCPToolCache.tool_name)
        )
    ).scalars()
    return [_tool_dict(r) for r in rows]


async def refresh_server(
    db: AsyncSession, *, provider: str, user_token: str | None = None, request_id: str | None = None
) -> list[dict[str, Any]]:
    """Re-discover ``provider``'s tools through the gateway and reconcile the
    cache: upsert returned tools (preserving each surviving tool's ``enabled``),
    delete cached tools the server no longer returns."""
    result = await get_gateway_client().discover_tools(
        provider, user_token=user_token, request_id=request_id
    )
    discovered = result.get("tools", [])
    existing = {
        r.tool_name: r
        for r in (
            await db.execute(
                select(MCPToolCache).where(MCPToolCache.provider_name == provider)
            )
        ).scalars()
    }
    seen: set[str] = set()
    for tool in discovered:
        name = tool["name"]
        seen.add(name)
        row = existing.get(name)
        if row is None:
            db.add(
                MCPToolCache(
                    provider_name=provider,
                    tool_name=name,
                    description=tool.get("description"),
                    parameters=tool.get("parameters") or {},
                    read_only=bool(tool.get("read_only", False)),
                    destructive=bool(tool.get("destructive", False)),
                    requires_confirmation=bool(tool.get("requires_confirmation", True)),
                    enabled=True,
                )
            )
        else:
            row.description = tool.get("description")
            row.parameters = tool.get("parameters") or {}
            row.read_only = bool(tool.get("read_only", False))
            row.destructive = bool(tool.get("destructive", False))
            row.requires_confirmation = bool(tool.get("requires_confirmation", True))
            # enabled preserved
    stale = set(existing) - seen
    if stale:
        await db.execute(
            delete(MCPToolCache).where(
                MCPToolCache.provider_name == provider, MCPToolCache.tool_name.in_(stale)
            )
        )
    await db.flush()
    return await list_cached_tools(db, provider=provider)


async def set_tool_enabled(
    db: AsyncSession, *, provider: str, tool: str, enabled: bool
) -> dict[str, Any]:
    row = (
        await db.execute(
            select(MCPToolCache).where(
                MCPToolCache.provider_name == provider, MCPToolCache.tool_name == tool
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound(f"MCP tool {provider}/{tool} is not in the discovery cache")
    row.enabled = enabled
    await db.flush()
    return _tool_dict(row)
```
(Confirm `NotFound` is in `app.errors` — it is, used by research service. `delete` import from sqlalchemy.)

- [ ] **Step 4: Run service tests (pass)**

Run the Step-2 command. Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/kevinkeller/Code/lq-ai && git add api/app/mcp/__init__.py api/app/mcp/service.py api/tests/test_mcp_service.py && git commit -s -m "PR4b: MCP registry + discovery-cache service (refresh reconcile, enable toggle)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `/api/v1/admin/mcp` admin surface

**Files:**
- Create: `api/app/schemas/mcp.py`
- Create: `api/app/api/admin_mcp.py`
- Modify: `api/app/api/__init__.py` (register router)
- Modify: `api/tests/test_endpoints.py`, `api/tests/test_openapi.py` (collision guards)
- Modify: `docs/api/backend-openapi.yaml`
- Test: `api/tests/test_admin_mcp.py`

**Three endpoints** (all `AdminUser`-gated):
- `GET /api/v1/admin/mcp` → `{servers:[{name, type, tools:[{name, description, read_only, destructive, requires_confirmation, enabled}]}]}` (servers from gateway config; tools from cache).
- `POST /api/v1/admin/mcp/{server}/refresh` → re-discover + reconcile; `{server, tools:[...]}`; audited `mcp.tools_refreshed`.
- `PATCH /api/v1/admin/mcp/{server}/tools/{tool}` → body `{enabled: bool}` → toggle; `{...tool...}`; audited `mcp.tool_enabled`.

- [ ] **Step 1: Write the schemas**

```python
# api/app/schemas/mcp.py
"""Pydantic schemas for /api/v1/admin/mcp (WS2/PR4b)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MCPToolView(BaseModel):
    name: str
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    read_only: bool
    destructive: bool
    requires_confirmation: bool
    enabled: bool


class MCPServerView(BaseModel):
    name: str
    type: str
    tools: list[MCPToolView] = Field(default_factory=list)


class MCPServersResponse(BaseModel):
    servers: list[MCPServerView] = Field(default_factory=list)


class MCPRefreshResponse(BaseModel):
    server: str
    tools: list[MCPToolView] = Field(default_factory=list)


class MCPToolEnableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
```

- [ ] **Step 2: Write failing endpoint tests**

```python
# api/tests/test_admin_mcp.py — follow api/tests/test_admin_*.py for the admin
# auth fixture (an admin user + auth header). Match how existing admin endpoint
# tests authenticate (e.g. test that hits /api/v1/admin/aliases).
```
Write tests for: (1) `GET /api/v1/admin/mcp` returns servers (mock `service.list_servers` to return `[{"name":"acme-mcp","type":"mcp"}]` and seed two cached tools) with their tools+enabled; (2) `POST /api/v1/admin/mcp/acme-mcp/refresh` (mock `service.refresh_server`) returns the tools and writes a `mcp.tools_refreshed` audit row; (3) `PATCH /api/v1/admin/mcp/acme-mcp/tools/read_doc` with `{"enabled": false}` flips it (200) and a missing tool → 404; (4) non-admin caller → 403. Read `test_admin_intake_bridges.py` or similar for the admin-auth client pattern and copy it.

- [ ] **Step 3: Run (fails — router missing)**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest tests/test_admin_mcp.py -q`
Expected: FAIL (404s / import error).

- [ ] **Step 4: Implement the router**

```python
# api/app/api/admin_mcp.py
"""/api/v1/admin/mcp — MCP registry admin surface (WS2/PR4b).

Lists configured MCP servers (from gateway config) + their cached tools,
refreshes discovery through the gateway, and toggles per-tool enable. All
AdminUser-gated. The api never speaks MCP directly (ADR 0014)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AdminUser
from app.audit import audit_action
from app.db.session import get_db
from app.mcp import service
from app.schemas.mcp import (
    MCPRefreshResponse,
    MCPServersResponse,
    MCPServerView,
    MCPToolEnableRequest,
    MCPToolView,
)

router = APIRouter(prefix="/admin/mcp", tags=["admin"])


@router.get("", response_model=MCPServersResponse)
async def list_mcp(
    _admin: AdminUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> MCPServersResponse:
    servers = await service.list_servers()
    views: list[MCPServerView] = []
    for s in servers:
        tools = await service.list_cached_tools(db, provider=s["name"])
        views.append(MCPServerView(name=s["name"], type=s["type"],
                                   tools=[MCPToolView(**t) for t in tools]))
    return MCPServersResponse(servers=views)


@router.post("/{server}/refresh", response_model=MCPRefreshResponse)
async def refresh_mcp(
    server: str,
    admin: AdminUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MCPRefreshResponse:
    tools = await service.refresh_server(db, provider=server)
    await audit_action(
        db, user_id=admin.id, action="mcp.tools_refreshed",
        resource_type="mcp_server", resource_id=server, request=request,
        details={"tool_count": len(tools)},
    )
    await db.commit()
    return MCPRefreshResponse(server=server, tools=[MCPToolView(**t) for t in tools])


@router.patch("/{server}/tools/{tool}", response_model=MCPToolView)
async def set_mcp_tool_enabled(
    server: str,
    tool: str,
    body: MCPToolEnableRequest,
    admin: AdminUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MCPToolView:
    updated = await service.set_tool_enabled(db, provider=server, tool=tool, enabled=body.enabled)
    await audit_action(
        db, user_id=admin.id, action="mcp.tool_enabled",
        resource_type="mcp_tool", resource_id=f"{server}/{tool}", request=request,
        details={"enabled": body.enabled},
    )
    await db.commit()
    return MCPToolView(**updated)
```
(Verify exact symbol names: `AdminUser` + `get_db` import paths, `audit_action` signature — match `admin.py`'s `update_tier_policy`. If `audit_action` has a different parameter set, adapt the calls to match it exactly.)

Register in `api/app/api/__init__.py`: import `admin_mcp` and add `api_router.include_router(admin_mcp.router, dependencies=_active)` next to the other admin routers.

- [ ] **Step 5: Update collision guards (CRITICAL — off-by-one crashes the whole suite)**

In `api/tests/test_endpoints.py` `IMPLEMENTED_ROUTES`, add:
```python
    # WS2/PR4b — MCP registry admin surface
    ("GET", "/api/v1/admin/mcp"),
    ("POST", "/api/v1/admin/mcp/{server}/refresh"),
    ("PATCH", "/api/v1/admin/mcp/{server}/tools/{tool}"),
```
In `api/tests/test_openapi.py` `EXPECTED_PATHS`, add the 3 path strings (deduped by path — all 3 are distinct):
```python
    "/api/v1/admin/mcp",
    "/api/v1/admin/mcp/{server}/refresh",
    "/api/v1/admin/mcp/{server}/tools/{tool}",
```
and bump `assert len(actual) == 124` → `== 127`.

- [ ] **Step 6: Run endpoint tests + the guard tests**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest tests/test_admin_mcp.py tests/test_endpoints.py tests/test_openapi.py -q`
Expected: all pass. If `test_openapi.py` fails on count/path mismatch, the guard edits are off — fix them.

- [ ] **Step 7: Document in `backend-openapi.yaml`**

Add the 3 paths under `/api/v1/admin/mcp*` (tags `[admin]`, bearer auth) mirroring the existing admin entries' style: GET → `MCPServersResponse` shape, POST refresh → `MCPRefreshResponse`, PATCH → `MCPToolView` with `{enabled: bool}` body. `test_openapi.py` is the authoritative conformance check.

- [ ] **Step 8: Commit**

```bash
cd /Users/kevinkeller/Code/lq-ai && git add api/app/schemas/mcp.py api/app/api/admin_mcp.py api/app/api/__init__.py api/tests/test_endpoints.py api/tests/test_openapi.py docs/api/backend-openapi.yaml api/tests/test_admin_mcp.py && git commit -s -m "PR4b: /api/v1/admin/mcp registry surface (list, refresh, enable/disable)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Full gates + ship

- [ ] **Step 1: Run the full api gates**

```
cd /Users/kevinkeller/Code/lq-ai/api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest -q
cd /Users/kevinkeller/Code/lq-ai && api/.venv/bin/ruff format --check api scripts && api/.venv/bin/ruff check api scripts
cd /Users/kevinkeller/Code/lq-ai/api && .venv/bin/mypy app
```
Expected: all green. The full suite confirms the collision guards + migration 0050 (conftest auto-migrates).

- [ ] **Step 2: Ship (api-only → self-merge after CI green)**

Push BOTH remotes (`origin` + `tucuxi`), open the PR, watch CI, self-merge on green, sync `main` to both remotes, report the squash SHA. Use the milestone's ship procedure.

---

## Definition of done (PR4b)
- `mcp_tools` table (migration 0050) caches discovered tools with an operator `enabled` toggle.
- `GatewayClient.discover_tools` brokers PR4a's discovery endpoint (with the `X-LQ-AI-User-Token` header path ready for PR4c).
- Service: `list_servers` (from gateway config), `refresh_server` (reconcile: upsert + preserve `enabled` + delete stale), `list_cached_tools`, `set_tool_enabled`.
- `/api/v1/admin/mcp` (GET list, POST refresh, PATCH enable/disable), AdminUser-gated, mutations audited.
- Full api suite + ruff (format & check) + mypy green; collision guards updated (124 → 127).
- End-to-end functional for `none`/`bearer` MCP servers. **Gate:** api-only → self-merge after CI green.

## Follow-on
- **PR4c (security review):** per-user OAuth (authz-code+PKCE `authorize`/`callback`), Fernet-encrypted `mcp_oauth_tokens` (migration 0051) reusing `app.security.encryption`'s pattern, refresh, and supplying the per-call `user_token` to `discover_tools`/`call_tool`. Retire `web/backend/open_webui/utils/mcp/client.py`.
</content>
