<script lang="ts">
	/**
	 * LedgerEntryRow — one row in the Citation Ledger panel (P1-C1).
	 *
	 * Renders the verification-state chip (reusing M2Citations' `lq-m2-cite-chip`
	 * + `state-*` classes), source identity, optional URL, and passage blockquotes.
	 * All state logic is delegated to the Task-1 helper `ledgerEntryState`.
	 *
	 * Refs ADR 0018 D3.
	 */
	import type { LedgerEntry } from '../types';
	import { ledgerEntryState } from '../citations/ledger-state';

	export let entry: LedgerEntry;

	$: state = ledgerEntryState(entry.verification_status);
	$: src = entry.source;

	function identity(): string {
		if (src.kind === 'kb_document') return 'Document';
		if (src.kind === 'caselaw')
			return `Opinion ${src.opinion_id ?? ''} · cluster ${src.cluster_id ?? ''}`.trim();
		return src.label ?? src.tool ?? src.kind;
	}
</script>

<li class="lq-ledger-row">
	<div class="lq-ledger-row-header">
		<!-- Reuse the M2Citations chip class + the state-* class directives from M2Citations.svelte. -->
		<span
			class="lq-m2-cite-chip lq-ledger-chip"
			class:state-verified-exact={state === 'verified-exact'}
			class:state-verified-tolerant={state === 'verified-tolerant'}
			class:state-verified-paraphrase={state === 'verified-paraphrase'}
			class:state-unverified={state === 'unverified'}
			data-state={state}
		>
			{entry.verification_status}
		</span>
		<span class="lq-ledger-identity">{identity()}</span>
		{#if src.url}
			<a class="lq-ledger-url" href={src.url} target="_blank" rel="noopener noreferrer">source ↗</a>
		{/if}
	</div>

	{#if src.passages && src.passages.length > 0}
		{#each src.passages as p}
			<blockquote class="lq-ledger-passage">
				<span class="lq-ledger-passage-text">{p.text}</span>
				<cite class="lq-ledger-offset">chars {p.offset_start}–{p.offset_end}</cite>
			</blockquote>
		{/each}
	{:else}
		<span class="lq-ledger-consulted">consulted</span>
	{/if}
</li>

<style>
	.lq-ledger-row {
		list-style: none;
		padding: var(--lq-space-3) 0;
		border-bottom: 1px solid var(--lq-border);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}
	.lq-ledger-row:last-child {
		border-bottom: none;
	}

	.lq-ledger-row-header {
		display: flex;
		align-items: center;
		gap: var(--lq-space-2);
		flex-wrap: wrap;
	}

	/* Override the button cursor — this chip is display-only in the ledger. */
	.lq-ledger-chip {
		cursor: default;
		font-size: 11px;
		padding: 1px 7px;
		/* Inherit the state color from M2Citations' state-* rules. */
	}

	.lq-ledger-identity {
		font-size: 13px;
		font-weight: 500;
		color: var(--lq-text);
	}

	.lq-ledger-url {
		font-size: 12px;
		color: var(--lq-accent);
		text-decoration: none;
		margin-left: auto;
	}
	.lq-ledger-url:hover {
		text-decoration: underline;
	}

	.lq-ledger-passage {
		margin: 0;
		padding: var(--lq-space-2) var(--lq-space-3);
		border-left: 3px solid var(--lq-border-strong);
		background: var(--lq-inset);
		border-radius: 0 var(--lq-radius-sm) var(--lq-radius-sm) 0;
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-1);
	}

	.lq-ledger-passage-text {
		font-size: 12px;
		line-height: 1.5;
		color: var(--lq-text);
	}

	.lq-ledger-offset {
		font-size: 10px;
		color: var(--lq-text-tertiary);
		font-style: normal;
	}

	.lq-ledger-consulted {
		font-size: 11px;
		color: var(--lq-text-tertiary);
		font-style: italic;
		padding-left: var(--lq-space-1);
	}
</style>
