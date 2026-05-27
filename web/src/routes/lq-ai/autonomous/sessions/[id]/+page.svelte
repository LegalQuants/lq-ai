<script lang="ts">
	/**
	 * /lq-ai/autonomous/sessions/[id] — M4-C2 Session receipt page.
	 *
	 * The headline audit UX for LQVern: a chronological interleaved timeline of
	 * every phase transition and tool call that occurred during the session.
	 *
	 * The receipt is built server-side (build_receipt) and is privacy-safe by
	 * construction — it carries only ids / enums / costs / timestamps, never raw
	 * entity values. We render exactly what's there; no transformations needed.
	 *
	 * Architecture note (ADR 0013 D2): the web layer renders the receipt; it does
	 * NOT run the agent loop. SvelteKit only; no React.
	 *
	 * Pattern mirrors web/src/routes/lq-ai/playbook-executions/[id]/+page.svelte:
	 *   - $page.params.id reactive via $:
	 *   - onMount(load)
	 *   - load() → API call → loading / error states
	 *   - action functions: confirm → call → reload + banner
	 *   - LQAIApiError for typed error handling
	 */
	import { onMount } from 'svelte';
	import { page } from '$app/stores';

	import { autonomousApi } from '$lib/lq-ai/api';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import type { AutonomousSessionRead, SessionReceipt } from '$lib/lq-ai/api/autonomous';
	import { formatCost, isHaltable, statusPillClass } from '../../page-helpers';
	import { buildTimeline } from '$lib/lq-ai/autonomous/receipt-timeline';
	import type { TimelineNode } from '$lib/lq-ai/autonomous/receipt-timeline';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let session: AutonomousSessionRead | null = null;
	let receipt: SessionReceipt | null = null;
	let loading = false;
	let loadError: string | null = null;
	let actionError: string | null = null;
	let actionSuccess: string | null = null;
	let haltPending = false;

	// Reactive: re-load if the route param changes (e.g. browser back/forward).
	$: sessionId = $page.params.id;
	$: timeline = receipt ? buildTimeline(receipt) : ([] as TimelineNode[]);

	onMount(() => {
		load();
	});

	// ---------------------------------------------------------------------------
	// Data loading
	// ---------------------------------------------------------------------------

	async function load(): Promise<void> {
		if (!sessionId) return;
		loading = true;
		loadError = null;
		try {
			const detail = await autonomousApi.getSession(sessionId);
			session = detail.session;
			receipt = detail.receipt;
		} catch (err) {
			if (err instanceof LQAIApiError && err.status === 404) {
				loadError = 'Session not found.';
			} else if (err instanceof LQAIApiError && err.status === 403) {
				loadError = 'You need to enable autonomous mode to view this session.';
			} else {
				loadError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			loading = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Halt action
	// ---------------------------------------------------------------------------

	async function haltSession(): Promise<void> {
		if (!session) return;
		const confirmed = confirm(
			`Halt session "${session.id.slice(0, 8)}…" (${session.trigger_kind}, ${session.current_phase})? ` +
				`The agent will stop at the next safe checkpoint. This action is idempotent.`
		);
		if (!confirmed) return;
		haltPending = true;
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
			haltPending = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Timestamp formatting
	// ---------------------------------------------------------------------------

	function formatTimestamp(iso: string | null): string {
		if (!iso) return '—';
		const d = new Date(iso);
		if (Number.isNaN(d.getTime())) return iso;
		return d.toLocaleString();
	}
</script>

<svelte:head>
	<title>Session receipt · LQ.AI</title>
</svelte:head>

<div class="receipt-page">
	<!-- Back link -->
	<a href="/lq-ai/autonomous" class="back-link">← Autonomous sessions</a>

	<!-- Action banners -->
	{#if actionError}
		<div class="error-banner" role="alert">{actionError}</div>
	{/if}
	{#if actionSuccess}
		<div class="success-banner" role="status">{actionSuccess}</div>
	{/if}

	<!-- Loading / error states -->
	{#if loading && !session}
		<p class="state-message">Loading session…</p>
	{:else if loadError && !session}
		<div class="error-banner" role="alert">{loadError}</div>
	{:else if session && receipt}
		<!-- ------------------------------------------------------------------ -->
		<!-- Header                                                               -->
		<!-- ------------------------------------------------------------------ -->
		<header class="receipt-header">
			<div class="receipt-header-top">
				<h1 class="lq-text-page-h">Session receipt</h1>
				{#if isHaltable(session.status)}
					<button
						type="button"
						class="halt-button"
						on:click={haltSession}
						disabled={haltPending}
					>
						{haltPending ? 'Halting…' : 'Halt session'}
					</button>
				{/if}
			</div>

			<dl class="receipt-meta">
				<div class="receipt-meta-item">
					<dt>Status</dt>
					<dd>
						<span class="status-pill {statusPillClass(session.status)}">
							{session.status}
						</span>
					</dd>
				</div>
				<div class="receipt-meta-item">
					<dt>Trigger</dt>
					<dd>{receipt.trigger_kind ?? '—'}</dd>
				</div>
				<div class="receipt-meta-item">
					<dt>Current phase</dt>
					<dd>{receipt.current_phase ?? '—'}</dd>
				</div>
				<div class="receipt-meta-item">
					<dt>Cost</dt>
					<dd class="cost-value">
						{formatCost(receipt.cost_total_usd, receipt.max_cost_usd)}
						{#if receipt.cost_cap_reached}
							<span class="cap-badge">cap reached</span>
						{/if}
					</dd>
				</div>
				<div class="receipt-meta-item">
					<dt>Started</dt>
					<dd>{formatTimestamp(receipt.created_at)}</dd>
				</div>
				{#if receipt.completed_at}
					<div class="receipt-meta-item">
						<dt>Completed</dt>
						<dd>{formatTimestamp(receipt.completed_at)}</dd>
					</div>
				{/if}
				{#if receipt.terminal_reason}
					<div class="receipt-meta-item receipt-meta-item--full">
						<dt>Terminal reason</dt>
						<dd class="terminal-reason">{receipt.terminal_reason}</dd>
					</div>
				{/if}
			</dl>
		</header>

		<!-- ------------------------------------------------------------------ -->
		<!-- Timeline                                                             -->
		<!-- ------------------------------------------------------------------ -->
		<section class="timeline-section">
			<h2 class="timeline-heading">Activity timeline</h2>

			{#if timeline.length === 0}
				<p class="empty-state">No activity recorded yet.</p>
			{:else}
				<ol class="timeline">
					{#each timeline as node, i (i)}
						{#if node.kind === 'phase'}
							<!-- Phase transition marker -->
							<li class="timeline-node timeline-node--phase">
								<span class="timeline-marker timeline-marker--phase" aria-hidden="true"></span>
								<div class="timeline-content">
									<span class="timeline-label">Phase: {node.phase ?? '(unknown)'}</span>
									<span class="timeline-time">{formatTimestamp(node.at)}</span>
								</div>
							</li>
						{:else}
							<!-- Tool call — expandable -->
							<li class="timeline-node timeline-node--tool">
								<span class="timeline-marker timeline-marker--tool" aria-hidden="true"></span>
								<div class="timeline-content">
									<details class="tool-details">
										<summary class="tool-summary">
											<span class="tool-name">{node.tool ?? '(unknown tool)'}</span>
											<span class="timeline-time">{formatTimestamp(node.at)}</span>
										</summary>
										<dl class="tool-detail-list">
											<div class="tool-detail-row">
												<dt>Outcome</dt>
												<dd>{node.outcome ?? '—'}</dd>
											</div>
											{#if node.cost_usd !== undefined}
												<div class="tool-detail-row">
													<dt>Cost</dt>
													<dd class="cost-value">${node.cost_usd.toFixed(4)}</dd>
												</div>
											{/if}
											<div class="tool-detail-row">
												<dt>Timestamp</dt>
												<dd>{formatTimestamp(node.at)}</dd>
											</div>
										</dl>
									</details>
								</div>
							</li>
						{/if}
					{/each}

					<!-- Terminal state as the final node (if present) -->
					{#if receipt.terminal_reason}
						<li class="timeline-node timeline-node--terminal">
							<span class="timeline-marker timeline-marker--terminal" aria-hidden="true"></span>
							<div class="timeline-content">
								<span class="timeline-label timeline-label--terminal">
									Ended: {receipt.terminal_reason}
								</span>
								<span class="timeline-time">{formatTimestamp(receipt.completed_at)}</span>
							</div>
						</li>
					{/if}
				</ol>
			{/if}
		</section>
	{/if}
</div>

<style>
	.receipt-page {
		padding: var(--lq-space-5);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-5);
		max-width: 60rem;
	}

	/* Back link */
	.back-link {
		display: inline-flex;
		align-items: center;
		gap: var(--lq-space-1);
		color: var(--lq-accent);
		text-decoration: none;
		font-size: 14px;
	}

	.back-link:hover {
		text-decoration: underline;
	}

	/* Banners */
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

	.state-message {
		color: var(--lq-text-secondary);
		padding: var(--lq-space-3);
	}

	/* Header */
	.receipt-header {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-4);
	}

	.receipt-header-top {
		display: flex;
		align-items: center;
		gap: var(--lq-space-4);
		flex-wrap: wrap;
	}

	.halt-button {
		padding: var(--lq-space-1) var(--lq-space-4);
		border-radius: 6px;
		font-size: 13px;
		cursor: pointer;
		border: 1px solid var(--lq-error-border, #fbb);
		background: transparent;
		color: var(--lq-error-text, #b00);
		margin-left: auto;
	}

	.halt-button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	/* Meta grid */
	.receipt-meta {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
		gap: var(--lq-space-3);
		margin: 0;
		padding: var(--lq-space-4);
		background: var(--lq-surface, #fff);
		border: 1px solid var(--lq-border);
		border-radius: 8px;
	}

	.receipt-meta-item {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-1);
	}

	.receipt-meta-item--full {
		grid-column: 1 / -1;
	}

	.receipt-meta dt {
		font-size: 11px;
		font-weight: 600;
		color: var(--lq-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.receipt-meta dd {
		margin: 0;
		font-size: 14px;
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

	/* Cost / cap badge */
	.cost-value {
		font-variant-numeric: tabular-nums;
		display: inline-flex;
		align-items: center;
		gap: var(--lq-space-2);
	}

	.cap-badge {
		display: inline-block;
		padding: 1px 6px;
		border-radius: 8px;
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		background: var(--lq-error-bg, #fee);
		color: var(--lq-error-text, #800);
		border: 1px solid var(--lq-error-border, #fbb);
	}

	/* Terminal reason */
	.terminal-reason {
		font-size: 14px;
		color: var(--lq-text-secondary);
	}

	/* Timeline section */
	.timeline-section {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
	}

	.timeline-heading {
		font-size: 15px;
		font-weight: 600;
		margin: 0;
		color: var(--lq-text);
	}

	.empty-state {
		color: var(--lq-text-secondary);
		font-style: italic;
		margin: 0;
	}

	/* Timeline list */
	.timeline {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		position: relative;
	}

	/* Vertical connector line */
	.timeline::before {
		content: '';
		position: absolute;
		left: 7px;
		top: 12px;
		bottom: 12px;
		width: 2px;
		background: var(--lq-border);
	}

	.timeline-node {
		display: flex;
		align-items: flex-start;
		gap: var(--lq-space-3);
		padding: var(--lq-space-2) 0;
		position: relative;
	}

	/* Dot markers */
	.timeline-marker {
		flex-shrink: 0;
		width: 16px;
		height: 16px;
		border-radius: 50%;
		margin-top: 2px;
		border: 2px solid var(--lq-border);
		background: var(--lq-surface, #fff);
		position: relative;
		z-index: 1;
	}

	.timeline-marker--phase {
		background: var(--lq-accent, #2563eb);
		border-color: var(--lq-accent, #2563eb);
	}

	.timeline-marker--tool {
		background: var(--lq-surface, #fff);
		border-color: var(--lq-border);
	}

	.timeline-marker--terminal {
		background: var(--lq-text-secondary, #666);
		border-color: var(--lq-text-secondary, #666);
	}

	/* Node content */
	.timeline-content {
		flex: 1;
		min-width: 0;
	}

	.timeline-label {
		display: block;
		font-size: 14px;
		font-weight: 500;
		color: var(--lq-text);
	}

	.timeline-label--terminal {
		color: var(--lq-text-secondary);
		font-style: italic;
	}

	.timeline-time {
		display: block;
		font-size: 12px;
		color: var(--lq-text-secondary);
		margin-top: 2px;
	}

	/* Tool details — expandable */
	.tool-details {
		width: 100%;
	}

	.tool-summary {
		display: flex;
		align-items: baseline;
		gap: var(--lq-space-3);
		cursor: pointer;
		list-style: none;
		padding: 0;
	}

	/* Remove default marker in WebKit */
	.tool-summary::-webkit-details-marker {
		display: none;
	}

	.tool-summary::before {
		content: '▶';
		font-size: 10px;
		color: var(--lq-text-secondary);
		transition: transform 0.15s;
		flex-shrink: 0;
	}

	details[open] .tool-summary::before {
		transform: rotate(90deg);
	}

	.tool-name {
		font-size: 14px;
		font-weight: 500;
		color: var(--lq-text);
	}

	.tool-detail-list {
		margin: var(--lq-space-2) 0 0 var(--lq-space-4);
		padding: var(--lq-space-3);
		background: var(--lq-inset, rgba(0, 0, 0, 0.03));
		border-radius: 6px;
		border: 1px solid var(--lq-border);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.tool-detail-row {
		display: flex;
		gap: var(--lq-space-3);
		align-items: baseline;
	}

	.tool-detail-row dt {
		font-size: 11px;
		font-weight: 600;
		color: var(--lq-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		min-width: 80px;
		flex-shrink: 0;
	}

	.tool-detail-row dd {
		margin: 0;
		font-size: 13px;
		color: var(--lq-text);
	}
</style>
