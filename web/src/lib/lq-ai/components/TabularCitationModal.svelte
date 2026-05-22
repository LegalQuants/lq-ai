<script lang="ts">
	/**
	 * Citation modal for a tabular grid cell — M3-C3 sub-phase 4.
	 *
	 * Decision C-2 said "reuse the existing M2-C2 citation drawer" but
	 * that drawer doesn't actually exist in the codebase — M2-C2 only
	 * ships a chip-list with tooltips (`M2Citations.svelte`) wired to
	 * chat content markers. Tabular cells need a different surface
	 * because the citation list is data-bound (no inline content
	 * markers to find), so M3-C3 introduces this purpose-built modal:
	 * a small popover showing the cell value + confidence + error
	 * (if any) + the citations attached to the cell.
	 *
	 * Per session-start AskUserQuestion (Cell citations decision).
	 */
	import { createEventDispatcher } from 'svelte';

	import type { TabularCellResult } from '$lib/lq-ai/types';

	export let documentName: string;
	export let columnName: string;
	export let cell: TabularCellResult;

	const dispatch = createEventDispatcher<{ close: void }>();

	function close(): void {
		dispatch('close');
	}

	function handleBackdropKey(e: KeyboardEvent): void {
		if (e.key === 'Escape') close();
	}
</script>

<svelte:window on:keydown={handleBackdropKey} />

<div class="lq-tabcm__backdrop" on:click={close} on:keydown role="presentation">
	<!-- Dialog content stops propagation so clicks inside don't close. -->
	<div
		class="lq-tabcm"
		role="dialog"
		aria-modal="true"
		aria-labelledby="lq-tabcm-title"
		tabindex="-1"
		data-testid="lq-tabcm"
		on:click|stopPropagation
		on:keydown|stopPropagation
	>
		<header class="lq-tabcm__header">
			<div>
				<div class="lq-tabcm__column" id="lq-tabcm-title">{columnName}</div>
				<div class="lq-tabcm__document">{documentName}</div>
			</div>
			<button
				type="button"
				class="lq-tabcm__close"
				data-testid="lq-tabcm-close"
				on:click={close}
				aria-label="Close citations">×</button
			>
		</header>

		<section class="lq-tabcm__body">
			{#if cell.confidence === 'failed'}
				<p class="lq-tabcm__failed">
					<strong>Not found.</strong> Extraction failed for this cell.
				</p>
				{#if cell.error}
					<pre class="lq-tabcm__error" data-testid="lq-tabcm-error">{cell.error}</pre>
				{/if}
			{:else}
				<dl class="lq-tabcm__meta">
					<div>
						<dt>Value</dt>
						<dd data-testid="lq-tabcm-value">{cell.value ?? '—'}</dd>
					</div>
					<div>
						<dt>Confidence</dt>
						<dd data-confidence={cell.confidence}>{cell.confidence}</dd>
					</div>
					{#if cell.tier_used !== null && cell.tier_used !== undefined}
						<div>
							<dt>Tier</dt>
							<dd>Tier {cell.tier_used}</dd>
						</div>
					{/if}
				</dl>
			{/if}

			<h3 class="lq-tabcm__cite-header">Citations</h3>
			{#if cell.citations.length === 0}
				<p class="lq-tabcm__empty">
					{cell.confidence === 'failed'
						? 'The cell errored before producing a citation.'
						: 'No citations were attached to this cell.'}
				</p>
			{:else}
				<ul class="lq-tabcm__cites" data-testid="lq-tabcm-citations">
					{#each cell.citations as cite (cite.citation_id)}
						<li class="lq-tabcm__cite" data-confidence={cite.confidence}>
							<div class="lq-tabcm__cite-id">
								<span class="lq-tabcm__cite-chip" data-confidence={cite.confidence}
									>{cite.confidence}</span
								>
								<code>{cite.citation_id}</code>
							</div>
							<div class="lq-tabcm__cite-meta">
								<span>Document: <code>{cite.document_id}</code></span>
								{#if cite.chunk_id}
									<span>· Chunk: <code>{cite.chunk_id}</code></span>
								{/if}
							</div>
						</li>
					{/each}
				</ul>
			{/if}
		</section>
	</div>
</div>

<style>
	.lq-tabcm__backdrop {
		position: fixed;
		inset: 0;
		background: rgba(15, 23, 42, 0.55);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
		padding: 1.5rem;
	}
	.lq-tabcm {
		max-width: 36rem;
		width: 100%;
		max-height: calc(100vh - 3rem);
		overflow-y: auto;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 0.5rem;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
	}
	.lq-tabcm__header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		padding: 1rem 1.25rem;
		border-bottom: 1px solid var(--lq-border);
	}
	.lq-tabcm__column {
		font-weight: 600;
		font-size: 1rem;
	}
	.lq-tabcm__document {
		font-size: 0.8125rem;
		color: var(--lq-text-secondary);
		margin-top: 0.25rem;
	}
	.lq-tabcm__close {
		background: none;
		border: none;
		font-size: 1.5rem;
		color: var(--lq-text-secondary);
		cursor: pointer;
		line-height: 1;
		padding: 0;
	}
	.lq-tabcm__body {
		padding: 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}
	.lq-tabcm__failed {
		padding: 0.75rem 1rem;
		background: var(--lq-warning-soft, #fef3c7);
		border: 1px solid var(--lq-warning-border, var(--lq-border));
		border-radius: 0.375rem;
		margin: 0;
	}
	.lq-tabcm__error {
		margin: 0.5rem 0 0;
		padding: 0.5rem 0.75rem;
		background: var(--lq-inset);
		border-radius: 0.25rem;
		font-size: 0.8125rem;
		white-space: pre-wrap;
		max-height: 8rem;
		overflow: auto;
	}
	.lq-tabcm__meta {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 0.75rem;
		margin: 0;
	}
	.lq-tabcm__meta dt {
		font-size: 0.6875rem;
		color: var(--lq-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.lq-tabcm__meta dd {
		margin: 0.25rem 0 0;
		font-size: 0.875rem;
		font-weight: 500;
	}
	.lq-tabcm__cite-header {
		margin: 0;
		font-size: 0.875rem;
		text-transform: uppercase;
		color: var(--lq-text-secondary);
		letter-spacing: 0.04em;
	}
	.lq-tabcm__empty {
		margin: 0;
		color: var(--lq-text-secondary);
		font-size: 0.875rem;
	}
	.lq-tabcm__cites {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.lq-tabcm__cite {
		padding: 0.5rem 0.75rem;
		border: 1px solid var(--lq-border);
		border-radius: 0.375rem;
		background: var(--lq-inset);
	}
	.lq-tabcm__cite-id {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-size: 0.8125rem;
	}
	.lq-tabcm__cite-chip {
		padding: 0.0625rem 0.375rem;
		border-radius: 999px;
		font-size: 0.6875rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.02em;
		background: var(--lq-surface);
	}
	.lq-tabcm__cite-meta {
		display: flex;
		gap: 0.5rem;
		flex-wrap: wrap;
		margin-top: 0.25rem;
		font-size: 0.75rem;
		color: var(--lq-text-secondary);
	}
	.lq-tabcm__cite-meta code,
	.lq-tabcm__cite-id code {
		font-family: 'Menlo', 'Monaco', monospace;
	}
</style>
