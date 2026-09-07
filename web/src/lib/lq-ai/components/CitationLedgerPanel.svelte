<script lang="ts">
	/**
	 * CitationLedgerPanel — fiduciary-grade citation trace display (P1-C1).
	 *
	 * Header carries the gateBadge TrustPill + InfoTip + per-tier counts.
	 * Body is a list of LedgerEntryRow components.
	 *
	 * Pure display — no backdrop, no Esc/close handling, no `open`/`onClose`
	 * props. Whatever renders this (a modal, a hover popover) owns the
	 * presentation entirely.
	 *
	 * Props:
	 *   entries  — ledger entries for this message turn.
	 *   gate     — gate verdict row (undefined when no gate was computed).
	 *
	 * Refs ADR 0018 D4.
	 */
	import type { LedgerEntry, LedgerGate } from '../types';
	import { gateBadge } from '../citations/ledger-state';
	import TrustPill from './TrustPill.svelte';
	import InfoTip from './InfoTip.svelte';
	import LedgerEntryRow from './LedgerEntryRow.svelte';

	export let entries: LedgerEntry[] = [];
	export let gate: LedgerGate | undefined = undefined;

	$: badge = gateBadge(gate);
</script>

<div
	class="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 max-w-lg lq-ledger-panel"
	data-testid="lq-ledger-panel"
>
	<header class="lq-ledger-header">
		<div class="lq-ledger-header-top">
			{#if badge}
				<TrustPill variant="audit" tone={badge.tone} label={badge.label} />
				<InfoTip content={badge.tip} />
			{:else}
				<span class="lq-ledger-no-gate">No gate verdict</span>
			{/if}
		</div>
		{#if gate}
			<p class="lq-ledger-counts">
				{gate.pass_count} verbatim · {gate.supported_count} supported · {gate.fail_count} unverified
			</p>
		{/if}
	</header>

	<div class="lq-ledger-body">
		{#if entries.length > 0}
			<ul class="lq-ledger-list">
				{#each entries as e (e.id)}
					<LedgerEntryRow entry={e} />
				{/each}
			</ul>
		{:else}
			<p class="lq-ledger-empty">No sources were brought into context for this turn.</p>
		{/if}
	</div>
</div>

<style>
	.lq-ledger-panel {
		max-height: 80vh;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.lq-ledger-header {
		padding: var(--lq-space-4);
		border-bottom: 1px solid var(--lq-border);
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.lq-ledger-header-top {
		display: flex;
		align-items: center;
		gap: var(--lq-space-2);
	}

	.lq-ledger-no-gate {
		font-size: 13px;
		color: var(--lq-text-tertiary);
		font-style: italic;
	}

	.lq-ledger-counts {
		font-size: 12px;
		color: var(--lq-text-secondary);
		margin: 0;
	}

	.lq-ledger-body {
		overflow-y: auto;
		padding: 0 var(--lq-space-4);
		flex: 1 1 auto;
	}

	.lq-ledger-list {
		list-style: none;
		padding: 0;
		margin: 0;
	}

	.lq-ledger-empty {
		padding: var(--lq-space-6) 0;
		font-size: 13px;
		color: var(--lq-text-tertiary);
		font-style: italic;
		text-align: center;
		margin: 0;
	}
</style>
