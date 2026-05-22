<script context="module" lang="ts">
	import type { TabularCellResult } from '$lib/lq-ai/types';

	export interface CellOpenEvent {
		documentId: string;
		documentName: string;
		columnName: string;
		cell: TabularCellResult | undefined;
	}
</script>

<script lang="ts">
	/**
	 * Tabular results grid — M3-C3 sub-phase 4.
	 *
	 * Renders the M × N grid as a single semantic <table> with sticky
	 * first column (document name) + sticky first row (column headers)
	 * via CSS `position: sticky`. Each cell is a `<TabularCell>` that
	 * dispatches `open` on click; this component re-dispatches with the
	 * full `CellOpenEvent` carrying the cell + its document / column
	 * coordinates so the parent's citation modal has everything it
	 * needs to render.
	 */
	import { createEventDispatcher } from 'svelte';

	import type {
		TabularColumnSpec,
		TabularResults
	} from '$lib/lq-ai/types';
	import TabularCell from './TabularCell.svelte';

	export let results: TabularResults | null;
	export let columns: TabularColumnSpec[];
	/**
	 * The execution's `document_ids` order — used to render rows for
	 * documents the worker hasn't filled yet (status='running'). Each
	 * id maps via `documentNameById[id]` to the row label; cells that
	 * haven't been produced yet render as `state='empty'`.
	 */
	export let documentIds: string[];
	export let documentNameById: Record<string, string>;

	const dispatch = createEventDispatcher<{ open: CellOpenEvent }>();

	// Build a documentId → row.cells map so the renderer can render
	// in document_ids order without depending on the row ordering the
	// backend returns.
	$: rowByDocId = (() => {
		const m: Record<string, TabularResults['rows'][number]> = {};
		for (const r of results?.rows ?? []) {
			m[r.document_id] = r;
		}
		return m;
	})();

	function handleCellOpen(
		event: CustomEvent<{ documentName: string; columnName: string }>,
		documentId: string,
		cell: TabularCellResult | undefined
	): void {
		dispatch('open', {
			documentId,
			documentName: event.detail.documentName,
			columnName: event.detail.columnName,
			cell
		});
	}
</script>

<div class="lq-tabgrid__scroll" data-testid="lq-tabgrid">
	<table class="lq-tabgrid">
		<thead>
			<tr>
				<th scope="col" class="lq-tabgrid__corner lq-tabgrid__sticky-col">Document</th>
				{#each columns as col (col.name)}
					<th
						scope="col"
						class="lq-tabgrid__sticky-row"
						data-testid="lq-tabgrid-header"
						data-column-name={col.name}
					>
						{col.name}
					</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each documentIds as docId (docId)}
				{@const row = rowByDocId[docId]}
				{@const name = documentNameById[docId] ?? docId}
				<tr data-testid="lq-tabgrid-row" data-document-id={docId}>
					<th
						scope="row"
						class="lq-tabgrid__sticky-col"
						data-testid="lq-tabgrid-row-label"
					>
						{name}
					</th>
					{#each columns as col (col.name)}
						{@const cell = row?.cells[col.name]}
						<td class="lq-tabgrid__cell">
							<TabularCell
								{cell}
								documentName={name}
								columnName={col.name}
								on:open={(e) => handleCellOpen(e, docId, cell)}
							/>
						</td>
					{/each}
				</tr>
			{/each}
		</tbody>
	</table>
</div>

<style>
	.lq-tabgrid__scroll {
		max-height: 32rem;
		overflow: auto;
		border: 1px solid var(--lq-border);
		border-radius: 0.5rem;
		background: var(--lq-surface);
	}
	.lq-tabgrid {
		border-collapse: separate;
		border-spacing: 0;
		min-width: 100%;
	}
	.lq-tabgrid th,
	.lq-tabgrid td {
		padding: 0;
		border-bottom: 1px solid var(--lq-border);
		border-right: 1px solid var(--lq-border);
		vertical-align: top;
	}
	.lq-tabgrid thead th {
		padding: 0.625rem 0.75rem;
		font-weight: 600;
		font-size: 0.8125rem;
		text-align: left;
		background: var(--lq-inset);
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}
	.lq-tabgrid__sticky-row {
		position: sticky;
		top: 0;
		z-index: 2;
	}
	.lq-tabgrid__sticky-col {
		position: sticky;
		left: 0;
		z-index: 1;
		background: var(--lq-surface);
		font-weight: 600;
		padding: 0.625rem 0.75rem;
		min-width: 12rem;
	}
	.lq-tabgrid__corner {
		z-index: 3;
		background: var(--lq-inset);
	}
	.lq-tabgrid__cell {
		min-width: 14rem;
	}
	.lq-tabgrid tbody tr:nth-child(even) .lq-tabgrid__sticky-col {
		background: var(--lq-inset);
	}
</style>
