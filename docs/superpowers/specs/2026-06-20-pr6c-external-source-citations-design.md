# PR6c — External-source citations (case-law provenance) Design Spec

> **Milestone:** Legal research + MCP (WS5 / PR6). **Slice:** 6c (after 6a transparency narrative + 6b chat tool-loop UI; before 6d case-law skill).
> **Date:** 2026-06-20. **Branch (to create):** `feat/pr6c-external-source-citations` off `main` (`47d9bed`).

## Goal

When a chat turn consults external case law (CourtListener, via the governed tool-loop), record **which cases it pulled in** as persisted provenance, and surface them in the chat as an inline "Sources consulted" sidecar with a provenance pill. This makes the founding-principle question — *"where did this answer's research come from?"* — answerable right where the user reads the answer, and discharges the D6 narrative obligation by flipping the "rich case-law provenance" claim from "coming next" to "shipped."

## Decisions locked in brainstorming (2026-06-20)

1. **Retrieval-provenance, not marker-grounding.** We persist every case the case-law tool *returned* for a turn ("sources consulted"), independent of whether the assistant quotes it. No fragile per-claim `(Source: [N])` marker-matching against external text, and no new verification path. Matches the narrative line already shipped in 6b ("the external sources a tool call pulled in").
2. **New table + endpoint, not an extension of `message_citations`.** `message_citations` stays purely about verified document quotes (offsets, `verified`, `verification_method`). External provenance has none of those semantics, so it lives in a dedicated `message_tool_sources` table with its own read endpoint.
3. **Inline per-message sidecar, not a chat-wide drawer.** Sources render under the assistant turn that retrieved them, mirroring the existing `M2Citations` sidecar + `ProvenancePill` pattern.

## Non-goals (explicit scope guard)

- **Case-law tools only.** Only research/case-law tools (`search_case_law`, `get_cluster`, `read_opinion`, `find_in_case`) produce source rows in 6c — that is where structured metadata already exists (`ResearchClusterMetadata`). Generic MCP tool results are **out of scope**; `source_kind` is designed to extend to them later → **DE-360** (see §9 follow-ups).
- **No claim-level grounding.** We do not tie a specific sentence to a specific case.
- **No chat-wide aggregation drawer.** Inline sidecar only.
- **No new SSE frames / protocol change.** The frontend fetches sources post-stream, exactly like citations. The streaming tool-loop (PR5b/6b) is untouched on the wire.
- **No cost model.** Per-provider research cost stays `Decimal("0")` (DE-344, unchanged).
- **`message_citations` is not modified.** No migration to that table; the verification cascade in `chats.py` is not touched.

## Architecture

```
tool-loop (research tool executes)
  └─ _dispatch_research() returns structured `data` (cluster/opinion metadata)
        └─ tool-loop accumulates ToolSourceRecord[] (dedup by external_ref within the turn)
              └─ turn-end: _persist_message_tool_sources(message_id, records)  [chats.py]
                    └─ message_tool_sources rows (FK message_id)

chat UI (assistant turn finished streaming)
  └─ MessageBubble lazy-fetches GET /messages/{id}/sources  (guard: !isStreaming)
        └─ ProvenancePill  "⚖ N sources consulted"
        └─ ToolSourcesPanel  collapsible "Sources consulted (N)" → one row per case
```

Source capture happens at tool-execution time (the structured data is in hand), but **persistence is post-hoc at turn-end** and **fetch is post-stream** — so 6c adds no streaming-protocol surface and reuses the proven citations lazy-fetch pattern.

## Data model

### New table `message_tool_sources` (migration **0055**, head is currently 0054)

| Column | Type | Constraints / notes |
|---|---|---|
| `id` | UUID | PK, default `gen_random_uuid()` |
| `message_id` | UUID | FK → `messages.id` ON DELETE CASCADE; indexed |
| `source_kind` | TEXT | NOT NULL; `'caselaw'` in 6c. Application-level enum (extensible). |
| `label` | TEXT | NOT NULL; human title, e.g. `"Roe v. Wade, 410 U.S. 113 (1973)"` (falls back to case name) |
| `subtitle` | TEXT | NULL; e.g. `"U.S. Supreme Court · 1973"` |
| `url` | TEXT | NULL; CourtListener `absolute_url` (absolutized to a full URL) |
| `external_ref` | TEXT | NULL; CourtListener cluster (or opinion) id — the per-turn dedupe key |
| `provider` | TEXT | NOT NULL; `'courtlistener'` |
| `tool` | TEXT | NOT NULL; the tool name that surfaced it (`search_case_law`, …) |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `now()` |

- **Index:** `(message_id)` for the endpoint's lookup; ordering by `created_at` (insertion order = retrieval order).
- **Dedup:** within a single turn, the same `external_ref` is recorded once (the first tool that surfaced it wins for `tool`). Across turns, the same case can recur (each turn records its own consultation).
- **Granularity:** one row per retrieved **cluster/case**. A `search_case_law` returning 5 clusters → up to 5 rows; `get_cluster`/`read_opinion` → 1 row (its cluster).

### `docs/db-schema.md`

Add a `message_tool_sources` section documenting the columns, the index, the retrieval-provenance semantics (vs `message_citations`' quote-verification semantics), and the case-law-only scope.

## Backend

### Capture (`api/app/chat/tool_loop.py`)

- Define a small internal `ToolSourceRecord` dataclass (`source_kind, label, subtitle, url, external_ref, provider, tool`).
- A pure helper `extract_tool_sources(tool_name: str, data: Any) -> list[ToolSourceRecord]` maps a research tool's structured result into source records:
  - `search_case_law` → one record per returned cluster (case_name → `label`, court+date → `subtitle`, `absolute_url` → `url`, cluster id → `external_ref`).
  - `get_cluster` / `read_opinion` / `find_in_case` → the single cluster the call concerned.
  - Non-research tools → `[]`.
  This helper is **pure and unit-tested** against representative payloads.
- `run_chat_tool_loop()` accumulates records across the turn into an ordered, `external_ref`-deduped list, and returns it alongside the existing result so the caller can persist it.

### Persist (`api/app/api/chats.py`)

- `_persist_message_tool_sources(db, message_id, records)` — mirrors `_persist_message_citations`: build rows, `db.add_all`, within the same turn-finalization path. No-op when the list is empty.

### Endpoint (`api/app/api/chats.py`)

- `GET /api/v1/chats/{chat_id}/messages/{message_id}/sources` → `list[ToolSourceOut]`.
- Reuses the same chat-ownership / message-belongs-to-chat checks as the citations GET. Returns `[]` (not 404) when the message has no sources, so the frontend lazy-fetch degrades cleanly (matches citations' tolerant behavior).
- Pydantic `ToolSourceOut` schema (`api/app/schemas/`).

### Test-suite collision guards (CLAUDE.md)

- Add the new route to `IMPLEMENTED_ROUTES` in `api/tests/test_endpoints.py`.
- Bump the exact path count **and** add the path to `EXPECTED_PATHS` in `api/tests/test_openapi.py` (currently pinned at 133 → 134).
- Add the `ToolSource` schema + the path to `docs/api/backend-openapi.yaml` (authoritative conformance check is `test_openapi.py` — run it, don't eyeball).

### Backend tests

- Unit: `extract_tool_sources` over representative `search_case_law` / `get_cluster` payloads + the empty/non-research cases; dedup-by-`external_ref`.
- Integration: a turn that runs a case-law tool persists `message_tool_sources` rows; `GET …/sources` returns them in retrieval order; empty when none; ownership 404s on a foreign chat.
- OpenAPI conformance (`test_openapi.py`) green with the bumped count.

## Frontend (`web/`)

- **`ToolSource` type** (`web/src/lib/lq-ai/types.ts`): `{ id, message_id, source_kind, label, subtitle?, url?, external_ref?, provider, tool, created_at }`.
- **`sourcesApi.getMessageSources(chatId, messageId): Promise<ToolSource[]>`** (`api/sources.ts`) mirroring `citationsApi.getMessageCitations`; tolerant of 404 → `[]`.
- **`ProvenancePill.svelte`**: add a `caselaw` kind → label like `⚖ {n} source{s} consulted`; reuse the pill chrome; clicking expands/scrolls to the panel.
- **`ToolSourcesPanel.svelte`** (new): collapsible sidecar mirroring `M2Citations.svelte` chrome. Header `Sources consulted (N)`; one row per case — `label` (bold), `subtitle` (muted), and a CourtListener link (`<a target="_blank" rel="noopener">`, plain text — never `{@html}`). Renders nothing when the list is empty.
- **`MessageBubble.svelte`**: lazy-fetch sources on the assistant branch with the same guarded reactive pattern as `fetchedCitations` (`role === 'assistant' && !isStreaming && fetchedSources === null && !inflight`). Render the pill in the metadata row and the panel after the citations sidecar. New props/state default-safe so existing callers and non-research turns are unaffected.

### Frontend tests

- Vitest on any pure helper (pill copy: singular/plural; a `buildSourceRows`-style mapper if extracted). Component chrome verified by `svelte-check` + a headless static render of `ToolSourcesPanel` (both populated and empty), per the 6a/6b visual-check convention. No `@testing-library/svelte` (not a project dep) — follow the `RefusalMessageBubble`/`ToolGatePrompt` module-helper pattern.

## D6 narrative flip (mandatory)

The 6b narrative currently says *Coming next: rich case-law provenance — source-kinded citations with provenance pills for the external sources a tool call pulled in.* Flip it to **shipped** and repoint "coming next" to 6d, in all three centralized spots:

- `web/static/learn/playgrounds/governed-tool-flow.html` — the `Availability` block (move case-law provenance into "Available today"; "Coming next" → 6d: the case-law research skill + retiring the legacy MCP stub).
- `web/src/routes/lq-ai/learn/how/+page.svelte` — section 17 sentence.
- `README.md` — the legal-research+MCP paragraph's availability sentence.

Grep gate: no stale "coming next" references the provenance surface; any remaining "coming next" points to 6d.

## Security / gating

Not security-gated by CODEOWNERS: a new **product** table + a read-only endpoint in `api/`, plus `web/` + narrative docs. It does **not** touch `gateway/**`, `docs/security/**`, the audit log (`tool_egress_log`), auth/authz, or crypto. → **self-merge after CI green** (maintainer may review the provenance-capture UX). If CI's CODEOWNERS routing flags anything unexpectedly, stop and confirm.

## Dev-environment guardrails (CLAUDE.md)

- Migration 0055 verified on a throwaway `pgvector/pgvector:pg16` (conftest auto-migrates) — **never** host-side `alembic upgrade` against the live dev DB.
- When 0055 lands, rebuild `api` + `arq-worker` + `ingest-worker` together (revision-mismatch crash-loop otherwise).
- `web` serves a pre-built static bundle — rebuild `web` to view the panel.
- Run BOTH `ruff format` and `ruff check`; run `npm run check:lq-ai` + Vitest.

## Build shape

One PR, two phases:
1. **Backend** (table + migration → `extract_tool_sources` + capture → persist → endpoint + schema + OpenAPI + collision guards → tests) — clean **subagent-driven TDD**.
2. **Frontend** (type + api → pill kind → `ToolSourcesPanel` → `MessageBubble` wiring → D6 flip) — **inline** with a headless visual check.

## §9 follow-ups (file as DEs, don't expand 6c)

- **DE-360:** extend `message_tool_sources` to generic MCP tool results (`source_kind='mcp'`) with a per-server label/url convention.
- (Existing) **DE-344:** per-provider research cost model — unchanged here.

## Acceptance criteria

1. A chat turn that runs a case-law tool persists one `message_tool_sources` row per retrieved case (deduped per turn), tied to the assistant message.
2. `GET /messages/{id}/sources` returns them in retrieval order; `[]` for turns with none; 404 for a foreign chat/message.
3. The assistant turn renders a `⚖ N sources consulted` pill and a collapsible "Sources consulted" sidecar listing each case (name, court·date, CourtListener link); turns with no sources are visually unchanged.
4. The D6 narrative (explorer + Learn §17 + README) states case-law provenance is shipped; "coming next" points to 6d.
5. Gates green: api ruff/mypy/pytest (incl. OpenAPI conformance with the bumped path count), web svelte-check + Vitest; migration verified on a throwaway pg container.
```
