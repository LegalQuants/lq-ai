<script lang="ts">
	/**
	 * LqAlert — inline status banner, modeled on Mantine's Alert.
	 *
	 * Takes `tone` only for now (the bundled soft-bg/text/border look, same
	 * as LqButton/LqPill) rather than the lower-level `color`+`shade` pair
	 * from `./types` — nothing here needs finer control than a whole tone
	 * yet. If that changes, `color`+`shade` props can be added alongside
	 * `tone` without breaking existing callers.
	 */
	import { IconX } from '@tabler/icons-svelte';
	import type { LqTone } from './types';

	export let tone: LqTone = 'neutral';
	export let title: string | undefined = undefined;
	export let role: 'alert' | 'status' = 'alert';
	export let onClose: (() => void) | undefined = undefined;

	let klass = '';
	export { klass as class };
</script>

<div {...$$restProps} class="lq-alert lq-alert-tone-{tone} {klass}" {role}>
	<div class="lq-alert-body">
		{#if title}
			<div class="lq-alert-title">{title}</div>
		{/if}
		<div class="lq-alert-message"><slot /></div>
	</div>
	{#if onClose}
		<button type="button" class="lq-alert-close" aria-label="Dismiss" on:click={onClose}>
			<IconX size={14} />
		</button>
	{/if}
</div>

<style>
	.lq-alert {
		display: flex;
		align-items: flex-start;
		gap: var(--lq-space-2, 8px);
		width: 100%;
		box-sizing: border-box;
		padding: var(--lq-space-2, 8px) var(--lq-space-3, 12px);
		border-radius: var(--lq-radius-input, 12px);
		border: 1px solid transparent;
		border-left-width: 3px;
		font-size: 13px;
		line-height: 1.4;
	}

	.lq-alert-body {
		flex: 1 1 auto;
		min-width: 0;
	}

	.lq-alert-title {
		font-weight: 600;
		margin-bottom: 2px;
	}

	.lq-alert-close {
		all: unset;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		cursor: pointer;
		border-radius: 999px;
		padding: 2px;
	}
	.lq-alert-close:hover {
		background: rgba(0, 0, 0, 0.08);
	}
	.lq-alert-close:focus-visible {
		outline: 2px solid currentColor;
		outline-offset: 1px;
	}

	.lq-alert-tone-accent {
		background: var(--lq-accent-soft, #f1f1f1);
		color: var(--lq-accent, #111114);
		border-color: var(--lq-accent-border, #cfcfd0);
		border-left-color: var(--lq-accent, #111114);
	}
	.lq-alert-tone-governance {
		background: var(--lq-governance-soft, #f8f1eb);
		color: var(--lq-governance, #a34a00);
		border-color: var(--lq-governance-border, #e3c9b3);
		border-left-color: var(--lq-governance, #a34a00);
	}
	.lq-alert-tone-info {
		background: var(--lq-info-soft, #f1f1f3);
		color: var(--lq-info, #111114);
		border-color: var(--lq-info-border, #e4e4e7);
		border-left-color: var(--lq-info, #111114);
	}
	.lq-alert-tone-warning {
		background: var(--lq-warning-soft, #f1f1f3);
		color: var(--lq-warning, #111114);
		border-color: var(--lq-warning-border, #e4e4e7);
		border-left-color: var(--lq-warning, #111114);
	}
	.lq-alert-tone-danger {
		background: var(--lq-danger-soft, #f9eded);
		color: var(--lq-danger, #b42318);
		border-color: var(--lq-danger-border, #ecc8c5);
		border-left-color: var(--lq-danger, #b42318);
	}
	.lq-alert-tone-neutral {
		background: var(--lq-inset, #f9f9fa);
		color: var(--lq-text-secondary, #4f5158);
		border-color: var(--lq-border, #e4e4e7);
		border-left-color: var(--lq-border-strong, #80828a);
	}
</style>
