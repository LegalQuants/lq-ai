<script lang="ts">
	/**
	 * CitationLedgerPanel — fiduciary-grade citation trace modal (P1-C1).
	 *
	 * Modal structure mirrors TierDetailsPanel.svelte (fixed inset-0 z-50,
	 * backdrop click and Esc-to-close via onMount document listener, role="dialog"
	 * aria-modal). Header carries the gateBadge TrustPill + InfoTip + per-tier
	 * counts. Body is a list of LedgerEntryRow components.
	 *
	 * Props:
	 *   entries  — ledger entries for this message turn.
	 *   gate     — gate verdict row (undefined when no gate was computed).
	 *   open     — whether the panel is visible.
	 *   onClose  — callback invoked on Esc or backdrop click.
	 *
	 * Refs ADR 0018 D4.
	 */
	import { onMount } from 'svelte';
	import type { LedgerEntry, LedgerGate } from '../types';
	import { gateBadge } from '../citations/ledger-state';
	import TrustPill from './TrustPill.svelte';
	import InfoTip from './InfoTip.svelte';
	import LedgerEntryRow from './LedgerEntryRow.svelte';

	export let entries: LedgerEntry[] = [];
	export let gate: LedgerGate | undefined = undefined;
	export let open = false;
	export let onClose: () => void;

	$: badge = gateBadge(gate);

	function handleKeydown(event: KeyboardEvent): void {
		if (event.key === 'Escape') onClose();
	}

	function handleBackdropClick(event: MouseEvent): void {
		if (event.target === event.currentTarget) onClose();
	}

	$: if (typeof document !== 'undefined') {
		if (open) document.addEventListener('keydown', handleKeydown);
		else document.removeEventListener('keydown', handleKeydown);
	}

	onMount(() => () => document.removeEventListener('keydown', handleKeydown));
</script>

{#if open}
	<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
		on:click={handleBackdropClick}
		on:keydown={handleKeydown}
		role="dialog"
		aria-modal="true"
		aria-label="Citation ledger"
		tabindex="-1"
		data-testid="lq-ledger-backdrop"
	>
		<!-- svelte-ignore a11y-no-static-element-interactions a11y-click-events-have-key-events -->
		<div
			class="bg-white dark:bg-gray-900 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 max-w-lg w-full lq-ledger-panel"
			on:click|stopPropagation
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
					<button
						type="button"
						class="lq-ledger-close"
						on:click={onClose}
						aria-label="Close citation ledger"
						data-testid="lq-ledger-close"
					>
						&times;
					</button>
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
	</div>
{/if}

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

	.lq-ledger-close {
		margin-left: auto;
		background: transparent;
		border: none;
		font-size: 1.25rem;
		line-height: 1;
		color: var(--lq-text-secondary);
		cursor: pointer;
		padding: 0 2px;
		border-radius: var(--lq-radius-sm);
	}
	.lq-ledger-close:hover {
		color: var(--lq-text);
	}
	.lq-ledger-close:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
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
