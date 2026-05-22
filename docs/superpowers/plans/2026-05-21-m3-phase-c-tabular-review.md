# M3 Phase C — Tabular / Multi-Document Review — Prep Notes

> **Scope:** Phase C in full — M3-C1 (`output_format: table` Skill mode) + M3-C2 (Tabular LangGraph workflow + execution endpoints + migration 0036) + M3-C3 (tabular UI surface + per-cell citation drawer) + M3-C4 (bulk operations + XLSX/CSV export). Per [PRD §3.14](../../PRD.md#314-tabular--multi-document-review-m3) and [M3 Plan §C](../../M3-IMPLEMENTATION-PLAN.md#phase-c--tabular--multi-document-review-week-6).
>
> **Branch:** `m3-phase-c-tabular-review` off `main` at `fa62142` (post-PR-#61 reconciliation; M3-A6 Easy Playbook wizard now on `main`).
>
> **Goal at Phase C close:** an LQ.AI operator can select N documents (KB / Project / free pick) + M columns (from a saved `output_format: table` skill or an ad-hoc column spec), see a cost preview, confirm, watch the grid populate progressively as cells complete, click any cell to open the existing M2-C2 citation drawer for that source, then export the grid as XLSX (each cell carrying its citation as a Excel comment) or CSV (citations flattened into a `citation_links` column). The Tabular workflow runs as a LangGraph executor inside `api/` and dispatches each `(document, column)` cell through the existing Citation Engine cascade. The grid is a first-class persisted artifact (`tabular_executions` table) so re-opening the result a week later still works.

---

## Design decisions locked at Phase C kickoff (2026-05-21)

| # | Decision | Choice | Why | DE if redirected |
|---|---|---|---|---|
| **C-1** | `output_format: table` Skill frontmatter shape | **`lq_ai.output_format: table` + a sibling `lq_ai.columns: [{name, query, ensemble_verification?, minimum_inference_tier?}]` list.** Each column is one extraction-per-row spec. `name` is the column header in the grid. `query` is the per-row prompt (instantiated against each document). Per-column `ensemble_verification` overrides the skill-level field (M2-D1 cascade). Per-column `minimum_inference_tier` (1–5) overrides the skill-level tier floor — high-stakes columns can demand Tier 4+ while routine columns route Tier 1. **No column types in v0.3.0 — every cell is a string** (Excel-side typing is the operator's affair; file DE if a typed-grid surface emerges as need). The validator additions live in `api/app/skills/schema.py` (NOT a new `validators.py` — the M3 plan's reference at §M3-C1 is a doc nit to fix in this PR). | Aligns with the existing permissive frontmatter substrate (`SkillFrontmatter` allows extras + `LQAIFrontmatter` already supports `output_format` + `ensemble_verification` + `minimum_inference_tier`). Adding `columns` as a new optional field is additive — no breakage for `report`-mode skills. Per-column tier-floor override is the practical win Tabular needs that single-skill `minimum_inference_tier` can't express; this is the structural change the existing `lq_ai` block is one frontmatter field away from supporting. | DE-XXX: "Typed column outputs (number / date / boolean) for Tabular Review" — file at Phase C close if any user-attorney walkthrough surfaces the need. |
| **C-2** | Per-cell citation surface | **Hybrid: small confidence-chip in each cell (matches M2-C2's chat 5-state visual) + click-anywhere-in-cell opens the existing citation side-drawer.** Cell renders `{value}` with the chip rendered right-aligned. Failed extraction renders as italic `not found` with a `verify` affordance (the same chip set, just routed to the "click to see why" state). | Reuses M2-C2's full citation rendering substrate (`web/src/lib/lq-ai/components/CitationChip.svelte` + the drawer) — no new component. Keeps the grid dense (the chip is ~20×16 px). The grid stays scannable visually while the depth-of-citation surface is one click away. Matches PRD §3.14's "Cells link to the cited chunk(s) in the source document" requirement literally. | None — single-decision; if the chip+drawer pairing turns out wrong in user testing, the change is local to the grid component. |
| **C-3** | Execution boundary: sync vs ARQ | **Always ARQ on the existing `arq:m3a6` queue** (no new queue). The `arq-worker` container's `WorkerSettings.functions` list gains `tabular_execution_job`. Even the smallest tabular run (5 docs × 4 cols = 20 cells × ~5 sec/cell = ~100 sec) exceeds reasonable HTTP timeout windows; the 200×10 = 2000-cell case is hours. ARQ + status-poll is the only honest shape. **Reuses `arq:m3a6` rather than a new `arq:m3c` queue** — both job types (Easy Playbook generation + Tabular execution) share the same worker container, share the same worker concurrency budget, and benefit from being deployable as a single sister-of-`ingest-worker` service. The queue constant is renamed `M3A6_QUEUE_NAME → M3_PLAYBOOK_QUEUE_NAME` aliased to its old name for backward compatibility on in-flight jobs. | Two arq containers per deployment would just double the operational surface for no isolation win — the workloads are bursty in different shapes (Easy Playbook = 1–10 docs over ~10 min; Tabular = up to 2000 cells over hours), but neither saturates a worker for long enough to deserve isolation. If we see queue contention in production, splitting is a follow-on `arq:m3-tabular` queue is trivial. | DE-XXX (file at Phase C close if needed): "Dedicated arq queue for tabular executions if Easy Playbook + Tabular contention becomes measurable." |
| **C-4** | XLSX library | **`openpyxl` ≥ 3.1.0 added as a new `api/pyproject.toml` dependency.** Pinned to a minor range. CSV uses the stdlib `csv` module (no new dep). | Canonical Python XLSX library; mature, MIT-licensed; supports cell-level comments (the load-bearing feature for the "citation as Excel comment" requirement in M3-C4 / PRD §3.14). Alternatives reviewed: `xlsxwriter` (write-only; can't read for round-trip tests), `pandas.to_excel` (drags in pandas as a dep for the wrong reason). Per CLAUDE.md "don't add libs without justification": XLSX export is a load-bearing user surface (legal teams live in Excel) and rolling our own XLSX writer is not viable. SBOM impact: 1 new direct dep, no transitive surprises. | DE-XXX if openpyxl's footprint becomes painful: "Replace openpyxl with a leaner XLSX writer." Unlikely. |
| **C-5** | Cost-preview UX | **Modal-confirm-before-execute matching M3-A4's `PlaybookExecuteModal.svelte` pattern.** Modal shows: documents-count, columns-count, cells = docs × cols, estimated tokens (per-cell average × cells), estimated cost in USD (using M2-E2's per-purpose rolling-average cost), per-tier breakdown if some columns demand Tier 4+. **Big "Run" button is gated** behind a checkbox "I understand this will cost approximately $X.XX." for runs above $1.00; for runs below $1.00, the checkbox is hidden (no friction on small runs). | Matches the existing playbook execution flow operators already know; introduces the gate only where the cost matters (the $1 threshold mirrors the heuristic Kevin used for M3-A4 PR review — most operator runs are well below, so the friction lands only on the 200×10 case). The cost estimator code path lives in a new `api/app/tabular/cost.py` that mirrors `app/citation/cost.py`'s rolling-average pattern. | None — single-decision. The threshold is tunable via deployment config later. |
| **C-6** | Migration sequence | **`api/alembic/versions/0036_tabular_executions.py`** — next number after M3-A6's 0035. Schema: `tabular_executions (id uuid PK, user_id uuid FK, status enum('pending','running','completed','failed','cancelled'), document_ids JSONB NOT NULL, skill_id uuid NULL FK skills.id, columns JSONB NOT NULL, results JSONB NULL, cost_estimate_usd numeric NULL, cost_actual_usd numeric NULL, error_text text NULL, created_at, started_at NULL, completed_at NULL)`. Includes a partial index `(user_id, created_at DESC)` for the list endpoint, and a foreign-key cascade on `documents.id` deletion (cascade `documents` references via the JSONB array is non-trivial; cell results carry document_id but the user_id-scoped query is the load-bearing index). | The schema is more elaborate than the M3 plan's sketch because tabular executions need cost reconciliation (estimate vs actual), status transitions, and error capture — same fields the Citation Engine cascade already needs. The `columns` JSONB stores the resolved spec (either the skill's `lq_ai.columns` snapshot at execution start, or the ad-hoc spec the operator typed) so re-rendering the grid a week later is honest about what was actually run, not what the skill currently says. | None — schema design; tunable in M4. |
| **C-7** | Document selection sources | **KB-scoped + Project-scoped + free-pick (select individual files from the operator's library), in that order in the UI.** Multi-select up to 200 documents per execution (matches the PRD §3.14 risk-row 7 ceiling; runs above 200 are blocked at the form with a clear "Tabular runs are capped at 200 documents — split your selection or contact your admin to lift the cap" message). The 200-cap is a deployment-config knob `LQ_AI_TABULAR_MAX_DOCS=200`. | Three sources is the natural reach because LQ.AI already has all three primitives. The 200-cap is conservative for v0.3.0 — 200 × 10 columns is already a 2000-cell run that takes hours; lifting the cap is a deployment-config change, not code. Document this in the cost-preview UX. | DE-XXX if any operator hits the 200-cap and wants it lifted with sub-deployment-config granularity: "Per-user / per-project tabular cap overrides." |
| **C-8** | PR strategy | **Single PR (M3-C1 + M3-C2 + M3-C3 + M3-C4 all together)** mirroring Phase B's PR #59 pattern. Branch is `m3-phase-c-tabular-review` per this prep doc; opens against `main`. Live verification against the running dev stack + fresh-install Docker rebuild + reviewing-attorney walkthrough land before the PR is opened. | The four tasks are tightly coupled: M3-C1's schema is what M3-C2 reads; M3-C2's results shape is what M3-C3 renders; M3-C4 reads M3-C2's persisted grid + uses M3-C3's selection model. Splitting introduces churn (each split PR would need its own contract docs + stub the next surface in). Single PR is reviewable as one feature shipped end-to-end. Risk hedge: if the PR grows beyond ~5K LOC, split is reconsidered at end of M3-C2 (the natural seam). | None — single-decision; split fallback documented. |
| **C-9** | Bulk-ops result shape (M3-C4) | **Each bulk op spawns a SIBLING `tabular_executions` row with `parent_execution_id` FK** (new column added in migration 0036). "Redline column N in all rows" runs a fresh `output_format: report` skill against each row's source document with the column-N value as context; results land as a new sibling execution rendered as a column-of-redlines tab on the original grid view. "Summarize column N" runs the configured summary skill once over all column-N values; result is a single Markdown report rendered as a "Summary of column N" tab. **Bulk ops do NOT mutate the original grid** (immutability matters for citation provenance + re-render correctness). | The sibling-row pattern preserves the original grid's auditability — an operator can always answer "what exactly did the Tabular run produce on 2026-05-22?" without worrying about subsequent bulk ops having overwritten cells. The tab-on-the-grid-view UX (rather than a separate page per bulk op) keeps the operator in their reading flow. | None — single-decision. |
| **C-10** | Failed-cell rendering | **Italic `not found` text + amber-chip in cell + drawer-on-click shows the error reason (model error / no citation found / cell rejected by Citation Engine).** Matches the PRD §3.14 "never as a confident wrong answer" requirement. Tabular workflow's per-cell try/except catches at the cell node and writes `{"value": None, "error": str, "confidence": "failed"}` to that cell's JSONB. Grid renderer detects `confidence: "failed"` and switches to the italic-not-found render. | The Citation Engine's 5-state UI doesn't have a "no citation" state explicitly — its weakest signal is the red `unverified` chip. For Tabular, failure modes are different (the cell can't even produce a value, not just fail to verify it). Amber + italic is a visually distinct state that doesn't conflict with the citation chips. | None — single-decision; if user testing shows the amber state confuses, the chip color is one CSS variable change. |

---

## Per-task scope (compact; M3 plan §C is canonical for the full text)

### Task M3-C1 — `output_format: table` Skill mode (~6–8 hr)

**Files to touch:**
- `api/app/skills/schema.py` — extend `LQAIFrontmatter` with `columns: list[ColumnSpec] | None = None`. New `ColumnSpec` Pydantic model with fields per Decision C-1 (`name`, `query`, optional `ensemble_verification`, optional `minimum_inference_tier`). Validation logic: when `output_format == "table"`, `columns` must be non-empty (else raise); when `output_format != "table"`, `columns` may be present but is ignored (so a skill author can pre-write the column spec while iterating on output mode).
- `api/app/skills/loader.py` (if needed) — propagate `columns` through to `SkillSummary` (existing `output_format` field already covers the mode signal; the column spec itself only needs to flow through to the `Skill` detail shape).
- `docs/skill-authoring-guide.md` — add a "Table-mode skills" section with worked example + acceptance criteria.
- `docs/api/backend-openapi.yaml` — extend `Skill` schema with `columns` field on the detail response.
- `docs/PRD.md` §3.4 — add a paragraph on the `table` mode pointing at the authoring guide.
- `api/tests/test_skills.py` (or new `test_skill_table_mode.py`) — unit tests: valid table skill, missing-columns table skill (raises), columns on a report skill (ignored), per-column overrides cascade correctly.
- Optional: one example `output_format: table` skill landed under `skills/` as the canonical reference for community contributors. Suggested: `skills/contract-snapshot/SKILL.md` with 4 columns (`Term`, `Survival`, `Carveouts`, `Governing Law`) — exactly the 4 columns the M3-C2 acceptance scenario uses against the 5-NDA corpus.

**Verification:**
- `pytest -k table_mode` green.
- Existing report-mode skills unaffected (full suite green).
- Schema validator rejects `output_format: table` with no `columns` field at skill-load time (WARNING log + skill skipped, mirrors existing pattern in `loader.py`).

---

### Task M3-C2 — Tabular LangGraph workflow + endpoints + migration (~12–16 hr)

**New module `api/app/tabular/`:**
- `__init__.py`
- `executor.py` — LangGraph workflow:
  - **Input state:** `TabularExecutionInput(execution_id, document_ids, columns, user_id, skill_id?)`
  - **Cell node:** for each `(document, column)` pair, run the column's `query` as a Citation-Engine-grounded extraction. Returns `{value: str, citations: [Citation], confidence: high|medium|low|failed, tier_used: int, cost_usd: float, error: str|None}`.
  - **Aggregation node:** assemble cell results into `results: {rows: [{document_id, document_name, cells: {column_name: CellResult}}]}` JSONB.
  - **Status transitions:** `pending → running → completed | failed | cancelled`.
- `nodes.py` — extraction-per-cell + aggregation node implementations.
- `cost.py` — per-purpose rolling-average cost estimator (mirrors `app/citation/cost.py`), used by the cost-preview endpoint.
- `repository.py` (optional, depends on whether we reuse existing `app/repositories/` pattern) — CRUD on `tabular_executions`.

**API endpoints (`api/app/api/tabular.py`):**
- `POST /api/v1/tabular/preview-cost` — request: `{document_ids, columns, skill_id?}` → response: `{cells_count, estimated_tokens, estimated_cost_usd, per_tier_breakdown}`. Synchronous (cost-preview is fast).
- `POST /api/v1/tabular/execute` — request: same as preview + `confirmed_cost_usd` (echo of the preview value so we have audit trail of the operator confirming a specific cost) → response: 202 + `{tabular_execution_id, status: "pending"}`.
- `GET /api/v1/tabular/executions` — list user's tabular executions (paginated, recent-first).
- `GET /api/v1/tabular/executions/{id}` — full state + grid results.
- `DELETE /api/v1/tabular/executions/{id}` — soft delete (sets `deleted_at` — new column added in migration 0036 alongside the table; matches the M3-A6 pattern for playbooks).
- `POST /api/v1/tabular/executions/{id}/cancel` — sets status to `cancelled`; the worker honors this on the next cell-iteration check.

**Worker `api/app/workers/tabular_worker.py`:**
- `tabular_execution_job(ctx, execution_id: str)` — load execution row, dispatch to `executor.run()`, persist results, transition status.
- Registered in `app.workers.arq_setup.WorkerSettings.functions` alongside `noop_job` + `easy_playbook_generation_job`.
- `app/workers/queue.py` gains `enqueue_tabular_execution_job(...)`.

**Migration `0036_tabular_executions.py`** per Decision C-6 schema.

**Verification:**
- 5 NDAs × 4 columns (Term, Survival, Carveouts, Governing Law) executes end-to-end against the dev stack; grid populates; each cell carries citations.
- Failed-cell path: ask "what is the dispute-resolution forum" against an NDA that doesn't have one; cell renders as `not found` with amber chip per Decision C-10.
- Cost preview before execution matches actual within 10% (matches M2-E2's rolling-average accuracy band).
- Concurrent execution: 2 tabular runs by the same user don't interfere; the arq-worker dispatches both fairly via its existing concurrency budget.

---

### Task M3-C3 — Tabular UI surface (~10–14 hr)

**New SvelteKit routes under `web/src/routes/lq-ai/tabular/`:**
- `+page.svelte` — list of the user's tabular executions (recent-first; "Start new tabular review" CTA at top).
- `new/+page.svelte` — the four-step wizard:
  1. **Documents step** — three-tab selector (KB / Project / Files) per Decision C-7; multi-select up to 200; shows running count + estimated cell count.
  2. **Columns step** — choose from saved `output_format: table` skills (dropdown showing `name + description + columns-preview`) OR define ad-hoc columns (table widget: name + query + per-column ensemble/tier overrides).
  3. **Cost preview step** — modal-style step matching `PlaybookExecuteModal.svelte`; renders the cost-preview endpoint's response per Decision C-5.
  4. **Confirm + execute** — POST to `/tabular/execute`; redirects to the result view with `tabular_execution_id`.
- `[id]/+page.svelte` — the result view:
  - Status banner (pending / running with progress bar / completed / failed / cancelled).
  - Sticky-first-column + sticky-first-row grid renderer (CSS `position: sticky`).
  - Per-cell: value + confidence chip per Decision C-2; click anywhere on cell opens the existing M2-C2 `CitationDrawer.svelte` with the cell's citations.
  - Bulk-ops menu (M3-C4 — see next task).
  - Export menu (XLSX / CSV — M3-C4).

**New shared components:**
- `web/src/lib/lq-ai/components/TabularGrid.svelte` — the sticky grid renderer; takes `results` JSONB shape.
- `web/src/lib/lq-ai/components/TabularCell.svelte` — single cell, with chip + click-handler that opens the citation drawer.
- `web/src/lib/lq-ai/components/TabularCostPreviewModal.svelte` — extends the playbook execute modal pattern.
- `web/src/lib/lq-ai/api/tabular.ts` — API client (matches `playbooks.ts` shape: types + fetch helpers + error mapping).
- `web/src/lib/lq-ai/types.ts` — extend with `TabularExecution`, `CellResult`, `ColumnSpec`.

**Cypress E2E `web/cypress/e2e/m3-c-tabular-review.cy.ts`:**
- 8-step happy path: open `/lq-ai/tabular/new` → pick 5 sample NDAs from the M3-A6 `Sample NDAs (for testing)` KB (if seeded — see DE-285; else from free-pick) → choose the `contract-snapshot` example skill from C-1 → click "Preview cost" → click "Confirm and run" → wait for status `completed` (intercept the poll; mock the worker via response stub for test determinism) → assert grid renders with 5 rows × 4 cols → click a cell → assert citation drawer opens with the right document.

**Verification:**
- Cypress E2E green (happy path).
- Visual review on a 30×5 grid: scroll performance OK, sticky headers behave correctly.
- Cell-to-citation linkage works for all three cell states (verified / partial / failed).

---

### Task M3-C4 — Bulk ops + XLSX/CSV export (~8–10 hr)

**Bulk ops (per Decision C-9):**
- New endpoint `POST /api/v1/tabular/executions/{id}/bulk-op` — request: `{op: 'redline' | 'summarize', column_name: str, skill_id_override?: str}` → response: 202 + `{sibling_execution_id}`.
- Worker: `bulk_op_job` enqueued onto the same `arq:m3a6` queue.
- The sibling execution writes back to `tabular_executions` with `parent_execution_id` set (column added in migration 0036).
- UI: result view's bulk-ops menu surfaces "Redline column …" + "Summarize column …" with column dropdown; submitting kicks off the bulk op and adds a new tab next to the main grid view.

**Export (per Decision C-4):**
- New endpoint `GET /api/v1/tabular/executions/{id}/export?format=xlsx|csv` — streams the file with `Content-Disposition: attachment`.
- XLSX path (`openpyxl`):
  - First row: column names + a hidden "_document_id" column for re-import-ability.
  - Each cell carries the value; if the cell has a citation, the cell gets an Excel comment with the citation's source snippet + a clickable URL pointing at `{deployment_origin}/lq-ai/documents/{document_id}#chunk-{chunk_id}`.
  - Failed cells render as italic empty cells with a "not found" comment.
- CSV path (`csv` stdlib):
  - Each cell's value goes in the value cell; a sibling `{column_name}_citation_url` column carries the citation URL when present.
  - Failed cells: empty value + `not found` in the citation_url column.

**Verification:**
- XLSX opens cleanly in Excel desktop (Windows + macOS), Numbers (macOS), Google Sheets.
- CSV round-trips through `pandas.read_csv()` (one-off check; pandas does NOT get added as a project dep).
- Excel comments resolve when clicked (manual: open in Excel, click a cell with citation, comment popup shows the snippet + URL is clickable).

---

## PR strategy

Per Decision C-8:

- **PR #N (C1 + C2 + C3 + C4):** Single Phase C PR against `main`. Final state is "operator can run a 5-NDA × 4-column tabular review end-to-end, export XLSX, run a bulk redline on one column." Branch is `m3-phase-c-tabular-review`. Reviewing-attorney walkthrough against real-world contracts happens before the PR opens (M3 plan §3 risk row mention).
- **Split fallback:** if implementation grows beyond ~5K LOC by end of M3-C2, split into PR #N (C1 + C2) + PR #N+1 (C3 + C4) at the natural seam (C2 is the backend-complete state; C3 + C4 are the UI + export layer).

---

## Effort estimate

| Task | Hours | Notes |
|---|---|---|
| M3-C1 — `output_format: table` Skill mode | 6–8 | Schema extension + tests + docs + 1 example skill |
| M3-C2 — LangGraph workflow + endpoints + migration | 12–16 | The largest task; new module, new worker, new migration, 6 endpoints |
| M3-C3 — UI surface | 10–14 | 5 new routes / components + Cypress E2E + sticky-grid renderer |
| M3-C4 — Bulk ops + XLSX/CSV export | 8–10 | New endpoint + worker + openpyxl integration |
| **Phase C total** | **36–48** | Matches M3 plan §C estimate; no upward revision at kickoff |

Plus ~2–4 hr for the reviewing-attorney walkthrough and pre-PR fresh-install verification.

---

## Risk register

| # | Risk | Mitigation |
|---|---|---|
| 1 | LangGraph workflow concurrency saturates the `arq-worker` container | Worker concurrency is configurable; ship default `max_jobs=4`; document in `docker-compose.yml` comment. Per-cell extraction is the bursty part — bounded by the gateway's per-tier concurrency cap anyway. |
| 2 | Cost-preview accuracy drifts as cells fan out | Use M2-E2's rolling-average cost per-purpose tag. New `purpose='tabular_extraction'` tag added at the cell-node level so future estimates calibrate against actuals. Surface estimate ± 10% in the preview text. |
| 3 | Per-cell citation drawer integration breaks on cell-source-document mismatch | Each cell's citation list carries `document_id` explicitly; the drawer reuses the M2-C2 source-doc resolver; integration test pins this. |
| 4 | XLSX with 2000 cells × Excel comments is slow to generate | Streaming write via `openpyxl.Workbook` + `write_only=True` mode; benchmark a 200×10 grid generation before PR opens; if >30 sec, file DE for async export generation (sibling job pattern). |
| 5 | Reviewing-attorney walkthrough surfaces tabular-specific UX issues | Calendar the walkthrough at the M3-C3 verification step (not the final pre-PR check); fix surfaces from the walkthrough during M3-C4 if scoped, defer to follow-on DE if not. |
| 6 | The `M3A6_QUEUE_NAME → M3_PLAYBOOK_QUEUE_NAME` rename breaks in-flight Easy Playbook jobs at deploy | Keep the old constant aliased for one release; document in the M3-A6 worker file; the queue string stays `arq:m3a6` so on-the-wire compatibility is preserved. |

---

## What's NOT in scope for Phase C

Stated explicitly so a future reader can verify scope was held:

- **No Phase D / E work.** Phase D (Slack/Teams plumbing) opens after Phase C lands cleanly.
- **No M4 work.** The Autonomous Layer + Contract Repository design discussions stay parked.
- **No typed columns.** Decision C-1 keeps every cell as a string; typed-grid is a Phase C-close DE candidate.
- **No tabular skill marketplace surface.** The new `output_format: table` example skill ships, but the wider community-skill discovery UX stays out of scope.
- **No tabular re-run / re-execute affordance.** Operators wanting to re-run with the same spec start a new execution from the result view's "Re-run as new execution" button (one-line UI affordance; counts as part of M3-C3 not a separate task).
- **No per-cell manual edit / annotation.** Cells are read-only — they're an auditable artifact of what the model produced. Operators export to Excel for editing.

---

## Sequenced next steps (this session and the next)

1. Commit this prep doc to `m3-phase-c-tabular-review` (this session).
2. M3-C1 implementation: schema extension + tests + docs + one example skill (next session).
3. M3-C2 implementation: tabular module + worker + migration + endpoints.
4. M3-C3 implementation: UI routes + components + Cypress E2E.
5. M3-C4 implementation: bulk ops + XLSX/CSV export.
6. Pre-PR: fresh-install Docker rebuild + reviewing-attorney walkthrough + ruff format AND ruff check AND mypy strict on gateway AND full pytest battery.
7. Open PR against `main` once everything green.

---

*Locked at 2026-05-21 by the maintainer track (Kevin + Claude Opus 4.7). Decisions are revisitable mid-phase only if a discovered constraint forces a change; otherwise hold to keep Phase C bounded.*
