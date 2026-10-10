# ADR 0040 — Tabular bulk operations (redline report + column memo)

**Status:** Accepted (2026-10-04) — approved at the committee meeting with the maintainer's review amendments. Hou Fu confirmed the approval and inclusion of those amendments on 2026-10-10. Implementation acceptance and security review remain separate from this architectural approval.

**Relates to:** [PRD §3.14](../PRD.md#314-tabular--multi-document-review-m3), [DE-304](../PRD.md#de-304--tabular-review-bulk-operations-redline-per-row--summarize-column-deferred-from-m3-c4), Phase C Decisions C-1, C-3, C-5, C-9 and C-10, [ADR 0007](0007-skill-prompt-assembly.md), and [ADR 0014](0014-gateway-egress-boundary-for-tool-providers.md).

## Context and user stories

A completed Tabular Review grid provides extracted values for multiple documents. Export already ships; DE-304 deferred bulk drafting until the output pattern was decided.

**Redline a selected column.** The operator selects a column such as “Term” and requests suggested revisions across the source documents. Before confirming, they see a cost estimate and the drafting skill's identity and version. One combined report contains a draft for each supported document and an explicit failed or missing item for every unsupported row. This produces suggested clause revisions, not document edits or tracked changes.

**Summarize a selected column.** The operator selects one column and a summary skill. One comparative memo accounts for all rows, including failed extractions, and identifies its source review. The memo remains accessible even if that review is deleted.

Phase C Decision C-9 specified sibling `tabular_executions` rows for bulk operations, including report-skill redlines and a Markdown summary. DE-304 reopened the output-pattern decision because long-form reports fit the current grid result schema poorly. This ADR **supersedes C-9's sibling-row storage choice for these two operations**. It preserves the immutable original grid and leaves `parent_execution_id` available for future grid-shaped child executions.

## Decisions

### D1 — Dedicated operation records and independent retention

Store one operation per `tabular_bulk_ops` row (migration 0071, after main's 0070):

- `execution_id`: nullable source link, `ON DELETE SET NULL`.
- `source_execution_id`: immutable original UUID, independent of the source foreign key.
- `user_id`: non-null owner, `ON DELETE CASCADE`. Deleting an account removes its work product; audit events follow their separate metadata-retention policy.
- `provenance`: source execution identity/time, snapshotted columns and document identifiers/names, and the immutable skill instructions, references, version, scope, hash and input bindings used. This does not retain a duplicate source grid or document text.
- `kind`: `redline_rows` or `summarize_column`; `params`: selected column and skill name.
- `status`, `results`, confirmation/cost fields and lifecycle timestamps.

Reports and memos remain owned and retrievable after either soft or hard deletion of their parent execution. Hard deletion severs the live relationship without deleting the output. A queued operation whose source is deleted fails rather than generating work against an unavailable source. Source files have their own lifecycle; the output's source identity is not a promise that those files remain accessible.

A dedicated table avoids forcing non-grid reports into `TabularResults` or adding report rows to the executions list. Results remain JSONB, matching the current whole-report access pattern. Downgrade refuses while retained operation rows exist; export and deliberately clear retained work before removing the table.

### D2 — Preview, create, and independent owner reads

- `POST /api/v1/tabular/executions/{execution_id}/bulk-ops/preview-cost` validates the source, column, skill and required inputs, returning estimated cost plus skill identity, version and content hash.
- `POST /api/v1/tabular/executions/{execution_id}/bulk-ops` repeats validation, requires the previewed skill hash, snapshots the resolved instructions, creates a pending operation and returns 202. Changed instructions return 409 and require a fresh preview.
- `GET /api/v1/tabular/bulk-ops` lists the caller's retained outputs, paginated and recent-first.
- `GET /api/v1/tabular/bulk-ops/{bulk_op_id}` reads one caller-owned output independently of the parent. Missing and cross-user outputs both return 404.

The existing execution-detail response also embeds `bulk_ops`. Creation requires a visible, caller-accessible completed execution and a nonempty grid. **Both operations require `column_name`**, validated against the execution's snapshotted column specification before enqueueing.

### D3 — Skill-backed instructions, with attribution

Redlining uses a loaded `output_format: report` skill; column summarization uses a loaded report/Markdown summary skill selected by the operator. Resolve it through the existing user > team > built-in path. Retain the exact body, references, version, scope, content hash and input bindings with the operation; later registry edits do not alter queued instructions.

Use the existing gateway inline-skill assembler for the instruction snapshot. Required document/file inputs refer to the selected-column source context supplied in the user message; other required inputs must be supplied or have a declared default. Apply the most restrictive selected-column and skill inference-tier floor: the minimum of declared values, with no floor when neither declares one (PRD §1.5.2). Preserve operator-configured anonymization for skill instructions and bound inputs; only the source-context message is exempt through the existing M2-1 per-message flag. Fixed task constraints define the operation and its honesty requirements; they do not replace the selected skill's drafting instructions. No additional tool or script execution is introduced.

### D4 — Cost preview and sequential execution

Keep the existing preview/confirmation idiom: one inference call per row for redlining, one for a column memo. Estimate with the recent purpose-tagged rolling average, with a $0.01/call cold-start fallback. The UI requires explicit confirmation above $1.00; the server retains the confirmed estimate without introducing a new estimate-drift rejection policy.

Bound each row draft at 1,500 output tokens and the single comparative memo at 4,000. The real-model recipe showed that sharing the row budget cut the memo off before its missing-evidence section. The larger memo budget can increase that call's spend; preview remains a historical estimate, not an exact price or a spend limit.

One ARQ job on the existing shared queue walks rows sequentially. Per-item failures remain visible and do not stop the remaining batch. `completed` means processing finished, including failed items; `failed` means the operation could not be orchestrated. Calls use the existing gateway path with `purpose='tabular_bulk_op'`.

### D5 — Selected-column grounding and honest results

The selected column defines the redline task. Its extracted value and status, available document chunks, and other explicitly contextual row values inform the draft; they do not silently broaden it into a whole-agreement review. A failed extraction or unavailable document context yields a visible failed item without a speculative revision.

The summary sees every row's selected value and explicit markers for missing or failed values. Both outputs are drafts for professional review. Existing source-chunk links are not proof that generated revisions are citation-verified. Per-call metered costs and citation verification are not added by this ADR; the current aggregate-cost field remains unreconciled and must not be presented as measured spend.

Recipe corrections (2026-10-10): retain the gateway finish reason on each delivered item. Only a normal `stop` below the output cap produces a completed draft; length-limited, filtered, tool-call or unconfirmed endings are failed items with partial text retained and an explicit incomplete warning. Processing may still complete with those failures, without an automatic inference retry. Memo items retain server-generated selected-column `source_rows` coverage separately from model prose, so missing evidence is always visible even if the model omits it. Render draft Markdown through the existing marked/DOMPurify pattern, including partial text.

## Acceptance examples and consequences

- A 40-document “Term” memo with 32 three-year values, five five-year values and three failed extractions identifies the three gaps; it does not claim 40 verified observations.
- One unsupported redline row stays visible while other rows complete; drafting targets the selected column and uses the frozen skill.
- After source soft/hard deletion, the owner can list and open retained output; another user cannot. Account export includes retained outputs, and account deletion removes them.
- Previewing a skill and then changing its instructions requires another preview. Changing it after enqueueing does not alter the stored snapshot.
- The original documents and grid are unchanged. Grid XLSX/CSV export remains grid-only; account export includes report/memo records.
- Deploy migration 0071 and rebuild `api`, `arq-worker` and `ingest-worker` together. Deployment, runtime/UI acceptance and applicable security review are still required before merge/release.

## Decision record

- The October 4 committee agenda included PR #418 under the ADR pipeline.
- [Maintainer review, 2026-10-02](https://github.com/LegalQuants/lq-ai/pull/418#pullrequestreview-5382101475) supplies the ADR amendments.
- Ratification authority/date: LQAI Committee, 2026-10-04, as confirmed by Hou Fu on 2026-10-10. The agenda establishes scheduling; the maintainer's confirmation supplies the approval record. No vote tally or independent minutes verification is claimed here.
