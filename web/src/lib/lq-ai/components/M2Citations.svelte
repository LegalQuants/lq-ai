<script context="module" lang="ts">
	/**
	 * Helpers exported for unit tests — accessible without
	 * `@testing-library/svelte` (mirrors the AttachKBModal / InfoTip
	 * pattern; per CLAUDE.md "Don't add libraries without justification").
	 */
	import type { Citation } from '../types';
	import {
		iterCitationMarkers,
		matchMarkerState,
		citationTooltip,
		type CitationRenderState,
		type ParsedCitationMarker
	} from '../citations/state';

	export interface CitationChip {
		key: string;
		state: CitationRenderState;
		quote: string;
		quotePreview: string;
		tooltip: string;
		citationId: string | null;
		sourceFileId: string | null;
		sourcePage: number | null;
		marker: ParsedCitationMarker;
	}

	/** Truncate a quote for chip display so a long sentence doesn't blow the layout. */
	export function previewQuote(quote: string, maxChars = 60): string {
		const trimmed = quote.trim();
		if (trimmed.length <= maxChars) return trimmed;
		return `${trimmed.slice(0, maxChars - 1).trimEnd()}…`;
	}

	/**
	 * Build the chip list for a message: one chip per `"<quote>" (Source: [N])`
	 * marker found in `content`, joined to its citation row by `source_text`.
	 * Markers without a matching row become unverified chips (per the api's
	 * "absence-of-row = unverified" contract).
	 */
	export function buildCitationChips(
		content: string,
		citations: Citation[]
	): CitationChip[] {
		const chips: CitationChip[] = [];
		let i = 0;
		for (const marker of iterCitationMarkers(content)) {
			const { state, citation } = matchMarkerState(marker, citations);
			chips.push({
				key: citation ? `cite-${citation.id}` : `uncite-${marker.start}-${i}`,
				state,
				quote: marker.quote,
				quotePreview: previewQuote(marker.quote),
				tooltip: citationTooltip(state, citation),
				citationId: citation?.id ?? null,
				sourceFileId: citation?.source_file_id ?? null,
				sourcePage: citation?.source_page ?? null,
				marker
			});
			i++;
		}
		return chips;
	}
</script>

<script lang="ts">
	/**
	 * `M2Citations.svelte` — sidecar chip list for the M2 Citation Engine's
	 * five-state UI (M2-C2). Renders one chip per `"<quote>" (Source: [N])`
	 * marker the assistant emitted: green for byte-level verification
	 * (exact / tolerant match), yellow for paraphrase-judge verification,
	 * grey for unverified attempts. The 'system-error' state is deferred
	 * to M2-D per the M2-C2 decision matrix; the helper's render-state
	 * union reserves the slot.
	 *
	 * Pairs with the `decorateCitationsInline` Svelte action which applies
	 * a subtle inline color underline to the same quotes in the rendered
	 * prose. Together they satisfy the plan's procurement-reviewer test:
	 * "scrolling the report, a reviewer should be able to identify
	 * unverified citations without reading the tooltips."
	 *
	 * The component is purely presentational — click behaviour for
	 * jumping to the source span lives in M2-D2 once the source viewer
	 * ships. For now, hover/focus reveals the state-specific tooltip.
	 */
	import { createEventDispatcher } from 'svelte';

	/** Persisted verified citation rows from `GET /messages/{id}/citations`. */
	export let citations: Citation[] = [];

	/**
	 * The assistant message's raw text. The component scans it for
	 * citation markers — including unverified attempts whose absence
	 * from `citations` is the unverified signal.
	 */
	export let messageContent: string = '';

	/** Hidden visually for the rare case where the caller wants the data path without UI. */
	export let hidden: boolean = false;

	const dispatch = createEventDispatcher<{
		select: { citation: Citation | null; quote: string };
	}>();

	$: chips = buildCitationChips(messageContent, citations);

	function handleSelect(chip: CitationChip): void {
		const fullCitation = chip.citationId
			? citations.find((c) => c.id === chip.citationId) ?? null
			: null;
		dispatch('select', { citation: fullCitation, quote: chip.quote });
	}
</script>

{#if !hidden && chips.length > 0}
	<div
		class="lq-m2-citations mt-2 flex flex-wrap items-center gap-1.5"
		data-testid="m2-citations"
		aria-label="Citation states for this message"
	>
		{#each chips as chip (chip.key)}
			<button
				type="button"
				class="lq-m2-cite-chip"
				class:state-verified-exact={chip.state === 'verified-exact'}
				class:state-verified-tolerant={chip.state === 'verified-tolerant'}
				class:state-verified-paraphrase={chip.state === 'verified-paraphrase'}
				class:state-unverified={chip.state === 'unverified'}
				data-state={chip.state}
				aria-label={chip.tooltip}
				title={chip.tooltip}
				disabled={chip.state === 'unverified'}
				on:click={() => handleSelect(chip)}
			>
				<span class="chip-icon" aria-hidden="true">
					{#if chip.state === 'verified-exact' || chip.state === 'verified-tolerant'}
						<!-- Checkmark — verified-green -->
						<svg viewBox="0 0 12 12" width="12" height="12" fill="currentColor">
							<path d="M10.28 3.22a.75.75 0 010 1.06L5.06 9.5 1.72 6.16a.75.75 0 011.06-1.06l2.28 2.28 4.16-4.16a.75.75 0 011.06 0z" />
						</svg>
					{:else if chip.state === 'verified-paraphrase'}
						<!-- Checkmark — verified-yellow (judge) -->
						<svg viewBox="0 0 12 12" width="12" height="12" fill="currentColor">
							<path d="M10.28 3.22a.75.75 0 010 1.06L5.06 9.5 1.72 6.16a.75.75 0 011.06-1.06l2.28 2.28 4.16-4.16a.75.75 0 011.06 0z" />
						</svg>
					{:else}
						<!-- Unverified marker -->
						<svg viewBox="0 0 12 12" width="12" height="12" fill="currentColor">
							<path d="M6 1a5 5 0 100 10A5 5 0 006 1zm0 2.25a.75.75 0 01.75.75v2.5a.75.75 0 01-1.5 0V4a.75.75 0 01.75-.75zm0 5a.875.875 0 110 1.75.875.875 0 010-1.75z" />
						</svg>
					{/if}
				</span>
				<span class="chip-text">
					{#if chip.state === 'unverified'}<span class="chip-unverified-tag">[unverified]</span
						>{/if}<span class="chip-quote">{chip.quotePreview}</span>
				</span>
			</button>
		{/each}
	</div>
{/if}

<style>
	.lq-m2-citations {
		font-size: 12px;
		line-height: 1.4;
	}

	.lq-m2-cite-chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 2px 8px;
		border-radius: 9999px;
		border: 1px solid transparent;
		background: transparent;
		font: inherit;
		cursor: pointer;
		max-width: 360px;
		transition: background-color 0.15s ease, border-color 0.15s ease;
	}
	.lq-m2-cite-chip:disabled {
		cursor: default;
	}
	.lq-m2-cite-chip:focus-visible {
		outline: 2px solid var(--lq-accent, #4338ca);
		outline-offset: 1px;
	}

	.chip-icon {
		display: inline-flex;
		align-items: center;
		flex-shrink: 0;
	}
	.chip-text {
		display: inline-flex;
		align-items: baseline;
		gap: 4px;
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
	}
	.chip-unverified-tag {
		font-weight: 500;
		opacity: 0.8;
	}
	.chip-quote {
		overflow: hidden;
		text-overflow: ellipsis;
	}

	/* verified-exact + verified-tolerant: emerald (green, WCAG AA against light + dark chat bgs) */
	.state-verified-exact,
	.state-verified-tolerant {
		color: #047857; /* emerald-700 */
		background-color: rgba(16, 185, 129, 0.08); /* emerald-500 @ 8% */
		border-color: rgba(16, 185, 129, 0.32);
	}
	.state-verified-exact:hover,
	.state-verified-tolerant:hover {
		background-color: rgba(16, 185, 129, 0.16);
	}
	:global(.dark) .state-verified-exact,
	:global(.dark) .state-verified-tolerant {
		color: #6ee7b7; /* emerald-300 */
		background-color: rgba(16, 185, 129, 0.12);
		border-color: rgba(16, 185, 129, 0.36);
	}

	/* verified-paraphrase: amber (yellow). Distinct from the green cluster. */
	.state-verified-paraphrase {
		color: #b45309; /* amber-700 */
		background-color: rgba(245, 158, 11, 0.08); /* amber-500 @ 8% */
		border-color: rgba(245, 158, 11, 0.32);
	}
	.state-verified-paraphrase:hover {
		background-color: rgba(245, 158, 11, 0.16);
	}
	:global(.dark) .state-verified-paraphrase {
		color: #fcd34d; /* amber-300 */
		background-color: rgba(245, 158, 11, 0.12);
		border-color: rgba(245, 158, 11, 0.36);
	}

	/* unverified: greyed text + clear [unverified] tag. Not interactive. */
	.state-unverified {
		color: #6b7280; /* gray-500 */
		background-color: rgba(107, 114, 128, 0.08);
		border-color: rgba(107, 114, 128, 0.32);
	}
	:global(.dark) .state-unverified {
		color: #9ca3af; /* gray-400 */
		background-color: rgba(107, 114, 128, 0.16);
		border-color: rgba(107, 114, 128, 0.36);
	}

	/* Inline counterpart — the `decorateCitationsInline` action injects
	   `<span class="lq-cite-inline lq-cite-inline-{state}">`. Styles ride
	   alongside the sidecar to keep the visual contract in one file. */
	:global(.lq-cite-inline) {
		text-decoration: underline;
		text-decoration-thickness: 2px;
		text-underline-offset: 2px;
		text-decoration-skip-ink: none;
	}
	:global(.lq-cite-inline-verified-exact),
	:global(.lq-cite-inline-verified-tolerant) {
		text-decoration-color: #10b981; /* emerald-500 */
	}
	:global(.lq-cite-inline-verified-paraphrase) {
		text-decoration-color: #f59e0b; /* amber-500 */
	}
	:global(.lq-cite-inline-unverified) {
		color: #6b7280; /* gray-500 */
		text-decoration-color: #9ca3af; /* gray-400 */
		text-decoration-style: dotted;
	}
	:global(.dark .lq-cite-inline-unverified) {
		color: #9ca3af; /* gray-400 */
	}
</style>
