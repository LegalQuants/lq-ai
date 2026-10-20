# WS-E PR1c — Chat Authority Consumer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the chat model fetch USCODE/CFR authority from GovInfo and char-verify its verbatim quotes at finalize — closing DE-369 for the chat path by reusing PR1b's substrate.

**Architecture:** Add granular `search_authority` + `get_authority` chat tools gated on the content-source registry; dispatch them through the existing governed tool-loop (writing the fetched body to the PR1b `authority_text_cache`); emit `MessageToolSource` provenance; and add a verbatim+paraphrase finalize verify hook that mirrors the caselaw path, producing `MessageAuthorityCitation` rows that flow through the unchanged ledger + gate. No migration; `gate.py` and `ledger.py` unchanged.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, pytest. Repo `api/` subsystem.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-06-30-wse-pr1c-chat-authority-design.md` — binding.
- **No migration.** `MessageToolSource.source_kind` is unconstrained `String(32)`; `message_authority_citations` (method CHECK already allows `exact_match`/`tolerant_match`/`paraphrase_judge`) + `authority_text_cache` exist (mig 0064). `gate.py` and `ledger.py` are **not** modified.
- **Reuse-not-fork:** reuse `verify()`, `locate_passage`, `authority_target`, `_AuthorityCandidate`, `store_authority_text`, `load_authority_text`, `extract_blockquote_passages`, `assemble_ledger_entries`, `compute_and_record_gate`.
- **Import-cycle rule (load-bearing):** the two new citation-boundary runtime imports MUST be **function-local** (mirror `app/autonomous/guard.py:874`): `store_authority_text` inside `_dispatch_authority`, `extract_blockquote_passages` inside `verify_and_persist_authority_citations`. `ToolSourceRecord` in `authority.py` is a `TYPE_CHECKING`-only import. `GovInfoAdapter` (leaf module, no app imports) may be module-level. Getting this wrong crashes the whole api suite at collection.
- **Never-poison-the-session:** the cache write in `_dispatch_authority` is savepoint-isolated + non-fatal; the finalize verify is best-effort try/except.
- **Level-2 depth:** verbatim + paraphrase, PASS/SUPPORTED, **drop-on-miss** (no chat-FAIL). Attributed-authority FAIL is DE-370 (out of scope).
- **Only `get_authority` is quotable:** `search_authority` returns title-only `citable_text` and writes no cache.
- **Gates (repo ROOT, DE-368 SOLO):** `ruff check api scripts` + `ruff format --check api scripts` + `mypy app` + full api suite run **serially** (never concurrent pytest vs the shared `lqai_test` DB).
- **Commits:** `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Test harness:** api host venv `api/.venv`; throwaway pgvector `lqai-test-pg` on `:55432`; `DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test` (conftest auto-migrates).

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `api/app/chat/tool_schemas.py` | `AUTHORITY_TOOL_SCHEMAS`, `ToolSpec.kind` third value, `assemble_allowlist(gateway)` authority block | 1 |
| `api/app/api/chats.py` | thread `gateway` into 3 `assemble_allowlist` call sites; wire verify hook into 2 finalize sites | 1, 5 |
| `api/app/chat/tool_loop.py` | `_dispatch_authority`, `execute_tool` intent/dispatch routing, `collect_tool_sources` authority branch | 2, 3 |
| `api/app/citation/authority.py` | `verify_and_persist_authority_citations` finalize orchestrator | 4 |
| `docs/PRD.md` | file DE-370; mark DE-369 chat path shipped | 6 |

---

## Task 1: Authority tool schemas + registry-gated allowlist

**Files:**
- Modify: `api/app/chat/tool_schemas.py`
- Modify: `api/app/api/chats.py:1618, 2013, 2119` (call sites)
- Test: `api/tests/chat/test_tool_schemas.py`

**Interfaces:**
- Consumes: `resolve_available_sources(gateway)` from `app/research/registry.py` (PR1a) — returns available sources each exposing `.type` (e.g. `"govinfo"`) and `.enabled`; and each source's supported ops. Confirm the exact attribute/op-list shape by reading `registry.py` before coding.
- Produces: `AUTHORITY_TOOL_SCHEMAS: dict[str, dict]`, `AUTHORITY_OPS: frozenset[str]`; `ToolSpec.kind` now `Literal["research", "mcp", "authority"]`; `assemble_allowlist(db, *, gateway, request_id=None)` emits `kind="authority"` specs (`provider="govinfo"`, `tool=<op>`, `read_only=True`, `destructive=False`, `requires_confirmation=False`) when a govinfo source is available.

- [ ] **Step 1: Read `registry.py` to pin the `resolve_available_sources` return shape**

Run: `sed -n '1,120p' api/app/research/registry.py`
Note the exact type of each available-source entry (`.type`, `.enabled`, and how to read its op set — the GovInfo source declares `search_authority` + `get_authority`). Use these exact accessors in Step 5.

- [ ] **Step 2: Write the failing tests**

Add to `api/tests/chat/test_tool_schemas.py`:

```python
import pytest
from app.chat.tool_schemas import (
    AUTHORITY_TOOL_SCHEMAS,
    AUTHORITY_OPS,
    assemble_allowlist,
)


def test_authority_schemas_declare_search_and_get():
    assert set(AUTHORITY_OPS) == {"search_authority", "get_authority"}
    for op in AUTHORITY_OPS:
        schema = AUTHORITY_TOOL_SCHEMAS[op]
        assert "description" in schema and schema["description"]
        assert schema["parameters"]["type"] == "object"


class _FakeGovInfoSource:
    type = "govinfo"
    enabled = True
    ops = ("search_authority", "get_authority")


class _FakeGateway:  # only what resolve_available_sources needs
    pass


@pytest.mark.asyncio
async def test_assemble_allowlist_adds_authority_when_govinfo_available(db, monkeypatch):
    async def _fake_resolve(gateway):
        return [_FakeGovInfoSource()]

    monkeypatch.setattr("app.chat.tool_schemas.resolve_available_sources", _fake_resolve)
    allowlist = await assemble_allowlist(db, gateway=_FakeGateway(), request_id="r1")
    authority_specs = [s for s in allowlist.specs.values() if s.kind == "authority"]
    assert {s.tool for s in authority_specs} == {"search_authority", "get_authority"}
    assert all(s.provider == "govinfo" and s.read_only for s in authority_specs)


@pytest.mark.asyncio
async def test_assemble_allowlist_no_authority_when_absent(db, monkeypatch):
    async def _fake_resolve(gateway):
        return []

    monkeypatch.setattr("app.chat.tool_schemas.resolve_available_sources", _fake_resolve)
    allowlist = await assemble_allowlist(db, gateway=_FakeGateway(), request_id="r1")
    assert not any(s.kind == "authority" for s in allowlist.specs.values())


@pytest.mark.asyncio
async def test_assemble_allowlist_authority_failure_does_not_kill_other_ops(db, monkeypatch):
    async def _boom(gateway):
        raise RuntimeError("registry down")

    monkeypatch.setattr("app.chat.tool_schemas.resolve_available_sources", _boom)
    # Should not raise, and should still return a (possibly empty) allowlist.
    allowlist = await assemble_allowlist(db, gateway=_FakeGateway(), request_id="r1")
    assert not any(s.kind == "authority" for s in allowlist.specs.values())
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd api && .venv/bin/python -m pytest tests/chat/test_tool_schemas.py -k authority -v`
Expected: FAIL — `ImportError` on `AUTHORITY_TOOL_SCHEMAS` / `assemble_allowlist` missing `gateway` kwarg.

- [ ] **Step 4: Add the schemas and extend `ToolSpec.kind`**

In `api/app/chat/tool_schemas.py`, after `RESEARCH_TOOL_SCHEMAS` / `RESEARCH_OPS` (around line 77) add:

```python
AUTHORITY_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "search_authority": {
        "description": (
            "Search free U.S. legal authority (U.S. Code, Code of Federal "
            "Regulations) on GovInfo for a statute or regulation. Returns "
            "matching packages with titles and identifiers; call get_authority "
            "to fetch a package's full text before quoting it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms, e.g. '17 USC 107 fair use'."},
                "collection": {
                    "type": "string",
                    "description": "Optional collection filter: 'USCODE' or 'CFR'.",
                },
            },
            "required": ["query"],
        },
    },
    "get_authority": {
        "description": (
            "Fetch the full text of a specific GovInfo authority package (from "
            "search_authority results) so its language can be quoted verbatim."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "package_id": {"type": "string", "description": "GovInfo package id, e.g. 'USCODE-2022-title17'."},
            },
            "required": ["package_id"],
        },
    },
}
AUTHORITY_OPS = frozenset(AUTHORITY_TOOL_SCHEMAS)
```

> Align the `parameters` with the actual GovInfo op contract from PR1a (`app/research/adapters.py` / the gateway `call_tool` args). If PR1a's op requires different arg names, use those exact names.

Extend `ToolSpec.kind` (line 99):

```python
    kind: Literal["research", "mcp", "authority"]
```

Add the registry import near the top imports (module-level is safe — `registry.py` does not import `chat` or `citation`):

```python
from app.research.registry import resolve_available_sources
```

- [ ] **Step 5: Change `assemble_allowlist` signature and add the guarded authority block**

Change the signature (line 130):

```python
async def assemble_allowlist(
    db: AsyncSession, *, gateway: Any, request_id: str | None = None
) -> ChatToolAllowlist:
```

After the research block and before the MCP block, add (use the exact accessors confirmed in Step 1):

```python
    # Authority ops (WS-E) gate on the content-source registry, NOT on
    # get_capabilities (which is CourtListener-only).  Guarded independently:
    # a registry/gateway hiccup must not strip research/MCP tools (PR1a lesson).
    try:
        sources = await resolve_available_sources(gateway)
        govinfo = next(
            (s for s in sources if getattr(s, "type", None) == "govinfo" and getattr(s, "enabled", False)),
            None,
        )
        if govinfo is not None:
            for op, schema in AUTHORITY_TOOL_SCHEMAS.items():
                specs[op] = ToolSpec(
                    function_name=op,
                    kind="authority",
                    provider="govinfo",
                    tool=op,
                    read_only=True,
                    destructive=False,
                    requires_confirmation=False,
                    parameters=schema["parameters"],
                    description=schema["description"],
                )
    except Exception:
        log.warning(
            "assemble_allowlist: authority source resolution failed — "
            "authority tools unavailable this turn",
            exc_info=True,
        )
```

> `specs` is the dict already being built in `assemble_allowlist`; match the exact variable name used for research/MCP. Use the module's existing `log` and `Any` import (add `from typing import Any` if not present).

- [ ] **Step 6: Thread `gateway` into the 3 call sites**

In `api/app/api/chats.py`, update all three call sites to pass the `gateway` already in scope:
- `:1618` → `allowlist = await assemble_allowlist(db, gateway=gateway, request_id=request_id)`
- `:2013` → `current_allowlist = await assemble_allowlist(db, gateway=gateway, request_id=request_id)`
- `:2119` → `resume_allowlist = await assemble_allowlist(db, gateway=gateway, request_id=request_id)`

Confirm `gateway` is the correct in-scope variable at each site (`grep -n "gateway" api/app/api/chats.py` around each line). If any site lacks `gateway`, resolve it the same way that function obtains its gateway client for the finalize path.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd api && .venv/bin/python -m pytest tests/chat/test_tool_schemas.py -v`
Expected: PASS (new authority tests + existing research/MCP tests still green).

- [ ] **Step 8: Commit**

```bash
git add api/app/chat/tool_schemas.py api/app/api/chats.py api/tests/chat/test_tool_schemas.py
git commit -s -m "feat(WS-E): expose search_authority/get_authority chat tools, registry-gated

Refs DE-369

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Authority dispatch + governance routing

**Files:**
- Modify: `api/app/chat/tool_loop.py`
- Test: `api/tests/chat/test_tool_loop.py`

**Interfaces:**
- Consumes: `ToolSpec` (kind `"authority"`), `store_authority_text` (function-local import), `GovInfoAdapter.from_response(op, payload) -> FetchedAuthority` (`.citable_text/.label/.subtitle/.url/.external_ref/.content_kind`), `ToolResult`, `ToolIntent.retrieve_authority`.
- Produces: `_dispatch_authority(db, spec, args, gateway, request_id) -> ToolResult` returning `data={"authority": {...}}`; `execute_tool` routes `kind=="authority"` through `governed_tool_invocation` with `intent=ToolIntent.retrieve_authority`.

- [ ] **Step 1: Write the failing tests**

Add to `api/tests/chat/test_tool_loop.py`:

```python
import pytest
from decimal import Decimal
from app.chat.tool_loop import _dispatch_authority, ToolResult
from app.chat.tool_schemas import ToolSpec


def _authority_spec(op: str) -> ToolSpec:
    return ToolSpec(
        function_name=op, kind="authority", provider="govinfo", tool=op,
        read_only=True, destructive=False, requires_confirmation=False,
        parameters={}, description="",
    )


class _FakeGateway:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    async def call_tool(self, provider, op, args):
        self.calls.append((provider, op, args))
        return {"payload": self._payload}


@pytest.mark.asyncio
async def test_dispatch_get_authority_writes_cache_and_returns_data(db):
    payload = {
        "package_id": "USCODE-2022-title17",
        "citation": "17 U.S.C. 107",
        "title": "Limitations on exclusive rights: Fair use",
        "url": "https://govinfo.example/uscode17",
        "text": "Notwithstanding the provisions of sections 106 and 106A ...",
    }
    gw = _FakeGateway(payload)
    result = await _dispatch_authority(
        db, spec=_authority_spec("get_authority"),
        args={"package_id": "USCODE-2022-title17"}, gateway=gw, request_id="r1",
    )
    assert isinstance(result, ToolResult)
    auth = result.data["authority"]
    assert auth["source"] == "govinfo"
    assert auth["external_ref"] == "USCODE-2022-title17"
    assert auth["content_kind"] == "statute"
    assert "Notwithstanding" in auth["citable_text"]
    # Body was written to the durable cache under source_type="govinfo".
    from app.citation.authority import load_authority_text
    body = await load_authority_text(db, source_type="govinfo", external_ref="USCODE-2022-title17")
    assert body is not None and "Notwithstanding" in body


@pytest.mark.asyncio
async def test_dispatch_search_authority_does_not_write_cache(db):
    payload = {"results": [{"package_id": "USCODE-2022-title17", "title": "Fair use", "dateIssued": "2022-01-01"}], "collection": "USCODE"}
    gw = _FakeGateway(payload)
    result = await _dispatch_authority(
        db, spec=_authority_spec("search_authority"),
        args={"query": "fair use"}, gateway=gw, request_id="r1",
    )
    auth = result.data["authority"]
    assert auth["op"] == "search_authority"
    from app.citation.authority import load_authority_text
    # search results carry the package_id but no body was stored.
    body = await load_authority_text(db, source_type="govinfo", external_ref=auth["external_ref"])
    assert body is None


@pytest.mark.asyncio
async def test_dispatch_authority_cache_failure_is_non_fatal(db, monkeypatch):
    async def _boom(db, *, source_type, external_ref, text):
        raise RuntimeError("storage down")

    monkeypatch.setattr("app.citation.authority.store_authority_text", _boom)
    payload = {"package_id": "USCODE-2022-title17", "citation": "17 U.S.C. 107",
               "title": "Fair use", "url": "u", "text": "body text"}
    result = await _dispatch_authority(
        db, spec=_authority_spec("get_authority"),
        args={"package_id": "USCODE-2022-title17"}, gateway=_FakeGateway(payload), request_id="r1",
    )
    # Dispatch still succeeds; the session is usable afterwards.
    assert result.data["authority"]["citable_text"] == "body text"
    await db.execute(__import__("sqlalchemy").text("SELECT 1"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && .venv/bin/python -m pytest tests/chat/test_tool_loop.py -k authority -v`
Expected: FAIL — `_dispatch_authority` not defined.

- [ ] **Step 3: Add module-level `GovInfoAdapter` import and `_dispatch_authority`**

In `api/app/chat/tool_loop.py`, add near the research imports (module-level — `adapters.py` is a leaf):

```python
from app.research.adapters import GovInfoAdapter
```

Add `_dispatch_authority` next to `_dispatch_research`:

```python
async def _dispatch_authority(
    db: AsyncSession,
    spec: ToolSpec,
    args: dict[str, Any],
    gateway: Any,
    request_id: str | None,
) -> ToolResult:
    """Dispatch an authority op (search_authority/get_authority) via the gateway.

    On get_authority, persist the fetched body to the durable authority cache
    so the finalize verify hook can char-verify quotes against it.  The cache
    write is savepoint-isolated + non-fatal (never poison the session — mirrors
    app/autonomous/guard.py).  Only get_authority yields a quotable body.
    """
    result = await gateway.call_tool(spec.provider, spec.tool, args)
    payload = result.get("payload") if isinstance(result, dict) else None
    authority = GovInfoAdapter().from_response(spec.tool, payload or {})

    if spec.tool == "get_authority" and authority.citable_text:
        # Function-local import breaks the tool_loop <-> citation.authority
        # module cycle (mirrors guard.py:874).
        from app.citation.authority import store_authority_text

        try:
            async with db.begin_nested():
                await store_authority_text(
                    db,
                    source_type=spec.provider,
                    external_ref=authority.external_ref,
                    text=authority.citable_text,
                )
        except Exception:
            log.warning(
                "chat authority dispatch: cache write failed — non-fatal",
                extra={"event": "chat_authority_cache_write_failed",
                       "external_ref": authority.external_ref},
                exc_info=True,
            )

    return ToolResult(
        cost_usd=Decimal("0"),
        data={
            "authority": {
                "source": spec.provider,
                "op": spec.tool,
                "content_kind": authority.content_kind,
                "external_ref": authority.external_ref,
                "label": authority.label,
                "subtitle": authority.subtitle,
                "url": authority.url,
                "citable_text": authority.citable_text,
            }
        },
        outcome="success",
    )
```

> Match `_dispatch_research`'s actual parameter passing convention when you wire the call in Step 4 (positional vs keyword). Confirm `log` and `Decimal` are already imported in this module (they are — used by `_dispatch_research`).

- [ ] **Step 4: Route `kind=="authority"` in `execute_tool`**

Change the intent map (line 462):

```python
    if spec.kind == "research":
        intent = ToolIntent.retrieve_caselaw
    elif spec.kind == "authority":
        intent = ToolIntent.retrieve_authority
    else:
        intent = ToolIntent.call_mcp_tool
```

Change the inner `_dispatch` closure:

```python
    async def _dispatch() -> ToolResult:
        if spec.kind == "research":
            return await _dispatch_research(db, spec, args, cluster_cache, request_id)
        elif spec.kind == "authority":
            return await _dispatch_authority(db, spec, args, gateway, request_id)
        else:
            return await _dispatch_mcp(db, user, gateway, spec, args, server_auth_map, request_id)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd api && .venv/bin/python -m pytest tests/chat/test_tool_loop.py -k authority -v`
Expected: PASS.

- [ ] **Step 6: Guard the import cycle didn't regress — import the module**

Run: `cd api && .venv/bin/python -c "import app.chat.tool_loop, app.citation.authority, app.citation.caselaw, app.api.chats; print('imports ok')"`
Expected: `imports ok` (no `ImportError`/partial-module error).

- [ ] **Step 7: Commit**

```bash
git add api/app/chat/tool_loop.py api/tests/chat/test_tool_loop.py
git commit -s -m "feat(WS-E): dispatch chat authority ops + cache write via governed loop

Refs DE-369

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Authority provenance (`collect_tool_sources`)

**Files:**
- Modify: `api/app/chat/tool_loop.py`
- Test: `api/tests/chat/test_tool_loop.py`

**Interfaces:**
- Consumes: `ToolSpec` (kind `"authority"`), the `data={"authority": {...}}` shape from Task 2.
- Produces: `collect_tool_sources` emits one `ToolSourceRecord(source_kind=<content_kind>, external_ref=<package_id>, provider="govinfo", ...)` for both search and get authority calls.

- [ ] **Step 1: Write the failing test**

Add to `api/tests/chat/test_tool_loop.py`:

```python
from app.chat.tool_loop import collect_tool_sources


def test_collect_tool_sources_authority_branch():
    spec = _authority_spec("get_authority")
    data = {"authority": {
        "source": "govinfo", "op": "get_authority", "content_kind": "statute",
        "external_ref": "USCODE-2022-title17", "label": "17 U.S.C. 107",
        "subtitle": "Fair use", "url": "https://govinfo.example/uscode17",
        "citable_text": "Notwithstanding ...",
    }}
    records = collect_tool_sources(spec, data)
    assert len(records) == 1
    rec = records[0]
    assert rec.source_kind == "statute"
    assert rec.external_ref == "USCODE-2022-title17"
    assert rec.provider == "govinfo"
    assert rec.tool == "get_authority"


def test_collect_tool_sources_authority_search_also_emits():
    spec = _authority_spec("search_authority")
    data = {"authority": {
        "source": "govinfo", "op": "search_authority", "content_kind": "regulation",
        "external_ref": "CFR-2023-title40", "label": "40 CFR", "subtitle": "2023",
        "url": "", "citable_text": "Title 40",
    }}
    records = collect_tool_sources(spec, data)
    assert len(records) == 1 and records[0].source_kind == "regulation"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && .venv/bin/python -m pytest tests/chat/test_tool_loop.py -k collect_tool_sources_authority -v`
Expected: FAIL — authority produces no records (falls into caselaw `else`, returns `[]`).

- [ ] **Step 3: Add the authority branch to `collect_tool_sources`**

In `collect_tool_sources` (line 283), before the caselaw `else`:

```python
def collect_tool_sources(spec: ToolSpec, data: Any) -> list[ToolSourceRecord]:
    if spec.kind == "mcp":
        rec = extract_mcp_tool_source(spec, data)
        return [rec] if rec else []
    if spec.kind == "authority":
        auth = (data or {}).get("authority") if isinstance(data, dict) else None
        if not auth or not auth.get("external_ref"):
            return []
        return [
            ToolSourceRecord(
                source_kind=auth.get("content_kind") or "authority",
                label=auth.get("label") or auth.get("external_ref"),
                subtitle=auth.get("subtitle"),
                url=auth.get("url") or None,
                external_ref=auth.get("external_ref"),
                provider=spec.provider,
                tool=spec.tool,
            )
        ]
    return extract_tool_sources(spec.tool, data)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd api && .venv/bin/python -m pytest tests/chat/test_tool_loop.py -k collect_tool_sources -v`
Expected: PASS (authority + existing caselaw/mcp cases).

- [ ] **Step 5: Commit**

```bash
git add api/app/chat/tool_loop.py api/tests/chat/test_tool_loop.py
git commit -s -m "feat(WS-E): emit MessageToolSource provenance for chat authority calls

Refs DE-369

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Finalize verify orchestrator (`verify_and_persist_authority_citations`)

**Files:**
- Modify: `api/app/citation/authority.py`
- Test: `api/tests/citation/test_authority_verify.py` (new)

**Interfaces:**
- Consumes: `ToolSourceRecord` (TYPE_CHECKING), `load_authority_text`, `authority_target`, `_AuthorityCandidate` (same module); `extract_blockquote_passages` (function-local from `caselaw`); `locate_passage` + `verify` from `app.citation.verification`; `MessageAuthorityCitation` model.
- Produces: `verify_and_persist_authority_citations(db, *, message_id, assistant_text, tool_sources, load_authority_text=load_authority_text, gateway=None, judge_model="fast") -> int`.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/citation/test_authority_verify.py`:

```python
import uuid
import pytest
from sqlalchemy import select
from app.citation.authority import verify_and_persist_authority_citations
from app.chat.tool_loop import ToolSourceRecord
from app.models.message_authority_citation import MessageAuthorityCitation

_BODY = "Notwithstanding the provisions of sections 106 and 106A, the fair use of a copyrighted work is not an infringement of copyright."


def _rec(kind="statute", ref="USCODE-2022-title17"):
    return ToolSourceRecord(
        source_kind=kind, label="17 U.S.C. 107", subtitle="Fair use",
        url="u", external_ref=ref, provider="govinfo", tool="get_authority",
    )


async def _seed_message(db) -> uuid.UUID:
    # Reuse the project's message/chat fixtures; return a persisted message id.
    # (Mirror how tests/citation/test_caselaw_verify.py seeds a message.)
    ...


@pytest.mark.asyncio
async def test_verbatim_quote_persists_pass_row(db, seeded_authority_cache):
    # seeded_authority_cache stores _BODY under (govinfo, USCODE-2022-title17)
    message_id = await _seed_message(db)
    text = f"The statute provides:\n\n> {_BODY}\n\nThat is the rule."
    n = await verify_and_persist_authority_citations(
        db, message_id=message_id, assistant_text=text,
        tool_sources=[_rec()], gateway=None,
    )
    assert n == 1
    rows = (await db.execute(select(MessageAuthorityCitation).where(
        MessageAuthorityCitation.message_id == message_id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].verified is True
    assert rows[0].verification_method in {"exact_match", "tolerant_match"}
    assert rows[0].content_kind == "statute"
    assert rows[0].source_type == "govinfo"


@pytest.mark.asyncio
async def test_quote_matching_no_body_is_dropped(db, seeded_authority_cache):
    message_id = await _seed_message(db)
    text = "> This sentence appears in no fetched authority body whatsoever."
    n = await verify_and_persist_authority_citations(
        db, message_id=message_id, assistant_text=text,
        tool_sources=[_rec()], gateway=None,
    )
    assert n == 0  # drop-on-miss: NO row (no false-FAIL)


@pytest.mark.asyncio
async def test_cache_miss_ref_skipped(db):
    message_id = await _seed_message(db)
    text = f"> {_BODY}"
    n = await verify_and_persist_authority_citations(
        db, message_id=message_id, assistant_text=text,
        tool_sources=[_rec(ref="USCODE-NOT-CACHED")], gateway=None,
    )
    assert n == 0


@pytest.mark.asyncio
async def test_no_authority_refs_returns_zero(db):
    message_id = await _seed_message(db)
    n = await verify_and_persist_authority_citations(
        db, message_id=message_id, assistant_text=f"> {_BODY}",
        tool_sources=[], gateway=None,
    )
    assert n == 0


@pytest.mark.asyncio
async def test_paraphrase_supported_via_stub_gateway(db, seeded_authority_cache):
    message_id = await _seed_message(db)
    # A near-verbatim quote that misses exact/tolerant but a stub judge accepts.
    text = "> the fair use of a copyrighted work is not an infringement"

    class _Judge:
        async def judge(self, *a, **k):
            return {"verdict": "yes", "confidence": 0.9}

    n = await verify_and_persist_authority_citations(
        db, message_id=message_id, assistant_text=text,
        tool_sources=[_rec()], gateway=_Judge(), judge_model="fast",
    )
    # Either exact/tolerant catches it (PASS) or the judge does (SUPPORTED);
    # both are a persisted verified row. Assert method is a SUPPORTED/PASS value.
    rows = (await db.execute(select(MessageAuthorityCitation).where(
        MessageAuthorityCitation.message_id == message_id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].verification_method in {"exact_match", "tolerant_match", "paraphrase_judge"}
```

> Implement `_seed_message` and the `seeded_authority_cache` fixture by mirroring `tests/citation/test_caselaw_verify.py` and `tests/test_authority_substrate.py` (which already stores authority bodies). Read those two files first; reuse their fixtures/helpers rather than re-inventing. Match the stub-gateway judge protocol to what `app.citation.verification.verify` actually calls (read `verify`'s judge invocation before finalizing the `_Judge` stub).

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && .venv/bin/python -m pytest tests/citation/test_authority_verify.py -v`
Expected: FAIL — `verify_and_persist_authority_citations` not defined.

- [ ] **Step 3: Add the `TYPE_CHECKING` import + type alias to `authority.py`**

Near the top of `api/app/citation/authority.py` (after existing imports; `from __future__ import annotations` is already present at line 22):

```python
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Sequence

if TYPE_CHECKING:
    from app.chat.tool_loop import ToolSourceRecord

_LoadAuthorityText = Callable[..., Awaitable[str | None]]
```

> If the module already imports some of these names, merge rather than duplicate.

- [ ] **Step 4: Implement `verify_and_persist_authority_citations`**

Append to `api/app/citation/authority.py`:

```python
async def verify_and_persist_authority_citations(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    assistant_text: str,
    tool_sources: "Sequence[ToolSourceRecord]",
    load_authority_text: _LoadAuthorityText = load_authority_text,
    gateway: Any = None,
    judge_model: str = "fast",
) -> int:
    """Char-verify verbatim/paraphrase quotes of fetched authority in a chat
    turn's answer, persisting MessageAuthorityCitation rows.

    Level-2 depth (WS-E PR1c): verbatim + paraphrase, PASS/SUPPORTED,
    drop-on-miss.  Unlike the autonomous ledger_bridge.build_authority_citations,
    chat blockquotes are unattributed, so a quote that matches NO fetched body
    is dropped (no row) rather than FAILed — avoiding false-positives on
    uploaded-document or caselaw blockquotes.  Attributed-authority FAIL is
    DE-370.  Best-effort: per-ref/per-passage exceptions are logged and skipped.
    """
    # Only get_authority-sourced refs carry a cached body; filter to authority
    # content kinds with an external_ref.
    refs = [
        r for r in tool_sources
        if r.source_kind in {"statute", "regulation"} and r.external_ref
    ]
    if not refs:
        return 0

    # Function-local import breaks the authority <-> caselaw <-> tool_loop cycle.
    from app.citation.caselaw import extract_blockquote_passages
    from app.citation.verification import locate_passage, verify

    passages = extract_blockquote_passages(assistant_text)
    if not passages:
        return 0

    # Load each distinct authority body once.
    targets: list[tuple[str, str, Any]] = []  # (source_type, content_kind, target)
    seen: set[tuple[str, str]] = set()
    for r in refs:
        key = (r.provider, r.external_ref)
        if key in seen:
            continue
        seen.add(key)
        try:
            body = await load_authority_text(
                db, source_type=r.provider, external_ref=r.external_ref
            )
        except Exception:
            log.warning(
                "authority verify: body load failed, skipping ref",
                extra={"event": "chat_authority_verify_load_failed",
                       "external_ref": r.external_ref},
                exc_info=True,
            )
            continue
        if not body:
            continue
        targets.append((r.provider, r.source_kind, authority_target(r.provider, r.external_ref, body)))

    if not targets:
        return 0

    rows: list[MessageAuthorityCitation] = []
    for passage in passages:
        for source_type, content_kind, target in targets:
            try:
                off = locate_passage(passage, target.normalized_content)
            except Exception:
                continue
            if off is None:
                continue
            start, end = off
            cand = _AuthorityCandidate(
                source_offset_start=start,
                source_offset_end=end,
                source_text=passage,
                source_document_id=target.id,
            )
            try:
                result = await verify(cand, target, gateway=gateway, judge_model=judge_model)
            except Exception:
                log.warning(
                    "authority verify: verify() failed, skipping passage",
                    extra={"event": "chat_authority_verify_failed"},
                    exc_info=True,
                )
                continue
            if result.verified:
                rows.append(
                    MessageAuthorityCitation(
                        message_id=message_id,
                        source_type=source_type,
                        external_ref=target.id and next(
                            (r.external_ref for r in refs if r.provider == source_type), None
                        ),
                        content_kind=content_kind,
                        source_offset_start=start,
                        source_offset_end=end,
                        source_text=passage,
                        verified=True,
                        verification_method=result.method,
                        verification_confidence=result.confidence,
                        partial=result.partial,
                    )
                )
                break  # first matching authority wins
            # drop-on-miss: not verified against this body — try the next.

    db.add_all(rows)
    await db.flush()
    return len(rows)
```

> **Simplify the `external_ref` resolution** during implementation: carry `external_ref` in the `targets` tuple (`(source_type, external_ref, content_kind, target)`) instead of the fragile `next(...)` lookup above — the plan shows intent, but the tuple should hold `external_ref` directly so the row records the exact package the quote matched. Ensure `MessageAuthorityCitation(source_type=..., external_ref=..., content_kind=...)` matches PR1b's `build_authority_citations` field usage (`source_type="govinfo"`, `external_ref=package_id`, `content_kind=statute/regulation`). Confirm `MessageAuthorityCitation` is already imported in this module; add `from app.models.message_authority_citation import MessageAuthorityCitation` if not. Confirm a module-level `log` exists; add `log = logging.getLogger(__name__)` if not.

- [ ] **Step 5: Run to verify it passes**

Run: `cd api && .venv/bin/python -m pytest tests/citation/test_authority_verify.py -v`
Expected: PASS.

- [ ] **Step 6: Verify no import cycle**

Run: `cd api && .venv/bin/python -c "import app.citation.authority, app.chat.tool_loop, app.citation.caselaw; print('ok')"`
Expected: `ok`.

- [ ] **Step 7: Commit**

```bash
git add api/app/citation/authority.py api/tests/citation/test_authority_verify.py
git commit -s -m "feat(WS-E): verify_and_persist_authority_citations (chat finalize hook)

Verbatim+paraphrase, PASS/SUPPORTED, drop-on-miss. Refs DE-369

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Wire the verify hook into the chat finalize trio

**Files:**
- Modify: `api/app/api/chats.py` (non-stream `~2948`, stream `~3543`)
- Test: `api/tests/integration/test_authority_citations.py` (new)

**Interfaces:**
- Consumes: `verify_and_persist_authority_citations` (Task 4); the resolved caselaw judge model (`_caselaw_judge_model`); `outcome.tool_sources` / `loop_outcome.tool_sources`.
- Produces: authority rows persisted at finalize → picked up by the unchanged `assemble_ledger_entries` → `compute_and_record_gate`.

- [ ] **Step 1: Write the failing integration test**

Create `api/tests/integration/test_authority_citations.py`, mirroring `tests/integration/test_caselaw_citations.py`:

```python
import pytest
from sqlalchemy import select
from app.models.message_authority_citation import MessageAuthorityCitation
from app.models.work_product_fiduciary_gate import WorkProductFiduciaryGate  # confirm class/module name

# Drive a chat turn (non-stream) where the model calls get_authority and the
# assistant answer quotes the fetched statute verbatim. Assert a PASS
# MessageAuthorityCitation row exists, a ledger entry with source_kind=statute
# exists, and the gate verdict is not "flagged" on account of authority.
#
# Reuse the caselaw integration harness's gateway/model stubs; swap the tool
# call to get_authority and the returned payload to a statute body.

@pytest.mark.asyncio
async def test_chat_get_authority_verbatim_quote_verifies_and_gates(...):
    ...
    rows = (await db.execute(select(MessageAuthorityCitation).where(
        MessageAuthorityCitation.message_id == message_id))).scalars().all()
    assert len(rows) == 1 and rows[0].verified is True


@pytest.mark.asyncio
async def test_chat_fabricated_authority_quote_dropped(...):
    # Model quotes text NOT in the fetched body -> 0 authority rows, gate
    # unaffected by authority.
    ...
```

> Read `tests/integration/test_caselaw_citations.py` first and clone its fixtures (chat creation, gateway stub, streaming vs non-streaming drivers). This is the highest-value test — it proves the whole path end to end.

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && .venv/bin/python -m pytest tests/integration/test_authority_citations.py -v`
Expected: FAIL — no authority rows (hook not wired).

- [ ] **Step 3: Import the hook in `chats.py`**

Near the caselaw import (line 86):

```python
from app.citation.authority import verify_and_persist_authority_citations
```

- [ ] **Step 4: Wire the non-stream finalize site (~2948)**

Immediately AFTER the `verify_and_persist_caselaw_citations(...)` try/except and BEFORE `assemble_ledger_entries(...)`:

```python
            try:
                await verify_and_persist_authority_citations(
                    db,
                    message_id=message_id,
                    assistant_text=assistant_text,
                    tool_sources=outcome.tool_sources,
                    gateway=gateway,
                    judge_model=_caselaw_judge_model,
                )
            except Exception:
                log.warning(
                    "chat finalize: authority citation verify failed — non-fatal",
                    extra={"event": "chat_authority_verify_finalize_failed"},
                    exc_info=True,
                )
```

> Use the exact `assistant_text` / `tool_sources` variable names in scope at this site (match what the caselaw call passes — same `assistant_text`, same `outcome.tool_sources`). Reuse the already-resolved `_caselaw_judge_model` (no second gateway round-trip).

- [ ] **Step 5: Wire the stream finalize site (~3543)**

Same insertion AFTER the streaming `verify_and_persist_caselaw_citations(...)` and BEFORE `assemble_ledger_entries(...)`, using the streaming site's tool-sources expression (`loop_outcome.tool_sources if isinstance(loop_outcome, LoopFinal) else []`):

```python
            try:
                await verify_and_persist_authority_citations(
                    db,
                    message_id=message_id,
                    assistant_text=assistant_text,
                    tool_sources=(loop_outcome.tool_sources if isinstance(loop_outcome, LoopFinal) else []),
                    gateway=gateway,
                    judge_model=_caselaw_judge_model,
                )
            except Exception:
                log.warning(
                    "chat finalize (stream): authority citation verify failed — non-fatal",
                    extra={"event": "chat_authority_verify_finalize_failed"},
                    exc_info=True,
                )
```

> Confirm the streaming site's `assistant_text` variable name (the assembled streamed answer) and the `_caselaw_judge_model` resolution both exist at that site (they do — lines 3540-3542). Match them exactly.

- [ ] **Step 6: Run the integration tests to verify they pass**

Run: `cd api && .venv/bin/python -m pytest tests/integration/test_authority_citations.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add api/app/api/chats.py api/tests/integration/test_authority_citations.py
git commit -s -m "feat(WS-E): verify chat authority quotes at finalize (both sites)

Closes DE-369 for the chat path. Refs DE-369

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: File DE-370; mark DE-369 chat path shipped

**Files:**
- Modify: `docs/PRD.md` (§9 Deferred Enhancements; DE-369 entry)

- [ ] **Step 1: Add DE-370 to PRD §9**

Add a new deferred-enhancement entry:

```markdown
- **DE-370 — Attributed-authority FAIL tier (chat).** WS-E PR1c verifies chat
  quotes of fetched authority verbatim+paraphrase (PASS/SUPPORTED) but drops a
  quote that matches no fetched body rather than FAILing it, because chat
  blockquotes carry no reliable authority attribution. DE-370 adds an
  attribution parser (blockquote → nearby statute/reg citation → matched
  get_authority ref) so a quote attributed to authority X that is not in X
  FAILs and flags the fiduciary gate — the B1c-analog for authority. Mirrors
  the caselaw B1b→B1c staging.
```

- [ ] **Step 2: Update the DE-369 entry**

Mark DE-369 fully shipped: autonomous path (PR1b) **and** chat path (PR1c). Note the honest ceiling (drop-on-miss for chat) and the DE-370 pointer.

- [ ] **Step 3: Commit**

```bash
git add docs/PRD.md
git commit -s -m "docs(PRD): file DE-370 (attributed-authority FAIL); DE-369 chat path shipped

Refs DE-369, DE-370

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final gates (run before opening the PR — repo ROOT, SOLO)

- [ ] `cd api && .venv/bin/python -m ruff check app scripts tests` → clean (run from repo root as `ruff check api scripts` in CI).
- [ ] `ruff format --check api scripts` (repo root) → clean.
- [ ] `cd api && .venv/bin/python -m mypy app` → clean.
- [ ] `cd api && .venv/bin/python -m pytest -p no:randomly -q` → full suite green, run **SOLO** (no other pytest process against `lqai_test`; DE-368).
- [ ] Confirm no new endpoint was added → `IMPLEMENTED_ROUTES` / `EXPECTED_PATHS` in `tests/test_endpoints.py` / `tests/test_openapi.py` unchanged.
- [ ] Opus whole-branch review, pointed at: (1) the `ToolSpec.kind` third-value change touching every `spec.kind ==` branch (dispatch, intent map, provenance); (2) the two function-local imports (cycle break); (3) the never-poison savepoint + best-effort finalize paths; (4) `external_ref` recorded on each authority row matches the body actually matched.

## Self-review notes (spec coverage)

- Spec §4.1 (schemas + `ToolSpec.kind` + `assemble_allowlist` gateway/guard) → Task 1. ✓
- Spec §4.2 (`_dispatch_authority`, intent map, dispatch routing) → Task 2. ✓
- Spec §4.2 (`collect_tool_sources` authority branch) → Task 3. ✓
- Spec §4.3 (`verify_and_persist_authority_citations`, verbatim+paraphrase, drop-on-miss) → Task 4. ✓
- Spec §4.4 (finalize wiring, both sites, single-shot untouched) → Task 5. ✓
- Spec §5 invariants (reuse, never-poison, honest, provenance-always, P3, one-egress, get-only-quotable) → enforced across Tasks 1–5. ✓
- Spec §6 (DE-370 deferral) → Task 6. ✓
- Spec §7 (no migration; no gate.py/ledger.py change) → Global Constraints; no task touches those files. ✓
```
