<script context="module" lang="ts">
	import { IconTool, IconLock, IconBrain, IconPaperclip, IconFileText, IconSparkles, IconScale } from '@tabler/icons-svelte';
	/**
	 * ProvenancePill — pill primitive attached to AI messages.
	 * Wave A defines the contract; Wave D wires it into the message renderer.
	 * See spec §5.2.
	 */
	export type ProvenanceKind = 'skill' | 'tier' | 'provider' | 'kb' | 'audit' | 'enhanced' | 'caselaw';

	/** Tabler line icons (ADR 0045 §5); the names are what `iconFor` returns. */
	const KIND_ICON: Record<ProvenanceKind, typeof IconTool> = {
		skill: IconTool,
		tier: IconLock,
		provider: IconBrain,
		kb: IconPaperclip,
		audit: IconFileText,
		enhanced: IconSparkles,
		caselaw: IconScale
	};
	const KIND_ICON_NAME: Record<ProvenanceKind, string> = {
		skill: 'tool',
		tier: 'lock',
		provider: 'brain',
		kb: 'paperclip',
		audit: 'file-text',
		enhanced: 'sparkles',
		caselaw: 'scale'
	};

	/**
	 * Plain-English hover descriptions for each provenance kind.
	 * Surfaced via the button's `title` attribute so non-technical users
	 * can hover to learn what each pill means without having to click
	 * through to the detail panel.
	 */
	const KIND_DESCRIPTION: Record<ProvenanceKind, string> = {
		skill:
			'Skill — this answer was shaped by a reusable structured prompt. Click to read the skill source.',
		tier: 'Inference tier — where this answer was processed (Tier 1 = local, Tier 5 = consumer). Click for details.',
		provider: 'AI provider — which model produced this answer. Click for details.',
		kb: 'Knowledge base — documents the AI could search and cite from for this answer. Click to view.',
		audit:
			'Audit log — this action was recorded for compliance and review. Click to view the entry.',
		enhanced:
			'Enhanced Prompt — the AI rewrote your short prompt into a structured legal prompt before answering. Click to compare.',
		caselaw:
			'Case law — this answer drew on external legal sources (e.g. CourtListener). Click to view sources consulted.'
	};

	/** The Tabler icon name for a kind (`tabler-icon-<name>` in the markup). */
	export function iconFor(kind: ProvenanceKind): string {
		return KIND_ICON_NAME[kind];
	}

	export function iconComponentFor(kind: ProvenanceKind): typeof IconTool {
		return KIND_ICON[kind];
	}

	export function descriptionFor(kind: ProvenanceKind): string {
		return KIND_DESCRIPTION[kind];
	}

	export type ProvenanceTone = 'sage' | 'slate' | 'governance';

	/** A tier mismatch is a governance signal, drawn at least as loudly as a matching tier. */
	export function toneFor(kind: ProvenanceKind, tierMismatch: boolean): ProvenanceTone {
		if (kind === 'tier') return tierMismatch ? 'governance' : 'slate';
		return 'sage';
	}
</script>

<script lang="ts">
	export let kind: ProvenanceKind;
	export let summary: string;
	export let tierMismatch = false;
	export let onTap: (() => void) | undefined = undefined;

	$: tone = toneFor(kind, tierMismatch);
	$: icon = iconComponentFor(kind);
	$: description = descriptionFor(kind);
</script>

<button
	type="button"
	class="lq-prov-pill lq-prov-tone-{tone}"
	aria-label="{kind}: {summary}"
	title={description}
	on:click={onTap}
>
	<svelte:component this={icon} size={12} stroke={1.75} class="lq-prov-icon" aria-hidden="true" />
	<span class="lq-prov-summary">{summary}</span>
</button>

<style>
	.lq-prov-pill {
		display: inline-flex;
		align-items: center;
		gap: var(--lq-space-1);
		padding: 2px 8px;
		border-radius: var(--lq-radius-pill);
		font-size: 11px;
		line-height: 1.4;
		border: 1px solid transparent;
		background: transparent;
		cursor: pointer;
	}
	.lq-prov-pill :global(.lq-prov-icon) {
		flex: none;
	}
	.lq-prov-summary {
		font-weight: 500;
	}
	/* ADR 0045: sage is a neutral outline; slate (the tier) adds a governance dot. */
	.lq-prov-tone-sage,
	.lq-prov-tone-slate {
		background: var(--lq-canvas);
		color: var(--lq-text);
		border-color: var(--lq-border);
	}
	.lq-prov-tone-slate::before {
		content: '';
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--lq-governance);
		flex: none;
	}
	/* A tier mismatch: governance text and edge on the governance tint. */
	.lq-prov-tone-governance {
		background: var(--lq-governance-soft);
		color: var(--lq-governance);
		border-color: var(--lq-governance-border);
	}
	.lq-prov-pill:hover {
		opacity: 0.85;
	}
	.lq-prov-pill:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
</style>
