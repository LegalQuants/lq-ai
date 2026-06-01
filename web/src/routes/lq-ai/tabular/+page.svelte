<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	import { listTabularExecutions } from '$lib/lq-ai/api/tabular';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import type { TabularExecutionSummary } from '$lib/lq-ai/types';

	import {
		sortTabularExecutionsByCreatedDesc,
		formatTabularStatus,
		formatCellCount,
		formatCostUsd,
		skillNameDisplay
	} from './page-helpers';

	let executions: TabularExecutionSummary[] = [];
	let loading = false;
	let listError: string | null = null;

	async function load(): Promise<void> {
		loading = true;
		listError = null;
		try {
			const fetched = await listTabularExecutions();
			executions = sortTabularExecutionsByCreatedDesc(fetched);
		} catch (err) {
			listError = err instanceof LQAIApiError ? err.message : 'Failed to load tabular executions.';
		} finally {
			loading = false;
		}
	}

	function open(id: string): void {
		goto(`/lq-ai/tabular/${id}`);
	}

	function startNew(): void {
		goto('/lq-ai/tabular/new');
	}

	function formatCreatedAt(iso: string): string {
		// e.g. "May 22, 2026 · 3:00 PM" — short and locale-aware.
		const d = new Date(iso);
		if (Number.isNaN(d.getTime())) return iso;
		const date = d.toLocaleDateString(undefined, {
			year: 'numeric',
			month: 'short',
			day: 'numeric'
		});
		const time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
		return `${date} · ${time}`;
	}

	function costColumn(row: TabularExecutionSummary): string {
		return row.status === 'completed'
			? formatCostUsd(row.cost_actual_usd)
			: formatCostUsd(row.cost_estimate_usd);
	}

	onMount(load);
</script>

<svelte:head>
	<title>Tabular Review · LQ.AI</title>
</svelte:head>

<section class="lq-tabular-page">
	<header class="lq-tabular-page__header">
		<div class="lq-tabular-page__heading">
			<h1>Tabular Review</h1>
			<button
				type="button"
				class="lq-tabular-page__cta"
				data-testid="lq-tabular-new-cta"
				on:click={startNew}
			>
				Start new tabular review
			</button>
		</div>
		<p class="lq-tabular-page__subtitle">
			Run a table-mode skill or an ad-hoc column spec across multiple documents. Each cell is
			grounded by source-chunk references; click any cell in the result view to see the source
			passage.
		</p>
	</header>

	{#if loading}
		<div class="lq-tabular-page__state" data-testid="lq-tabular-loading">Loading…</div>
	{:else if listError}
		<div class="lq-tabular-page__error" role="alert" data-testid="lq-tabular-error">
			{listError}
		</div>
	{:else if executions.length === 0}
		<div class="lq-tabular-page__empty" data-testid="lq-tabular-empty">
			<p class="lq-tabular-page__empty-title">No tabular reviews yet.</p>
			<p class="lq-tabular-page__empty-body">
				Start your first one by selecting a set of documents and choosing a column spec — either
				from a saved table-mode skill or by typing the columns inline.
			</p>
		</div>
	{:else}
		<table class="lq-tabular-table" data-testid="lq-tabular-table">
			<thead>
				<tr>
					<th scope="col">Skill</th>
					<th scope="col" class="lq-tabular-table__compact">Scope</th>
					<th scope="col" class="lq-tabular-table__compact">Cost</th>
					<th scope="col" class="lq-tabular-table__compact">Status</th>
					<th scope="col" class="lq-tabular-table__compact">Created</th>
				</tr>
			</thead>
			<tbody>
				{#each executions as row (row.id)}
					<tr
						data-testid="lq-tabular-row"
						data-execution-id={row.id}
						on:click={() => open(row.id)}
						on:keydown={(e) => {
							if (e.key === 'Enter' || e.key === ' ') {
								e.preventDefault();
								open(row.id);
							}
						}}
						tabindex="0"
						role="link"
					>
						<td class="lq-tabular-table__skill">{skillNameDisplay(row.skill_name)}</td>
						<td class="lq-tabular-table__compact"
							>{formatCellCount(row.document_count, row.column_count)}</td
						>
						<td class="lq-tabular-table__compact">{costColumn(row)}</td>
						<td class="lq-tabular-table__compact">
							<span
								class="lq-tabular-table__status"
								data-status={row.status}
								data-testid="lq-tabular-row-status"
							>
								{formatTabularStatus(row.status)}
							</span>
						</td>
						<td class="lq-tabular-table__compact">{formatCreatedAt(row.created_at)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</section>

<style>
	.lq-tabular-page {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
		max-width: 64rem;
		margin: 0 auto;
		padding: 1.5rem;
	}
	.lq-tabular-page__heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
		margin-bottom: 0.5rem;
	}
	.lq-tabular-page__header h1 {
		margin: 0;
		font-size: 1.5rem;
	}
	.lq-tabular-page__cta {
		padding: 0.5rem 0.875rem;
		background: var(--lq-accent, #4f46e5);
		color: var(--lq-on-accent, #ffffff);
		border: none;
		border-radius: 0.375rem;
		font-size: 0.875rem;
		font-weight: 500;
		cursor: pointer;
	}
	.lq-tabular-page__cta:hover {
		opacity: 0.9;
	}
	.lq-tabular-page__subtitle {
		margin: 0;
		color: var(--lq-text-secondary);
	}
	.lq-tabular-page__state,
	.lq-tabular-page__error,
	.lq-tabular-page__empty {
		padding: 1.5rem;
		text-align: center;
		color: var(--lq-text-secondary);
		background: var(--lq-inset);
		border-radius: 0.5rem;
	}
	.lq-tabular-page__error {
		color: var(--lq-error);
		background: var(--lq-error-soft, var(--lq-inset));
		border: 1px solid var(--lq-error-border, var(--lq-border));
	}
	.lq-tabular-page__empty-title {
		margin: 0 0 0.5rem;
		font-weight: 600;
		color: var(--lq-text);
	}
	.lq-tabular-page__empty-body {
		margin: 0;
	}
	.lq-tabular-table {
		width: 100%;
		border-collapse: collapse;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 0.5rem;
		overflow: hidden;
	}
	.lq-tabular-table th,
	.lq-tabular-table td {
		padding: 0.75rem 1rem;
		text-align: left;
		border-bottom: 1px solid var(--lq-border);
	}
	.lq-tabular-table tbody tr {
		cursor: pointer;
	}
	.lq-tabular-table tbody tr:hover {
		background: var(--lq-inset);
	}
	.lq-tabular-table tbody tr:last-child td {
		border-bottom: none;
	}
	.lq-tabular-table__skill {
		font-weight: 600;
	}
	.lq-tabular-table__compact {
		width: 1%;
		white-space: nowrap;
		vertical-align: top;
	}
	.lq-tabular-table__status {
		display: inline-block;
		padding: 0.125rem 0.5rem;
		border-radius: 999px;
		font-size: 0.8125rem;
		font-weight: 500;
		background: var(--lq-inset);
	}
	.lq-tabular-table__status[data-status='completed'] {
		background: var(--lq-success-soft, var(--lq-inset));
		color: var(--lq-success, inherit);
	}
	.lq-tabular-table__status[data-status='failed'] {
		background: var(--lq-error-soft, var(--lq-inset));
		color: var(--lq-error, inherit);
	}
	.lq-tabular-table__status[data-status='cancelled'] {
		background: var(--lq-inset);
		color: var(--lq-text-secondary);
	}
	.lq-tabular-table__status[data-status='running'],
	.lq-tabular-table__status[data-status='pending'] {
		background: var(--lq-warning-soft, var(--lq-inset));
		color: var(--lq-warning, inherit);
	}
</style>
