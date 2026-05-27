<script lang="ts">
	/**
	 * /lq-ai/autonomous — M4-C2 Sessions list page.
	 *
	 * Rail landing page: surfaces all autonomous sessions newest-first.
	 * Each row links to /lq-ai/autonomous/sessions/{id} (the receipt page,
	 * Task 11). Running sessions expose an inline Halt button.
	 *
	 * Mirrors the structure of admin/intake-bridges/+page.svelte:
	 *   - onMount(load)
	 *   - load() calls the API client, sets sessions/loading/listError
	 *   - action functions confirm→call→reload with actionError/actionSuccess
	 *   - LQAIApiError for typed error handling
	 */
	import { onMount } from 'svelte';

	import { autonomousApi } from '$lib/lq-ai/api';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import type { AutonomousSessionRead } from '$lib/lq-ai/api/autonomous';
	import { formatCost, formatCreatedAt, isHaltable, statusPillClass } from './page-helpers';

	let sessions: AutonomousSessionRead[] = [];
	let loading = false;
	let listError: string | null = null;
	let actionError: string | null = null;
	let actionSuccess: string | null = null;
	let pendingHaltId: string | null = null;

	onMount(load);

	async function load(): Promise<void> {
		loading = true;
		listError = null;
		try {
			const resp = await autonomousApi.listSessions();
			sessions = resp.sessions;
		} catch (err) {
			if (err instanceof LQAIApiError && err.status === 403) {
				listError = 'You need to enable autonomous mode to view sessions.';
			} else {
				listError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			loading = false;
		}
	}

	async function haltSession(session: AutonomousSessionRead): Promise<void> {
		const confirmed = confirm(
			`Halt session "${session.id.slice(0, 8)}…" (${session.trigger_kind}, ${session.current_phase})? ` +
				`The agent will stop at the next safe checkpoint. This action is idempotent — ` +
				`sending halt to an already-halted session is harmless.`
		);
		if (!confirmed) return;
		pendingHaltId = session.id;
		actionError = null;
		actionSuccess = null;
		try {
			await autonomousApi.haltSession(session.id);
			actionSuccess = `Halt requested for session ${session.id.slice(0, 8)}….`;
			await load();
		} catch (err) {
			if (err instanceof LQAIApiError) {
				actionError = `Halt failed (${err.status}): ${err.message}`;
			} else {
				actionError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			pendingHaltId = null;
		}
	}
</script>

<div class="sessions-page">
	<header class="page-header">
		<h1 class="lq-text-page-h">Autonomous sessions</h1>
		<p class="page-intro">
			Audit what LQVern did — every autonomous run, its cost, current phase, and terminal state.
			Running sessions can be halted inline. Select a row to view the full receipt.
		</p>
	</header>

	{#if listError}
		<div class="error-banner" role="alert">{listError}</div>
	{/if}
	{#if actionError}
		<div class="error-banner" role="alert">{actionError}</div>
	{/if}
	{#if actionSuccess}
		<div class="success-banner" role="status">{actionSuccess}</div>
	{/if}

	{#if loading && sessions.length === 0}
		<p class="loading">Loading sessions…</p>
	{/if}

	{#if !loading && sessions.length === 0 && !listError}
		<p class="empty-state">No autonomous sessions yet.</p>
	{/if}

	{#if sessions.length > 0}
		<table class="sessions-table">
			<thead>
				<tr>
					<th>Status</th>
					<th>Trigger</th>
					<th>Phase</th>
					<th>Cost</th>
					<th>Started</th>
					<th class="sessions-table-actions">Actions</th>
				</tr>
			</thead>
			<tbody>
				{#each sessions as session (session.id)}
					<tr>
						<td>
							<span class="status-pill {statusPillClass(session.status)}">
								{session.status}
							</span>
						</td>
						<td>{session.trigger_kind}</td>
						<td>{session.current_phase}</td>
						<td class="cost-cell">
							{formatCost(session.cost_total_usd, session.max_cost_usd)}
						</td>
						<td class="date-cell">{formatCreatedAt(session.created_at)}</td>
						<td class="sessions-table-actions">
							<a href="/lq-ai/autonomous/sessions/{session.id}" class="action-link">
								View
							</a>
							{#if isHaltable(session.status)}
								<button
									type="button"
									class="action-button danger"
									on:click={() => haltSession(session)}
									disabled={pendingHaltId === session.id}
								>
									{pendingHaltId === session.id ? 'Halting…' : 'Halt'}
								</button>
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>

<style>
	.sessions-page {
		padding: var(--lq-space-5);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-5);
	}

	.page-header {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.page-intro {
		color: var(--lq-text-secondary);
		max-width: 60rem;
		font-size: 14px;
		line-height: 1.5;
	}

	.error-banner {
		padding: var(--lq-space-3) var(--lq-space-4);
		background: var(--lq-error-bg, #fee);
		color: var(--lq-error-text, #800);
		border-radius: 6px;
		border: 1px solid var(--lq-error-border, #fbb);
	}

	.success-banner {
		padding: var(--lq-space-3) var(--lq-space-4);
		background: var(--lq-success-bg, #efe);
		color: var(--lq-success-text, #060);
		border-radius: 6px;
		border: 1px solid var(--lq-success-border, #bfb);
	}

	.loading {
		color: var(--lq-text-secondary);
		padding: var(--lq-space-3);
	}

	.empty-state {
		color: var(--lq-text-secondary);
		font-style: italic;
		margin: 0;
	}

	.sessions-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 14px;
	}

	.sessions-table th,
	.sessions-table td {
		text-align: left;
		padding: var(--lq-space-2) var(--lq-space-3);
		border-bottom: 1px solid var(--lq-border);
	}

	.sessions-table th {
		font-weight: 600;
		color: var(--lq-text-secondary);
		font-size: 12px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.sessions-table-actions {
		text-align: right;
		width: 1px;
		white-space: nowrap;
	}

	/* Status pill */
	.status-pill {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 10px;
		font-size: 12px;
		font-weight: 500;
		text-transform: capitalize;
		white-space: nowrap;
	}

	.lq-status--running {
		background: var(--lq-info-bg, #e8f4fd);
		color: var(--lq-info-text, #0a5fa8);
		border: 1px solid var(--lq-info-border, #9ed3f5);
	}

	.lq-status--completed {
		background: var(--lq-success-bg, #efe);
		color: var(--lq-success-text, #060);
		border: 1px solid var(--lq-success-border, #bfb);
	}

	.lq-status--halted {
		background: var(--lq-warning-bg, #fff8e1);
		color: var(--lq-warning-text, #7a5a00);
		border: 1px solid var(--lq-warning-border, #ffe08a);
	}

	.lq-status--failed {
		background: var(--lq-error-bg, #fee);
		color: var(--lq-error-text, #800);
		border: 1px solid var(--lq-error-border, #fbb);
	}

	.cost-cell {
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}

	.date-cell {
		color: var(--lq-text-secondary);
		white-space: nowrap;
	}

	.action-link {
		display: inline-block;
		padding: var(--lq-space-1) var(--lq-space-3);
		border-radius: 6px;
		font-size: 13px;
		color: var(--lq-accent);
		text-decoration: none;
		border: 1px solid var(--lq-border);
	}

	.action-link:hover {
		background: var(--lq-surface-hover, rgba(0, 0, 0, 0.04));
	}

	.action-button {
		padding: var(--lq-space-1) var(--lq-space-3);
		border-radius: 6px;
		font-size: 13px;
		cursor: pointer;
		border: 1px solid var(--lq-border);
		background: transparent;
		color: var(--lq-text);
		margin-left: var(--lq-space-2);
	}

	.action-button.danger {
		color: var(--lq-error-text, #b00);
		border-color: var(--lq-error-border, #fbb);
	}

	.action-button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
