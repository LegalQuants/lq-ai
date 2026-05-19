<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { page } from '$app/stores';

	import { getPlaybook, getPlaybookExecution } from '$lib/lq-ai/api/playbooks';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import PlaybookDisclaimerBanner from '$lib/lq-ai/components/PlaybookDisclaimerBanner.svelte';
	import type { Playbook, PlaybookExecution } from '$lib/lq-ai/types';

	import {
		severityClass,
		severityLabel,
		outcomeClass,
		outcomeLabel,
		filterPositions,
		type SeverityFilter,
		type OutcomeFilter
	} from './page-helpers';

	let execution: PlaybookExecution | null = null;
	let playbook: Playbook | null = null;
	let loading = true;
	let loadError: string | null = null;

	let expanded = new Set<string>();
	let severityFilter: SeverityFilter = 'all';
	let outcomeFilter: OutcomeFilter = 'all';

	let pollTimer: ReturnType<typeof setTimeout> | null = null;

	$: executionId = $page.params.id;
	$: positions = execution?.results?.positions ?? [];
	$: filteredPositions = filterPositions(positions, severityFilter, outcomeFilter);
	$: summary = execution?.results?.summary ?? {
		matches_standard: 0,
		matches_fallback: 0,
		deviates: 0,
		missing: 0
	};

	async function loadOnce(): Promise<void> {
		if (!executionId) return;
		loadError = null;
		try {
			const exec = await getPlaybookExecution(executionId);
			execution = exec;
			if (playbook === null) {
				playbook = await getPlaybook(exec.playbook_id);
			}
			scheduleNextPoll();
		} catch (err) {
			loadError = err instanceof LQAIApiError ? err.message : 'Failed to load execution.';
		} finally {
			loading = false;
		}
	}

	function scheduleNextPoll(): void {
		if (!execution) return;
		const terminal = execution.status === 'completed' || execution.status === 'error';
		if (terminal) {
			if (pollTimer) clearTimeout(pollTimer);
			pollTimer = null;
			return;
		}
		if (pollTimer) clearTimeout(pollTimer);
		pollTimer = setTimeout(loadOnce, 3000);
	}

	function toggleExpand(positionId: string): void {
		if (expanded.has(positionId)) expanded.delete(positionId);
		else expanded.add(positionId);
		expanded = new Set(expanded);
	}

	onMount(loadOnce);
	onDestroy(() => {
		if (pollTimer) clearTimeout(pollTimer);
	});
</script>

<svelte:head>
	<title>Playbook execution · LQ.AI</title>
</svelte:head>

<section class="lq-pbx-page">
	{#if loading && !execution}
		<div class="lq-pbx-page__state" data-testid="lq-pbx-loading">Loading…</div>
	{:else if loadError && !execution}
		<div class="lq-pbx-page__error" role="alert" data-testid="lq-pbx-error">{loadError}</div>
	{:else if execution}
		<header class="lq-pbx-page__header">
			<div>
				<h1>{playbook?.name ?? 'Playbook execution'}</h1>
				<p class="lq-pbx-page__sub">
					Status: <span
						class="lq-pbx-status lq-pbx-status--{execution.status}"
						data-testid="lq-pbx-status">{execution.status}</span
					>
					{#if execution.completed_at}
						· completed {new Date(execution.completed_at).toLocaleString()}
					{:else}
						· started {new Date(execution.created_at).toLocaleString()}
					{/if}
				</p>
			</div>
		</header>

		<PlaybookDisclaimerBanner />

		{#if execution.status === 'error'}
			<div class="lq-pbx-page__error" role="alert" data-testid="lq-pbx-execution-error">
				Execution failed: {execution.error ?? 'unknown error'}
			</div>
		{:else if execution.status === 'pending' || execution.status === 'running'}
			<div class="lq-pbx-page__state" data-testid="lq-pbx-running">
				Playbook is {execution.status}. Refreshing every 3 seconds…
			</div>
		{:else if execution.status === 'completed' && execution.results}
			<aside class="lq-pbx-summary" data-testid="lq-pbx-summary">
				<div class="lq-pbx-summary__item">
					<div class="lq-pbx-summary__count">{summary.matches_standard}</div>
					<div class="lq-pbx-summary__label">Matches standard</div>
				</div>
				<div class="lq-pbx-summary__item">
					<div class="lq-pbx-summary__count">{summary.matches_fallback}</div>
					<div class="lq-pbx-summary__label">Matches fallback</div>
				</div>
				<div class="lq-pbx-summary__item">
					<div class="lq-pbx-summary__count">{summary.deviates}</div>
					<div class="lq-pbx-summary__label">Deviates</div>
				</div>
				<div class="lq-pbx-summary__item">
					<div class="lq-pbx-summary__count">{summary.missing}</div>
					<div class="lq-pbx-summary__label">Missing</div>
				</div>
			</aside>

			<div class="lq-pbx-filters" data-testid="lq-pbx-filters">
				<label>
					Severity:
					<select bind:value={severityFilter} data-testid="lq-pbx-filter-severity">
						<option value="all">All</option>
						<option value="critical">Critical</option>
						<option value="high">High</option>
						<option value="medium">Medium</option>
						<option value="low">Low</option>
					</select>
				</label>
				<label>
					Outcome:
					<select bind:value={outcomeFilter} data-testid="lq-pbx-filter-outcome">
						<option value="all">All</option>
						<option value="matches_standard">Matches standard</option>
						<option value="matches_fallback">Matches fallback</option>
						<option value="deviates">Deviates</option>
						<option value="missing">Missing</option>
					</select>
				</label>
				<div class="lq-pbx-filters__count">
					{filteredPositions.length} of {positions.length} positions
				</div>
			</div>

			<table class="lq-pbx-table" data-testid="lq-pbx-table">
				<thead>
					<tr>
						<th class="lq-pbx-table__chev" scope="col">&nbsp;</th>
						<th scope="col">Severity</th>
						<th scope="col">Issue</th>
						<th scope="col">Outcome</th>
						<th scope="col">Citations</th>
					</tr>
				</thead>
				<tbody>
					{#each filteredPositions as pos (pos.position_id)}
						{@const isOpen = expanded.has(pos.position_id)}
						<tr
							class="lq-pbx-row"
							class:lq-pbx-row--open={isOpen}
							data-testid="lq-pbx-row"
							data-position-id={pos.position_id}
						>
							<td class="lq-pbx-table__chev">
								<button
									type="button"
									class="lq-pbx-chev-btn"
									aria-expanded={isOpen}
									aria-controls={`lq-pbx-detail-${pos.position_id}`}
									on:click={() => toggleExpand(pos.position_id)}
								>
									{isOpen ? '▼' : '▶'}
								</button>
							</td>
							<td>
								<span class="lq-severity-pill {severityClass(pos.severity_if_missing)}">
									{severityLabel(pos.severity_if_missing)}
								</span>
							</td>
							<td class="lq-pbx-table__issue">{pos.issue}</td>
							<td>
								<span class="lq-outcome-pill {outcomeClass(pos.verdict)}">
									{outcomeLabel(pos.verdict)}
								</span>
							</td>
							<td>{pos.cited_chunk_ids.length}</td>
						</tr>
						{#if isOpen}
							<tr id={`lq-pbx-detail-${pos.position_id}`} class="lq-pbx-detail-row">
								<td colspan="5">
									<div class="lq-pbx-detail">
										<div class="lq-pbx-detail__field">
											<div class="lq-pbx-detail__label">Confidence</div>
											<div>{(pos.confidence * 100).toFixed(0)}%</div>
										</div>
										{#if pos.matched_text}
											<div class="lq-pbx-detail__field">
												<div class="lq-pbx-detail__label">Contract clause</div>
												<blockquote class="lq-pbx-detail__quote">{pos.matched_text}</blockquote>
											</div>
										{/if}
										<div class="lq-pbx-detail__field">
											<div class="lq-pbx-detail__label">Justification</div>
											<div>{pos.justification}</div>
										</div>
										{#if pos.redline}
											<div class="lq-pbx-detail__field lq-pbx-detail__redline">
												<div class="lq-pbx-detail__label">Suggested redline</div>
												<div class="lq-pbx-detail__redline-old">{pos.redline.old_text}</div>
												<div class="lq-pbx-detail__redline-new">{pos.redline.new_text}</div>
												<div class="lq-pbx-detail__redline-just">
													{pos.redline.justification}
												</div>
											</div>
										{/if}
										{#if pos.cited_chunk_ids.length > 0}
											<div class="lq-pbx-detail__field">
												<div class="lq-pbx-detail__label">Cited chunks</div>
												<div class="lq-pbx-detail__chunks">
													{#each pos.cited_chunk_ids as chunkId (chunkId)}
														<code class="lq-pbx-detail__chunk-id">{chunkId}</code>
													{/each}
												</div>
											</div>
										{/if}
									</div>
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		{/if}
	{/if}
</section>

<style>
	.lq-pbx-page {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
		max-width: 80rem;
		margin: 0 auto;
		padding: 1.5rem;
	}
	.lq-pbx-page__header h1 {
		margin: 0 0 0.25rem;
		font-size: 1.5rem;
	}
	.lq-pbx-page__sub {
		margin: 0;
		color: var(--lq-text-secondary);
		font-size: 0.875rem;
	}
	.lq-pbx-page__state,
	.lq-pbx-page__error {
		padding: 1.5rem;
		text-align: center;
		background: var(--lq-inset);
		border-radius: 0.5rem;
		color: var(--lq-text-secondary);
	}
	.lq-pbx-page__error {
		color: var(--lq-error);
		background: var(--lq-error-soft, var(--lq-inset));
		border: 1px solid var(--lq-error-border, var(--lq-border));
	}

	.lq-pbx-status {
		display: inline-block;
		padding: 0.125rem 0.5rem;
		border-radius: 9999px;
		font-size: 0.75rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.lq-pbx-status--pending,
	.lq-pbx-status--running {
		background: var(--lq-warn-soft, var(--lq-inset));
		color: var(--lq-warn, var(--lq-text-secondary));
	}
	.lq-pbx-status--completed {
		background: var(--lq-accent-soft, var(--lq-inset));
		color: var(--lq-accent);
	}
	.lq-pbx-status--error {
		background: var(--lq-error-soft, var(--lq-inset));
		color: var(--lq-error);
	}

	.lq-pbx-summary {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 0.75rem;
	}
	.lq-pbx-summary__item {
		padding: 0.875rem 1rem;
		background: var(--lq-inset);
		border-radius: 0.5rem;
		text-align: center;
	}
	.lq-pbx-summary__count {
		font-size: 1.5rem;
		font-weight: 600;
	}
	.lq-pbx-summary__label {
		font-size: 0.8125rem;
		color: var(--lq-text-secondary);
	}

	.lq-pbx-filters {
		display: flex;
		gap: 1rem;
		align-items: center;
		padding: 0.625rem 0.875rem;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 0.5rem;
		font-size: 0.875rem;
	}
	.lq-pbx-filters label {
		display: inline-flex;
		gap: 0.375rem;
		align-items: center;
	}
	.lq-pbx-filters select {
		padding: 0.25rem 0.5rem;
		border: 1px solid var(--lq-border);
		border-radius: 0.375rem;
		background: var(--lq-surface);
		font-size: 0.875rem;
	}
	.lq-pbx-filters__count {
		margin-left: auto;
		color: var(--lq-text-secondary);
	}

	.lq-pbx-table {
		width: 100%;
		border-collapse: collapse;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 0.5rem;
		overflow: hidden;
	}
	.lq-pbx-table th,
	.lq-pbx-table td {
		padding: 0.625rem 0.875rem;
		text-align: left;
		border-bottom: 1px solid var(--lq-border);
		font-size: 0.875rem;
	}
	.lq-pbx-table__chev {
		width: 2rem;
		text-align: center;
	}
	.lq-pbx-table__issue {
		font-weight: 500;
	}
	.lq-pbx-chev-btn {
		background: none;
		border: none;
		cursor: pointer;
		color: var(--lq-text-secondary);
		font-size: 0.875rem;
	}
	.lq-pbx-detail-row td {
		background: var(--lq-inset);
		padding: 1rem;
	}
	.lq-pbx-detail {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}
	.lq-pbx-detail__field {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	.lq-pbx-detail__label {
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--lq-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.lq-pbx-detail__quote {
		margin: 0;
		padding: 0.5rem 0.75rem;
		border-left: 3px solid var(--lq-border);
		background: var(--lq-surface);
		font-style: italic;
	}
	.lq-pbx-detail__redline-old {
		text-decoration: line-through;
		color: var(--lq-error);
	}
	.lq-pbx-detail__redline-new {
		color: var(--lq-accent);
	}
	.lq-pbx-detail__redline-just {
		margin-top: 0.25rem;
		font-size: 0.8125rem;
		color: var(--lq-text-secondary);
	}
	.lq-pbx-detail__chunks {
		display: flex;
		flex-wrap: wrap;
		gap: 0.375rem;
	}
	.lq-pbx-detail__chunk-id {
		font-size: 0.75rem;
		padding: 0.125rem 0.375rem;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 0.25rem;
	}

	/* Severity pills — match the existing --lq-* token palette */
	.lq-severity-pill {
		display: inline-block;
		padding: 0.125rem 0.5rem;
		border-radius: 9999px;
		font-size: 0.75rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.lq-severity--critical {
		background: var(--lq-error-soft, var(--lq-inset));
		color: var(--lq-error);
		border: 1px solid var(--lq-error-border, transparent);
	}
	.lq-severity--high {
		background: var(--lq-warn-soft, var(--lq-inset));
		color: var(--lq-warn);
		border: 1px solid var(--lq-warn-border, transparent);
	}
	.lq-severity--medium {
		background: var(--lq-inset);
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
	}
	.lq-severity--low {
		background: var(--lq-inset);
		color: var(--lq-text-tertiary, var(--lq-text-secondary));
		border: 1px solid var(--lq-border);
	}

	/* Outcome pills */
	.lq-outcome-pill {
		display: inline-block;
		padding: 0.125rem 0.5rem;
		border-radius: 9999px;
		font-size: 0.75rem;
		font-weight: 500;
	}
	.lq-outcome--matches-standard {
		background: var(--lq-accent-soft, var(--lq-inset));
		color: var(--lq-accent);
	}
	.lq-outcome--matches-fallback {
		background: var(--lq-inset);
		color: var(--lq-text-secondary);
	}
	.lq-outcome--deviates {
		background: var(--lq-warn-soft, var(--lq-inset));
		color: var(--lq-warn);
	}
	.lq-outcome--missing {
		background: var(--lq-error-soft, var(--lq-inset));
		color: var(--lq-error);
	}
</style>
