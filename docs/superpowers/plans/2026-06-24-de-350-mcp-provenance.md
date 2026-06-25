# DE-350 — Generic-MCP-result provenance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record one `message_tool_sources` row (`source_kind='mcp'`) per successful MCP tool call in a chat turn, with a defensive best-effort label/url, so MCP consultations show up in "Sources consulted" and flow into the Citation Ledger.

**Architecture:** A pure extractor `extract_mcp_tool_source(spec, data)` builds one `ToolSourceRecord` from a `ToolSpec` + the MCP result payload (label/url via a never-raising helper). A `collect_tool_sources(spec, data)` router keyed on `spec.kind` replaces the direct `extract_tool_sources` call at the capture site; the existing caselaw path and dedup loop are untouched. No schema change; the P1-A2 ledger picks up `mcp` rows automatically.

**Tech Stack:** Python 3.12, pytest (host venv), ruff, mypy. No DB/migration.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-06-24-de-350-mcp-provenance-design.md`. Tracking: [DE-350](../../PRD.md#de-350).
- **One row per MCP call** (not per item); **best-effort defensive label/url** (never crash on an odd payload).
- **No schema change** — `message_tool_sources.source_kind` already accepts `'mcp'`; **no ledger change** (assembler is source-kind-agnostic).
- **No regression to the caselaw path** — `extract_tool_sources` and its tests stay unchanged.
- **Gates:** `ruff format`, `ruff check`, `mypy app` (standard mode), `pytest`.
- **Test DB env (only needed for the chat-loop regression in Task 2):** `cd /Users/kevinkeller/Code/lq-ai/api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest <args>`. If the throwaway container isn't running: `docker run -d --rm --name lqai-test-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=lqai_test -p 55432:5432 pgvector/pgvector:pg16`, then `docker exec lqai-test-pg psql -U postgres -d lqai_test -c "CREATE EXTENSION IF NOT EXISTS vector;"`. NEVER host alembic; never port 15432. The Task 1 unit tests need NO DB.
- **Commits:** `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Reference shapes:** `ToolSpec(function_name, kind, provider, tool, read_only, destructive, requires_confirmation, parameters, description="")` (frozen dataclass, `app/chat/tool_schemas.py`); `ToolSourceRecord(source_kind, label, subtitle, url, external_ref, provider, tool)` (`app/chat/tool_loop.py`).

## File Structure

- `api/app/chat/tool_loop.py` — **modify**: add `_MCP_TITLE_KEYS`/`_MCP_URL_KEYS`, `_mcp_label_url`, `extract_mcp_tool_source`, `collect_tool_sources`; swap the capture-site call.
- `api/tests/test_extract_tool_sources.py` — **modify**: add MCP + routing unit tests.
- `api/app/models/message_tool_source.py` — **modify**: docstring (MCP now supported).
- `docs/PRD.md` — **modify**: mark DE-350 shipped.

---

### Task 1: MCP source extractor + router (pure)

**Files:**
- Modify: `api/app/chat/tool_loop.py`
- Test: `api/tests/test_extract_tool_sources.py`

**Interfaces:**
- Consumes: `ToolSpec` (`app.chat.tool_schemas`), `ToolSourceRecord` + `extract_tool_sources` (already in `tool_loop.py`).
- Produces:
  - `extract_mcp_tool_source(spec: ToolSpec, data: Any) -> ToolSourceRecord | None`
  - `collect_tool_sources(spec: ToolSpec, data: Any) -> list[ToolSourceRecord]`
  - `_mcp_label_url(data: Any) -> tuple[str | None, str | None]`

- [ ] **Step 1: Write the failing tests** — append to `api/tests/test_extract_tool_sources.py`

```python
from app.chat.tool_loop import (
    collect_tool_sources,
    extract_mcp_tool_source,
)
from app.chat.tool_schemas import ToolSpec


def _spec(kind: str, provider: str, tool: str) -> ToolSpec:
    return ToolSpec(
        function_name=f"{provider}__{tool}",
        kind=kind,  # type: ignore[arg-type]
        provider=provider,
        tool=tool,
        read_only=True,
        destructive=False,
        requires_confirmation=False,
        parameters={},
    )


def test_mcp_source_from_dict_payload_with_title_and_url():
    spec = _spec("mcp", "deepwiki", "ask_question")
    data = {"title": "Repo answer", "url": "https://example.com/x", "body": "..."}
    rec = extract_mcp_tool_source(spec, data)
    assert rec is not None
    assert rec.source_kind == "mcp"
    assert rec.provider == "deepwiki"
    assert rec.tool == "ask_question"
    assert rec.label == "Repo answer"
    assert rec.url == "https://example.com/x"
    assert rec.external_ref is None


def test_mcp_source_from_text_blocks_falls_back_to_descriptor():
    spec = _spec("mcp", "deepwiki", "ask_question")
    data = [{"type": "text", "text": "some answer"}, {"type": "text", "text": "more"}]
    rec = extract_mcp_tool_source(spec, data)
    assert rec is not None
    assert rec.label == "deepwiki · ask_question"
    assert rec.url is None


def test_mcp_source_from_dict_block_inside_list_surfaces_url():
    spec = _spec("mcp", "srv", "search")
    data = [{"type": "text", "text": "intro"}, {"name": "Result One", "link": "https://e/1"}]
    rec = extract_mcp_tool_source(spec, data)
    assert rec is not None
    assert rec.label == "Result One"
    assert rec.url == "https://e/1"


def test_mcp_source_malformed_payload_never_crashes():
    spec = _spec("mcp", "srv", "t")
    for data in (None, "a bare string", [1, 2, 3], {"url": 5}):  # url=5 is not a str -> ignored
        rec = extract_mcp_tool_source(spec, data)
        assert rec is not None
        assert rec.label == "srv · t"
        assert rec.url is None


def test_extract_mcp_returns_none_for_non_mcp_spec():
    assert extract_mcp_tool_source(_spec("research", "courtlistener", "get_cluster"), {}) is None


def test_collect_routes_mcp_to_one_record():
    recs = collect_tool_sources(_spec("mcp", "srv", "t"), {"title": "T"})
    assert len(recs) == 1
    assert recs[0].source_kind == "mcp"


def test_collect_routes_research_caselaw_to_existing_path():
    data = {"cluster": {"cluster_id": 7, "case_name": "X v. Y", "court": "ca9",
                        "date_filed": "2001-05-05", "absolute_url": "https://www.courtlistener.com/opinion/7/"}}
    recs = collect_tool_sources(_spec("research", "courtlistener", "get_cluster"), data)
    assert len(recs) == 1
    assert recs[0].source_kind == "caselaw"
    assert recs[0].external_ref == "7"


def test_collect_research_non_caselaw_tool_yields_no_rows():
    assert collect_tool_sources(_spec("research", "courtlistener", "read_opinion"), {"text": "..."}) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && .venv/bin/pytest tests/test_extract_tool_sources.py -v`
Expected: FAIL — `ImportError: cannot import name 'extract_mcp_tool_source'`.

- [ ] **Step 3: Implement the extractor + router** — add to `api/app/chat/tool_loop.py`, immediately after the existing `extract_tool_sources` function (around line 224)

```python
# ---------------------------------------------------------------------------
# Generic-MCP provenance (DE-350)
# ---------------------------------------------------------------------------

_MCP_TITLE_KEYS: tuple[str, ...] = ("title", "name", "label")
_MCP_URL_KEYS: tuple[str, ...] = ("url", "link", "href")


def _mcp_label_url(data: Any) -> tuple[str | None, str | None]:
    """Best-effort (title, url) from a heterogeneous MCP payload. Never raises.

    Reads a title/url only from dict-shaped data (a top-level dict, or the first
    dict element inside a list — the standard MCP ``content`` block list). Plain
    text blocks yield ``(None, None)``. Any odd shape or error → ``(None, None)``.
    """

    def _from_dict(d: dict[str, Any]) -> tuple[str | None, str | None]:
        title = next((d[k] for k in _MCP_TITLE_KEYS if isinstance(d.get(k), str) and d[k]), None)
        url = next((d[k] for k in _MCP_URL_KEYS if isinstance(d.get(k), str) and d[k]), None)
        return title, url

    try:
        if isinstance(data, dict):
            return _from_dict(data)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    title, url = _from_dict(item)
                    if title is not None or url is not None:
                        return title, url
        return None, None
    except Exception:
        return None, None


def extract_mcp_tool_source(spec: ToolSpec, data: Any) -> ToolSourceRecord | None:
    """One retrieval-provenance record for a successful MCP tool call (DE-350).

    Per-call provenance: ``source_kind='mcp'``, provider/tool from the spec, a
    best-effort label/url, ``external_ref=None``. Returns ``None`` for a
    non-MCP spec (defensive; the router only calls it for ``kind == 'mcp'``).
    """
    if spec.kind != "mcp":
        return None
    title, url = _mcp_label_url(data)
    return ToolSourceRecord(
        source_kind="mcp",
        label=title or f"{spec.provider} · {spec.tool}",
        subtitle=None,
        url=url,
        external_ref=None,
        provider=spec.provider,
        tool=spec.tool,
    )


def collect_tool_sources(spec: ToolSpec, data: Any) -> list[ToolSourceRecord]:
    """Route a tool result to its provenance records by ``spec.kind`` (DE-350).

    MCP → one ``mcp`` record; research → the existing case-law extraction.
    """
    if spec.kind == "mcp":
        rec = extract_mcp_tool_source(spec, data)
        return [rec] if rec is not None else []
    return extract_tool_sources(spec.tool, data)
```

> `ToolSpec` is already imported in `tool_loop.py` (used by `_dispatch_mcp`); confirm with `grep -n "ToolSpec" api/app/chat/tool_loop.py` and add it to the existing `from app.chat.tool_schemas import ...` line only if absent.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && .venv/bin/pytest tests/test_extract_tool_sources.py -v`
Expected: PASS (the new tests + all pre-existing caselaw tests).

- [ ] **Step 5: Lint + type-check**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && .venv/bin/ruff format app/chat/tool_loop.py tests/test_extract_tool_sources.py && .venv/bin/ruff check app/chat/tool_loop.py tests/test_extract_tool_sources.py && .venv/bin/mypy app/chat/tool_loop.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add api/app/chat/tool_loop.py api/tests/test_extract_tool_sources.py
git commit -s -m "feat(chat): generic-MCP provenance extractor + router (DE-350)"
```

---

### Task 2: Wire the capture site + docs

**Files:**
- Modify: `api/app/chat/tool_loop.py` (the capture site)
- Modify: `api/app/models/message_tool_source.py` (docstring)
- Modify: `docs/PRD.md` (DE-350 status)

**Interfaces:**
- Consumes: `collect_tool_sources` (Task 1).

- [ ] **Step 1: Swap the capture-site call** — `api/app/chat/tool_loop.py`

Find the provenance-capture loop (`grep -n "extract_tool_sources(spec.tool, result.data)" api/app/chat/tool_loop.py` — one site, ~line 604). Change ONLY the iterator expression, leaving the dedup body unchanged:

```python
                # retrieval-provenance: record the sources this call surfaced
                # (case-law clusters and, per DE-350, generic MCP consultations).
                for rec in collect_tool_sources(spec, result.data):
                    if rec.external_ref is None or rec.external_ref not in _seen_source_refs:
                        if rec.external_ref is not None:
                            _seen_source_refs.add(rec.external_ref)
                        collected_sources.append(rec)
```

(Only the `for rec in ...` line changes from `extract_tool_sources(spec.tool, result.data)` to `collect_tool_sources(spec, result.data)`, plus the comment. MCP records have `external_ref=None`, so each MCP call appends one row.)

- [ ] **Step 2: Run the chat-loop regression + the unit tests**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest tests/test_extract_tool_sources.py tests/integration/test_chat_tool_loop_send.py tests/integration/test_chat_tool_call_resume.py tests/test_message_tool_sources.py -q`
Expected: PASS, no regressions. (If `tests/integration/test_chat_tool_loop_send.py` already exercises an MCP tool call, confirm an `mcp` source row now appears; if it doesn't exercise MCP, the unit tests are the coverage and these prove no caselaw regression.)

- [ ] **Step 3: Update the model docstring** — `api/app/models/message_tool_source.py`

Replace the docstring sentence that currently reads (verbatim find):

```
Case-law only
in PR6c (``source_kind='caselaw'``); generic MCP results are DE-350.
```

with:

```
Case-law (``source_kind='caselaw'``, PR6c) and generic MCP connector results
(``source_kind='mcp'``, DE-350).
```

- [ ] **Step 4: Mark DE-350 shipped** — `docs/PRD.md`

Under the `#### DE-350 — Generic-MCP-result provenance ...` heading, the line currently reads:

```
**Priority:** P3 · **Effort:** M
```

Change it to:

```
**Priority:** P3 · **Effort:** M · **Status: SHIPPED** (2026-06-24)
```

And append one sentence to the end of the DE-350 **Context** paragraph:

```
Shipped: one `message_tool_sources` row per MCP call (`source_kind='mcp'`, provider=server, tool=tool) with a defensive best-effort label/url; per-result-item parsing and per-server label/url conventions remain deferred. Design: `docs/superpowers/specs/2026-06-24-de-350-mcp-provenance-design.md`.
```

- [ ] **Step 5: Run the full gate**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && .venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy app && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest -q`
Expected: all green (no `-m provider`). If a failure traces to this branch, fix it; if pre-existing/unrelated, report it with diagnosis.

- [ ] **Step 6: Commit**

```bash
git add api/app/chat/tool_loop.py api/app/models/message_tool_source.py docs/PRD.md
git commit -s -m "feat(chat): record MCP provenance at chat finalize + docs (DE-350)"
```

---

## Self-Review

**Spec coverage:**
- Component 1 (`extract_mcp_tool_source`) → Task 1. ✓
- Component 1a (`_mcp_label_url`, defensive) → Task 1. ✓
- Component 2 (`collect_tool_sources` router + capture-site swap) → Task 1 (router) + Task 2 (swap). ✓
- Error handling (never raises; success-only) → Task 1 helper + Task 2 site (extraction already runs only on dispatch success). ✓
- Testing (dict/list/malformed/routing) → Task 1. ✓
- Docs (model docstring + PRD DE-350) → Task 2. ✓
- Acceptance criteria 1–4 → Task 1 unit tests + Task 2 regression + gate. ✓

**Placeholder scan:** none — every code step is complete; the only "find" steps are exact-string doc replacements with verbatim before/after.

**Type consistency:** `extract_mcp_tool_source(spec: ToolSpec, data: Any) -> ToolSourceRecord | None`, `collect_tool_sources(spec: ToolSpec, data: Any) -> list[ToolSourceRecord]`, `_mcp_label_url(data: Any) -> tuple[str | None, str | None]` consistent across tasks. `ToolSpec` fields and `ToolSourceRecord` fields match the model definitions. `source_kind='mcp'`, `external_ref=None` consistent with the dedup behavior described.
