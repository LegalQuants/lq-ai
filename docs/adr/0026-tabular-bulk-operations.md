# ADR 0026 — Tabular bulk operations (redline report + column memo)

**Status:** Proposed — self-authored in the DE-304 implementation PR. This ADR introduces a novel output pattern (non-grid work product attached to a tabular execution); the review committee can reject it at PR review, in which case the implementation is reverted with it. *AI-drafted, pending maintainer review.*

**Relates to:** the Phase C prep doc Decisions C-1 (snapshotting), C-3 (shared playbook queue), C-5 (cost-confirmation gate), C-9 (bulk ops must not mutate the original grid), C-10 (failed cells render as failures); [PRD §3.14](../PRD.md#314-tabular--multi-document-review-m3) (Tabular / Multi-Document Review); [ADR 0014](0014-gateway-egress-boundary-for-tool-providers.md) (single egress boundary — bulk ops add no new egress path).

---

## Context

The Tabular Review surface (M3-C2/C3/C4) produces a documents × columns grid of Citation-Engine-grounded extractions. PRD §3.14 and the Phase C prep doc anticipated *bulk operations* over a completed grid — "Redline column N", "Summarize column N" — and Decision C-9 reserved `tabular_executions.parent_execution_id` for "bulk-op sibling rows". A `TabularBulkOpRequest` wire-schema stub landed with M3-C4 but no endpoint, worker, or storage ever shipped. DE-304 ships the first two operations.

The two operations chosen, and their output shapes:

1. **Redline-per-row (`redline_rows`)** — for every document (row) of the parent execution, generate a redline-style review memo of that document (issues found, suggested edits, negotiation posture), grounded in the row's extracted cell values plus retrieved document text. The per-row outputs combine into a single **redline report** rendered on the execution detail page.
2. **Summarize-column (`summarize_column`)** — for one operator-chosen column, synthesize the column's values across all rows into a comparative **memo artifact** attached to the execution (e.g., "Term lengths across the 40 NDAs: 32 are 3 years, 5 are 5 years, 3 failed extraction").

Neither output is a grid. That creates the fork this ADR settles: Decision C-9's sibling-execution mechanism assumed bulk-op output would be *another grid* (a child `tabular_executions` row whose `results` is a `TabularResults` payload). A redline report and a memo do not fit `rows × cells` without abusing the schema.

## Decision drivers

1. **Causal linkage (C-1 spirit).** The output must remain attached to the execution that produced it. Re-opening the execution a week later must show *exactly* which grid snapshot the redlines/memo were derived from — not the skill's or documents' current state.
2. **Cost control (C-5).** Bulk ops fan out one inference call per row; a 200-row redline op is real money. The operator must see an estimate and confirm before the run starts, with the same preview → `confirmed_cost_usd` echo idiom the tabular execute path uses.
3. **Fail-closed honesty (C-10).** A row whose redline call fails must render as a failure in the report; the batch must complete around it; the report must never silently omit failed rows.
4. **No new egress.** All inference goes through the same `GatewayClient.chat_completion` path as tabular cell extraction (ADR 0014); the only change is a new `lq_ai_purpose` tag.
5. **Small API surface delta.** Prefer extending existing wire shapes over minting new paths where the UI already polls.

## Decisions

### D1 — Storage: a dedicated `tabular_bulk_ops` table (refines Decision C-9)

Bulk-op results are stored in a new table, `tabular_bulk_ops` (migration 0066), one row per operation:

- `id` UUID PK; `execution_id` UUID FK → `tabular_executions.id` `ON DELETE CASCADE` (the causal-linkage column — an op cannot exist without its parent execution); `user_id` FK → `users.id` `ON DELETE SET NULL` (audit survives operator deletion, matching `tabular_executions.user_id`).
- `kind` text CHECK (`'redline_rows'`, `'summarize_column'`); `params` JSONB (snapshot of op parameters at request time, e.g. `{"column_name": "Term"}`).
- `status` text CHECK `pending → running → completed | failed`. `completed` means the batch finished, *including* batches with per-item failures (see D4). `failed` is reserved for whole-batch orchestration crashes. No `cancelled` in v1 — ops are minutes, not hours; cancellation is a follow-on if operators ask.
- `results` JSONB — `{schema_version, items: [{document_id, document_name, status: 'completed'|'failed', output_text, error, cost_usd}], summary: {total_items, failed_items}}`. `redline_rows` yields one item per parent grid row, in grid-row order; `summarize_column` yields one item with `document_id = null` (the memo spans the grid).
- `confirmed_cost_usd` / `cost_actual_usd` Numeric(10,4); `error_text`; `created_at` / `started_at` / `completed_at`.

**Why not C-9's sibling `tabular_executions` rows:** the sibling mechanism was designed for grid-shaped output. Stuffing a redline report into `TabularExecution.results` would either violate the `TabularResults` schema (breaking every consumer that validates it, including export) or force a fake one-column grid; sibling rows would also pollute the executions list endpoint with rows that are not executions. `parent_execution_id` and its index are **retained unchanged** for future grid-shaped bulk ops (e.g. "re-run column N at a higher tier"); this ADR narrows C-9's mechanism to that case rather than repealing it. This is the novel pattern the committee may reject.

**Why JSONB items, not a per-item results table:** matches the established `tabular_executions.results` convention (grid cells are JSONB, not rows); items are only ever read whole-report; no per-item query pattern exists to index for.

### D2 — API surface: preview + create under the execution, read-side embedded in the detail response

Two new paths, mirroring the existing `preview-cost` / `execute` split exactly:

- `POST /api/v1/tabular/executions/{execution_id}/bulk-ops/preview-cost` — synchronous estimate; no row created.
- `POST /api/v1/tabular/executions/{execution_id}/bulk-ops` — creates the row at `pending`, enqueues the ARQ job, returns 202 + the row.

Both require the parent execution to be caller-owned (missing / cross-user / soft-deleted collapse into 404, the M3-A6 posture) and in `status='completed'` (409 otherwise — the same posture as export: bulk-operating a partial grid would mislead). `summarize_column` additionally validates `column_name` against the execution's *snapshotted* column spec (400 on unknown — C-1: the op targets what was actually run).

**Read-side:** `TabularExecutionResponse` gains a `bulk_ops` array (recent-first). No new GET path — the detail page already polls `GET /tabular/executions/{id}`, so embedding gives the results panel live progress for free and keeps the OpenAPI delta at two paths instead of three.

### D3 — Cost control: same preview → confirm idiom, purpose-tagged rolling average

The estimator mirrors the M2-E2 / M3-C2 rolling-average pattern: per-call cost = average `cost_estimate` over the last 100 `inference_routing_log` rows where `purpose = 'tabular_bulk_op'` (30-day cap, 5-sample minimum), falling back to a conservative cold-start default of **$0.01/call** — 2× the tabular per-cell default, because bulk-op calls generate long-form prose (redline memos) rather than short extractions. Calls count: `n_rows` for `redline_rows`, `1` for `summarize_column`.

`confirmed_cost_usd` on the create body is the echo of the preview value, persisted for audit — **exactly** the existing tabular-execute idiom: the $1.00 confirmation gate is enforced UI-side (Decision C-5), and the server does not reject on estimate drift (no 402/409-on-mismatch exists anywhere in the tabular surface today; inventing one here would fork the idiom).

### D4 — Execution: one ARQ job on the shared queue; per-item failures never block the batch

One job (`tabular_bulk_op_job`, registered on the shared `arq:m3a6` playbook queue per Decision C-3) walks the parent grid's rows sequentially, one gateway call per item, each wrapped in try/except. A failed item is persisted as `{status: 'failed', error, output_text: null}` and the loop continues; the batch lands at `completed` with `summary.failed_items > 0`, and the UI renders failed items as failures (C-10). The whole-batch `failed` state is reserved for pre-flight errors (parent execution vanished mid-flight, results payload unreadable).

Rejected: one ARQ job *per item* — queue churn for no isolation win, and it forks the established convention (the tabular executor already walks 2000 cells inside one job). Sequential dispatch matches the cell node; per-item parallelism is a follow-on if latency forces it.

Inference goes through the same `GatewayClient.chat_completion` surface as cell extraction, tagged `lq_ai_purpose='tabular_bulk_op'` (feeds the D3 estimator) — no new egress path, no new provider wiring.

### D5 — Grounding: cells first, document text second

The redline prompt for a row carries (a) the row's extracted cell values with their confidences — including `(extraction failed)` markers for failed cells, honestly — and (b) the top document chunks retrieved via the same FTS helper the cell node uses. The memo prompt for a column carries every row's value for that column, with failed/missing rows explicitly listed as such (the memo must account for every row, not just the extractable ones). Per the M3-C2 quality bar, both outputs are drafts for attorney review, and the UI labels them as such.

## Consequences

- Two tables now carry tabular work product; the detail response joins them. Export (`/export`) covers the grid only — exporting bulk-op reports is a follow-on (DE candidate) rather than scope creep here.
- The `TabularBulkOpRequest` schema stub from M3-C4 (`op`/`column_name`/`skill_name_override`) is replaced by the shapes above; it was never referenced by an endpoint, worker, or the frontend. `skill_name_override` is dropped — v1 bulk ops use fixed prompts, not skill dispatch; skill-driven bulk ops are a follow-on.
- Deployments must rebuild `api` + `arq-worker` + `ingest-worker` together when this lands (migration 0066 + a new registered job).
- If the committee rejects D1, the fallback is C-9 sibling rows with a new results discriminator — a larger schema change; the code isolates storage behind the model + one shaping function to keep that pivot cheap.
