# Tabular / Multi-Document Review

Tabular Review runs the same per-position extraction over **many documents at once** and lays the answers out in a grid: one row per document, one column per question. It is the "compare these N agreements on these M points" surface — the multi-document complement to the single-document Playbook engine ([docs/playbooks.md](playbooks.md)).

This document is the implementation companion to [PRD §3.14](PRD.md#314-tabular--multi-document-review-m3). It describes the grid, LangGraph workflow and XLSX/CSV export, plus navigable source resolution (#125), per-column ensemble verification (#127) and executor-minted positional provenance (DE-309, #420). Per-cell cost/tier telemetry (DE-310) and typed generated-client results (DE-330) remain deferred. Bulk operations have their own [ADR 0040](adr/0040-tabular-bulk-operations.md) implementation.

---

## Scope

A tabular execution takes:

- a **document set** (`document_ids`, 1–200 documents — the 200 cap is a Phase C decision), and
- a **column spec** — either supplied inline (ad-hoc `columns: [{name, query, …}]`) or named by an `output_format: table` skill (`skill_name`).

It produces a `tabular_executions` row whose `results` JSONB holds the grid: `rows[].cells[column_name]` where each cell carries an extracted `value`, a `confidence`, the chunks it was grounded against, and (for failed cells) an `error`. The operator reviews the grid in the web UI, opens a per-cell citation drawer to see the grounding chunks, and exports the grid to XLSX or CSV.

What Tabular Review is **not**: it is not a verification engine. Execution completion does not mean every cell is correct — the per-cell citation drawer is where the user-attorney validates each extraction before relying on it. Bias the column queries toward "failed" over false confidence; the system prompt does the same.

Each `(document, column)` pair is one **cell**, dispatched as one structured-output LLM call. The upper bound is 200 documents × 10 columns = 2,000 cells; the retrieval and prompt budgets (below) are sized against that ceiling.

---

## The workflow

The executor (`api/app/tabular/executor.py`) is a three-node LangGraph graph run by the ARQ worker (`api/app/workers/tabular_worker.py`) on the shared playbook queue (`arq:m3a6`, per Phase C Decision C-3 — the same queue as the Easy Playbook wizard). The nodes live in `api/app/tabular/nodes.py`:

1. **`load_documents_node`** — resolves `document_ids` to `Document` rows in the operator's selection order (missing / soft-deleted documents are skipped silently; the row is preserved as audit but the result set is honest about which sources resolved). It joins the parent `File` so each row's display name is the operator-uploaded filename, not the document UUID.
2. **`extract_cells_node`** — for each `(document, column)` pair: runs a lexical full-text search (FTS) over that document's `document_chunks` using the column's `query` as keyword input (top-K = 4 chunks; falls back to the first N chunks when FTS yields nothing, so the LLM still sees document content), then dispatches one structured-output LLM call. The model returns `{value, cited_chunk_indices, confidence, justification}`; the node maps `cited_chunk_indices` → `cited_chunk_ids` against the retrieved chunks. Every cell is wrapped in its own try/except: any failure (no chunks retrieved, gateway error, malformed response, empty value) lands as `confidence='failed'` with a populated `error` (Decision C-10) rather than aborting the run. Dispatch is sequential in v0.3.0; per-cell parallelism is a follow-on if the 2,000-cell latency forces it.
3. **`aggregate_node`** — groups per-cell results by document into the `results` JSONB and flips status to `completed` (or `failed` if a prior node set `state['error']`). It writes `cost_actual_usd` as the sum of per-cell costs — which is currently always 0 (see [Per-cell cost & tier](#per-cell-cost--tier-telemetry)).

Retrieval is **lexical FTS, not vector search** — the column query is treated as keyword input over the document's chunks. This is a deliberate v0.3.0 choice: it needs no embedding pre-pass and keeps each cell's context small. It also means a column query whose wording diverges from the contract's vocabulary may retrieve weaker chunks; the FTS-falls-back-to-first-N behavior keeps the cell from failing outright, but the operator should treat low-confidence cells accordingly.

---

## The `output_format: table` skill mode (M3-C1)

A skill declares table mode in its frontmatter: `output_format: table` plus a `columns:` list, each entry `{name, query, ensemble_verification?, minimum_inference_tier?}`. The per-column `ensemble_verification` and `minimum_inference_tier` shadow the skill-level defaults, so a high-stakes column can demand Tier 4+ while routine columns inherit cheaper routing. The skill loader rejects malformed table skills at load time (missing or empty `columns`). See [docs/skill-authoring-guide.md](skill-authoring-guide.md) and the reference skill [`skills/contract-snapshot/SKILL.md`](../skills/contract-snapshot/SKILL.md).

A tabular execution supplies **either** `skill_name` **or** inline `columns` — never both (the endpoint returns 400 if both are present, or if the named skill has no columns). Inline columns are the ad-hoc path the web UI's column builder uses; skill-named columns are the reusable path.

The wire shape `ColumnSpec` is defined twice on purpose — `app.skills.schema.ColumnSpec` (loaded from SKILL.md frontmatter at startup) and `app.schemas.tabular.ColumnSpec` (arrives as JSON on each execution request). The shapes are identical today; the split lets the wire surface evolve independently of the authoring surface.

---

## Per-column ensemble verification (post-v0.4.0, #127)

A column's `ensemble_verification` flag is **honored at execution**. The executor resolves the gateway's Stage-4 ensemble config once for the whole run (`gateway.get_citation_engine_ensemble_config()`); for each column it computes an effective flag with the precedence **column `ensemble_verification` > skill snapshot > deployment default** (`ensemble_config.default_enabled`). A column can only actually run an ensemble when the gateway has one configured, so the effective flag is false whenever no ensemble exists regardless of the column setting. The same resolution runs identically at preview and at execute.

When a column resolves to ensemble-on and a cell has grounding chunks, `extract_cell` runs **one** Stage-4 ensemble verify pass (`_verify_cell_ensemble`, `api/app/tabular/nodes.py`) over the concatenation of that cell's cited chunks: the extracted `value` is the claim, the cited chunk text is the source. Stages 1–2 usually miss (a short value rarely equals the long concatenation) so Stage 4 fires — but a near-verbatim single-chunk value can legitimately hit `exact_match`/`tolerant_match` instead, which is a *stronger* verification, not an error. The pass is defensively wrapped: a verification failure (or any exception) degrades to `verification_method = None` and **never** fails the cell or alters its `value`/`confidence`/`citations`.

The resulting `verification_method` — `ensemble_strict`, `ensemble_majority`, or `None` — persists on each cell and is **mirrored onto each synthesized `Citation`** by the read-side validator. Cost preview reflects the premium: `ensemble_cells_count` (= `n_docs × count-of-ensemble-columns`) and `ensemble_premium_usd` are added to the preview response, and the premium is included in `estimated_cost_usd` (`api/app/tabular/cost.py`). There is **no** mid-run / per-cell cost ceiling on the tabular ensemble path the way the chat path has one — that is deferred as **[DE-331](PRD.md#9-deferred-enhancements-and-identified-future-work)**; the pre-flight preview + the operator's `confirmed_cost_usd` ceiling are the only economic guard.

---

## Persisted row shape

The `tabular_executions` table (migration 0036) carries a 5-state status (`pending` / `running` / `completed` / `failed` / `cancelled`) with a soft-delete column, plus `document_ids`, `columns`, `skill_name`, `results` (JSONB), `cost_estimate_usd`, `cost_actual_usd`, `error_text`, a `parent_execution_id` self-reference (non-null on bulk-op sibling rows), and the usual timestamps. (The per-document display names returned by the API as `document_names` are **not** a stored column — they are assembled onto the response from the documents' parent filenames; see [docs/db-schema.md](db-schema.md).)

The `results` JSONB (validated by `app.schemas.tabular.TabularResults`) is:

```jsonc
{
  "schema_version": "m3-c2-v2",
  "rows": [
    {
      "document_id": "<uuid>",
      "document_name": "nda-1-acme-beta.pdf",
      "cells": {
        "Term": {
          "value": "3 years from the Effective Date; …",
          "cited_chunk_ids": ["<chunk-uuid>", "<chunk-uuid>"],
          "confidence": "high",          // high | medium | low | failed
          "tier_used": null,             // see telemetry limitation below
          "cost_usd": "0",               // see telemetry limitation below
          "verification_method": "ensemble_strict", // ensemble column: set by the Stage-4 pass
          "error": null
        },
        "Governing Law": {
          "value": "Delaware",
          "cited_chunk_ids": ["<chunk-uuid>"],
          "confidence": "high",
          "tier_used": null,
          "cost_usd": "0",
          "verification_method": null,   // non-ensemble column: no Stage-4 pass ran
          "error": null
        }
        // … one entry per column
      }
    }
    // … one row per document, in document_ids order
  ],
  "summary": { "total_cells": 20, "failed_cells": 0 }
}
```

The `results` schema is version-stamped (`schema_version`) so the result-view renderer can refuse unknown versions rather than crash.

---

## Citations: how the cell grounding is surfaced

Each non-failed cell records the chunks the model cited as `cited_chunk_ids`. This is the cell's **grounding** — the FTS-retrieved chunks whose content the model said supported its answer.

**The synthetic-citation bridge.** The web surface and the read-side schema model a structured `Citation` (`{citation_id, document_id, chunk_id, confidence, …}`) under `CellResult.citations`, but the executor only persists `cited_chunk_ids: list[str]`. A read-side `model_validator` on `TabularRow` (`app/schemas/tabular.py`) bridges the two: for each persisted `cited_chunk_id` it synthesizes a `Citation` using the row's `document_id`, the cell's `confidence`, the cell's `verification_method` (mirrored down), and a **deterministic** `citation_id = uuid5(NS, chunk_id)`.

**Navigable source resolution (post-v0.4.0, #125).** `GET /api/v1/tabular/executions/{id}` now *enriches* each synthesized citation read-side with its source location: `source_file_id` (`documents.file_id`), `source_page` (`document_chunks.page_start`), and `source_text` (the chunk content). The handler (`api/app/api/tabular.py`) resolves these with **two batched IN-queries** across all cited chunks for the whole grid — one over `document_chunks`, one mapping documents to their files — rather than per-cell lookups. Existing executions are enriched on read too (the resolution is read-side, so no re-run or migration is needed). With these fields the drawer can offer a "jump to the source span" affordance.

**Minted provenance (DE-309, #420).** Extraction locates the cell value verbatim in each cited chunk and confirms it through the canonical verifier with `gateway=None` (no LLM judge). The aggregate node writes `tabular_cell_citations` rows (migration 0079) in the same transaction as the results. On GET and cancel, the persisted `m3-c2-v2` stamp selects these real ids and chunk-local offsets, even if no rows were minted. An unlocated new-vintage cell has an empty citation list; it does not regain synthetic citations merely because the execution has zero rows. The existing confidence badge still describes cell confidence, not positional verification. Legacy `m3-c2-v1` executions keep the display-only bridge with null offsets. Export also keeps bridge ids. Typed generated-client results remain **[DE-330](PRD.md#9-deferred-enhancements-and-identified-future-work)**.

> **Why the bridge remains.** Before the M3-E1 fix (PR #80), the persisted key (`cited_chunk_ids`) did not map to `citations`, so the drawer showed nothing even though grounding chunks were recorded. The validator still supports legacy executions and exports; GET/cancel replace its output with minted rows for `m3-c2-v2`.

---

## UI rendering

The grid renders at `/lq-ai/tabular/[id]` (`web/src/routes/lq-ai/tabular/[id]/+page.svelte`):

- **`TabularGrid.svelte`** — the N × M grid; the leftmost sticky column is the document name.
- **`TabularCell.svelte`** — one cell; shows the extracted value, a confidence affordance, and the failed-cell state. Cells with `confidence='failed'` render distinctly (and export as `"(failed)"`) so operators spot gaps without cross-referencing the source run.
- **`TabularCitationModal.svelte`** — the per-cell citation drawer. Clicking a cell opens it with the cell's citations (`citation_id`, `confidence`, `document_id`, `chunk_id`, and the read-side-resolved `source_file_id`/`source_page`/`source_text` from #125). Empty cells show "No citations were attached to this cell"; failed cells explain the cell errored before producing a citation.

---

## Cost preview

`POST /api/v1/tabular/preview-cost` is a synchronous estimate — no execution row is created. The UI calls it before showing the confirmation modal so the operator sees the cell count + estimated cost + per-tier breakdown (Decision C-5). The estimator uses a rolling average over recent `purpose='tabular_extraction'` routing-log rows; cold-start deployments see a conservative default per-cell cost until enough calibration data accumulates. When any column resolves to ensemble-on, the preview also reports `ensemble_cells_count` and `ensemble_premium_usd` — the added cost of the per-cell Stage-4 passes — and folds the premium into `estimated_cost_usd` (per-column ensemble section above). The operator confirms a cost ceiling (`confirmed_cost_usd`) that is echoed onto the execution row as an audit trail.

The confirmation modal is mandatory above a ~$1.00 threshold (Decision C-5).

---

## Export (M3-C4a)

`GET /api/v1/tabular/executions/{id}/export?format=xlsx|csv` streams the completed grid. The execution must be in `status='completed'` — pending / running / cancelled / failed rows return 409 (a partial grid would mislead downstream consumers). Both formats carry the document column (leftmost) plus one column per declared column, in spec order.

- **XLSX** — each grid cell with at least one citation carries an openpyxl `Comment` listing the citation ids + confidences (up to 5 per comment; the cell retains the full count). Operators hover any cell in Excel / Numbers / Google Sheets to see the sources.
- **CSV** — a trailing `citation_links` column per row carries a semicolon-separated list of `"<column_name>:<citation_id>"` pairs across the row's cells; empty when no cell in the row had citations.

Exports use the same provenance resolver as GET and cancellation. For minting-vintage executions (`m3-c2-v2`), CSV citation links and XLSX comments contain the real minted citation IDs; unlocated cells have no citation, including executions that minted zero rows. Genuine legacy executions retain their display-only bridge IDs. XLSX comments retain full citation IDs. Source passages and highlights remain available in the result dialog.

---

## Per-cell cost & tier telemetry

DE-310 (#421) propagates the gateway's `routed_inference_tier` and `cost_estimate` as `tier_used` and a fixed-point decimal-string `cost_usd`. Received annotations survive failed extractions too: empty/malformed responses and responses without a usable value retain their reported tier/cost. Missing response annotations stay null; the column's minimum tier is not reported as the routed tier. `cost_actual_usd` sums reported extraction costs from successful and failed cells, with missing costs contributing zero. Calls without a received response retain the existing zero placeholder, which is not proof of zero spend. This remains incomplete accounting when annotations are unavailable, and it excludes ensemble judge spend; the routing log remains the source for those calls. It is not a complete billed-spend total.

---

## Known limitations

- **Positional provenance is verbatim-only.** A paraphrased value that cannot be located mints no row. New-vintage GET/cancel responses and exports expose no citations for that cell; only genuine legacy executions retain synthetic bridge ids. See [Citations](#citations-how-the-cell-grounding-is-surfaced).
- **Cost totals include reported extraction costs only.** Received annotations are retained even when extraction fails; missing annotations remain null per response and contribute zero to the stored aggregate. The result page says "Extraction cost not reported" when no cell has a reported cost and marks known subtotals as partial when other costs are missing. A reported zero remains distinguishable from unknown cost. Costs without received annotations and ensemble-judge spend may be absent. [DE-310](PRD.md#9-deferred-enhancements-and-identified-future-work).
- **Bulk-operation scope is bounded.** The current DE-304 implementation supports selected-row redline reports and single-column summaries; its retained work-product and execution rules are documented in [ADR 0040](adr/0040-tabular-bulk-operations.md).
- **Lexical FTS retrieval, not vector.** A column query whose vocabulary diverges from the contract's wording may retrieve weaker chunks; low-confidence cells should be treated with corresponding skepticism.
- **Sequential cell dispatch.** No per-cell parallelism in v0.3.0; large grids (toward the 200 × 10 ceiling) run cell-by-cell.

---

## References

- Executor + nodes: [`api/app/tabular/executor.py`](../api/app/tabular/executor.py), [`api/app/tabular/nodes.py`](../api/app/tabular/nodes.py), [`api/app/tabular/cost.py`](../api/app/tabular/cost.py), [`api/app/tabular/state.py`](../api/app/tabular/state.py)
- Worker: [`api/app/workers/tabular_worker.py`](../api/app/workers/tabular_worker.py)
- Endpoints: [`api/app/api/tabular.py`](../api/app/api/tabular.py) — preview-cost, execute, executions, cancel, export
- Tests: [`api/tests/tabular/`](../api/tests/tabular/) — `test_nodes.py` (cell extraction / FTS fallback / chunk-index coercion), `test_cost.py` (preview estimator + cold-start fallback), `test_export.py` (XLSX/CSV round-trip + citation-comment cap), `test_schemas.py` (the read-side citation bridge), `test_worker.py` (job registration + `arq:m3a6` queue naming), `test_executor_spans.py` (tracing). Plus cross-cutting endpoint coverage in `api/tests/test_endpoints.py` (auth-gate on every tabular route) and `api/tests/test_openapi.py` (schema conformance). These cover the executor, cost estimator, export, schema bridge, worker wiring, auth gating, and OpenAPI conformance; what is **not** yet present is a per-endpoint business-logic integration test that drives the `api/app/api/tabular.py` handlers end-to-end against a live DB (e.g., POST `/tabular/execute` → poll → assert grid).
- Schemas: [`api/app/schemas/tabular.py`](../api/app/schemas/tabular.py) — `ColumnSpec`, `Citation`, `CellResult`, `TabularRow`, `TabularResults`
- ORM + migration: [`api/app/models/tabular.py`](../api/app/models/tabular.py), alembic migration `0036`
- Web UI: [`web/src/lib/lq-ai/components/TabularGrid.svelte`](../web/src/lib/lq-ai/components/TabularGrid.svelte), `TabularCell.svelte`, `TabularCitationModal.svelte`, [`web/src/routes/lq-ai/tabular/[id]/+page.svelte`](../web/src/routes/lq-ai/tabular/[id]/+page.svelte)
- Table-mode skill: [`skills/contract-snapshot/SKILL.md`](../skills/contract-snapshot/SKILL.md), [`docs/skill-authoring-guide.md`](skill-authoring-guide.md)
- Capability spec: [PRD §3.14](PRD.md#314-tabular--multi-document-review-m3)
- Related deferred work: [DE-304](PRD.md#9-deferred-enhancements-and-identified-future-work) (bulk ops), [DE-309](PRD.md#9-deferred-enhancements-and-identified-future-work) (executor-minted citation provenance), [DE-310](PRD.md#9-deferred-enhancements-and-identified-future-work) (per-cell tier/cost telemetry), [DE-330](PRD.md#9-deferred-enhancements-and-identified-future-work) (typed cell/citation OpenAPI schema), [DE-331](PRD.md#9-deferred-enhancements-and-identified-future-work) (mid-run ensemble cost ceiling)
- Companion surface: [docs/playbooks.md](playbooks.md) (single-document Playbook engine)
