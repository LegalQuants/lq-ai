# PR5b — Governed chat tool-loop + confirmation gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give interactive chat a real multi-step tool-calling loop over an operator-enabled allowlist of CourtListener + MCP tools, governed per-call through PR5a's `governed_tool_invocation`, with a persist-and-resume human confirmation gate for destructive tools.

**Architecture:** The api assembles a per-turn tool allowlist (research function schemas when CourtListener is enabled + enabled MCP tools), then drives a **non-streaming** tool-decision loop against the gateway: each round the model returns either a final answer or tool-call(s); `read_only` tools execute inline through the shared governance substrate and feed results back; `destructive`/`requires_confirmation` tools persist resume state and end the turn with a terminal SSE event; a separate POST resumes. The final answer is emitted as SSE delta frames (streaming endpoint) or JSON (non-streaming). The only `gateway/**` change is adding `tools`/`tool_choice` to the request schema and bridging Anthropic's non-streaming `tool_use`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Alembic, Pydantic v2, httpx/respx, pytest. Two services: `api/` (standard mypy) and `gateway/` (mypy `--strict`).

## Global Constraints

- **Branch:** `feat/pr5b-chat-tool-loop` off `main` (`36223de`). Push `origin` + `tucuxi`. `origin/main` is PROTECTED — PR + GitHub merge only; sync tucuxi after. **Security-gated** (touches the chat send path + a gateway capability) → **Kevin reviews/merges**; do not self-merge.
- **ruff pinned `==0.15.17`** in both venvs. Run BOTH `ruff format` and `ruff check` (separate CI gates) + `mypy app` (gateway is `--strict`).
- **Tests via host venv, NOT docker.** Gateway: `cd gateway && .venv/bin/pytest tests/X -v`. API: `cd api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest tests/X -v` (throwaway pgvector on :15433; conftest auto-migrates). NEVER host `alembic upgrade` against the dev DB (:15432). NEVER `docker compose down -v`.
- **Commit trailer (every commit):** `git commit -s` plus `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Stage explicitly — never `git add -A`.
- **Subagents have no network** — `pip install` happens in the controller before dispatch. No deps are added by this PR.
- **Collision guards (crash the whole api suite at collection):** a new route → add to `IMPLEMENTED_ROUTES` (`api/tests/test_endpoints.py`) AND bump the pinned path count + `EXPECTED_PATHS` set (`api/tests/test_openapi.py`, currently **132 → 133**) AND update `docs/api/backend-openapi.yaml` (hand-maintained, DE-337). 204 DELETE needs `response_class=Response`. Decimal cost fields serialize as JSON **strings**.
- **Migration head 0053 → 0054.** Verify migrations on a throwaway pgvector container (conftest), never the dev DB.

## Locked decisions (from the spec + forks resolved with Kevin 2026-06-19)

- **L1–L6** per `docs/superpowers/specs/2026-06-18-pr5-governed-chat-tool-loop-design.md`. PR5a is merged; reuse `app/tools/governance.py::governed_tool_invocation` **unmodified**.
- **Fork 1 (loop streaming) = "non-stream rounds, stream final".** Tool-decision rounds call the gateway **non-streaming**; the final answer is emitted as SSE delta frame(s). Gateway needs only Anthropic **non-streaming** `tool_use` bridging — **no** streaming `tool_use` delta work. Empty allowlist ⇒ unchanged single-shot streaming.
- **Fork 2 (tier ceiling) = `max_allowed_tier=None`.** Mirror PR5a's autonomous path; the gateway's own per-provider egress-tier policy is the enforcement authority (defense-in-depth). Document the deviation from the spec's cross-cutting note.
- **Per-turn cap = 8**, operator-overridable via a settings field.
- **Confirmation gate = persist-and-resume.** Resume state lives in a NEW dedicated table (`chat_pending_tool_call`), NOT on `tool_call_log` (which stays counts-only). The pending row carries the call args + the conversation-so-far (same sensitivity class as `messages.content`, stored the same way).
- **MCP tool function-name scheme = `mcp__{server}__{tool}`** (OpenAI function-name charset `^[A-Za-z0-9_-]+$`; no dots). Research tools use bare op names.

---

## File Structure

**New files (api):**
- `api/app/chat/__init__.py` — package marker.
- `api/app/chat/tool_schemas.py` — fixed research function schemas + allowlist assembly + the function-name↔ToolSpec resolver.
- `api/app/chat/tool_loop.py` — the loop engine + typed outcomes + dispatch closures.
- `api/app/models/chat_pending_tool_call.py` — the resume-state model.
- `api/alembic/versions/0054_*.py` — `chat_pending_tool_call` migration.

**Modified files (gateway — the only `gateway/**` surface):**
- `gateway/app/providers/openai_schema.py` — add `tools`/`tool_choice` to `ChatCompletionRequest`.
- `gateway/app/providers/anthropic.py` — forward request tools/tool_choice; extract non-streaming `tool_use` → `tool_calls`.

**Modified files (api):**
- `api/app/schemas/gateway.py` — add `tools`/`tool_choice` to the api `ChatCompletionRequest`.
- `api/app/clients/gateway.py` — add `user_token` param to `call_tool`.
- `api/app/config.py` (settings) — add `chat_tool_call_cap` (default 8).
- `api/app/api/chats.py` — assemble allowlist in `send_message`; tool-loop stream/non-stream variants; new resume route.
- `api/app/schemas/chats.py` (or wherever `MessagePostResponse` lives) — gate-payload response fields for the non-streaming path + resume request body schema.
- `docs/api/backend-openapi.yaml` — the new route.
- `api/tests/test_openapi.py`, `api/tests/test_endpoints.py` — collision guards.

**New test files (api):** `api/tests/chat/test_tool_schemas.py`, `api/tests/chat/test_tool_loop.py`, `api/tests/integration/test_chat_tool_loop_send.py`, `api/tests/integration/test_chat_tool_call_resume.py`, `api/tests/test_chat_pending_tool_call_model.py`.
**New test files (gateway):** extend `gateway/tests/providers/test_anthropic.py` (or the existing anthropic test module) + a schema test.

---

## Task 1 (gateway/** — security-gated): Anthropic non-streaming tool_use bridging + request `tools`/`tool_choice`

**Files:**
- Modify: `gateway/app/providers/openai_schema.py` (`ChatCompletionRequest`, ~line 144–167)
- Modify: `gateway/app/providers/anthropic.py` (`_to_anthropic_request` ~338–409; `_from_anthropic_response` ~415–458; `STOP_REASON_MAP` ~90)
- Test: `gateway/tests/providers/test_anthropic.py` (extend), `gateway/tests/providers/test_openai_schema.py` (extend or create)

**Interfaces:**
- Consumes: nothing from other tasks (first task).
- Produces: a gateway `chat_completion` that, given `tools`/`tool_choice` in the request, forwards them to Anthropic and returns `response.choices[0].message.tool_calls` (OpenAI shape: `[{"id","type":"function","function":{"name","arguments"(JSON string)}}]`) with `finish_reason="tool_calls"`. OpenAI/Ollama already do this (regression-verify only).

Background (verified against `main`): OpenAI/Azure forward `tools`/`tool_choice` via `model_dump()` of `extra="allow"` and pass tool_calls through; Ollama forwards them explicitly (`ollama.py:476-482`) and round-trips assistant `tool_calls`. **Anthropic does neither.** `STOP_REASON_MAP` already maps `"tool_use" → "tool_calls"`. Tool-*result* incoming messages are already translated to Anthropic `tool_result` blocks (`anthropic.py:374-389`); assistant messages carrying `tool_calls` are currently flattened to text (acceptable for v1 — the loop re-sends the full OpenAI-shaped history and Anthropic is stateless per call; **but** the assistant `tool_use` turn MUST round-trip so Anthropic accepts the following `tool_result`. See Step 5.)

- [ ] **Step 1: Write failing schema test for explicit `tools`/`tool_choice` fields**

In `gateway/tests/providers/test_openai_schema.py`:
```python
from gateway.app.providers.openai_schema import ChatCompletionRequest


def test_chat_completion_request_accepts_tools_and_tool_choice():
    req = ChatCompletionRequest(
        model="smart",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "verify_citations", "parameters": {}}}],
        tool_choice="auto",
    )
    assert req.tools is not None and req.tools[0]["function"]["name"] == "verify_citations"
    assert req.tool_choice == "auto"
    # Round-trips through model_dump (the OpenAI adapter serializes this).
    dumped = req.model_dump(mode="json", exclude_none=True)
    assert "tools" in dumped and "tool_choice" in dumped
```

- [ ] **Step 2: Run it; expect FAIL** — `cd gateway && .venv/bin/pytest tests/providers/test_openai_schema.py -v` → FAIL (`tools` lands in `model_extra`, attribute access via `req.tools` raises `AttributeError`).

- [ ] **Step 3: Add explicit fields to `ChatCompletionRequest`** (after `n:` ~line 167):
```python
    # --- Function/tool calling (PR5b) ---------------------------------------
    tools: list[dict[str, Any]] | None = None
    """OpenAI-style tool/function declarations. Forwarded to the provider
    so the model may emit ``tool_calls``. The backend assembles a closed
    allowlist per turn (research + operator-enabled MCP tools); the
    gateway's egress-tier / SSRF guards still gate the eventual call."""

    tool_choice: str | dict[str, Any] | None = None
    """OpenAI-style tool_choice (``"auto"`` / ``"none"`` / a forced
    function). Forwarded verbatim to providers that support it."""
```
(`Any` is already imported in this module.)

- [ ] **Step 4: Run it; expect PASS.**

- [ ] **Step 5: Write failing Anthropic round-trip test**

In `gateway/tests/providers/test_anthropic.py`, add (follow the module's existing respx + adapter-construction fixtures):
```python
@pytest.mark.asyncio
async def test_anthropic_forwards_tools_and_surfaces_tool_calls(respx_mock):
    captured = {}

    def _capture(request):
        import json as _j
        captured["body"] = _j.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "stop_reason": "tool_use",
                "content": [
                    {"type": "text", "text": "Let me check."},
                    {"type": "tool_use", "id": "toolu_1", "name": "verify_citations",
                     "input": {"text": "Brown v. Board"}},
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

    respx_mock.post("https://api.anthropic.com/v1/messages").mock(side_effect=_capture)

    adapter = _make_anthropic_adapter()  # existing helper in this module
    req = ChatCompletionRequest(
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": "verify this"}],
        tools=[{"type": "function",
                "function": {"name": "verify_citations",
                             "parameters": {"type": "object",
                                            "properties": {"text": {"type": "string"}}}}}],
        tool_choice="auto",
    )
    resp = await adapter.chat_completion(req, model="claude-sonnet-4-6", stream=False)

    # Request side: Anthropic-shaped tools forwarded.
    assert captured["body"]["tools"][0]["name"] == "verify_citations"
    assert "input_schema" in captured["body"]["tools"][0]
    assert captured["body"]["tool_choice"] == {"type": "auto"}
    # Response side: tool_use -> OpenAI tool_calls.
    msg = resp.choices[0].message
    assert resp.choices[0].finish_reason == "tool_calls"
    assert msg.tool_calls[0]["id"] == "toolu_1"
    assert msg.tool_calls[0]["function"]["name"] == "verify_citations"
    import json as _j
    assert _j.loads(msg.tool_calls[0]["function"]["arguments"]) == {"text": "Brown v. Board"}
```

- [ ] **Step 6: Run it; expect FAIL** (tools not forwarded; tool_calls empty).

- [ ] **Step 7: Forward `tools`/`tool_choice` in `_to_anthropic_request`**

Anthropic's Messages API uses `tools: [{name, description, input_schema}]` (not the OpenAI `{type:function, function:{...}}` envelope) and `tool_choice: {"type": "auto"|"any"|"tool", "name"?}`. Before `return body` in `_to_anthropic_request` (~line 408):
```python
    extra = request.model_extra or {}
    raw_tools = request.tools if request.tools is not None else extra.get("tools")
    if raw_tools:
        anthropic_tools: list[dict[str, Any]] = []
        for t in raw_tools:
            fn = t.get("function", t) if isinstance(t, dict) else {}
            anthropic_tools.append(
                {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", "") or "",
                    "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
                }
            )
        body["tools"] = anthropic_tools

        raw_choice = request.tool_choice if request.tool_choice is not None else extra.get("tool_choice")
        if raw_choice is None or raw_choice == "auto":
            body["tool_choice"] = {"type": "auto"}
        elif raw_choice == "none":
            # Anthropic has no "none"; omit tools to disable. Honor by dropping tools.
            body.pop("tools", None)
        elif raw_choice == "required":
            body["tool_choice"] = {"type": "any"}
        elif isinstance(raw_choice, dict):
            fn = raw_choice.get("function", {})
            if fn.get("name"):
                body["tool_choice"] = {"type": "tool", "name": fn["name"]}
```

- [ ] **Step 8: Extract `tool_use` blocks in `_from_anthropic_response`**

After the text-extraction loop (~line 427), and update the returned message (~line 454):
```python
    tool_calls: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_calls.append(
                {
                    "id": str(block.get("id", "")),
                    "type": "function",
                    "function": {
                        "name": str(block.get("name", "")),
                        # OpenAI tool_calls carry arguments as a JSON STRING.
                        "arguments": _json.dumps(block.get("input") or {}),
                    },
                }
            )
    message = ChatCompletionMessage(
        role="assistant",
        content=text or None,
        tool_calls=tool_calls or None,
    )
```
Ensure `_json` (stdlib `json`) is imported at module top; if the module uses a different alias, match it. The `finish_reason` already derives from `STOP_REASON_MAP["tool_use"] = "tool_calls"`.

- [ ] **Step 9: Round-trip the assistant tool_use turn back to Anthropic** (so a follow-up `tool_result` is accepted). In `_to_anthropic_request`, where assistant messages are built (~line 391), if `msg.role == "assistant"` and `msg.tool_calls`:
```python
        if msg.role == "assistant" and msg.tool_calls:
            content_blocks: list[dict[str, Any]] = []
            if msg.content:
                content_blocks.append({"type": "text", "text": msg.content})
            for tc in msg.tool_calls:
                fn = tc.get("function", {})
                try:
                    parsed_input = _json.loads(fn.get("arguments") or "{}")
                except (ValueError, TypeError):
                    parsed_input = {}
                content_blocks.append(
                    {"type": "tool_use", "id": tc.get("id", ""),
                     "name": fn.get("name", ""), "input": parsed_input}
                )
            chat_messages.append({"role": "assistant", "content": content_blocks})
            continue  # skip the default text-only append below
```
Place this branch BEFORE the existing default `{"role": msg.role, "content": content}` append. Remove/adjust the old "tool-call assistant messages passed through as text only" DE comment.

- [ ] **Step 10: Add a multi-hop round-trip test** (assistant tool_use → tool message → final answer) asserting Anthropic receives the `tool_use` block then a `user` message with a `tool_result` block, and returns `finish_reason="stop"` with text. (Mirror the Step 5 fixture; second mocked response has `stop_reason="end_turn"`, content `[{"type":"text","text":"Confirmed."}]`.)

- [ ] **Step 11: Regression-verify OpenAI + Ollama still forward tools.** Add a one-liner assertion to each adapter's existing request test that `tools`/`tool_choice` appear in the upstream body when set (they already pass through; this pins it).

- [ ] **Step 12: Run the full gateway suite + lint.**
```bash
cd gateway && .venv/bin/pytest tests/ -q && .venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy app
```
Expected: all green (`--strict` mypy).

- [ ] **Step 13: Commit.**
```bash
git add gateway/app/providers/openai_schema.py gateway/app/providers/anthropic.py gateway/tests/providers/
git commit -s -m "feat(gateway): forward tools/tool_choice + bridge Anthropic non-streaming tool_use

PR5b dependency: the chat tool-loop drives non-streaming completions with
function schemas. OpenAI/Ollama already forward tools and surface tool_calls;
Anthropic now forwards request tools (OpenAI->Anthropic input_schema/tool_choice
mapping), extracts tool_use response blocks into OpenAI-shaped tool_calls, and
round-trips the assistant tool_use turn so a follow-up tool_result is accepted.
No streaming tool_use delta work (loop uses non-streaming rounds; final answer
streams as text). Refs ADR 0015.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2 (api): thread the per-user OAuth token through `GatewayClient.call_tool`

**Files:**
- Modify: `api/app/clients/gateway.py` (`call_tool` ~689)
- Modify: `api/app/schemas/gateway.py` (`ChatCompletionRequest` — add `tools`/`tool_choice`)
- Test: `api/tests/clients/test_gateway_call_tool.py` (extend or create)

**Interfaces:**
- Consumes: nothing.
- Produces: `GatewayClient.call_tool(provider, tool, args, *, max_allowed_tier=None, user_token=None, request_id=None) -> dict` — sets `X-LQ-AI-User-Token` header when `user_token` is given (the gateway route already reads it, `gateway/app/api/tools.py:110-124`). And the api `ChatCompletionRequest` carrying `tools`/`tool_choice` for the loop.

- [ ] **Step 1: Failing test for the api request-schema fields.** In a schema test:
```python
from app.schemas.gateway import ChatCompletionRequest

def test_api_chat_request_carries_tools():
    req = ChatCompletionRequest(
        model="smart",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}],
        tool_choice="auto",
    )
    assert req.tools[0]["function"]["name"] == "x"
    assert req.tool_choice == "auto"
```

- [ ] **Step 2: Run; expect FAIL.**

- [ ] **Step 3: Add fields** to `api/app/schemas/gateway.py::ChatCompletionRequest` (after `n:` ~line 114):
```python
    tools: list[dict[str, Any]] | None = None
    """PR5b: per-turn closed allowlist of function schemas the backend
    assembles (research + operator-enabled MCP tools). Forwarded to the
    gateway, which forwards to the provider."""
    tool_choice: str | dict[str, Any] | None = None
```

- [ ] **Step 4: Run; expect PASS.**

- [ ] **Step 5: Failing test for `user_token` header on `call_tool`.**
```python
@pytest.mark.asyncio
async def test_call_tool_sets_user_token_header(respx_mock):
    captured = {}
    def _cap(request):
        captured["hdr"] = request.headers.get("X-LQ-AI-User-Token")
        return httpx.Response(200, json={"provider": "p", "tool": "t", "payload": {}, "tier": 1})
    respx_mock.post("http://gw/v1/tools/p/t").mock(side_effect=_cap)
    client = _make_gateway_client(base_url="http://gw")  # existing helper
    await client.call_tool("p", "t", {"a": 1}, user_token="secret-tok")
    assert captured["hdr"] == "secret-tok"

@pytest.mark.asyncio
async def test_call_tool_omits_user_token_header_when_none(respx_mock):
    captured = {}
    def _cap(request):
        captured["hdr"] = request.headers.get("X-LQ-AI-User-Token")
        return httpx.Response(200, json={"provider": "p", "tool": "t", "payload": {}, "tier": 1})
    respx_mock.post("http://gw/v1/tools/p/t").mock(side_effect=_cap)
    client = _make_gateway_client(base_url="http://gw")
    await client.call_tool("p", "t", {"a": 1})
    assert captured["hdr"] is None
```

- [ ] **Step 6: Run; expect FAIL.**

- [ ] **Step 7: Add the param.** In `call_tool` (~689) add `user_token: str | None = None` to the keyword-only params, then after `headers = self._build_headers(request_id=request_id)`:
```python
        if user_token is not None:
            # Per-user OAuth token for `auth: oauth` MCP servers. Header,
            # never query/body (PR4c discipline — keeps it out of access
            # logs and never written to tool_egress_log).
            headers["X-LQ-AI-User-Token"] = user_token
```
Update the docstring to note the new param mirrors `discover_tools`.

- [ ] **Step 8: Run; expect PASS.**

- [ ] **Step 9: Lint + commit.**
```bash
cd api && .venv/bin/ruff format api/app/clients/gateway.py api/app/schemas/gateway.py && .venv/bin/ruff check api/app/clients/gateway.py api/app/schemas/gateway.py && .venv/bin/mypy app
git add api/app/clients/gateway.py api/app/schemas/gateway.py api/tests/
git commit -s -m "feat(api): thread per-user OAuth token through call_tool; add tools/tool_choice to chat request

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3 (api): allowlist assembly + the function-name↔ToolSpec resolver

**Files:**
- Create: `api/app/chat/__init__.py` (empty)
- Create: `api/app/chat/tool_schemas.py`
- Test: `api/tests/chat/test_tool_schemas.py`

**Interfaces:**
- Consumes: `app.research.service.get_capabilities`, `app.mcp.service.list_servers`/`list_cached_tools`.
- Produces:
  - `@dataclass(frozen=True) class ToolSpec: function_name: str; kind: Literal["research","mcp"]; provider: str; tool: str; read_only: bool; destructive: bool; requires_confirmation: bool; parameters: dict[str, Any]`
  - `@dataclass class ChatToolAllowlist: specs: dict[str, ToolSpec]` with `def function_schemas(self) -> list[dict[str, Any]]` (OpenAI shape) and `def resolve(self, function_name: str) -> ToolSpec | None`.
  - `async def assemble_allowlist(db, *, request_id=None) -> ChatToolAllowlist`
  - `MCP_NAME_PREFIX = "mcp__"`; `def mcp_function_name(server, tool) -> str`; `def parse_mcp_function_name(name) -> tuple[str, str] | None`
  - `RESEARCH_TOOL_SCHEMAS: dict[str, dict]` — the 5 fixed schemas, and `RESEARCH_OPS: frozenset[str]`.

- [ ] **Step 1: Failing tests** (`api/tests/chat/test_tool_schemas.py`) — mock `get_capabilities`, `list_servers`, `list_cached_tools`:
```python
import pytest
from unittest.mock import AsyncMock, patch
from app.chat.tool_schemas import (
    assemble_allowlist, mcp_function_name, parse_mcp_function_name, RESEARCH_OPS,
)

@pytest.mark.asyncio
async def test_research_only_allowlist(db):
    with patch("app.chat.tool_schemas.get_capabilities",
               new=AsyncMock(return_value={"enabled": True, "providers": [{"name": "cl-prod", "type": "courtlistener"}]})), \
         patch("app.chat.tool_schemas.research_resolve_provider", new=AsyncMock(return_value="cl-prod")), \
         patch("app.chat.tool_schemas.list_servers", new=AsyncMock(return_value=[])):
        al = await assemble_allowlist(db)
    assert RESEARCH_OPS <= set(al.specs)
    spec = al.resolve("search_case_law")
    assert spec.kind == "research" and spec.provider == "cl-prod" and spec.read_only

@pytest.mark.asyncio
async def test_mcp_only_allowlist(db):
    tools = [
        {"name": "get_doc", "description": "", "parameters": {"type": "object"},
         "read_only": True, "destructive": False, "requires_confirmation": False, "enabled": True},
        {"name": "delete_doc", "description": "", "parameters": {"type": "object"},
         "read_only": False, "destructive": True, "requires_confirmation": True, "enabled": True},
        {"name": "disabled_tool", "description": "", "parameters": {}, "read_only": True,
         "destructive": False, "requires_confirmation": False, "enabled": False},
    ]
    with patch("app.chat.tool_schemas.get_capabilities", new=AsyncMock(return_value={"enabled": False, "providers": []})), \
         patch("app.chat.tool_schemas.list_servers", new=AsyncMock(return_value=[{"name": "files", "type": "mcp"}])), \
         patch("app.chat.tool_schemas.list_cached_tools", new=AsyncMock(return_value=tools)):
        al = await assemble_allowlist(db)
    assert mcp_function_name("files", "get_doc") in al.specs
    assert al.resolve(mcp_function_name("files", "delete_doc")).destructive is True
    # disabled tools are NOT in the allowlist
    assert mcp_function_name("files", "disabled_tool") not in al.specs

@pytest.mark.asyncio
async def test_empty_allowlist_when_nothing_enabled(db):
    with patch("app.chat.tool_schemas.get_capabilities", new=AsyncMock(return_value={"enabled": False, "providers": []})), \
         patch("app.chat.tool_schemas.list_servers", new=AsyncMock(return_value=[])):
        al = await assemble_allowlist(db)
    assert al.specs == {}
    assert al.function_schemas() == []

def test_mcp_name_roundtrip():
    n = mcp_function_name("files", "get_doc")
    assert parse_mcp_function_name(n) == ("files", "get_doc")
    assert parse_mcp_function_name("verify_citations") is None
```
Note: `db` is the existing async session fixture; `assemble_allowlist` takes it but research/MCP enumeration is what's mocked. `list_cached_tools` is `async(db, *, provider)`.

- [ ] **Step 2: Run; expect FAIL** (module missing).

- [ ] **Step 3: Implement `api/app/chat/tool_schemas.py`.** Full module:
```python
"""Per-turn chat tool allowlist (PR5b).

Assembles the closed set of function schemas the chat model may call this
turn — fixed CourtListener research ops (when enabled) + operator-enabled
MCP tools — and resolves a model-emitted function name back to a typed
:class:`ToolSpec`. The allowlist IS the closed set (ADR 0015, alt A): the
model picks among allowed tools and cannot reach beyond them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.service import list_cached_tools, list_servers
from app.research.service import _resolve_provider as research_resolve_provider
from app.research.service import get_capabilities

MCP_NAME_PREFIX = "mcp__"
_MCP_SEP = "__"

# Fixed CourtListener research function schemas (OpenAI `parameters` shape).
# All are read_only. `op` is the research-service op name AND the
# tool_call_log `tool` column value.
RESEARCH_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "verify_citations": {
        "description": "Verify legal citations in text against CourtListener; "
        "returns each citation's match status.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text containing citations."}},
            "required": ["text"],
        },
    },
    "search_case_law": {
        "description": "Search CourtListener case law. Returns matching clusters.",
        "parameters": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query."},
                "cursor": {"type": "string", "description": "Pagination cursor (optional)."},
            },
            "required": ["q"],
        },
    },
    "get_cluster": {
        "description": "Fetch a CourtListener opinion cluster's metadata and opinions by cluster id.",
        "parameters": {
            "type": "object",
            "properties": {"cluster_id": {"type": "integer"}},
            "required": ["cluster_id"],
        },
    },
    "read_opinion": {
        "description": "Read the full plaintext of a fetched opinion by opinion id "
        "(the cluster must have been fetched via get_cluster first).",
        "parameters": {
            "type": "object",
            "properties": {"opinion_id": {"type": "integer"}},
            "required": ["opinion_id"],
        },
    },
    "find_in_case": {
        "description": "Find snippets matching a query within a fetched opinion.",
        "parameters": {
            "type": "object",
            "properties": {
                "opinion_id": {"type": "integer"},
                "query": {"type": "string"},
                "max_matches": {"type": "integer", "default": 3},
            },
            "required": ["opinion_id", "query"],
        },
    },
}
RESEARCH_OPS: frozenset[str] = frozenset(RESEARCH_TOOL_SCHEMAS)


def mcp_function_name(server: str, tool: str) -> str:
    """Model-visible function name for an MCP tool: ``mcp__{server}__{tool}``."""
    return f"{MCP_NAME_PREFIX}{server}{_MCP_SEP}{tool}"


def parse_mcp_function_name(name: str) -> tuple[str, str] | None:
    """Inverse of :func:`mcp_function_name`; returns ``(server, tool)`` or None."""
    if not name.startswith(MCP_NAME_PREFIX):
        return None
    rest = name[len(MCP_NAME_PREFIX) :]
    server, sep, tool = rest.partition(_MCP_SEP)
    if not sep or not server or not tool:
        return None
    return server, tool


@dataclass(frozen=True)
class ToolSpec:
    function_name: str
    kind: Literal["research", "mcp"]
    provider: str
    tool: str
    read_only: bool
    destructive: bool
    requires_confirmation: bool
    parameters: dict[str, Any]
    description: str = ""


@dataclass
class ChatToolAllowlist:
    specs: dict[str, ToolSpec]

    def resolve(self, function_name: str) -> ToolSpec | None:
        return self.specs.get(function_name)

    def function_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": s.function_name,
                    "description": s.description,
                    "parameters": s.parameters,
                },
            }
            for s in self.specs.values()
        ]


async def assemble_allowlist(db: AsyncSession, *, request_id: str | None = None) -> ChatToolAllowlist:
    """Build the per-turn allowlist. Empty when no research/MCP is configured."""
    specs: dict[str, ToolSpec] = {}

    caps = await get_capabilities(request_id=request_id)
    if caps.get("enabled"):
        provider = await research_resolve_provider(request_id=request_id)
        for op, schema in RESEARCH_TOOL_SCHEMAS.items():
            specs[op] = ToolSpec(
                function_name=op,
                kind="research",
                provider=provider,
                tool=op,
                read_only=True,
                destructive=False,
                requires_confirmation=False,
                parameters=schema["parameters"],
                description=schema["description"],
            )

    for server in await list_servers(request_id=request_id):
        name = server.get("name")
        if not name:
            continue
        for t in await list_cached_tools(db, provider=name):
            if not t.get("enabled"):
                continue
            fn = mcp_function_name(name, t["name"])
            specs[fn] = ToolSpec(
                function_name=fn,
                kind="mcp",
                provider=name,
                tool=t["name"],
                read_only=bool(t.get("read_only")),
                destructive=bool(t.get("destructive")),
                requires_confirmation=bool(t.get("requires_confirmation")),
                parameters=t.get("parameters") or {"type": "object", "properties": {}},
                description=t.get("description") or "",
            )

    return ChatToolAllowlist(specs=specs)
```
Note: importing the underscored `research.service._resolve_provider` mirrors `guard.py:324`'s precedent (PR5a already reaches into it). `get_capabilities` returns `{"enabled": bool, "providers": [...]}` (PR3b `/research/capabilities`).

- [ ] **Step 4: Run; expect PASS.** `cd api && DATABASE_URL=... .venv/bin/pytest tests/chat/test_tool_schemas.py -v`

- [ ] **Step 5: Lint + commit** (`ruff format`/`check` + `mypy app`; `git add api/app/chat/ api/tests/chat/`).

---

## Task 4 (api): `chat_pending_tool_call` model + migration 0054

**Files:**
- Create: `api/app/models/chat_pending_tool_call.py`
- Create: `api/alembic/versions/0054_chat_pending_tool_call.py`
- Modify: `api/app/models/__init__.py` (export, if the package re-exports models)
- Test: `api/tests/test_chat_pending_tool_call_model.py`

**Interfaces:**
- Produces: `ChatPendingToolCall` ORM model (`__tablename__ = "chat_pending_tool_call"`) with columns:
  - `id: UUID` PK (server default `gen_random_uuid()`), = the route's `pending_call_id`.
  - `chat_id: UUID` FK `chats.id` ON DELETE CASCADE, indexed.
  - `user_id: UUID` FK `users.id` ON DELETE CASCADE.
  - `assistant_message_id: UUID` (the in-flight assistant message id allocated up front).
  - `tool_call_log_id: UUID | None` FK `tool_call_log.id` ON DELETE SET NULL.
  - `function_name: str`, `kind: str` (`research`/`mcp`), `provider: str`, `tool: str`.
  - `destructive: bool`, `tier: int`.
  - `tool_call_args: dict` (JSONB) — args for the pending call (a payload — deliberately OFF `tool_call_log`).
  - `resume_state: dict` (JSONB) — `{"messages": [...openai msgs incl tool results so far...], "calls_used": int}`. Same sensitivity class as `messages.content`; stored the same way; NEVER logged.
  - `status: str` — `pending` / `resolved` (single-use), server default `pending`.
  - `expires_at: datetime` (TTL).
  - `created_at`/`updated_at: datetime` (app-bumped, mirror PR5a).

**Security note (record in the migration docstring):** `tool_call_args` + `resume_state` hold conversation/tool payloads needed to resume. They live here — NOT on `tool_call_log` — to preserve `tool_call_log`'s counts-only invariant. Treated like `messages.content` (the existing plaintext conversation store): never emitted to logs.

- [ ] **Step 1: Failing model test:**
```python
import uuid
from datetime import UTC, datetime, timedelta
import pytest
from app.models.chat_pending_tool_call import ChatPendingToolCall

@pytest.mark.asyncio
async def test_pending_tool_call_roundtrip(db, user, chat):  # existing fixtures
    row = ChatPendingToolCall(
        chat_id=chat.id, user_id=user.id, assistant_message_id=uuid.uuid4(),
        function_name="mcp__files__delete_doc", kind="mcp", provider="files", tool="delete_doc",
        destructive=True, tier=2, tool_call_args={"path": "/x"},
        resume_state={"messages": [{"role": "user", "content": "hi"}], "calls_used": 1},
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    db.add(row)
    await db.flush()
    assert row.status == "pending"
    assert row.id is not None
```

- [ ] **Step 2: Run; expect FAIL.**

- [ ] **Step 3: Write the model** (mirror `api/app/models/tool_call_log.py` conventions — `Mapped`/`mapped_column`, app-bumped timestamps, `gen_random_uuid()` server default).

- [ ] **Step 4: Generate the migration as 0054.** Do NOT run host alembic against the dev DB. Hand-write `0054_chat_pending_tool_call.py` (down_revision `0053`) with `op.create_table(...)`, the two FKs (`ondelete="CASCADE"` / `"SET NULL"`), an index on `chat_id`, and `op.drop_table` in `downgrade`. Match column types to the model (JSONB for the two dict columns, `server_default=sa.text("'pending'")` for `status`).

- [ ] **Step 5: Run the model test against throwaway pgvector** (conftest auto-migrates to head 0054). Expect PASS.

- [ ] **Step 6: Lint + commit** (`git add api/app/models/chat_pending_tool_call.py api/alembic/versions/0054_*.py api/app/models/__init__.py api/tests/test_chat_pending_tool_call_model.py`). Commit message notes migration head 0053→0054.

---

## Task 5 (api): the loop engine `api/app/chat/tool_loop.py`

**Files:**
- Create: `api/app/chat/tool_loop.py`
- Modify: `api/app/config.py` — add `chat_tool_call_cap: int = 8`
- Test: `api/tests/chat/test_tool_loop.py`

**Interfaces:**
- Consumes: Task 2 (`call_tool(user_token=)`), Task 3 (`ChatToolAllowlist`, `ToolSpec`, `parse_mcp_function_name`), `app.tools.governance.governed_tool_invocation`/`resolve_provider_tier`/`ToolTierRefused` (PR5a), `app.autonomous.guard.ToolResult`/`_args_digest`, `app.autonomous.cost.estimate_tool_cost`, `app.autonomous.enums.ToolIntent`, `app.research.service`, `app.mcp.oauth.get_valid_token`/`MCPAuthorizationRequired`.
- Produces (all consumed by Task 6/7):
  - Outcome dataclasses: `LoopFinal(text, usage_prompt, usage_completion, tier, provider, model, applied_skills, messages)`; `LoopConfirmation(spec, args, tier, args_summary, messages, calls_used)`; `LoopMcpAuth(server, authorize_url, messages, calls_used)`; `LoopCapReached(text, ...)` (folds into `LoopFinal` — see Step note).
  - `async def run_chat_tool_loop(db, *, user, gateway, base_request: ChatCompletionRequest, allowlist: ChatToolAllowlist, assistant_message_id, calls_used: int = 0, cluster_cache: dict | None = None, request_id=None) -> LoopOutcome`
  - `async def execute_tool(db, *, user, gateway, spec: ToolSpec, args: dict, cluster_cache: dict, request_id=None) -> ToolResult` — runs ONE read_only/approved call through `governed_tool_invocation` (origin="chat", max_allowed_tier=None). Raises `MCPAuthorizationRequired` for oauth-no-token, `ToolTierRefused` for tier.
  - `def tool_result_message(tool_call_id: str, result: ToolResult) -> dict` — builds the `role="tool"` message fed back.

**Design notes:**
- The loop calls `gateway.chat_completion(base_request_with_tools, request_id=...)` (NON-streaming) each round. `base_request` is rebuilt per round with the growing `messages` list and `tools=allowlist.function_schemas()`, `tool_choice="auto"`.
- Response: `choices[0]`. If `finish_reason != "tool_calls"` (or no `message.tool_calls`) → `LoopFinal` with `message.content`.
- If tool_calls: for EACH call, resolve `spec = allowlist.resolve(fn_name)`.
  - `spec is None` (model hallucinated a name) → treat as a **policy refusal**: append a `role="tool"` message `{"error": "tool not permitted"}`, continue (do NOT call the gateway). (Matches PR5a D4 "unknown MCP tool → not granted".)
  - `spec.read_only and not spec.destructive and not spec.requires_confirmation` → `execute_tool(...)`, append the result tool message. On `ToolTierRefused` → append an error tool message and continue (the model finalizes without it). On `MCPAuthorizationRequired` → return `LoopMcpAuth`.
  - else (`destructive` or `requires_confirmation`) → return `LoopConfirmation` (Task 6/7 persists + emits the gate). Only the FIRST such call in a round triggers the gate (process one at a time; remaining proposed calls are abandoned for this turn — document this).
- After processing all read_only calls in a round, append the assistant tool_calls message + the tool result messages to `messages`, increment `calls_used` by the number executed, and loop. Stop when `calls_used >= settings.chat_tool_call_cap` → do ONE final gateway round WITHOUT tools (`tool_choice="none"` / omit tools) so the model finalizes with what it has → `LoopFinal`.
- **Cluster cache:** `execute_tool` for research `get_cluster`/`read_opinion` checks/fills `cluster_cache` (keys `("cluster", id)` / `("opinion", id)`) before calling the service. Cache is request-scoped (passed in, discarded at turn end).
- **Cost:** `estimated_cost = await estimate_tool_cost(intent, args, db)` where intent = `ToolIntent.retrieve_caselaw` (research) or `ToolIntent.call_mcp_tool` (mcp). Both are `Decimal("0")` today (DE-344) — forwarded verbatim (single-estimate invariant).
- **`governed_tool_invocation` call** (per executed tool): `origin="chat"`, `provider=spec.provider`, `tool=spec.tool`, `intent=<the ToolIntent>`, `provider_tier=await resolve_provider_tier(spec.provider)`, `max_allowed_tier=None`, `estimated_cost=...`, `dispatch=<closure>`, `confirmation_state="not_required"` (or `"approved"` when called from resume), `user_id=user.id`, `chat_id`, `message_id=assistant_message_id`, `args_digest=_args_digest(args)`, `denied_on=()`, `span=None` (OTel for the chat tool-path is a follow-on DE — note it).

- [ ] **Step 1: Failing tests** (`api/tests/chat/test_tool_loop.py`), mocking `gateway.chat_completion` to return scripted responses. Cover: (a) immediate final answer (no tools); (b) one read_only research call → execute → final; (c) MCP read_only with token threaded (assert `call_tool` got `user_token`); (d) cap reached after 8 → final-without-tools; (e) cluster cache hit (second `get_cluster` does not re-call the service); (f) `ToolTierRefused` → error tool message, loop continues; (g) destructive tool → `LoopConfirmation`; (h) MCP oauth no token → `LoopMcpAuth`. Example for (b):
```python
@pytest.mark.asyncio
async def test_loop_executes_readonly_research_then_finalizes(db, user, chat):
    gateway = AsyncMock()
    gateway.chat_completion.side_effect = [
        _resp_tool_call("search_case_law", {"q": "Brown"}, call_id="c1"),
        _resp_final("Found Brown v. Board."),
    ]
    al = _allowlist_with_research(provider="cl-prod")  # helper
    with patch("app.chat.tool_loop.research_service.search_case_law",
               new=AsyncMock(return_value={"results": [{"cluster_id": 1}]})), \
         patch("app.chat.tool_loop.resolve_provider_tier", new=AsyncMock(return_value=1)):
        outcome = await run_chat_tool_loop(
            db, user=user, gateway=gateway, base_request=_req([_user("find Brown")]),
            allowlist=al, assistant_message_id=uuid.uuid4(),
        )
    from app.chat.tool_loop import LoopFinal
    assert isinstance(outcome, LoopFinal)
    assert "Brown" in outcome.text
    # a tool_call_log row was written (governed_tool_invocation)
    rows = (await db.execute(select(ToolCallLog).where(ToolCallLog.origin == "chat"))).scalars().all()
    assert len(rows) == 1 and rows[0].outcome == "executed"
```
(`_resp_tool_call`/`_resp_final`/`_allowlist_with_research`/`_req`/`_user` are small local builders returning the api `ChatCompletionResponse` / requests.)

- [ ] **Step 2: Run; expect FAIL** (module missing).

- [ ] **Step 3: Add the settings field.** In `api/app/config.py` add `chat_tool_call_cap: int = 8` (operator-overridable via env, follow the module's `Settings` pattern; add a docstring referencing L4).

- [ ] **Step 4: Implement `tool_loop.py`.** Build the outcome dataclasses, `execute_tool`, the research/MCP dispatch closures, and `run_chat_tool_loop` per the design notes. Research dispatch maps op→service call:
```python
async def _dispatch_research(db, spec, args, cluster_cache, request_id):
    op = spec.tool
    if op == "verify_citations":
        data = await research_service.verify_citations(args["text"], request_id=request_id)
    elif op == "search_case_law":
        data = await research_service.search_case_law(args, request_id=request_id)
    elif op == "get_cluster":
        key = ("cluster", int(args["cluster_id"]))
        data = cluster_cache.get(key)
        if data is None:
            data = await research_service.get_cluster(db, cluster_id=int(args["cluster_id"]), request_id=request_id)
            cluster_cache[key] = data
    elif op == "read_opinion":
        key = ("opinion", int(args["opinion_id"]))
        data = cluster_cache.get(key)
        if data is None:
            data = await research_service.read_opinion(db, opinion_id=int(args["opinion_id"]))
            cluster_cache[key] = data
    elif op == "find_in_case":
        data = await research_service.find_in_case(db, opinion_id=int(args["opinion_id"]),
                                                   query=args["query"], max_matches=int(args.get("max_matches", 3)))
    else:
        raise ToolNotGranted(...)
    return ToolResult(cost_usd=Decimal("0"), data=data, outcome="success")
```
MCP dispatch resolves the user token then calls the gateway:
```python
async def _dispatch_mcp(db, user, gateway, spec, args, request_id):
    token = await get_valid_token(db, user_id=user.id, server=spec.provider)  # may raise MCPAuthorizationRequired
    result = await gateway.call_tool(spec.provider, spec.tool, args,
                                     max_allowed_tier=None, user_token=token, request_id=request_id)
    return ToolResult(cost_usd=Decimal("0"), data=result.get("payload"), outcome="success")
```
`execute_tool` wraps the right dispatch closure in `governed_tool_invocation`. **Important:** `get_valid_token` returns `None` for connected-but-no-token AND raises `MCPAuthorizationRequired` for not-connected — verify the exact contract (`api/app/mcp/oauth.py:370`); if it returns `None`, treat `None` (for `auth=oauth` servers) as the connect-on-demand signal and raise `MCPAuthorizationRequired` yourself. Only resolve a token when the server's `auth == "oauth"` (look up via `list_servers`/server config; for `none`/`bearer` servers pass `user_token=None`).

- [ ] **Step 5: Run; expect PASS.** Iterate until all 8 scenarios pass.

- [ ] **Step 6: Lint + commit.**

---

## Task 6 (api): integrate the loop into `send_message` (stream + non-stream) + new SSE events

**Files:**
- Modify: `api/app/api/chats.py` (`send_message` ~1118; `_stream_response` ~2269; `_non_streaming_response` ~2145)
- Modify: response schema module — add gate fields to the non-streaming response (and a `ConfirmationRequiredPayload`/`McpAuthRequiredPayload`)
- Test: `api/tests/integration/test_chat_tool_loop_send.py`

**Interfaces:**
- Consumes: Task 3 `assemble_allowlist`, Task 5 `run_chat_tool_loop` + outcomes.
- Produces: behavior — when the allowlist is non-empty, `send_message` drives the loop; gates surface as terminal SSE events (`tool_confirmation_required`, `mcp_authorization_required`) on the streaming path and as JSON fields on the non-streaming path. Empty allowlist ⇒ existing code path unchanged.

**SSE wire shapes** (follow the existing `data: {json}\n\n`, `separators=(',',':')` convention; both are TERMINAL — emitted then `[DONE]`, stream ends):
```json
{"type": "tool_confirmation_required", "lq_ai_message_id": "<uuid>",
 "pending_call_id": "<uuid>", "provider": "files", "tool": "delete_doc",
 "function_name": "mcp__files__delete_doc", "args_summary": {...redacted-safe...},
 "tier": 2, "destructive": true}
{"type": "mcp_authorization_required", "lq_ai_message_id": "<uuid>",
 "server": "files", "authorize_url": "/api/v1/mcp/oauth/files/authorize"}
```
`args_summary` is a shallow, size-bounded view of the args (keys + short string values; NO large payloads) — define `_safe_args_summary(args) -> dict` in chats.py.

- [ ] **Step 1: Failing integration tests** (`test_chat_tool_loop_send.py`): (a) streaming send with a research allowlist + scripted gateway → `start`/`delta`(final)/`complete`/`[DONE]`, assistant message persisted, a `tool_call_log` chat row exists; (b) streaming send proposing a destructive MCP tool → `tool_confirmation_required` terminal event, a `chat_pending_tool_call` row in `status=pending` + a `tool_call_log` row `confirmation_state=pending_confirmation outcome=pending`, NO gateway tool call executed, stream ends; (c) streaming send hitting an oauth MCP server with no token → `mcp_authorization_required` terminal event; (d) **empty allowlist → byte-identical to today** (mock `assemble_allowlist` → empty; assert the existing single-shot path runs).

- [ ] **Step 2: Run; expect FAIL.**

- [ ] **Step 3: Assemble the allowlist in `send_message`.** After `gw_request` is built (~1500) and before the `if payload.stream:` branch (~1536):
```python
    allowlist = await assemble_allowlist(db, request_id=request_id)
```
Thread `allowlist` into `_stream_response`/`_non_streaming_response`.

- [ ] **Step 4: Branch on the allowlist inside the response helpers.** In `_stream_response._generate`, after the `start` frame: if `allowlist.specs` is empty → the EXISTING `gateway.chat_completion_stream` path (unchanged). Else → run the loop:
```python
            cluster_cache: dict = {}
            outcome = await run_chat_tool_loop(
                db, user=user, gateway=gateway, base_request=request,
                allowlist=allowlist, assistant_message_id=assistant_message_id,
                cluster_cache=cluster_cache, request_id=request_id,
            )
            # render outcome -> SSE frames (see Step 5)
```
Wrap loop execution in the same `try/except LQAIError` the existing path uses (a gateway failure mid-loop → the existing error frame + partial persist).

- [ ] **Step 5: Render outcomes to frames.**
  - `LoopFinal` → emit the answer as one (or chunked) `delta` frame(s) using the existing `delta` shape, set `accumulated`, then persist via `_persist_assistant_message` + `_persist_message_citations` + `_audit_message_sent` (reuse the existing tail), then the existing `complete` frame + `[DONE]`.
  - `LoopConfirmation` → persist the `chat_pending_tool_call` row (`status=pending`, `expires_at = now + CONFIRM_TTL` [define `CONFIRM_TTL = timedelta(minutes=15)`], `resume_state={"messages": outcome.messages, "calls_used": outcome.calls_used}`, `tool_call_args=outcome.args`) AND a `tool_call_log` row via `governed_tool_invocation`-style write in `confirmation_state="pending_confirmation"`/`outcome="pending"` (call the helper with a dispatch that is never run — OR write the pending `tool_call_log` row directly; simplest: have `run_chat_tool_loop` already have written nothing for the gated call, and write both rows here). Emit `tool_confirmation_required` (with `pending_call_id = row.id`), then `[DONE]`. **Do NOT** persist a final assistant Message (resume will). Commit the session so the pending row survives the turn.
  - `LoopMcpAuth` → emit `mcp_authorization_required`, then `[DONE]`. No persistence beyond audit.
- [ ] **Step 6: Non-streaming path** (`_non_streaming_response`): same branch — empty allowlist → existing single `gateway.chat_completion`. Else run the loop; `LoopFinal` → existing JSON `MessagePostResponse`; `LoopConfirmation`/`LoopMcpAuth` → return a 200 JSON body carrying the gate payload (add optional `pending_tool_call: ConfirmationRequiredPayload | None` and `mcp_authorization_required: McpAuthRequiredPayload | None` fields to `MessagePostResponse`, defaulting None so the existing wire shape is preserved).

- [ ] **Step 7: Persist-commit boundary.** The loop uses `governed_tool_invocation`'s flush-not-commit; the chat send path already commits at the end (verify where `send_message`/helpers commit — the existing path relies on the request-scoped session commit). Ensure the pending-row write + tool_call_log rows are committed before the stream closes (the generator must `await db.commit()` for the gate case, mirroring how the existing tail persists). Add an explicit `await db.commit()` in the gate branches.

- [ ] **Step 8: Run integration tests; iterate to PASS.**

- [ ] **Step 9: Lint + commit.**

---

## Task 7 (api): resume route `POST /api/v1/chats/{chat_id}/tool-calls/{pending_call_id}` + collision guards

**Files:**
- Modify: `api/app/api/chats.py` (new route + a shared `_resume_after_decision` helper)
- Modify: response/request schema module — `ToolCallDecisionRequest {decision: Literal["approve","deny"]}`
- Modify: `docs/api/backend-openapi.yaml`, `api/tests/test_openapi.py` (132→133 + `EXPECTED_PATHS`), `api/tests/test_endpoints.py` (`IMPLEMENTED_ROUTES`)
- Test: `api/tests/integration/test_chat_tool_call_resume.py`

**Interfaces:**
- Consumes: Task 4 model, Task 5 `run_chat_tool_loop`/`execute_tool`, Task 6's outcome-rendering tail (factor the streaming-render-of-`LoopOutcome` into a reusable `_stream_loop_outcome(...)` generator so both initial send and resume share it).
- Produces: route handler `resume_tool_call(chat_id, pending_call_id, request, user, db, gateway) -> StreamingResponse`.

- [ ] **Step 1: Failing integration tests** (`test_chat_tool_call_resume.py`): (a) approve → executes the pending tool via `governed_tool_invocation` (a new `executed` tool_call_log row), feeds result, resumes loop → streamed final answer + assistant message persisted; pending row `status=resolved`. (b) deny → feeds "user denied", resumes → final answer without the tool; pending `status=resolved`; tool_call_log `confirmation_state=denied`. (c) expired (`expires_at < now`) → 409/410. (d) already-resolved (replay) → 409. (e) non-owner user → 403/404 (id-probing-safe). (f) unknown `pending_call_id` → 404.

- [ ] **Step 2: Run; expect FAIL** (route missing).

- [ ] **Step 3: Add `ToolCallDecisionRequest` schema** (`decision: Literal["approve","deny"]`).

- [ ] **Step 4: Implement the route:**
```python
@router.post(
    "/{chat_id}/tool-calls/{pending_call_id}",
    response_model=None,
    summary="Approve or deny a pending destructive chat tool-call; resumes the turn",
)
async def resume_tool_call(
    chat_id: str, pending_call_id: str, request: Request, user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> StreamingResponse:
    cid = _validate_chat_id(chat_id)
    pid = _validate_uuid(pending_call_id)  # 404 on malformed
    chat = await _load_visible_chat(db, cid, user.id, include_archived=False)  # 404 cross-user
    body = ToolCallDecisionRequest.model_validate(await request.json())

    pending = (await db.execute(
        select(ChatPendingToolCall).where(
            ChatPendingToolCall.id == pid,
            ChatPendingToolCall.chat_id == cid,
            ChatPendingToolCall.user_id == user.id,  # owner-scoped (id-probing-safe)
        )
    )).scalar_one_or_none()
    if pending is None:
        raise NotFound("pending tool-call not found")
    if pending.status != "pending":
        raise Conflict("tool-call already resolved")          # 409
    if pending.expires_at < datetime.now(UTC):
        pending.status = "resolved"; await db.commit()
        raise Conflict("tool-call confirmation expired")       # 409 (or Gone/410)
    pending.status = "resolved"  # single-use: mark before doing work
    await db.flush()
    # ... build messages from resume_state; on approve execute_tool + append result,
    #     on deny append a denial tool message; then resume run_chat_tool_loop and
    #     stream the outcome via the shared _stream_loop_outcome generator.
```
On **approve**: reconstruct the `ChatToolAllowlist` (re-`assemble_allowlist`) to resolve the spec for the pending `function_name`; `execute_tool(...)` with `confirmation_state="approved"`; append the tool result message; resume `run_chat_tool_loop` with `messages=resume_state["messages"] + [assistant_tool_call_msg, tool_result_msg]`, `calls_used=resume_state["calls_used"]`. On **deny**: append a `role="tool"` message `{"error": "user denied this tool call"}` for the pending call id; resume so the model finalizes. Both return a `StreamingResponse` wrapping `_stream_loop_outcome`. Commit at the end (as the streaming tail does).

- [ ] **Step 5: Collision guards.** Add the path to `IMPLEMENTED_ROUTES` (`test_endpoints.py`), bump the pinned count + add to `EXPECTED_PATHS` (`test_openapi.py`, 132→133), add the path to `docs/api/backend-openapi.yaml` (request body `ToolCallDecisionRequest`; response: `text/event-stream`). Run `tests/test_openapi.py` (authoritative — don't eyeball the YAML).

- [ ] **Step 6: Run resume tests + the openapi/endpoints guards; iterate to PASS.**

- [ ] **Step 7: Lint + commit.**

---

## Task 8 (api+gateway): full-suite verification, DE notes, ship

**Files:** none new (verification + docs).

- [ ] **Step 1: Full api suite** against :15433:
```bash
cd api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest -q
```
Expected: all pass (baseline was 2159 pass/1 skip after PR5a; this PR adds tests). Confirm `test_openapi.py`/`test_endpoints.py` collection-guards pass (path count 133).
- [ ] **Step 2: Full gateway suite + both lints + mypy:**
```bash
cd gateway && .venv/bin/pytest -q && .venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy app
cd ../api && .venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy app
```
- [ ] **Step 3: DE notes (PRD §9).** File/append: **chat tool-path OTel** (the loop passes `span=None`; the `chat.tool_call` domain span is deferred — fold into the standing tool-path-OTel DE). Note **DE-341** (retire the OpenWebUI `web/.../utils/mcp/client.py` stub) is now unblocked for PR6 (chat path is gateway-brokered). Note the **multi-call-per-round** abandonment (only the first destructive call in a round gates; siblings abandoned) and the **non-streaming-final** UX (no token streaming on tool-using turns) as accepted v1 behavior / candidate DEs. Note **per-chat cost cap** remains a DE (v1 bounds by the per-turn cap).
- [ ] **Step 4: Update the milestone memory + write a handoff** (`docs/LQVern/HANDOFF-...-pr6-next.md`) after merge. Record: migration head 0054, `EXPECTED_PATHS` 133, the new route, the `chat_pending_tool_call` table, and PR6 = transparency surfaces (see `[[project-pr6-transparency-posture-narrative]]`).
- [ ] **Step 5: Push both remotes, open the PR vs `main`, attach the security-review context, request Kevin's review.** Do NOT self-merge (security-gated). After Kevin merges, sync `tucuxi/main` to the squash SHA.

---

## Self-Review (run before dispatching execution)

**Spec coverage (§PR5b):** Gateway `tools`/`tool_choice` passthrough → Task 1 ✓. Allowlist assembly (research/MCP/mixed/empty) → Task 3 ✓. The loop + per-turn cap + cluster cache → Task 5 ✓. Connect-on-demand (`mcp_authorization_required`) → Tasks 5/6 ✓. Confirmation gate persist-and-resume (SSE event + POST resume, single-use+TTL) → Tasks 4/6/7 ✓. Surface/collision guards (`EXPECTED_PATHS` +1) → Task 7 ✓. PR5b tests (happy/MCP-token/allowlist variants/cap/cache/passthrough/gate-cycle/tier-refusal/no-payload) → distributed across Tasks 1,3,5,6,7 ✓. Cross-cutting (tier ceiling, audit layering, no raw payloads) → `max_allowed_tier=None` (Fork 2, documented), `tool_call_log` counts-only + payloads only in `chat_pending_tool_call` ✓.

**Open items pinned:** per-adapter forwarding (Task 1 — Anthropic is the only gap; OpenAI/Ollama verified) ✓; resume-state shape (Task 4 — `resume_state` JSONB on a dedicated table) ✓; migration number (0054) + `EXPECTED_PATHS` (132→133) ✓; gateway passthrough as PR5b's first task ✓.

**Deviations to call out in the PR description:** (1) `max_allowed_tier=None` deviates from the spec's cross-cutting "compute+thread a ceiling" — gateway egress-tier policy is the authority (Fork 2, Kevin-approved). (2) Tool-using turns emit the final answer as delta frame(s), not token-streamed (Fork 1, Kevin-approved). (3) Only the first destructive call in a round triggers the gate; sibling proposed calls are abandoned that turn.
