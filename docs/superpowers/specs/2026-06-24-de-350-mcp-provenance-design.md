# DE-350 — Generic-MCP-result provenance (design)

**Date:** 2026-06-24
**Tracking:** [DE-350](../../PRD.md#de-350) (PRD §9). Milestone: fiduciary-grade — sequenced immediately after P1-A2 (the Citation Ledger), per maintainer directive 2026-06-24.
**Branch:** `feat/de-350-mcp-provenance`
**Security review:** the change is in the chat tool-loop provenance path (no egress, no governance change) — routine review; flag if CODEOWNERS routes it.

## Problem

PR6c shipped retrieval-provenance (`message_tool_sources`, the "Sources consulted" panel) for **case-law** tool results only: `extract_tool_sources(tool_name, data)` (`api/app/chat/tool_loop.py`) emits records only for `search_case_law` / `get_cluster` (`source_kind='caselaw'`). A chat turn that calls an operator-wired **MCP** tool records nothing — the consultation is invisible. The P1-A2 Citation Ledger maps every `message_tool_sources` row into a ledger entry, so an MCP call also produces no ledger entry today.

DE-350 extends provenance capture to generic MCP tool results (`source_kind='mcp'`). Because the ledger assembler is source-kind-agnostic (it copies `source_kind` from the row), MCP rows flow into the ledger automatically with no ledger change.

## Decisions (maintainer-approved 2026-06-24)

- **One row per MCP tool call** (not per result item). Each successful MCP call → one `message_tool_sources` row. Honest "the agent consulted tool X on server Y"; robust against heterogeneous MCP result shapes; mirrors how `get_cluster` makes one row per cluster.
- **Best-effort, defensive label/url.** `label` defaults to a server/tool descriptor; a `url`/`title` is surfaced only when the payload obviously carries one, behind a try/except that never crashes on an odd shape.

## Grounding (verified against `main`, 2026-06-24)

- `ToolSpec` carries `kind: Literal["research", "mcp"]` (`api/app/chat/tool_schemas.py`) — the clean discriminator; non-caselaw *research* tools (`read_opinion`/`find_in_case`/`verify_citations`) are `kind="research"`, so they will not be mistaken for MCP.
- The MCP dispatch (`_dispatch_mcp`) returns `ToolResult(data=result.get("payload"))` where the gateway's MCP adapter sets `payload = content` — the MCP result's `content` (a list of content blocks, typically `{"type":"text","text":...}`, occasionally structured). The adapter raises on `isError`, so extraction only runs on success.
- The provenance capture site is `tool_loop.py:604`: `for rec in extract_tool_sources(spec.tool, result.data):` followed by an `external_ref`-keyed dedup into `collected_sources` (via `_seen_source_refs`).
- `ToolSourceRecord` fields: `source_kind, label, subtitle, url, external_ref, provider, tool`.

## Design

### Component 1 — `extract_mcp_tool_source(spec, data) -> ToolSourceRecord | None`

New function in `api/app/chat/tool_loop.py`, beside `extract_tool_sources`. For a successful MCP call it returns one record:

- `source_kind="mcp"`
- `provider=spec.provider` (the MCP server name)
- `tool=spec.tool`
- `label` / `url` from `_mcp_label_url(data)` (Component 1a); `label` falls back to `f"{spec.provider} · {spec.tool}"` when no title is found
- `subtitle=None`, `external_ref=None`

Returns `None` only if `spec.kind != "mcp"` (defensive guard; the caller already routes by kind). It always emits a record for an MCP call — provenance records the consultation even when the payload carries no title/url.

### Component 1a — `_mcp_label_url(data) -> tuple[str | None, str | None]`

A defensive best-effort extractor. Returns `(title, url)` where either may be `None`:

- If `data` is a `dict`: read a title from the first present of `title` / `name` / `label`; read a url from the first present of `url` / `link` / `href` (only when the value is a non-empty `str`).
- If `data` is a `list` (the standard MCP `content` shape): scan for the first element that is a `dict` carrying any of those title/url keys and use it. Plain text blocks (`{"type":"text","text":...}`) yield `(None, None)`.
- Any exception → `(None, None)`. The whole body is wrapped so a malformed payload can never break the turn.

### Component 2 — `collect_tool_sources(spec, data) -> list[ToolSourceRecord]`

A thin router in `tool_loop.py` so the capture site stays clean:

- `spec.kind == "mcp"` → `[r for r in (extract_mcp_tool_source(spec, data),) if r is not None]`
- otherwise → `extract_tool_sources(spec.tool, data)` (the existing caselaw path, unchanged)

The capture site (`tool_loop.py:604`) changes from `extract_tool_sources(spec.tool, result.data)` to `collect_tool_sources(spec, result.data)`; the surrounding `external_ref` dedup loop is **unchanged**. MCP records carry `external_ref=None`, so each call appends one row (the dedup only suppresses repeated *caselaw* clusters).

## Error handling

- `_mcp_label_url` never raises (try/except → `(None, None)`).
- Extraction runs only on dispatch success (the adapter raises on `isError`).
- No new egress, no governance/tier change — purely how a successful result is recorded.

## Testing

Extend `api/tests/test_extract_tool_sources.py` (unit, no DB):

- `extract_mcp_tool_source` with a **dict payload** carrying `title` + `url` → those surface; `source_kind='mcp'`, `provider`/`tool` from the spec.
- with a **list-of-text-blocks** payload → `label == "{provider} · {tool}"`, `url is None`.
- with a **dict content block inside a list** carrying a url → url surfaces.
- with `None` / a malformed payload (e.g. a bare string, a list of ints) → no crash, fallback label, `url is None`.
- `collect_tool_sources` routes: a `kind="mcp"` spec → one mcp record; a `kind="research"` `get_cluster` spec → the existing caselaw record(s); a `kind="research"` `read_opinion` spec → `[]`.

If `api/tests/test_extract_tool_sources.py` already has `ToolSpec` fixtures, reuse them; otherwise build minimal `ToolSpec(kind=..., provider=..., tool=...)` instances.

## Acceptance criteria

1. A successful MCP tool call in a chat turn yields one `message_tool_sources` row with `source_kind='mcp'`, `provider=`server, `tool=`tool name.
2. The label is a sensible server/tool descriptor; a url/title surfaces when the payload obviously carries one; a malformed payload never crashes the turn.
3. The caselaw path and its tests are unchanged (no regression); non-caselaw research tools still produce no MCP rows.
4. `ruff` + `mypy` clean; the extended unit tests + the existing chat-loop tests green.

## Out of scope / follow-ons

- Per-result-item provenance and per-server label/url convention config — deferred (heavier; revisit if a real MCP server needs richer surfacing).
- The autonomous layer's `call_mcp_tool` path — `message_tool_sources` is chat-turn-scoped (FK to `messages`); autonomous provenance is a separate surface, out of scope.
- No `message_tool_sources` schema change (the `source_kind` string already accepts `'mcp'`). No ledger change (the assembler is source-kind-agnostic).
- Docs: update the `message_tool_source` model docstring (drop "Case-law only … generic MCP results are DE-350") and note DE-350 shipped in PRD §9.
