<script context="module" lang="ts">
	/**
	 * ProvenancePill — pill primitive attached to AI messages.
	 * Wave A defines the contract; Wave D wires it into the message renderer.
	 * See spec §5.2.
	 */
	export type ProvenanceKind = 'skill' | 'tier' | 'provider' | 'kb' | 'audit' | 'enhanced' | 'caselaw';

	const KIND_ICON: Record<ProvenanceKind, string> = {
		skill: '🛠️',
		tier: '🔒',
		provider: '🧠',
		kb: '📎',
		audit: '📜',
		enhanced: '✨',
		caselaw: '⚖'
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
			'Enhanced Prompt — the AI rewrote your short prompt into a structured legal prompt before answering. Hover to compare.',
		caselaw:
			'Case law — this answer drew on external legal sources (e.g. CourtListener). Click to view sources consulted.'
	};

	export function iconFor(kind: ProvenanceKind): string {
		return KIND_ICON[kind];
	}

	export function descriptionFor(kind: ProvenanceKind): string {
		return KIND_DESCRIPTION[kind];
	}

	export type ProvenanceTone = 'sage' | 'slate' | 'amber';

	export function toneFor(kind: ProvenanceKind, tierMismatch: boolean): ProvenanceTone {
		if (kind === 'tier') return tierMismatch ? 'amber' : 'slate';
		if (kind === 'caselaw') return 'slate';
		return 'sage';
	}
</script>

<script lang="ts">
	export let kind: ProvenanceKind;
	export let summary: string;
	export let tierMismatch = false;
	export let onTap: (() => void) | undefined = undefined;

	$: tone = toneFor(kind, tierMismatch);
	$: icon = iconFor(kind);
	$: description = descriptionFor(kind);
</script>

<button
	type="button"
	class="lq-prov-pill lq-prov-tone-{tone}"
	aria-label="{kind}: {summary}"
	title={description}
	on:click={onTap}
>
	<span class="lq-prov-icon" aria-hidden="true">{icon}</span>
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
	.lq-prov-icon {
		font-size: 11px;
	}
	.lq-prov-summary {
		font-weight: 500;
	}
	.lq-prov-tone-sage {
		background: var(--lq-accent-soft);
		color: var(--lq-accent);
		border-color: var(--lq-accent-border);
	}
	.lq-prov-tone-slate {
		background: var(--lq-tier-soft);
		color: var(--lq-tier);
		border-color: var(--lq-tier-border);
	}
	.lq-prov-tone-amber {
		background: var(--lq-warn-soft);
		color: var(--lq-warn);
		border-color: var(--lq-warn-border);
	}
	.lq-prov-pill:hover {
		filter: brightness(0.97);
	}
	.lq-prov-pill:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
</style>
