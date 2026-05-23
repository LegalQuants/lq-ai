<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';

	import { getTabularExecution, cancelTabularExecution } from '$lib/lq-ai/api/tabular';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import TabularGrid from '$lib/lq-ai/components/TabularGrid.svelte';
	import TabularCitationModal from '$lib/lq-ai/components/TabularCitationModal.svelte';
	import type {
		TabularCellResult,
		TabularExecution
	} from '$lib/lq-ai/types';

	import {
		isTerminalStatus,
		progressFraction,
		formatProgress,
		TABULAR_POLL_INTERVAL_MS
	} from './page-helpers';
	import { formatTabularStatus, formatCostUsd, skillNameDisplay } from '../page-helpers';

	let execution: TabularExecution | null = null;
	let loading = true;
	let loadError: string | null = null;
	let pollTimer: ReturnType<typeof setTimeout> | null = null;
	let cancelling = false;

	// Citation modal state.
	interface OpenCellState {
		documentName: string;
		columnName: string;
		cell: TabularCellResult;
	}
	let openCell: OpenCellState | null = null;

	$: executionId = $page.params.id;
	$: docCount = execution?.document_ids.length ?? 0;
	$: colCount = execution?.columns.length ?? 0;
	$: fraction = execution
		? progressFraction(execution.status, execution.results, docCount, colCount)
		: 0;
	// Map document_id -> document_name. Primary source: the parallel
	// `document_names` array on the execution (populated at every
	// response build by joining documents → files.filename) so the
	// grid renders human-readable headers from the moment the
	// execution is created, before any row is written. Falls back to
	// row.document_name (worker-written) for older executions that
	// pre-date the document_names field.
	$: documentNameById = (() => {
		const m: Record<string, string> = {};
		if (execution?.document_ids && execution?.document_names) {
			const ids = execution.document_ids;
			const names = execution.document_names;
			for (let i = 0; i < ids.length; i++) {
				if (names[i]) m[ids[i]] = names[i];
			}
		}
		for (const row of execution?.results?.rows ?? []) {
			if (!m[row.document_id]) m[row.document_id] = row.document_name;
		}
		return m;
	})();

	async function loadOnce(): Promise<void> {
		if (!executionId) return;
		loadError = null;
		try {
			const exec = await getTabularExecution(executionId);
			execution = exec;
			scheduleNextPoll();
		} catch (err) {
			loadError = err instanceof LQAIApiError ? err.message : 'Failed to load tabular execution.';
		} finally {
			loading = false;
		}
	}

	function scheduleNextPoll(): void {
		if (!execution) return;
		if (isTerminalStatus(execution.status)) {
			if (pollTimer) {
				clearTimeout(pollTimer);
				pollTimer = null;
			}
			return;
		}
		if (pollTimer) clearTimeout(pollTimer);
		pollTimer = setTimeout(loadOnce, TABULAR_POLL_INTERVAL_MS);
	}

	async function cancelRun(): Promise<void> {
		if (!execution || isTerminalStatus(execution.status)) return;
		cancelling = true;
		try {
			execution = await cancelTabularExecution(execution.id);
		} catch (err) {
			loadError = err instanceof LQAIApiError ? err.message : 'Failed to cancel.';
		} finally {
			cancelling = false;
		}
	}

	function handleCellOpen(event: CustomEvent<{
		documentId: string;
		documentName: string;
		columnName: string;
		cell: TabularCellResult | undefined;
	}>): void {
		const { documentName, columnName, cell } = event.detail;
		if (!cell) return;
		openCell = { documentName, columnName, cell };
	}

	function closeCellModal(): void {
		openCell = null;
	}

	onMount(loadOnce);
	onDestroy(() => {
		if (pollTimer) clearTimeout(pollTimer);
	});
</script>

<svelte:head>
	<title>Tabular result · LQ.AI</title>
</svelte:head>

<section class="lq-tabres">
	{#if loading && !execution}
		<div class="lq-tabres__state" data-testid="lq-tabres-loading">Loading…</div>
	{:else if loadError && !execution}
		<div class="lq-tabres__error" role="alert" data-testid="lq-tabres-error">{loadError}</div>
	{:else if execution}
		<header class="lq-tabres__header">
			<div>
				<h1>Tabular result</h1>
				<p class="lq-tabres__sub">
					<strong>{skillNameDisplay(execution.skill_name)}</strong>
					· {docCount} docs × {colCount} cols
				</p>
			</div>
			<div class="lq-tabres__actions">
				<button
					type="button"
					class="lq-tabres__rerun"
					data-testid="lq-tabres-rerun"
					on:click={() => goto('/lq-ai/tabular/new')}>Re-run as new execution</button
				>
			</div>
		</header>

		<!-- Status banner -->
		<div
			class="lq-tabres__banner"
			data-status={execution.status}
			data-testid="lq-tabres-banner"
		>
			<div class="lq-tabres__banner-row">
				<span class="lq-tabres__banner-label">Status:</span>
				<span class="lq-tabres__banner-status" data-testid="lq-tabres-status">
					{formatTabularStatus(execution.status)}
				</span>
				{#if !isTerminalStatus(execution.status)}
					<button
						type="button"
						class="lq-tabres__cancel"
						data-testid="lq-tabres-cancel"
						on:click={cancelRun}
						disabled={cancelling}
					>
						{cancelling ? 'Cancelling…' : 'Cancel'}
					</button>
				{/if}
				{#if execution.status === 'completed'}
					<span class="lq-tabres__banner-cost" data-testid="lq-tabres-cost">
						{formatCostUsd(execution.cost_actual_usd)} actual
						{#if execution.cost_estimate_usd}
							(est. {formatCostUsd(execution.cost_estimate_usd)})
						{/if}
					</span>
				{/if}
			</div>
			{#if !isTerminalStatus(execution.status)}
				<div
					class="lq-tabres__progress"
					data-testid="lq-tabres-progress"
					role="progressbar"
					aria-valuemin="0"
					aria-valuemax="100"
					aria-valuenow={Math.round(fraction * 100)}
				>
					<div class="lq-tabres__progress-bar" style="width: {fraction * 100}%"></div>
					<span class="lq-tabres__progress-text">{formatProgress(fraction)}</span>
				</div>
			{/if}
			{#if execution.error_text}
				<pre class="lq-tabres__banner-error" data-testid="lq-tabres-error-text"
					>{execution.error_text}</pre
				>
			{/if}
		</div>

		{#if execution.columns.length > 0 && execution.document_ids.length > 0}
			<TabularGrid
				results={execution.results}
				columns={execution.columns}
				documentIds={execution.document_ids}
				{documentNameById}
				on:open={handleCellOpen}
			/>
		{:else}
			<div class="lq-tabres__state">No grid to render (empty execution).</div>
		{/if}
	{/if}

	{#if openCell}
		<TabularCitationModal
			documentName={openCell.documentName}
			columnName={openCell.columnName}
			cell={openCell.cell}
			on:close={closeCellModal}
		/>
	{/if}
</section>

<style>
	.lq-tabres {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
		max-width: 80rem;
		margin: 0 auto;
		padding: 1.5rem;
	}
	.lq-tabres__header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1rem;
	}
	.lq-tabres__header h1 {
		margin: 0;
		font-size: 1.5rem;
	}
	.lq-tabres__sub {
		margin: 0.25rem 0 0;
		color: var(--lq-text-secondary);
		font-size: 0.875rem;
	}
	.lq-tabres__rerun {
		padding: 0.5rem 0.75rem;
		border: 1px solid var(--lq-border);
		border-radius: 0.375rem;
		background: var(--lq-surface);
		font-size: 0.875rem;
		cursor: pointer;
	}
	.lq-tabres__banner {
		padding: 0.875rem 1rem;
		background: var(--lq-inset);
		border-radius: 0.5rem;
		border: 1px solid var(--lq-border);
	}
	.lq-tabres__banner[data-status='completed'] {
		background: var(--lq-success-soft, var(--lq-inset));
		border-color: var(--lq-success-border, var(--lq-border));
	}
	.lq-tabres__banner[data-status='failed'] {
		background: var(--lq-error-soft, var(--lq-inset));
		border-color: var(--lq-error-border, var(--lq-border));
	}
	.lq-tabres__banner[data-status='cancelled'] {
		background: var(--lq-inset);
		border-color: var(--lq-border);
	}
	.lq-tabres__banner-row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}
	.lq-tabres__banner-label {
		font-size: 0.75rem;
		color: var(--lq-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.lq-tabres__banner-status {
		font-weight: 600;
	}
	.lq-tabres__banner-cost {
		margin-left: auto;
		font-size: 0.8125rem;
		color: var(--lq-text-secondary);
	}
	.lq-tabres__cancel {
		padding: 0.25rem 0.625rem;
		border: 1px solid var(--lq-border);
		border-radius: 0.25rem;
		background: var(--lq-surface);
		font-size: 0.75rem;
		cursor: pointer;
	}
	.lq-tabres__cancel:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.lq-tabres__progress {
		position: relative;
		height: 1.25rem;
		margin-top: 0.5rem;
		background: var(--lq-surface);
		border-radius: 999px;
		border: 1px solid var(--lq-border);
		overflow: hidden;
	}
	.lq-tabres__progress-bar {
		height: 100%;
		background: var(--lq-accent, #4f46e5);
		transition: width 0.3s ease-out;
	}
	.lq-tabres__progress-text {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--lq-text);
		mix-blend-mode: difference;
	}
	.lq-tabres__banner-error {
		margin: 0.625rem 0 0;
		padding: 0.5rem 0.75rem;
		background: var(--lq-surface);
		border-radius: 0.25rem;
		font-size: 0.8125rem;
		white-space: pre-wrap;
		max-height: 6rem;
		overflow: auto;
	}
	.lq-tabres__state {
		padding: 1.5rem;
		text-align: center;
		color: var(--lq-text-secondary);
		background: var(--lq-inset);
		border-radius: 0.5rem;
	}
	.lq-tabres__error {
		padding: 0.875rem;
		background: var(--lq-error-soft, var(--lq-inset));
		border: 1px solid var(--lq-error-border, var(--lq-border));
		border-radius: 0.375rem;
		color: var(--lq-error, inherit);
	}
</style>
