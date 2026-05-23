# Tabular / Multi-Document Review

Tabular Review runs the same per-position extraction over **many documents at once** and lays the answers out in a grid: one row per document, one column per question. It is the "compare these N agreements on these M points" surface — the multi-document complement to the single-document Playbook engine ([docs/playbooks.md](playbooks.md)).

This document is the implementation companion to [PRD §3.14](PRD.md#314-tabular--multi-document-review-m3). It describes what shipped in M3-C2 (the grid + LangGraph workflow), M3-C1 (the `output_format: table` skill mode), and M3-C4a (XLSX/CSV export) — and is scrupulous about what did **not** ship: per-cell citations are surfaced as *display-only* references rather than resolvable Citation-Engine rows (DE-309), per-cell cost/tier telemetry is not yet captured (DE-310), and bulk row/column operations are deferred (DE-304).

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

## Persisted row shape

The `tabular_executions` table (migration 0036) carries a 5-state status (`pending` / `running` / `completed` / `failed` / `cancelled`) with a soft-delete column, plus `document_ids`, `columns`, `skill_name`, `results` (JSONB), `cost_estimate_usd`, `cost_actual_usd`, `error_text`, a `parent_execution_id` self-reference (non-null on bulk-op sibling rows), and the usual timestamps. (The per-document display names returned by the API as `document_names` are **not** a stored column — they are assembled onto the response from the documents' parent filenames; see [docs/db-schema.md](db-schema.md).)

The `results` JSONB (validated by `app.schemas.tabular.TabularResults`) is:

```jsonc
{
  "schema_version": "m3-c2-v1",
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

**Important honesty point.** The web surface and the read-side schema model a structured `Citation` (`{citation_id, document_id, chunk_id, confidence}`) under `CellResult.citations`, but the executor only persists `cited_chunk_ids: list[str]`. A read-side `model_validator` on `TabularRow` (`app/schemas/tabular.py`) bridges the two: for each persisted `cited_chunk_id` it synthesizes a `Citation` using the row's `document_id`, the cell's `confidence`, and a **deterministic, display-only** `citation_id = uuid5(NS, chunk_id)`.

That synthetic `citation_id` is **not** a real Citation-Engine row. The tabular citation drawer is display-only — it shows the `chunk_id`, `document_id`, and `confidence`; it never resolves the `citation_id` against the M2 Citation Engine and offers no "jump to the exact source span" affordance. This is the same posture as the Playbook executor ([docs/playbooks.md](playbooks.md)): both surfaces ground answers in chunk references + verbatim matched text, but neither runs the M2 Citation Engine verification cascade. Real Citation-Engine-backed provenance for tabular cells — resolvable `citation_id`, character-precise source spans — is deferred to **[DE-309](PRD.md#9-deferred-enhancements-and-identified-future-work)**.

> **Why the bridge exists.** Before the M3-E1 fix (PR #80), the persisted key (`cited_chunk_ids`) did not map to the schema field (`citations`), so `CellResult.citations` deserialized empty on every cell and the citation drawer showed nothing — even though the grounding chunks were recorded all along. The `model_validator` is the contained read-side fix; a future executor that emits real `Citation` objects passes through untouched.

---

## UI rendering

The grid renders at `/lq-ai/tabular/[id]` (`web/src/routes/lq-ai/tabular/[id]/+page.svelte`):

- **`TabularGrid.svelte`** — the N × M grid; the leftmost sticky column is the document name.
- **`TabularCell.svelte`** — one cell; shows the extracted value, a confidence affordance, and the failed-cell state. Cells with `confidence='failed'` render distinctly (and export as `"(failed)"`) so operators spot gaps without cross-referencing the source run.
- **`TabularCitationModal.svelte`** — the per-cell citation drawer. Clicking a cell opens it with the cell's citations (display-only: `citation_id`, `confidence`, `document_id`, `chunk_id`). Empty cells show "No citations were attached to this cell"; failed cells explain the cell errored before producing a citation.

---

## Cost preview

`POST /api/v1/tabular/preview-cost` is a synchronous estimate — no execution row is created. The UI calls it before showing the confirmation modal so the operator sees the cell count + estimated cost + per-tier breakdown (Decision C-5). The estimator uses a rolling average over recent `purpose='tabular_extraction'` routing-log rows; cold-start deployments see a conservative default per-cell cost until enough calibration data accumulates. The operator confirms a cost ceiling (`confirmed_cost_usd`) that is echoed onto the execution row as an audit trail.

The confirmation modal is mandatory above a ~$1.00 threshold (Decision C-5).

---

## Export (M3-C4a)

`GET /api/v1/tabular/executions/{id}/export?format=xlsx|csv` streams the completed grid. The execution must be in `status='completed'` — pending / running / cancelled / failed rows return 409 (a partial grid would mislead downstream consumers). Both formats carry the document column (leftmost) plus one column per declared column, in spec order.

- **XLSX** — each grid cell with at least one citation carries an openpyxl `Comment` listing the citation ids + confidences (up to 5 per comment; the cell retains the full count). Operators hover any cell in Excel / Numbers / Google Sheets to see the sources.
- **CSV** — a trailing `citation_links` column per row carries a semicolon-separated list of `"<column_name>:<citation_id>"` pairs across the row's cells; empty when no cell in the row had citations.

Because export reads the grid through the same `TabularResults.model_validate` path as the API, it picks up the citation bridge described above — the `citation_links` column and XLSX comments carry the same display-only synthetic citation ids.

---

## Per-cell cost & tier telemetry

Cells persist `tier_used: null` and `cost_usd: "0"`, and the execution's `cost_actual_usd` sums to 0. This is a **known, code-documented v0.3.0 limitation** (`api/app/tabular/nodes.py` — the cell node comments and `_sum_cell_costs`): the cell node does not yet propagate the per-call tier + cost back from the gateway response. The cost *estimator* still converges off the routing log either way, so the pre-flight preview stays accurate; it is only the post-hoc per-cell economics in the grid that read 0. Threading real per-cell tier + cost through is **[DE-310](PRD.md#9-deferred-enhancements-and-identified-future-work)**.

---

## Known limitations

- **Citations are display-only, not Citation-Engine-resolved.** See [Citations](#citations-how-the-cell-grounding-is-surfaced). Real provenance is [DE-309](PRD.md#9-deferred-enhancements-and-identified-future-work).
- **Per-cell `tier_used` + `cost_usd` are not captured** (always null / 0). [DE-310](PRD.md#9-deferred-enhancements-and-identified-future-work).
- **Bulk operations are deferred.** The M3-C4 spec bundled export (shipped as M3-C4a) with bulk operations — "redline column N in all rows" and "summarize column N into a memo." Only export shipped; the bulk operations are **[DE-304](PRD.md#9-deferred-enhancements-and-identified-future-work)** (they surface an architectural choice about where the output lands that the substrate doesn't anticipate).
- **Lexical FTS retrieval, not vector.** A column query whose vocabulary diverges from the contract's wording may retrieve weaker chunks; low-confidence cells should be treated with corresponding skepticism.
- **Sequential cell dispatch.** No per-cell parallelism in v0.3.0; large grids (toward the 200 × 10 ceiling) run cell-by-cell.

---

## References

- Executor + nodes: [`api/app/tabular/executor.py`](../api/app/tabular/executor.py), [`api/app/tabular/nodes.py`](../api/app/tabular/nodes.py), [`api/app/tabular/cost.py`](../api/app/tabular/cost.py), [`api/app/tabular/state.py`](../api/app/tabular/state.py)
- Worker: [`api/app/workers/tabular_worker.py`](../api/app/workers/tabular_worker.py)
- Endpoints: [`api/app/api/tabular.py`](../api/app/api/tabular.py) — preview-cost, execute, executions, cancel, export
- Schemas: [`api/app/schemas/tabular.py`](../api/app/schemas/tabular.py) — `ColumnSpec`, `Citation`, `CellResult`, `TabularRow`, `TabularResults`
- ORM + migration: [`api/app/models/tabular.py`](../api/app/models/tabular.py), alembic migration `0036`
- Web UI: [`web/src/lib/lq-ai/components/TabularGrid.svelte`](../web/src/lib/lq-ai/components/TabularGrid.svelte), `TabularCell.svelte`, `TabularCitationModal.svelte`, [`web/src/routes/lq-ai/tabular/[id]/+page.svelte`](../web/src/routes/lq-ai/tabular/[id]/+page.svelte)
- Table-mode skill: [`skills/contract-snapshot/SKILL.md`](../skills/contract-snapshot/SKILL.md), [`docs/skill-authoring-guide.md`](skill-authoring-guide.md)
- Capability spec: [PRD §3.14](PRD.md#314-tabular--multi-document-review-m3)
- Related deferred work: [DE-304](PRD.md#9-deferred-enhancements-and-identified-future-work) (bulk ops), [DE-309](PRD.md#9-deferred-enhancements-and-identified-future-work) (real citation provenance), [DE-310](PRD.md#9-deferred-enhancements-and-identified-future-work) (per-cell tier/cost telemetry)
- Companion surface: [docs/playbooks.md](playbooks.md) (single-document Playbook engine)
