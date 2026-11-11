<script lang="ts">
	import { IconScale, IconChevronDown, IconChevronRight } from '@tabler/icons-svelte';
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
	import { treatmentSummary, formatCitingRef } from '../citations/treatment-display';

	export let entry: LedgerEntry;

	$: state = ledgerEntryState(entry.verification_status);
	$: src = entry.source;
	let treatmentOpen = false;

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

	{#if entry.treatment && src.kind === 'caselaw'}
		{@const t = treatmentSummary(entry.treatment)}
		{@const interactive = t.preview.length > 0}
		{@const notEditorial =
			'Derived from the citation graph — not an editorial ‘good law’ judgment. Treatment classification arrives in a later release.'}
		<div class="lq-ledger-treatment">
			{#if interactive}
				<button
					type="button"
					class="lq-ledger-treatment-line"
					aria-expanded={treatmentOpen}
					aria-label={`Citation-graph treatment — ${t.label}, derived ${t.asOf} — not an editorial good-law judgment`}
					title={notEditorial}
					on:click={() => (treatmentOpen = !treatmentOpen)}
				>
					<span class="lq-ledger-treatment-icon" aria-hidden="true"
						><IconScale size={12} stroke={1.75} /></span
					>
					<span class="lq-ledger-treatment-label">{t.label}</span>
					<span class="lq-ledger-treatment-asof">· derived {t.asOf}</span>
					<span class="lq-ledger-treatment-caret" aria-hidden="true"
						>{#if treatmentOpen}<IconChevronDown size={12} stroke={1.75} />{:else}<IconChevronRight
								size={12}
								stroke={1.75}
							/>{/if}</span
					>
				</button>
			{:else}
				<!-- No citing refs to disclose → a non-interactive line (no broken aria-expanded). -->
				<div
					class="lq-ledger-treatment-line lq-ledger-treatment-static"
					title={notEditorial}
					aria-label={`Citation-graph treatment — ${t.label}, derived ${t.asOf} — not an editorial good-law judgment`}
				>
					<span class="lq-ledger-treatment-icon" aria-hidden="true"
						><IconScale size={12} stroke={1.75} /></span
					>
					<span class="lq-ledger-treatment-label">{t.label}</span>
					<span class="lq-ledger-treatment-asof">· derived {t.asOf}</span>
				</div>
			{/if}
			{#if treatmentOpen && interactive}
				<ul class="lq-ledger-treatment-list">
					{#each t.preview as ref}
						{@const refLabel = formatCitingRef(ref)}
						{#if refLabel}
							<li>{refLabel}</li>
						{/if}
					{/each}
					{#if t.moreCount > 0}
						<li class="lq-ledger-treatment-more">
							+ {t.moreCount} more{#if t.capped}
								· {t.shown} most recent of {t.total}{/if}
						</li>
					{/if}
				</ul>
			{/if}
		</div>
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

	/* Chip shape — reproduced locally because Svelte scopes <style> to its
	   own component; M2Citations' .lq-m2-cite-chip rules never apply here. */
	.lq-m2-cite-chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 2px 8px;
		border-radius: 9999px;
		border: 1px solid transparent;
		background: transparent;
		font: inherit;
		cursor: default;
		max-width: 360px;
		transition:
			background-color 0.15s ease,
			border-color 0.15s ease;
	}

	/* Override padding/font-size for the ledger context. */
	.lq-ledger-chip {
		font-size: 11px;
		padding: 1px 7px;
	}

	/* verified-exact + verified-tolerant: emerald (same tokens as M2Citations) */
	.state-verified-exact,
	.state-verified-tolerant {
		color: var(--lq-text);
		background-color: var(--lq-surface-muted);
		border-color: var(--lq-border-strong);
	}

	/* verified-paraphrase: amber */
	.state-verified-paraphrase {
		color: var(--lq-text);
		background-color: var(--lq-surface-muted);
		border-color: var(--lq-border-strong);
		border-style: dashed;
	}

	/* unverified: gray */
	.state-unverified {
		color: var(--lq-text-tertiary);
		background-color: var(--lq-canvas);
		border-color: var(--lq-border);
		border-style: dotted;
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

	.lq-ledger-treatment {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-1);
	}
	.lq-ledger-treatment-line {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		align-self: flex-start;
		padding: 0;
		border: none;
		background: transparent;
		font: inherit;
		font-size: 11px;
		color: var(--lq-text-tertiary);
		cursor: pointer;
	}
	.lq-ledger-treatment-line:hover {
		color: var(--lq-text-secondary);
	}
	.lq-ledger-treatment-static {
		cursor: default;
	}
	.lq-ledger-treatment-icon {
		font-size: 12px;
	}
	.lq-ledger-treatment-label {
		font-weight: 500;
	}
	.lq-ledger-treatment-asof {
		color: var(--lq-text-tertiary);
	}
	.lq-ledger-treatment-caret {
		font-size: 10px;
		margin-left: 2px;
	}
	.lq-ledger-treatment-list {
		list-style: none;
		margin: 0;
		padding: 0 0 0 var(--lq-space-4);
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: 11px;
		color: var(--lq-text-tertiary);
	}
	.lq-ledger-treatment-more {
		color: var(--lq-text-tertiary);
		font-style: italic;
	}
</style>
