<script lang="ts">
	/**
	 * The document picker for a profile that reads documents the owner selects, or may
	 * (ADR 0038 D5). Selection order is the numbering: the plan and the answer refer to the
	 * documents by those numbers. A file the run cannot read is listed, disabled, with the
	 * reason: it is never silently left out. In a matter, a candidate that is not attached
	 * to it yet says it will be added when the plan is proposed; a chat in no matter adds
	 * nothing to one, and nothing here names one.
	 *
	 * It is a native fold so that it takes one line above the composer: the closed line
	 * says what is selected ("Documents · 2 selected: msa.txt, dpa.md"). It starts open
	 * only when the profile needs a document and none is selected, and that is decided
	 * once, when the picker is drawn. After that it is the reader's: the element is bound
	 * to `open`, which nothing here changes. Drawn as `open={value}` it shut under someone
	 * ticking files, because the element's `open` was assigned again each time the closed
	 * line's text changed.
	 *
	 * File names are the owner's own text and are rendered as text only.
	 */
	import type { RunDocument } from '$lib/lq-ai/api/orchestration';
	import { documentRows, documentsSummary, pickerEmpty, pickerHelp } from '$lib/lq-ai/run/composer';

	export let documents: RunDocument[] = [];
	/** Selected file ids, in the order they were picked. */
	export let selected: string[] = [];
	export let max = 8;
	/** The fewest documents a request needs: 0 for a profile that takes them as the owner likes. */
	export let min = 0;
	/** False for a chat in no matter. */
	export let inMatter = true;
	export let loading = false;
	export let error: string | null = null;
	export let onToggle: (fileId: string) => void = () => undefined;
	export let onRefresh: () => void = () => undefined;

	// Evaluated once, not reactively: a fold that re-opened or re-closed itself as the
	// selection changed would fight the person using it.
	let open = documentsSummary({ documents, selected, min }).startsOpen;

	$: rows = documentRows(documents, selected, max, { inMatter });
	$: summary = documentsSummary({ documents, selected, min, loading, error });
	$: help = pickerHelp({ max, min });
</script>

<details class="picker" bind:open data-testid="lq-ai-run-document-picker">
	<summary title={summary.full ?? undefined} data-testid="lq-ai-run-document-summary"
		>{summary.line}</summary
	>
	<div class="body">
		<div class="head">
			<h4>Documents for this run</h4>
			<span class="count" aria-live="polite">{selected.length} of {max} selected</span>
		</div>
		<p class="help">{help}</p>

		{#if loading}<p class="state" role="status">Loading documents…</p>{/if}
		{#if error}<p class="state error" role="alert">{error}</p>{/if}
		{#if !loading && !error && documents.length === 0}
			<p class="state">{pickerEmpty(inMatter)}</p>
		{/if}

		{#if rows.length > 0}
			<ul class="list">
				{#each rows as row (row.fileId)}
					<li>
						<label
							class="row"
							class:disabled={row.disabled}
							data-testid={`lq-ai-run-document-${row.fileId}`}
							data-selected={row.checked}
							data-number={row.number ?? undefined}
						>
							<input
								type="checkbox"
								checked={row.checked}
								disabled={row.disabled}
								on:change={() => onToggle(row.fileId)}
							/>
							<span class="num" aria-hidden={row.number === null}>{row.number ?? ''}</span>
							<span class="text">
								<span class="name">{row.filename}</span>
								{#if row.reason}<span class="reason">{row.reason}</span>{/if}
								{#if row.note}<span class="note">{row.note}</span>{/if}
							</span>
						</label>
					</li>
				{/each}
			</ul>
		{/if}

		<button type="button" class="link" disabled={loading} on:click={onRefresh}>Refresh list</button>
	</div>
</details>

<style>
	.picker {
		margin-top: 0.35rem;
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-lg);
		background: var(--lq-canvas);
	}
	.picker > summary {
		/* A list item, so that the line keeps its disclosure marker; inside, so that
		   the marker is not clipped with the overflow. */
		display: list-item;
		list-style-position: inside;
		padding: 0.3rem 0.6rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		cursor: pointer;
		font-size: 0.78rem;
		color: var(--lq-text-secondary);
	}
	.picker > summary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.body {
		padding: 0.1rem 0.75rem 0.6rem;
	}
	.head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	h4 {
		margin: 0;
		font-size: 0.85rem;
		font-weight: 600;
	}
	.count {
		font-size: 0.75rem;
		color: var(--lq-text-secondary);
	}
	.help {
		margin: 0.25rem 0 0.4rem;
		font-size: 0.75rem;
		line-height: 1.5;
		color: var(--lq-text-secondary);
	}
	.state {
		margin: 0.25rem 0;
		font-size: 0.78rem;
		color: var(--lq-text-secondary);
	}
	.state.error {
		color: var(--lq-error);
	}
	.list {
		list-style: none;
		margin: 0;
		padding: 0;
		max-height: 14rem;
		overflow: auto;
	}
	.row {
		display: flex;
		align-items: flex-start;
		gap: 0.5rem;
		padding: 0.35rem 0.25rem;
		border-top: 1px solid var(--lq-border);
		cursor: pointer;
	}
	.row.disabled {
		cursor: not-allowed;
	}
	.row.disabled .name {
		color: var(--lq-text-tertiary);
	}
	input {
		margin-top: 0.2rem;
		flex: none;
	}
	.num {
		flex: none;
		min-width: 1.1rem;
		text-align: center;
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--lq-accent);
	}
	.text {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.name {
		font-size: 0.82rem;
		overflow-wrap: anywhere;
	}
	.reason {
		font-size: 0.72rem;
		line-height: 1.4;
		color: var(--lq-warn);
	}
	.note {
		font-size: 0.72rem;
		line-height: 1.4;
		color: var(--lq-accent);
	}
	.link {
		margin-top: 0.4rem;
		background: none;
		border: 0;
		padding: 0.1rem 0;
		font-size: 0.75rem;
		color: var(--lq-accent);
		text-decoration: underline;
		cursor: pointer;
	}
	.link:disabled {
		opacity: 0.5;
		cursor: default;
	}
</style>
