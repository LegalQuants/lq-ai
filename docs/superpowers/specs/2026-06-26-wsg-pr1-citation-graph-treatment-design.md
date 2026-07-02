# WS-G PR1 — Citation-graph treatment signal (design)

**Date:** 2026-06-26
**Milestone:** Fiduciary-grade agentic legal work — Phase 2 (WS-G)
**Branch:** `feat/wsg-pr1-citation-graph-treatment`
**Pins:** [ADR 0019](../../adr/0019-transparent-validity-treatment-layer.md) (transparent validity/treatment layer) — realizes **D2** (per-cited-case, cached, off the critical path), **D3** (the new `get_citing_opinions` gateway egress op), **D4 PR1** (graph-first, no judge), **D7** (P3-preserving reference storage), **D8** (staleness/as-of), **D10** (DE-344 cost estimate so R4 can see the op). Builds on [ADR 0018](../../adr/0018-citation-ledger-and-fiduciary-grade-output.md) D6 (fills the reserved `citation_ledger_entry.treatment_id` slot) and [ADR 0014](../../adr/0014-gateway-egress-boundary-for-tool-providers.md) (where the new egress op lives).
**Security review:** **required** (new gateway egress operation `gateway/**`; citation/derivation surface `api/app/citation/**`; new audit-adjacent table). **Do not self-merge** — Kevin/security merges; mirror `origin/main → tucuxi` after.

## Problem

The Phase-1 citation engine verifies a citation **exists** and is **accurately quoted**; it says nothing about whether a later court has **followed, distinguished, criticized, questioned, overruled, or superseded** the cited case — the validity/treatment gap (the KeyCite/Shepard's parity axis). ADR 0019 answers it **LQ.AI's way — derive the signal transparently, never assert an editorial verdict** — and phases the build: **PR1 ships the citation graph as a derived provenance signal** ("cited by N later opinions; here are the most significant"), **with no judge fan-out**; PR2 adds the treatment-classifying judge.

PR1 stands up the whole spine — the new egress operation, the `citation_treatment` table, the per-cited-case cached derivation, the async trigger, and the read-API exposure — at the **cheapest, deterministic** tier. It delivers immediate value (a lawyer sees and can inspect the citing set) and pre-stages the exact ranked subset PR2's judge will run over.

## Decisions (ADR-0019-derived + maintainer-approved 2026-06-26)

- **Backend vertical only.** PR1 is the security-gated backend: the gateway op + `citation_treatment` table + derivation service + async trigger + read-API exposure. The web trace rendering is a **separate, non-gated PR1-UI** follow-on (mirrors P1's split of the gate backend #225 from the C1 UI #228).
- **Graph-only signal (no judge).** `citation_treatment` stores `cited_by_count` + a **capped, ordered top-N** (N=30, highest-court-then-most-recent) of citing-opinion refs `{cluster_id, opinion_id, case_name, court, date_filed}`. No LLM-judge runs in PR1 (that is PR2). The capped list **pre-stages PR2's judge subset** — PR2 ranks/judges over the same selection.
- **Per-cited-case, cached, async.** Treatment is keyed by the cited **`cluster_id`** (one cached row per case), derived **off the turn's critical path** by an arq job enqueued after `_audit_message_sent`, reused within a **30-day TTL** (D8), and re-fetched when stale. The fiduciary-grade gate stays **independent** of treatment (ADR 0018 D3 / 0019 D2) — treatment enriches the ledger entry; it never gates the turn.
- **P3-preserving storage.** `citing_opinions` holds **structured refs only** (ids + case_name + court + date), never opinion **text**; the opinion body is read from the content layer at trace time, as the ledger does (ADR 0018 D5). `citation_treatment` is metadata-only and is **added to the P3 no-raw-payload tripwire** in this PR.
- **Extensible row.** The table is designed so **PR2 extends it** (nullable judge-classification + rollup fields, or a per-citing-opinion treatment slot), never rewrites it. `derived_method` discriminates (`"citation_graph"` in PR1).
- **Lazy-on-trace-open fallback deferred (tracked, must land in Phase 2).** ADR 0019 D2 names a lazy fallback for entries the async job hasn't populated yet. PR1 ships **async-only**; an entry with no treatment yet renders nothing/"pending." The lazy fallback is filed as **DE-363** and is committed to land within WS-G (by end of these phases) — not dropped.
- **R4: estimate only, no enforcement yet.** PR1 adds a real `estimate_tool_cost` for `get_citing_opinions` (DE-344) so the R4 brake can *see* the op; real per-case budget **enforcement** is PR2 (where the judge fan-out is the actual cost).

## Design

### Component 1 — Gateway op `get_citing_opinions` (`gateway/app/providers/tool/courtlistener.py`)

A fourth read operation, following the `get_cases` pattern (`ToolSpec` in `list_tools` + a branch in `invoke_tool` + a `_get_citing_opinions` method building a `ToolResult` via `self._result`). 

- **Input:** `{ "cluster_id": int }` (required). `read_only=True`. BYO-key-gated exactly like the existing CL ops (operator `user_token`).
- **Upstream:** CourtListener's citing-relationships surface. **Pin in the plan (task 1) via a CourtListener v4 docs check:** the candidate is the search API `GET /search/?q=cites:(<opinion_ids>)&type=o&order_by=dateFiled desc` (returns later opinions citing the given opinion(s), already date-orderable) vs. the `/opinions-cited/?cited_opinion=<id>` relation endpoint. The op resolves the cluster's opinion id(s) (reuse the `get_cases`/cluster path) then queries citing opinions.
- **Output:** `{ "cited_by_count": int, "citing": [ {cluster_id, opinion_id, case_name, court, date_filed}, ... ] }` — `citing` is the **ordered top-N** (N=30): **highest-court-first, then most-recent** (the ordering PR2's judge prioritization reuses). `cited_by_count` is the *total* (from the upstream `count`), not the truncated list length.
- **Cost:** add `get_citing_opinions` to the provider's `estimate_tool_cost` with a small real estimate (per-call API cost; no inference) so R4/DE-344 can read it. (Confirm the exact `estimate_tool_cost` location in the plan.)
- **Errors:** invalid/missing `cluster_id` → `ToolProviderInvalidRequestError`; upstream failure → the provider's existing error mapping. Never returns opinion text.

### Component 2 — Model `citation_treatment` + migration `0061` (`api/app/models/citation_treatment.py`)

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | `server_default gen_random_uuid()` |
| `cluster_id` | bigint, **unique** | the cited case; the cache key (one treatment per case) |
| `opinion_id` | bigint, nullable | the specific cited opinion, when known |
| `cited_by_count` | int, not null | total citing count (upstream `count`) |
| `citing_opinions` | JSONB, not null | the capped top-N refs `[{cluster_id, opinion_id, case_name, court, date_filed}]` — **refs only, no opinion text** (P3) |
| `derived_method` | text, not null | `"citation_graph"` (PR1); PR2 adds judge methods. CHECK constrains the allowed set |
| `as_of` | timestamptz, not null | when this row was derived (D8 staleness anchor) |
| `created_at` / `updated_at` | timestamptz | standard |

- Unique constraint on `cluster_id` (upsert key). Index on `cluster_id`.
- **P3:** add `citation_treatment` to the no-raw-payload tripwire test (`test_audit_models_have_no_raw_payload_columns` or its WS-G equivalent) — assert it carries no `payload`/`raw`/`body`/`response`/text-content column. `citing_opinions` is structured refs, not a raw upstream-response dump.
- **PR2 extension note (non-binding):** PR2 will add nullable treatment-classification + rollup columns (or a child table) and additional `derived_method` values; the migration/CHECK is written to make that additive.

### Component 3 — Derivation service (`api/app/citation/treatment.py`, new module)

```python
async def derive_treatment_for_message(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    gateway: _CitingGraphGatewayProtocol,
    now: datetime,
    ttl_days: int = TREATMENT_TTL_DAYS,   # 30
) -> int:
    """Derive/refresh graph-level treatment for each case this turn cited, and
    link the turn's caselaw ledger entries to it. Returns rows linked. Non-fatal
    per case (conservative posture); never raises on a per-case failure."""
```

Flow:
1. Load the turn's `message_caselaw_citations` → the distinct cited `cluster_id`s (and `opinion_id`s) the turn actually relied on. (None → return 0.)
2. For each cited cluster:
   - **Reuse** an existing `citation_treatment` row whose `as_of` is within `ttl_days` → link.
   - Else **fetch** `get_citing_opinions(cluster_id)` via the gateway, **upsert** the `citation_treatment` row (`as_of=now`, `derived_method="citation_graph"`, the capped list), → link.
   - A per-case gateway/storage failure is logged and skipped (never fatal).
3. **Link:** set `citation_ledger_entry.treatment_id` for this message's caselaw entries (those whose `cluster_id` matches) to the treatment row's id.

`_CitingGraphGatewayProtocol` is a narrow Protocol (one method, mirroring the citation judge's `_JudgeGatewayProtocol` convention) so the service is unit-testable with a fake gateway. No judge, no cost budget enforcement in PR1.

### Component 4 — Async trigger (`api/app/workers/` + `api/app/api/chats.py`)

- New arq job `treatment_derivation_job(ctx, message_id_str) -> dict` (mirrors `easy_playbook_generation_job`): opens a DB session + a gateway client from `ctx`, calls `derive_treatment_for_message`, returns a small result dict. Registered in the **ingest** `WorkerSettings.functions` (the `_get_pool()` queue, **not** the m3a6 playbook queue) — confirm the exact `WorkerSettings`/queue in the plan.
- **Enqueue** `treatment_derivation_job(str(assistant_message_id))` **after `_audit_message_sent`** at **both** finalize sites (chats.py ~2953 and ~3545), via an `enqueue_treatment_derivation_job` helper that mirrors the existing best-effort enqueue helpers (catch + log on failure; **never block the turn response**).
- The job constructs its own gateway client (the worker context has no request-scoped gateway) — confirm the worker's gateway-client construction pattern in the plan.

### Component 5 — Read-API exposure (`api/app/citation/ledger.py` `resolve_ledger_entries`)

`resolve_ledger_entries` already returns `treatment_id`. PR1 resolves it: batch-load the referenced `citation_treatment` rows and attach a `treatment` object to each caselaw entry:

```json
"treatment": { "cited_by_count": 412, "as_of": "2026-06-26T...", "derived_method": "citation_graph",
               "citing": [ {"cluster_id":..., "opinion_id":..., "case_name":"...", "court":"...", "date_filed":"..."}, ... ] }
```

Entries with no `treatment_id` (job pending/failed) carry `"treatment": null`. No N+1 (batch-load by id set, as A3 does for the ref tables). The `/chats/{id}/ledger` response shape gains `treatment` on caselaw entries; this is additive (the UI PR consumes it).

## Testing

Gateway (provider unit, mocked HTTP — no live CL):
- `get_citing_opinions` shapes `{cited_by_count, citing[]}`; the list is capped at N=30 and ordered highest-court-then-most-recent; `cited_by_count` is the upstream total, not the truncated length; invalid `cluster_id` → invalid-request; upstream error → mapped error; never returns opinion text.

API unit (mocked gateway op — no `-m provider`):
- Derivation service: cache **reuse** within TTL (no fetch); **refetch** when `as_of` is stale; upsert is idempotent on `cluster_id`; top-N cap/order preserved into the row; per-case failure is non-fatal (one bad case doesn't sink the others); `treatment_id` linked on the right caselaw entries only.

Integration (throwaway pgvector; conftest auto-migrates):
- enqueue path: calling the derivation directly (job body) on a seeded turn writes a `citation_treatment` row and populates the caselaw entries' `treatment_id`; the `/ledger` read returns the `treatment` object; an entry with no treatment → `treatment: null`.
- **P3 tripwire** includes `citation_treatment` (no raw-payload column).
- **Additive guarantee:** a turn with no caselaw citations writes no treatment row and changes nothing; the fiduciary gate verdict is unchanged by treatment derivation (gate independence).

## Out of scope (PR1) / Deferred

- **Treatment-classifying judge + rollup + per-case cost budget** — **WS-G PR2**.
- **Web trace rendering** of the treatment signal — **PR1-UI** (separate, non-gated).
- **Lazy-on-trace-open fallback** — **DE-363** (filed this PR; committed to land within WS-G/Phase 2 per maintainer 2026-06-26).
- **R4 budget enforcement** for the op — PR2 (PR1 adds the estimate only).
- **Editorial-connector treatment coexistence** (ADR 0019 D9) — later, when a licensed connector ships.

## Pointers

- ADR: [`0019-transparent-validity-treatment-layer.md`](../../adr/0019-transparent-validity-treatment-layer.md) (D2/D3/D4/D7/D8/D10)
- Reused: `gateway/app/providers/tool/courtlistener.py` (op pattern: `_get_cases`), `api/app/workers/` (arq enqueue pattern: `easy_playbook_*`), `api/app/citation/ledger.py` (`resolve_ledger_entries`), `api/app/models/citation_ledger_entry.py` (`treatment_id` slot), `api/app/research/service.py` (`read_opinion`, cluster/opinion ids).
- Next migration = `0061`. Next DE after this = DE-364 (DE-363 = the lazy-fallback, filed here).
