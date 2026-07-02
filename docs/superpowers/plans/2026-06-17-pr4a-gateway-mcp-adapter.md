# PR4a — Gateway MCP tool-provider adapter (WS2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `type: mcp` tool-provider to the gateway — a `streamable_http` MCP-protocol client, `mcp.yaml` loading, a live tool-discovery endpoint, and per-call `user_token` plumbing — so the api (PR4b/c) can broker MCP tools through the existing ADR-0014 egress boundary, with the gateway as the sole egress and MCP-protocol speaker.

**Architecture:** New `MCPToolProviderAdapter(ToolProviderAdapter)` in `gateway/app/providers/tool/mcp.py` ports the proven `web/backend/open_webui/utils/mcp/client.py` session logic (the `mcp` SDK becomes a gateway dependency). Each `mcp.yaml` entry is parsed and synthesized into a `type: mcp` `ToolProviderConfig` merged into `GatewayConfig.tool_providers` at load. `build_tool_adapter` gains an `mcp` branch. `route_tool_call` + the adapter contract gain an optional per-call `user_token` (for `auth: oauth` servers; never logged). A new `GET /v1/tools/{provider}` returns live `list_tools`. Every outbound call passes `validate_egress_target`.

**Tech Stack:** Python 3.12, FastAPI, httpx, the `mcp` SDK **1.28.x** (streamable_http client; `mcp.types.ToolAnnotations` for `readOnlyHint`/`destructiveHint`), Pydantic v2, pytest + respx. mypy `--strict` (gateway).

**Scope:** PR4a is the gateway slice only (security review → Kevin merges). PR4b (api registry/cache/admin) and PR4c (api per-user OAuth) are separate plans written against PR4a as merged. Per the spec `docs/superpowers/specs/2026-06-17-mcp-client-ws2-design.md`.

**Pre-flight facts (from main-loop research; subagents have no network):**
- The `mcp` SDK client API to port is exactly what `web/backend/open_webui/utils/mcp/client.py` already uses: `from mcp import ClientSession`, `from mcp.client.streamable_http import streamablehttp_client`; `session.initialize()`, `session.list_tools()` → `result.tools` (each `tool.name`, `tool.description`, `tool.inputSchema`, `tool.annotations`), `session.call_tool(name, args)` → `result.content` / `result.isError`. The stub's `disconnect()` cancel-scope discipline (lines 141-172) is load-bearing — port it verbatim.
- Tool safety flags live on `tool.annotations` (a `mcp.types.ToolAnnotations | None`): `.readOnlyHint`, `.destructiveHint` (both `bool | None`).
- Gateway integration seams (exact): factory `build_tool_adapter` at `gateway/app/main.py:150-165`; startup loop `gateway/app/main.py:275-299`; `Router.route_tool_call` at `gateway/app/router.py:736-828`; `invoke_tool` abstract sig `gateway/app/providers/tool/base.py:125`; HTTP layer `gateway/app/api/tools.py:33-37,64-100`; config loader `gateway/app/config_loader.py:122-158`; config-path resolution `gateway/app/main.py:92-98,176-179`; `validate_egress_target` `gateway/app/providers/tool/egress.py:37-53`; `ToolProviderType` `gateway/app/config.py:150`; `tool_provider_by_name` `gateway/app/config.py:611-616`.
- Test patterns: adapter unit tests `gateway/tests/test_courtlistener_adapter.py` (respx + injected client + monkeypatched `app.providers.tool.egress._resolve_ips`); router tests `gateway/tests/test_route_tool_call.py` (`RecordingToolEgressLogWriter`); route tests `gateway/tests/test_tools_route.py`.

**Run-everything reminders (from the milestone handoff):**
- Gateway tests via host venv: `cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/pytest tests/<file>.py -q`. NOT docker compose.
- Gateway gates: `cd gateway && .venv/bin/ruff format --check app tests && .venv/bin/ruff check app tests && .venv/bin/mypy app` (mypy is `--strict`).
- Commit `-s` + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Stage files explicitly (never `git add -A`).

---

## File structure

| File | Responsibility |
|---|---|
| `gateway/pyproject.toml` (modify) | Add `mcp>=1.28,<2` dependency |
| `gateway/app/config.py` (modify) | New `MCPServerConfig` Pydantic model + `MCPAuthType` literal; helper to synthesize a `ToolProviderConfig` from it |
| `gateway/app/config_loader.py` (modify) | Load an optional second `MCP_CONFIG_PATH` YAML, parse to `MCPServerConfig[]`, merge synthesized `type: mcp` providers into `GatewayConfig.tool_providers` |
| `gateway/app/main.py` (modify) | `build_tool_adapter` gains `mcp` branch; `_resolve_config_path` companion `_resolve_mcp_config_path`; lifespan passes the mcp path to the loader |
| `gateway/app/providers/tool/mcp.py` (create) | `MCPToolProviderAdapter` — connect/list_tools/invoke_tool/health_check/aclose, annotation→flags mapping, per-call token auth, egress guard |
| `gateway/app/router.py` (modify) | `route_tool_call` + threading of optional `user_token` to `invoke_tool` |
| `gateway/app/providers/tool/base.py` (modify) | Add `user_token: str | None = None` kwarg to the `invoke_tool` / (new) `list_tools` discovery contract |
| `gateway/app/api/tools.py` (modify) | `ToolCallRequest.user_token`; new `GET /v1/tools/{provider}` discovery handler |
| `gateway.yaml.example` / `mcp.yaml.example` (modify/create) | Document the `mcp.yaml` shape |
| `docs/api/gateway-openapi.yaml` (modify) | Document `GET /v1/tools/{provider}` + the `user_token` body field |
| `gateway/tests/test_mcp_adapter.py` (create) | Adapter unit tests with a fake injected session |
| `gateway/tests/test_mcp_config.py` (create) | `mcp.yaml` load+merge tests |
| `gateway/tests/test_tools_route.py` (modify) | Discovery endpoint + `user_token` plumbing tests |

---

## Task 1: Add the `mcp` SDK dependency

**Files:**
- Modify: `gateway/pyproject.toml` (dependencies list, ~line 13-69)
- Test: `gateway/tests/test_mcp_import.py` (create, temporary smoke)

- [ ] **Step 1: Add the dependency**

In `gateway/pyproject.toml`, add to the `dependencies = [...]` list (alongside `"httpx>=0.27,<0.29"`), keeping the existing pinning style:

```toml
    "mcp>=1.28,<2",
```

- [ ] **Step 2: Install into the gateway venv**

Run: `cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/pip install 'mcp>=1.28,<2'`
Expected: installs `mcp` 1.28.x and its deps (anyio, httpx-sse, pydantic, etc.) with no conflicts.

- [ ] **Step 3: Write an import smoke test**

```python
# gateway/tests/test_mcp_import.py
import pytest


@pytest.mark.unit
def test_mcp_sdk_importable() -> None:
    from mcp import ClientSession  # noqa: F401
    from mcp.client.streamable_http import streamablehttp_client  # noqa: F401
    from mcp.types import ToolAnnotations  # noqa: F401
```

- [ ] **Step 4: Run it**

Run: `cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/pytest tests/test_mcp_import.py -q`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/kevinkeller/Code/lq-ai && git add gateway/pyproject.toml gateway/tests/test_mcp_import.py && git commit -s -m "PR4a: add mcp SDK dependency to the gateway

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `mcp.yaml` config schema + loader merge

**Files:**
- Modify: `gateway/app/config.py` (add models near `ToolProviderConfig`, ~line 210)
- Modify: `gateway/app/config_loader.py` (`load_config`, ~line 122-158)
- Modify: `gateway/app/main.py` (`_resolve_config_path` companion, lifespan)
- Create: `mcp.yaml.example`
- Test: `gateway/tests/test_mcp_config.py`

**Design:** `mcp.yaml` is a list under `mcp_servers:`. Each entry parses to `MCPServerConfig`, then `to_tool_provider_config()` synthesizes a `ToolProviderConfig` with `type="mcp"`, `base_url=server_url`, carrying `auth`, `egress_tier`, `allowlist`, `rate_limit`. The loader reads `MCP_CONFIG_PATH` (optional; absent ⇒ no MCP providers) and appends the synthesized providers to `tool_providers`.

- [ ] **Step 1: Write the failing config-model test**

```python
# gateway/tests/test_mcp_config.py
import pytest

from app.config import MCPServerConfig


@pytest.mark.unit
def test_mcp_server_config_synthesizes_tool_provider() -> None:
    s = MCPServerConfig(
        name="acme-mcp",
        server_url="https://mcp.acme.example/sse",
        auth="bearer",
        api_key_env="ACME_MCP_TOKEN",
        egress_tier=2,
        allowlist={"hosts": ["mcp.acme.example"]},
    )
    tp = s.to_tool_provider_config()
    assert tp.type == "mcp"
    assert tp.name == "acme-mcp"
    assert tp.base_url == "https://mcp.acme.example/sse"
    assert tp.egress_tier == 2
    assert tp.allowlist.hosts == ["mcp.acme.example"]
    # auth carried through extra fields (ToolProviderConfig is extra="allow")
    assert tp.auth == "bearer"


@pytest.mark.unit
def test_mcp_server_config_oauth_needs_no_static_key() -> None:
    s = MCPServerConfig(
        name="oauth-mcp",
        server_url="https://o.example/sse",
        auth="oauth",
        egress_tier=2,
        allowlist={"hosts": ["o.example"]},
    )
    assert s.to_tool_provider_config().auth == "oauth"
```

- [ ] **Step 2: Run it (fails — model not defined)**

Run: `cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/pytest tests/test_mcp_config.py -q`
Expected: FAIL — `ImportError: cannot import name 'MCPServerConfig'`.

- [ ] **Step 3: Implement the models**

In `gateway/app/config.py`, after `ToolProviderConfig` (~line 210):

```python
MCPAuthType = Literal["none", "bearer", "oauth"]
"""How the gateway authenticates to an MCP server. ``none``/``bearer`` use
operator-static config; ``oauth`` uses a per-call user token supplied by the
api (the gateway stays user-unaware — spec D4)."""


class MCPServerConfig(BaseModel):
    """One entry under ``mcp_servers:`` in ``mcp.yaml``. Synthesized into a
    ``type: mcp`` :class:`ToolProviderConfig` at load (spec D2)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    server_url: str = Field(min_length=1)
    auth: MCPAuthType = "none"
    api_key_env: str | None = None
    api_key_encrypted: str | None = None
    egress_tier: InferenceTier
    allowlist: EgressAllowlistConfig
    rate_limit: ToolProviderRateLimitConfig = Field(default_factory=ToolProviderRateLimitConfig)
    enabled: bool = True

    @model_validator(mode="after")
    def _bearer_needs_key(self) -> MCPServerConfig:
        if self.auth == "bearer" and not (self.api_key_env or self.api_key_encrypted):
            raise ValueError(
                f"MCP server {self.name!r}: auth 'bearer' requires api_key_env or api_key_encrypted."
            )
        if self.auth in ("none", "oauth") and (self.api_key_env or self.api_key_encrypted):
            raise ValueError(
                f"MCP server {self.name!r}: api_key_* is only valid with auth 'bearer'."
            )
        return self

    def to_tool_provider_config(self) -> ToolProviderConfig:
        return ToolProviderConfig(
            name=self.name,
            type="mcp",
            base_url=self.server_url,
            api_key_env=self.api_key_env,
            api_key_encrypted=self.api_key_encrypted,
            egress_tier=self.egress_tier,
            allowlist=self.allowlist,
            rate_limit=self.rate_limit,
            enabled=self.enabled,
            auth=self.auth,  # extra field; ToolProviderConfig is extra="allow"
        )
```

- [ ] **Step 4: Run the model test (passes)**

Run: `cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/pytest tests/test_mcp_config.py -q`
Expected: 2 passed.

- [ ] **Step 5: Write the loader-merge failing test**

```python
# append to gateway/tests/test_mcp_config.py
from pathlib import Path

from app.config_loader import load_config


@pytest.mark.unit
def test_load_config_merges_mcp_yaml(tmp_path: Path, monkeypatch) -> None:
    gw = tmp_path / "gateway.yaml"
    gw.write_text(Path("gateway.yaml.example").read_text())
    mcp = tmp_path / "mcp.yaml"
    mcp.write_text(
        "mcp_servers:\n"
        "  - name: acme-mcp\n"
        "    server_url: https://mcp.acme.example/sse\n"
        "    auth: none\n"
        "    egress_tier: 2\n"
        "    allowlist: {hosts: [mcp.acme.example]}\n"
    )
    cfg = load_config(gw, mcp_path=mcp)
    names = {tp.name: tp for tp in cfg.tool_providers}
    assert "acme-mcp" in names
    assert names["acme-mcp"].type == "mcp"


@pytest.mark.unit
def test_load_config_without_mcp_yaml_is_fine(tmp_path: Path) -> None:
    gw = tmp_path / "gateway.yaml"
    gw.write_text(Path("gateway.yaml.example").read_text())
    cfg = load_config(gw, mcp_path=tmp_path / "does-not-exist.yaml")
    assert all(tp.type != "mcp" for tp in cfg.tool_providers)
```

- [ ] **Step 6: Run it (fails — `load_config` has no `mcp_path`)**

Run: `cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/pytest tests/test_mcp_config.py -q`
Expected: FAIL — `TypeError: load_config() got an unexpected keyword argument 'mcp_path'`.

- [ ] **Step 7: Extend `load_config`**

In `gateway/app/config_loader.py`, change the signature to `def load_config(path: Path, *, mcp_path: Path | None = None) -> GatewayConfig:`. After the `GatewayConfig` is built and validated, if `mcp_path is not None and mcp_path.exists()`: read it with the same `${VAR}`-expansion path the main config uses, parse `mcp_servers:` into `list[MCPServerConfig]`, call `.to_tool_provider_config()` on each, and append to `config.tool_providers` (re-validate the merged `GatewayConfig` so a duplicate name / bad merge fails at load). Import `MCPServerConfig` from `app.config`. Keep the env-expansion DRY — reuse the existing helper that `load_config` already applies to the main YAML.

- [ ] **Step 8: Run the loader tests (pass)**

Run: `cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/pytest tests/test_mcp_config.py -q`
Expected: 4 passed.

- [ ] **Step 9: Wire the path in `main.py` + add `mcp.yaml.example`**

In `gateway/app/main.py`: add `_resolve_mcp_config_path()` mirroring `_resolve_config_path()` (env `MCP_CONFIG_PATH`; default = `mcp.yaml` sibling of the gateway config, returned only if it exists). In the lifespan (~line 176-179) pass `mcp_path=_resolve_mcp_config_path()` to `load_config(...)`. Create `mcp.yaml.example`:

```yaml
# mcp.yaml — operator-allowlisted MCP servers (spec D2). Loaded by the gateway
# (MCP_CONFIG_PATH; defaults to ./mcp.yaml). Each entry becomes a type: mcp
# tool-provider behind the same egress boundary as gateway.yaml tool_providers.
mcp_servers:
  - name: example-mcp
    server_url: https://mcp.example.com/sse
    auth: none              # none | bearer | oauth
    egress_tier: 2
    allowlist:
      hosts: [mcp.example.com]
    # auth: bearer -> also set api_key_env: EXAMPLE_MCP_TOKEN
    # auth: oauth  -> per-user token supplied by the api at call time (PR4c)
```

- [ ] **Step 10: Run the full config test module + commit**

Run: `cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/pytest tests/test_mcp_config.py -q`
Expected: 4 passed.

```bash
cd /Users/kevinkeller/Code/lq-ai && git add gateway/app/config.py gateway/app/config_loader.py gateway/app/main.py mcp.yaml.example gateway/tests/test_mcp_config.py && git commit -s -m "PR4a: mcp.yaml schema + loader merge into tool_providers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `MCPToolProviderAdapter` (core: connect / list_tools / invoke_tool)

**Files:**
- Create: `gateway/app/providers/tool/mcp.py`
- Test: `gateway/tests/test_mcp_adapter.py`

**Design:** Mirror `CourtListenerToolAdapter` structure (`from_config`, `validate_base_url`, `_result`, `aclose`). The MCP session is reached through an **injectable async factory** `session_factory(url, headers) -> async context manager yielding a connected `ClientSession`` so unit tests pass a fake and never touch the network. The default factory ports the web stub's `streamablehttp_client` + `ClientSession` + `initialize()` + the verbatim disconnect discipline. `validate_egress_target(server_url, allowlist=...)` runs before every connect. Annotation→flags mapping per spec §2.

- [ ] **Step 1: Write the failing adapter tests (fake session)**

```python
# gateway/tests/test_mcp_adapter.py
import pytest

from app.config import ToolProviderConfig
from app.providers.tool.base import ToolSpec
from app.providers.tool.mcp import MCPToolProviderAdapter


class _FakeTool:
    def __init__(self, name, description, input_schema, annotations=None):
        self.name = name
        self.description = description
        self.inputSchema = input_schema
        self.annotations = annotations


class _Ann:
    def __init__(self, read_only=None, destructive=None):
        self.readOnlyHint = read_only
        self.destructiveHint = destructive


class _FakeResult:
    def __init__(self, tools=None, content=None, is_error=False):
        self.tools = tools or []
        self.content = content
        self.isError = is_error

    def model_dump(self, mode="json"):
        return {"content": self.content}


class _FakeSession:
    def __init__(self, tools=None, call_result=None):
        self._tools = tools or []
        self._call_result = call_result

    async def initialize(self):
        return None

    async def list_tools(self):
        return _FakeResult(tools=self._tools)

    async def call_tool(self, name, args):
        return self._call_result


def _cfg() -> ToolProviderConfig:
    return ToolProviderConfig(
        name="acme-mcp",
        type="mcp",
        base_url="https://mcp.acme.example/sse",
        egress_tier=2,
        allowlist={"hosts": ["mcp.acme.example"]},
        auth="none",
    )


def _adapter(session: _FakeSession) -> MCPToolProviderAdapter:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def factory(url, headers):
        yield session

    return MCPToolProviderAdapter.from_config(_cfg(), session_factory=factory)


@pytest.mark.unit
async def test_list_tools_maps_annotations() -> None:
    tools = [
        _FakeTool("read_doc", "reads", {"type": "object"}, _Ann(read_only=True)),
        _FakeTool("delete_doc", "deletes", {"type": "object"}, _Ann(destructive=True)),
        _FakeTool("mystery", "no hints", {"type": "object"}, None),
    ]
    specs = await _adapter(_FakeSession(tools=tools)).list_tools()
    by = {s.name: s for s in specs}
    assert by["read_doc"].read_only and not by["read_doc"].requires_confirmation
    assert by["delete_doc"].destructive and by["delete_doc"].requires_confirmation
    # un-annotated -> safe default: not auto-runnable
    assert by["mystery"].requires_confirmation and not by["mystery"].read_only


@pytest.mark.unit
async def test_invoke_tool_returns_tool_result() -> None:
    res = _FakeResult(content=[{"type": "text", "text": "hi"}], is_error=False)
    out = await _adapter(_FakeSession(call_result=res)).invoke_tool(
        "read_doc", {"q": "x"}, request_id="r1"
    )
    assert out.provider == "acme-mcp"
    assert out.tool == "read_doc"
    assert out.payload == [{"type": "text", "text": "hi"}]


@pytest.mark.unit
async def test_invoke_tool_error_raises() -> None:
    from app.providers.tool.base import ToolProviderError

    res = _FakeResult(content=[{"type": "text", "text": "boom"}], is_error=True)
    with pytest.raises(ToolProviderError):
        await _adapter(_FakeSession(call_result=res)).invoke_tool("x", {}, request_id="r1")


@pytest.mark.unit
async def test_validate_base_url_rejects_non_allowlisted(monkeypatch) -> None:
    from app.providers.tool import egress
    monkeypatch.setattr(egress, "_resolve_ips", lambda host: ["93.184.216.34"])
    bad = ToolProviderConfig(
        name="x", type="mcp", base_url="https://evil.example/sse",
        egress_tier=2, allowlist={"hosts": ["mcp.acme.example"]}, auth="none",
    )
    a = MCPToolProviderAdapter.from_config(bad)
    from app.providers.tool.egress import EgressRefused
    with pytest.raises(EgressRefused):
        a.validate_base_url()
```

- [ ] **Step 2: Run (fails — module missing)**

Run: `cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/pytest tests/test_mcp_adapter.py -q`
Expected: FAIL — `ModuleNotFoundError: app.providers.tool.mcp`.

- [ ] **Step 3: Implement the adapter**

Create `gateway/app/providers/tool/mcp.py`:

```python
"""``mcp`` tool provider — Model Context Protocol egress (ADR 0014, WS2/PR4a).

The gateway is the sole egress AND the only MCP-protocol speaker (spec D1):
streamable_http sessions are stateful, so the holder of the connection must
speak MCP. Ports the proven client logic from
``web/backend/open_webui/utils/mcp/client.py`` behind an injectable session
factory so unit tests never touch the network. Every connect passes
``validate_egress_target`` (SSRF/allowlist)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable

from app.config import ToolProviderConfig
from app.providers.base import ProviderHealth
from app.providers.tool.base import (
    ToolProviderAdapter,
    ToolProviderError,
    ToolProviderNetworkError,
    ToolResult,
    ToolSpec,
)
from app.providers.tool.egress import validate_egress_target
from app.secrets import ProviderKeyResolver

SessionFactory = Callable[..., Any]  # (url, headers) -> async ctx mgr yielding a ClientSession


def _default_session_factory() -> SessionFactory:
    @asynccontextmanager
    async def factory(url: str, headers: dict[str, str] | None) -> AsyncIterator[Any]:
        # Port of web/backend/open_webui/utils/mcp/client.py connect/disconnect.
        from contextlib import AsyncExitStack

        import anyio
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with AsyncExitStack() as stack:
            transport = await stack.enter_async_context(
                streamablehttp_client(url, headers=headers)
            )
            read_stream, write_stream, _ = transport
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            with anyio.fail_after(10):
                await session.initialize()
            yield session

    return factory


def _map_flags(annotations: Any) -> tuple[bool, bool, bool]:
    """(read_only, destructive, requires_confirmation) from MCP tool annotations.

    Safe default for un-annotated tools: not read-only, not destructive, but
    requires_confirmation=True (treat unknown as needing the PR5 gate)."""
    read_only = bool(getattr(annotations, "readOnlyHint", False)) if annotations else False
    destructive = bool(getattr(annotations, "destructiveHint", False)) if annotations else False
    if read_only and not destructive:
        return True, False, False
    if destructive:
        return False, True, True
    return False, False, True  # un-annotated / ambiguous -> confirm


class MCPToolProviderAdapter(ToolProviderAdapter):
    def __init__(
        self,
        *,
        name: str,
        server_url: str,
        auth: str,
        api_key: str | None,
        allowlist: list[str],
        session_factory: SessionFactory | None = None,
    ) -> None:
        self.name = name
        self._server_url = server_url
        self._auth = auth
        self._api_key = api_key
        self._allowlist = allowlist
        self._session_factory = session_factory or _default_session_factory()

    @classmethod
    def from_config(
        cls,
        provider: ToolProviderConfig,
        *,
        key_resolver: ProviderKeyResolver | None = None,
        session_factory: SessionFactory | None = None,
    ) -> MCPToolProviderAdapter:
        if provider.type != "mcp":
            raise ValueError(f"MCPToolProviderAdapter from non-mcp {provider.type!r}")
        auth = getattr(provider, "auth", "none")
        api_key: str | None = None
        if auth == "bearer":
            resolver = key_resolver or ProviderKeyResolver.from_environ()
            api_key = resolver.resolve(
                provider_name=provider.name,
                api_key_env=provider.api_key_env,
                api_key_encrypted=provider.api_key_encrypted,
            )
            if not api_key:
                raise ValueError(f"MCP provider {provider.name!r}: bearer auth but no token resolved.")
        return cls(
            name=provider.name,
            server_url=provider.base_url,
            auth=auth,
            api_key=api_key,
            allowlist=provider.allowlist.hosts,
            session_factory=session_factory,
        )

    def validate_base_url(self) -> None:
        validate_egress_target(self._server_url, allowlist=self._allowlist)

    def _headers(self, user_token: str | None) -> dict[str, str] | None:
        if self._auth == "bearer" and self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        if self._auth == "oauth":
            if not user_token:
                raise ToolProviderError(
                    f"MCP server {self.name!r} requires per-user authorization",
                    details={"code": "mcp_authorization_required"},
                )
            return {"Authorization": f"Bearer {user_token}"}
        return None

    @asynccontextmanager
    async def _session(self, user_token: str | None) -> AsyncIterator[Any]:
        validate_egress_target(self._server_url, allowlist=self._allowlist)
        try:
            async with self._session_factory(self._server_url, self._headers(user_token)) as s:
                yield s
        except ToolProviderError:
            raise
        except Exception as exc:  # transport/protocol failure
            raise ToolProviderNetworkError(f"mcp session error: {exc}") from exc

    async def list_tools(self, *, user_token: str | None = None) -> list[ToolSpec]:
        async with self._session(user_token) as session:
            result = await session.list_tools()
        specs: list[ToolSpec] = []
        for tool in result.tools:
            read_only, destructive, requires_confirmation = _map_flags(
                getattr(tool, "annotations", None)
            )
            specs.append(
                ToolSpec(
                    name=tool.name,
                    description=tool.description or "",
                    parameters=tool.inputSchema or {"type": "object"},
                    read_only=read_only,
                    destructive=destructive,
                    requires_confirmation=requires_confirmation,
                )
            )
        return specs

    async def invoke_tool(
        self, tool: str, args: dict[str, Any], *, request_id: str, user_token: str | None = None
    ) -> ToolResult:
        async with self._session(user_token) as session:
            result = await session.call_tool(tool, args)
        dumped = result.model_dump(mode="json")
        content = dumped.get("content")
        if getattr(result, "isError", False):
            raise ToolProviderError("mcp tool returned an error", details={"content": content})
        return ToolResult(
            provider=self.name,
            tool=tool,
            payload=content,
            bytes_out=len(json.dumps(args).encode("utf-8")),
            bytes_in=len(json.dumps(content).encode("utf-8")),
            skip_anonymization=False,
        )

    async def health_check(self) -> ProviderHealth:
        try:
            async with self._session(None):
                pass
        except ToolProviderError as exc:
            return ProviderHealth(name=self.name, reachable=False, error=str(exc))
        return ProviderHealth(name=self.name, reachable=True, latency_ms=0)

    async def aclose(self) -> None:
        return None
```

NOTE on the abstract contract: this adds an optional `user_token` kwarg to `list_tools`/`invoke_tool`. Task 4 updates the ABC in `base.py` and the other two adapters (echo, courtlistener) to accept-and-ignore `user_token` so the contract stays uniform and mypy `--strict` passes.

- [ ] **Step 4: Run adapter tests**

Run: `cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/pytest tests/test_mcp_adapter.py -q`
Expected: 4 passed (the `validate_base_url` test needs Task 4's signature only if `list_tools` is called; it isn't here, so it passes now).

- [ ] **Step 5: Commit**

```bash
cd /Users/kevinkeller/Code/lq-ai && git add gateway/app/providers/tool/mcp.py gateway/tests/test_mcp_adapter.py && git commit -s -m "PR4a: MCPToolProviderAdapter (streamable_http, annotation->flags, egress-guarded)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Uniform `user_token` in the adapter contract + factory wiring

**Files:**
- Modify: `gateway/app/providers/tool/base.py` (abstract `list_tools`/`invoke_tool` sigs, ~line 120-126)
- Modify: `gateway/app/providers/tool/echo.py`, `gateway/app/providers/tool/courtlistener.py` (accept-and-ignore `user_token`)
- Modify: `gateway/app/main.py` (`build_tool_adapter` mcp branch, ~line 150-165)
- Test: `gateway/tests/test_tool_adapter_wiring.py` (extend)

- [ ] **Step 1: Write the failing wiring test**

```python
# add to gateway/tests/test_tool_adapter_wiring.py
import pytest

from app.config import ToolProviderConfig
from app.main import build_tool_adapter
from app.providers.tool.mcp import MCPToolProviderAdapter


@pytest.mark.unit
def test_build_tool_adapter_mcp(monkeypatch) -> None:
    from app.providers.tool import egress
    monkeypatch.setattr(egress, "_resolve_ips", lambda host: ["93.184.216.34"])
    cfg = ToolProviderConfig(
        name="acme-mcp", type="mcp", base_url="https://mcp.acme.example/sse",
        egress_tier=2, allowlist={"hosts": ["mcp.acme.example"]}, auth="none",
    )
    adapter = build_tool_adapter(cfg)
    assert isinstance(adapter, MCPToolProviderAdapter)
```

- [ ] **Step 2: Run (fails — mcp branch returns None)**

Run: `cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/pytest tests/test_tool_adapter_wiring.py::test_build_tool_adapter_mcp -q`
Expected: FAIL — `assert None is MCPToolProviderAdapter` (build returns `None` today).

- [ ] **Step 3: Update the ABC + the two existing adapters + the factory**

In `gateway/app/providers/tool/base.py`, change the abstract methods to:
```python
    @abstractmethod
    async def list_tools(self, *, user_token: str | None = None) -> list[ToolSpec]: ...

    @abstractmethod
    async def invoke_tool(
        self, tool: str, args: dict[str, Any], *, request_id: str, user_token: str | None = None
    ) -> ToolResult: ...
```
In `echo.py` and `courtlistener.py`, add `user_token: str | None = None` to both method signatures (ignore it — those providers don't use per-user auth). In `gateway/app/main.py` `build_tool_adapter`, replace the `# mcp (PR4) lands later. return None` tail with:
```python
    if provider.type == "mcp":
        from app.providers.tool.mcp import MCPToolProviderAdapter

        mcp_adapter = MCPToolProviderAdapter.from_config(provider)
        mcp_adapter.validate_base_url()
        return mcp_adapter
    return None
```

- [ ] **Step 4: Run wiring + existing adapter tests**

Run: `cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/pytest tests/test_tool_adapter_wiring.py tests/test_courtlistener_adapter.py tests/test_mcp_adapter.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/kevinkeller/Code/lq-ai && git add gateway/app/providers/tool/base.py gateway/app/providers/tool/echo.py gateway/app/providers/tool/courtlistener.py gateway/app/main.py gateway/tests/test_tool_adapter_wiring.py && git commit -s -m "PR4a: wire mcp into build_tool_adapter; uniform user_token in adapter contract

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Thread `user_token` through `route_tool_call` + the transport

**Files:**
- Modify: `gateway/app/router.py` (`route_tool_call`, ~line 736-828)
- Modify: `gateway/app/api/tools.py` (`ToolCallRequest`, `call_tool` handler)
- Test: `gateway/tests/test_route_tool_call.py`, `gateway/tests/test_tools_route.py`

- [ ] **Step 1: Write the failing router test**

```python
# add to gateway/tests/test_route_tool_call.py — assert user_token reaches the adapter
# and never appears in the audit row.
import pytest


class _CaptureAdapter:
    name = "acme-mcp"
    captured_token = None

    async def invoke_tool(self, tool, args, *, request_id, user_token=None):
        type(self).captured_token = user_token
        from app.providers.tool.base import ToolResult
        return ToolResult(provider=self.name, tool=tool, payload={"ok": True})

    async def list_tools(self, *, user_token=None):
        return []


@pytest.mark.unit
async def test_route_tool_call_threads_user_token() -> None:
    # Build a Router whose tool_provider config has an mcp provider named acme-mcp
    # (reuse the _router(...) helper already in this file; add a type: mcp provider
    # to its config + register _CaptureAdapter() in the adapters dict).
    router, recorder = _router_with_mcp_capture()  # helper added below
    await router.route_tool_call(
        "acme-mcp", "read_doc", {"q": "x"}, request_id="r1", user_token="secret-user-token"
    )
    assert _CaptureAdapter.captured_token == "secret-user-token"
    # audit row must NOT contain the token anywhere
    row = recorder.rows[-1]
    assert "secret-user-token" not in str(row.__dict__)
```

Add a `_router_with_mcp_capture()` helper next to the existing `_router(...)` in the file: build a `GatewayConfig` with a `type: mcp` `ToolProviderConfig` named `acme-mcp` (egress_tier 2, allowlist hosts `["mcp.acme.example"]`, `auth="none"`), an adapters dict `{"acme-mcp": _CaptureAdapter()}`, and a `RecordingToolEgressLogWriter`.

- [ ] **Step 2: Run (fails — `route_tool_call` has no `user_token`)**

Run: `cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/pytest tests/test_route_tool_call.py::test_route_tool_call_threads_user_token -q`
Expected: FAIL — `TypeError: unexpected keyword argument 'user_token'`.

- [ ] **Step 3: Add `user_token` to `route_tool_call`**

In `gateway/app/router.py`, add `user_token: str | None = None` to the `route_tool_call` keyword-only args, and pass it to the adapter at the invoke site (`router.py:797`):
```python
result = await adapter.invoke_tool(tool, args, request_id=request_id, user_token=user_token)
```
Do NOT add `user_token` to any `ToolEgressLogRow` (it must never be persisted). Confirm by inspection that no log-row construction references it.

- [ ] **Step 4: Run router test (passes)**

Run: `cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/pytest tests/test_route_tool_call.py -q`
Expected: all pass.

- [ ] **Step 5: Add `user_token` to the transport body + handler**

In `gateway/app/api/tools.py`, add to `ToolCallRequest`:
```python
    user_token: str | None = Field(default=None)
```
and pass `user_token=body.user_token` into `gw_router.route_tool_call(...)` in the `call_tool` handler.

- [ ] **Step 6: Write + run the transport test**

```python
# add to gateway/tests/test_tools_route.py — POST with user_token reaches route_tool_call.
# Use the existing app/AsyncClient fixture; monkeypatch the router's route_tool_call
# to capture kwargs, POST {"args": {...}, "user_token": "t"} and assert it was forwarded.
```
Run: `cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/pytest tests/test_tools_route.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd /Users/kevinkeller/Code/lq-ai && git add gateway/app/router.py gateway/app/api/tools.py gateway/tests/test_route_tool_call.py gateway/tests/test_tools_route.py && git commit -s -m "PR4a: thread optional per-call user_token transport->router->adapter (never logged)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `GET /v1/tools/{provider}` discovery endpoint

**Files:**
- Modify: `gateway/app/api/tools.py` (new handler)
- Modify: `docs/api/gateway-openapi.yaml` (document the route + `user_token`)
- Test: `gateway/tests/test_tools_route.py`

- [ ] **Step 1: Write the failing discovery test**

```python
# add to gateway/tests/test_tools_route.py
@pytest.mark.unit
async def test_discovery_lists_tools(gateway_app) -> None:
    # The example config wires an echo tool-provider; GET its tools.
    async with httpx_async_client(gateway_app) as client:  # match the file's client helper
        resp = await client.get("/v1/tools/echo-test", headers=_key_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "echo-test"
    assert any(t["name"] == "echo" for t in body["tools"])


@pytest.mark.unit
async def test_discovery_unknown_provider_404(gateway_app) -> None:
    async with httpx_async_client(gateway_app) as client:
        resp = await client.get("/v1/tools/nope", headers=_key_headers())
    assert resp.status_code == 404
```
(Use the same app fixture, key headers, and client helper the other tests in this file use — match them exactly; the echo provider name in `gateway.yaml.example` is the one already used by the POST happy-path test.)

- [ ] **Step 2: Run (fails — no GET route)**

Run: `cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/pytest tests/test_tools_route.py -k discovery -q`
Expected: FAIL — 405/404 (route not registered).

- [ ] **Step 3: Implement the handler**

In `gateway/app/api/tools.py`, add (same `require_gateway_key` router, so it's key-gated):
```python
@router.get("/tools/{provider}")
async def list_provider_tools(
    provider: str, request: Request, user_token: str | None = None
) -> JSONResponse:
    # user_token is an optional query param so an `auth: oauth` server can be
    # discovered with the user's token (PR4c supplies it). For none/bearer
    # servers it is ignored. Never logged.
    gw_router = _router(request)
    adapter = gw_router._tool_adapters.get(provider)
    if adapter is None:
        return _error(404, "unknown_provider", f"tool provider {provider!r} not found")
    try:
        specs = await adapter.list_tools(user_token=user_token)
    except ToolProviderError as exc:
        return _error(502, "tool_provider_unavailable", exc.message, exc.details)
    return JSONResponse(
        content={
            "provider": provider,
            "tools": [
                {
                    "name": s.name,
                    "description": s.description,
                    "parameters": s.parameters,
                    "read_only": s.read_only,
                    "destructive": s.destructive,
                    "requires_confirmation": s.requires_confirmation,
                }
                for s in specs
            ],
        }
    )
```
(Accessing `gw_router._tool_adapters` mirrors how `route_tool_call` reaches them; if the Router exposes a public accessor, prefer it — check `router.py` and match the existing style.)

- [ ] **Step 4: Run discovery tests**

Run: `cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/pytest tests/test_tools_route.py -q`
Expected: all pass.

- [ ] **Step 5: Document in `gateway-openapi.yaml`**

Add `GET /v1/tools/{provider}` (key-gated; 200 → `{provider, tools:[{name, description, parameters, read_only, destructive, requires_confirmation}]}`; 404 unknown provider; 502 provider unavailable) next to the existing `POST /v1/tools/{provider}/{tool}` entry, and add the optional `user_token` field to the POST request-body schema. Match the file's existing style. If the gateway test-suite has a route-count/conformance guard (mirror of the api's `test_openapi.py` — check `gateway/tests/`), update it in this commit.

- [ ] **Step 6: Commit**

```bash
cd /Users/kevinkeller/Code/lq-ai && git add gateway/app/api/tools.py docs/api/gateway-openapi.yaml gateway/tests/test_tools_route.py && git commit -s -m "PR4a: GET /v1/tools/{provider} discovery endpoint

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Full-suite gates + retire-stub note

**Files:** none (verification) — plus a one-line note that the `web/` stub is retired in PR4c (not here; it's still imported by web/ until then).

- [ ] **Step 1: Run the full gateway gates**

Run:
```
cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/pytest -q
cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/ruff format --check app tests && .venv/bin/ruff check app tests
cd /Users/kevinkeller/Code/lq-ai/gateway && .venv/bin/mypy app
```
Expected: all green (mypy `--strict` clean — pay attention to the `Any` session-factory types; add precise `# type:` or `cast` where the `mcp` SDK lacks stubs, rather than blanket `ignore`).

- [ ] **Step 2: Confirm no secret leakage**

Grep the diff: `git diff main...HEAD | grep -i -E "user_token|api_key|Authorization"` and confirm `user_token`/tokens never reach a `ToolEgressLogRow`, a `log.*`, or the discovery payload.

- [ ] **Step 3: Final commit (if any formatting fixups)**

```bash
cd /Users/kevinkeller/Code/lq-ai && git add -p   # stage only intended hunks
git commit -s -m "PR4a: gate fixups

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Definition of done (PR4a)
- `mcp.yaml.example` parses; an `mcp_servers:` entry becomes a `type: mcp` tool-provider at gateway startup (config test).
- `MCPToolProviderAdapter` connects via streamable_http (injectable factory), maps annotations→`ToolSpec` flags (un-annotated ⇒ `requires_confirmation`), invokes tools, guards egress.
- `none`/`bearer` auth fully functional; `oauth` refuses with `mcp_authorization_required` when no `user_token` is supplied (PR4c will supply it).
- `GET /v1/tools/{provider}` returns live discovery; `POST /v1/tools/{provider}/{tool}` accepts an optional `user_token`; tokens are never logged.
- Gateway `pytest` + `ruff` (format & check) + `mypy --strict` all green.
- **Gate:** `gateway/**` → security review → **Kevin reviews/merges** (offer review-vs-self).

## Follow-on (separate plans, written against PR4a as merged)
- **PR4b (api, self-merge):** `api/app/mcp/` registry (filter `list_tool_providers` to `type==mcp`), discovery DB-cache (migration 0050 `mcp_tools`), per-tool enable/disable, `/api/v1/admin/mcp` list/refresh. Works for `none`/`bearer` servers.
- **PR4c (api, security review):** per-user OAuth (authz-code+PKCE `authorize`/`callback`), Fernet-encrypted `mcp_oauth_tokens`, refresh, per-call `user_token` plumbing to the gateway. Retire `web/backend/open_webui/utils/mcp/client.py`.
</content>
