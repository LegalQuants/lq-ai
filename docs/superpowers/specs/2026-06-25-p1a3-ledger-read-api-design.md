# P1-A3 — Citation Ledger read API + one-click trace (design)

**Date:** 2026-06-25
**Milestone:** Fiduciary-grade agentic legal work — Phase 1 (WS-A)
**Branch:** `feat/fiduciary-p1a3-ledger-read-api`
**Pins:** [ADR 0018](../../adr/0018-citation-ledger-and-fiduciary-grade-output.md) D4 (one-click trace read model), D5 (no-raw-payload). Builds on **P1-A2** (`citation_ledger_entry` + assembly, #219) and **P1-A1** (`message_caselaw_citations`, #218).
**Security review:** required (citation surface; new read endpoint over owner-scoped content). No new egress.

## Problem

P1-A2 made the ledger a populated, queryable artifact — one `citation_ledger_entry` row per (assistant turn, source consulted), each referencing exactly one of `message_citations` / `message_caselaw_citations` / `message_tool_sources`. But the ledger is **write-only today**: nothing reads it back. ADR 0018 D4 requires the transparency payoff — *one click from any cited assertion to the exact source and passage read, with its verification status visible.* P1-A3 builds that read surface. It does **not** build the fiduciary-grade gate (P1-B1) or the UI (P1-C1).

## Decisions (maintainer-approved 2026-06-25)

- **One rich list endpoint, not list + per-entry trace.** `GET /api/v1/chats/{chat_id}/ledger` returns each entry already **resolved** to its source identity + passage(s) read + offsets + status + provenance. The "one-click trace" is satisfied by embedding the resolved passage in the list response — the chat owner is already entitled to their turn's quoted text, so there is no payload-minimization reason to gate it behind a second round-trip. A separate `…/ledger/{entry_id}/trace` route is **deferred** (only worth it if per-entry resolution becomes expensive).
- **Chat-scoped now; matter-scoped deferred.** Scope is the chat resource, with an optional `?message_id=<uuid>` filter for a single turn. Project/matter-wide aggregation (`GET /projects/{id}/ledger`) is deferred to a DE / built when P1-C1 concretely needs it — the per-chat view unblocks the UI and the chat endpoint already accumulates across that chat's turns (ADR D7).
- **Plain-dict response, matching the siblings.** `get_citations` and `get_message_sources` return `list[dict[str, Any]]` with no Pydantic `response_model`; A3 matches that convention. The response is a top-level object `{ "entries": [...] }` (object, not bare list, so P1-B1 can add a `gates` key additively without a breaking change).
- **No content duplicated into the ledger.** Passage text is resolved **at read time** from the referenced content rows (`MessageCitation.source_text`, `MessageCaselawCitation.source_text`); the `citation_ledger_entry` row itself still holds no payload (P3 intact).

## Design

### Component 1 — Read-side resolver (`api/app/citation/ledger.py`)

A new function alongside the existing `assemble_ledger_entries`:

```python
async def resolve_ledger_entries(
    db: AsyncSession, *, chat_id: uuid.UUID, message_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
```

1. Select `CitationLedgerEntry` rows for `chat_id` (and `message_id` when given), ordered `created_at, id`.
2. **Batch-load** the three referenced tables by collecting the non-null FK id sets and issuing one `select(...).where(id.in_(...))` per table (no N+1). Build id→row maps.
3. Shape one dict per entry, resolving by `source_kind` / which FK is set:

| Entry kind | Resolved `source` block |
|---|---|
| `message_citation_id` set (`kb_document`) | `{kind, source_file_id, passages:[{text, offset_start, offset_end, page}]}` from `MessageCitation` |
| `message_caselaw_citation_id` set (`caselaw`) | `{kind, opinion_id, cluster_id, passages:[{text, offset_start, offset_end}]}` from `MessageCaselawCitation` |
| `message_tool_source_id` set (`mcp`/`caselaw` provenance) | `{kind, label, subtitle, url, external_ref, tool}` from `MessageToolSource` — **no `passages`** (provenance, not a quote) |

Each entry dict carries the ledger-level fields too: `id, message_id, source_kind, verification_status, confidence, provider, retrieved_at, created_at`.

A referenced row that is unexpectedly missing (FK should prevent this, but defense-in-depth) is **skipped with a logged warning**, never fatal — a partial trace beats a 500.

### Component 2 — Endpoint (`api/app/api/chats.py`)

```python
@router.get("/{chat_id}/ledger", summary="Citation Ledger for a chat (one-click trace) — P1-A3")
async def get_chat_ledger(
    chat_id: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    message_id: str | None = None,
) -> dict[str, Any]:
```

- Validate `chat_id` (and `message_id` when present) via the existing `_validate_chat_id` / `uuid.UUID(...)` pattern → `ValidationError` on a non-UUID.
- `await _load_visible_chat(db, cid, user.id, include_archived=True)` — same ownership gate as `get_citations` (cross-user → 404; archived chats still readable).
- When `message_id` is given, confirm the message exists in the chat (mirror `get_citations`' `select(Message.id).where(id==mid, chat_id==cid)` → `NotFound`) so a caller can't probe message ids.
- Return `{"chat_id": str(cid), "entries": resolve_ledger_entries(db, chat_id=cid, message_id=mid)}`.

Registered in `__all__` at the bottom of the module like its siblings.

### Component 3 — Collision guards (P10)

- `api/tests/test_endpoints.py` — add `("GET", "/api/v1/chats/{chat_id}/ledger")` to `IMPLEMENTED_ROUTES`.
- `api/tests/test_openapi.py` — add `"/api/v1/chats/{chat_id}/ledger"` to `EXPECTED_PATHS` and bump the pinned count `134 → 135`.
- `docs/api/backend-openapi.yaml` — add the path block, mirroring the `/messages/{message_id}/sources` style: `chat_id` path param (uuid), optional `message_id` query param (uuid), `200` (the ledger object), `404` (chat/message absent). A `LedgerEntry` schema under `components/schemas` documents the resolved-entry shape.

## Error handling (conservative posture)

- Non-UUID `chat_id`/`message_id` → `ValidationError` (422-class), consistent with siblings.
- Cross-user or unknown chat → `NotFound` (404) via `_load_visible_chat`; unknown `message_id` in a visible chat → `NotFound`.
- A dangling/missing referenced content row → skip that entry, log a warning, return the rest (never 500).
- Pure DB reads; no gateway/LLM call, no egress.

## Testing

- **Unit (resolver):** a turn with one `message_citations` row, one `message_caselaw_citations` row, one `message_tool_sources` row → three resolved dicts with correct `source_kind`, the right `source` block (passages present for the two quote kinds, absent for provenance), and mirrored `verification_status`/`confidence`. Empty ledger → `[]`. `message_id` filter narrows to one turn. A missing referenced row is skipped, not raised. Assert no N+1 (one query per referenced table).
- **Integration (real Postgres, host venv + throwaway pgvector):** seed a chat + assistant message + the three artifact rows + ledger entries; `GET /chats/{id}/ledger` → 200 with the resolved entries; `?message_id=` filters; cross-user → 404; unknown chat → 404; unknown `message_id` → 404; non-UUID → 422.
- **OpenAPI conformance:** `test_openapi.py` green at count 135; `test_endpoints.py` green with the new route in `IMPLEMENTED_ROUTES`.
- Gates: `ruff format` + `ruff check` + `mypy app` + full `pytest` (coverage no-decrease).

## Acceptance criteria

1. `GET /api/v1/chats/{chat_id}/ledger` returns, for each ledger entry, its source identity + the passage(s) read (offsets + text for quote kinds) + verification status + confidence + provenance — one click, one call.
2. `?message_id=` narrows to a single turn; ownership is enforced identically to `get_citations` (cross-user → 404).
3. The `citation_ledger_entry` row still holds no content — passages are resolved from the content layer at read time (P3 intact).
4. P10 guards updated (route in `IMPLEMENTED_ROUTES`, path in `EXPECTED_PATHS`, count bumped, OpenAPI sketch + schema added); `test_openapi.py` / `test_endpoints.py` green.
5. `ruff` + `mypy` clean; unit + integration + conformance tests green; no new egress.

## Out of scope / sequencing

- **Fiduciary-grade gate** (P1-B1) — adds a `gates` key to this response additively; sequenced in parallel (whichever merges second wires the field).
- **Per-entry trace route**, **matter/project-scoped aggregation** (`GET /projects/{id}/ledger`) — deferred (file a DE if P1-C1 needs the latter).
- **UI** (P1-C1) consumes this endpoint.
- **Derived treatment** (`treatment_id`) stays null until WS-G; the resolver passes it through when present.
