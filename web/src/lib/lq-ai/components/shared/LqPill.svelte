<script lang="ts">
	/**
	 * LqPill — general-purpose tag/chip pill, modeled on TrustPill's visual
	 * language (same tone palette + shape) but generalized: TrustPill is
	 * fixed to the ambient-trust chrome's variant→tone mapping, LqPill takes
	 * a plain tone directly and adds a removable (✕) affordance, for the
	 * "applied skills", "attached files" style use cases.
	 *
	 * The label and the remove button are two separate `<button>`s (not one
	 * button wrapping the other — nested interactive elements are invalid
	 * HTML) when both `onClick` and `onRemove` are supplied. If neither is
	 * given, the label renders as plain (non-interactive) text.
	 */
	import { IconX } from '@tabler/icons-svelte';
	import type { LqTone } from './types';

	export let text: string;
	export let tone: LqTone = 'neutral';
	export let onClick: (() => void) | undefined = undefined;
	export let onRemove: (() => void) | undefined = undefined;
</script>

<span class="lq-pill lq-pill-tone-{tone}">
	{#if onClick}
		<button type="button" class="lq-pill-label lq-pill-label-clickable" on:click={onClick}>
			{text}
		</button>
	{:else}
		<span class="lq-pill-label">{text}</span>
	{/if}
	{#if onRemove}
		<button
			type="button"
			class="lq-pill-remove"
			aria-label="Remove {text}"
			on:click={onRemove}
		>
			<IconX size={12} />
		</button>
	{/if}
</span>

<style>
	.lq-pill {
		display: inline-flex;
		align-items: center;
		gap: var(--lq-space-1, 4px);
		padding: 2px 10px;
		border-radius: var(--lq-radius-pill, 999px);
		font-size: 12px;
		font-weight: 500;
		line-height: 1.4;
		border: 1px solid transparent;
		background: transparent;
	}

	.lq-pill-label {
		all: unset;
		display: inline;
	}

	.lq-pill-label-clickable {
		cursor: pointer;
	}
	.lq-pill-label-clickable:hover {
		text-decoration: underline;
	}
	.lq-pill-label-clickable:focus-visible {
		outline: 2px solid currentColor;
		outline-offset: 2px;
	}

	.lq-pill-remove {
		all: unset;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		cursor: pointer;
		border-radius: 999px;
		padding: 1px;
		line-height: 0;
	}
	.lq-pill-remove:hover {
		background: rgba(0, 0, 0, 0.08);
	}
	.lq-pill-remove:focus-visible {
		outline: 2px solid currentColor;
		outline-offset: 1px;
	}

	.lq-pill-tone-sage {
		background: var(--lq-accent-soft, #e8f4ec);
		color: var(--lq-accent, #1f7a6b);
		border-color: var(--lq-accent-border, #c5e6d1);
	}
	.lq-pill-tone-slate {
		background: var(--lq-tier-soft, #e8eff7);
		color: var(--lq-tier, #355a82);
		border-color: var(--lq-tier-border, #d4e2f1);
	}
	.lq-pill-tone-amber {
		background: var(--lq-warn-soft, #fdf3e2);
		color: var(--lq-warn, #a16e1f);
		border-color: var(--lq-warn-border, #ead9c5);
	}
	.lq-pill-tone-red {
		background: var(--lq-error-soft, #fbeaea);
		color: var(--lq-error, #b54848);
		border-color: var(--lq-error-border, #f1d2d2);
	}
	.lq-pill-tone-neutral {
		background: var(--lq-inset, #fafbfa);
		color: var(--lq-text-secondary, #4b5563);
		border-color: var(--lq-border, #e5e7eb);
	}
</style>
