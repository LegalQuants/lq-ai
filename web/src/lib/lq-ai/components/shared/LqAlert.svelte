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
	export let onClose: (() => void) | undefined = undefined;

	let klass = '';
	export { klass as class };
</script>

<div {...$$restProps} class="lq-alert lq-alert-tone-{tone} {klass}" role="alert">
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
		border-radius: var(--lq-radius, 6px);
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

	.lq-alert-tone-sage {
		background: var(--lq-accent-soft, #e8f4ec);
		color: var(--lq-accent, #1f7a6b);
		border-color: var(--lq-accent-border, #c5e6d1);
		border-left-color: var(--lq-accent, #1f7a6b);
	}
	.lq-alert-tone-slate {
		background: var(--lq-tier-soft, #e8eff7);
		color: var(--lq-tier, #355a82);
		border-color: var(--lq-tier-border, #d4e2f1);
		border-left-color: var(--lq-tier, #355a82);
	}
	.lq-alert-tone-amber {
		background: var(--lq-warn-soft, #fdf3e2);
		color: var(--lq-warn, #a16e1f);
		border-color: var(--lq-warn-border, #ead9c5);
		border-left-color: var(--lq-warn, #a16e1f);
	}
	.lq-alert-tone-red {
		background: var(--lq-error-soft, #fbeaea);
		color: var(--lq-error, #b54848);
		border-color: var(--lq-error-border, #f1d2d2);
		border-left-color: var(--lq-error, #b54848);
	}
	.lq-alert-tone-neutral {
		background: var(--lq-inset, #fafbfa);
		color: var(--lq-text-secondary, #4b5563);
		border-color: var(--lq-border, #e5e7eb);
		border-left-color: var(--lq-border-strong, #d4d4d4);
	}
</style>
