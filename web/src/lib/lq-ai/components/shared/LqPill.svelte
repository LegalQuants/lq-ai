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
	let klass = '';
	export { klass as class };
</script>

<span {...$$restProps} class="lq-pill lq-pill-tone-{tone} {klass}">
	{#if onClick}
		<button type="button" class="lq-pill-label lq-pill-label-clickable" on:click={onClick}>
			{text}
		</button>
	{:else}
		<span class="lq-pill-label">{text}</span>
	{/if}
	{#if onRemove}
		<button type="button" class="lq-pill-remove" aria-label="Remove {text}" on:click={onRemove}>
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

	.lq-pill-tone-accent {
		background: var(--lq-accent-soft, #f1f1f1);
		color: var(--lq-accent, #111114);
		border-color: var(--lq-accent-border, #cfcfd0);
	}
	.lq-pill-tone-governance {
		background: var(--lq-governance-soft, #f8f1eb);
		color: var(--lq-governance, #a34a00);
		border-color: var(--lq-governance-border, #e3c9b3);
	}
	.lq-pill-tone-info {
		background: var(--lq-info-soft, #f1f1f3);
		color: var(--lq-info, #111114);
		border-color: var(--lq-info-border, #e4e4e7);
	}
	.lq-pill-tone-warning {
		background: var(--lq-warning-soft, #f1f1f3);
		color: var(--lq-warning, #111114);
		border-color: var(--lq-warning-border, #e4e4e7);
	}
	.lq-pill-tone-danger {
		background: var(--lq-danger-soft, #f9eded);
		color: var(--lq-danger, #b42318);
		border-color: var(--lq-danger-border, #ecc8c5);
	}
	.lq-pill-tone-neutral {
		background: var(--lq-inset, #f9f9fa);
		color: var(--lq-text-secondary, #4f5158);
		border-color: var(--lq-border, #e4e4e7);
	}
</style>
