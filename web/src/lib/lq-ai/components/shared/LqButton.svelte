<script lang="ts">
	import type { LqVariant, LqTone, LqSize } from './types';

	export let variant: LqVariant = 'filled';
	export let tone: LqTone = 'accent';
	export let size: LqSize = 'md';
	export let disabled = false;
	export let type: 'button' | 'submit' | 'reset' = 'button';
	let klass = '';
	export { klass as class };
</script>

<button
	{type}
	{disabled}
	{...$$restProps}
	class="lq-btn lq-btn-{variant} lq-btn-{size} lq-tone-{tone} {klass}"
	on:click
>
	<slot />
</button>

<style>
	.lq-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: var(--lq-space-1, 4px);
		border-radius: var(--lq-radius-pill, 999px);
		border: 1.5px solid transparent;
		font-weight: 500;
		line-height: 1.2;
		cursor: pointer;
		transition:
			background 120ms ease,
			border-color 120ms ease,
			color 120ms ease,
			filter 120ms ease;
	}

	.lq-btn:disabled {
		cursor: not-allowed;
		opacity: 0.5;
	}

	.lq-btn:focus-visible {
		outline: 2px solid var(--lq-accent, #111114);
		outline-offset: 2px;
	}

	/* sizes */
	.lq-btn-sm {
		font-size: 12px;
		padding: var(--lq-space-1, 4px) var(--lq-space-2, 8px);
	}
	.lq-btn-md {
		font-size: 14px;
		padding: var(--lq-space-2, 8px) var(--lq-space-4, 16px);
	}
	.lq-btn-lg {
		font-size: 16px;
		padding: var(--lq-space-3, 12px) var(--lq-space-6, 24px);
	}

	/* tone: accent */
	.lq-tone-accent.lq-btn-filled {
		background: var(--lq-accent, #111114);
		color: white;
	}
	.lq-tone-accent.lq-btn-outline {
		border-color: var(--lq-accent, #111114);
		color: var(--lq-accent, #111114);
		background: transparent;
	}
	.lq-tone-accent.lq-btn-subtle {
		background: var(--lq-accent-soft, #f1f1f1);
		color: var(--lq-accent, #111114);
	}
	.lq-tone-accent.lq-btn-ghost {
		background: transparent;
		color: var(--lq-accent, #111114);
	}

	/* tone: governance (text and marks; ADR 0045 §1) */
	.lq-tone-governance.lq-btn-filled {
		background: var(--lq-governance, #a34a00);
		color: white;
	}
	.lq-tone-governance.lq-btn-outline {
		border-color: var(--lq-governance, #a34a00);
		color: var(--lq-governance, #a34a00);
		background: transparent;
	}
	.lq-tone-governance.lq-btn-subtle {
		background: var(--lq-governance-soft, #f8f1eb);
		color: var(--lq-governance, #a34a00);
	}
	.lq-tone-governance.lq-btn-ghost {
		background: transparent;
		color: var(--lq-governance, #a34a00);
	}

	/* tone: info */
	.lq-tone-info.lq-btn-filled {
		background: var(--lq-info, #111114);
		color: white;
	}
	.lq-tone-info.lq-btn-outline {
		border-color: var(--lq-info, #111114);
		color: var(--lq-info, #111114);
		background: transparent;
	}
	.lq-tone-info.lq-btn-subtle {
		background: var(--lq-info-soft, #f1f1f3);
		color: var(--lq-info, #111114);
	}
	.lq-tone-info.lq-btn-ghost {
		background: transparent;
		color: var(--lq-info, #111114);
	}

	/* tone: warning */
	.lq-tone-warning.lq-btn-filled {
		background: var(--lq-warning, #111114);
		color: white;
	}
	.lq-tone-warning.lq-btn-outline {
		border-color: var(--lq-warning, #111114);
		color: var(--lq-warning, #111114);
		background: transparent;
	}
	.lq-tone-warning.lq-btn-subtle {
		background: var(--lq-warning-soft, #f1f1f3);
		color: var(--lq-warning, #111114);
	}
	.lq-tone-warning.lq-btn-ghost {
		background: transparent;
		color: var(--lq-warning, #111114);
	}

	/* tone: danger */
	.lq-tone-danger.lq-btn-filled {
		background: var(--lq-danger, #b42318);
		color: white;
	}
	.lq-tone-danger.lq-btn-outline {
		border-color: var(--lq-danger, #b42318);
		color: var(--lq-danger, #b42318);
		background: transparent;
	}
	.lq-tone-danger.lq-btn-subtle {
		background: var(--lq-danger-soft, #f9eded);
		color: var(--lq-danger, #b42318);
	}
	.lq-tone-danger.lq-btn-ghost {
		background: transparent;
		color: var(--lq-danger, #b42318);
	}

	/* tone: neutral */
	.lq-tone-neutral.lq-btn-filled {
		background: var(--lq-text-secondary, #4f5158);
		color: white;
	}
	.lq-tone-neutral.lq-btn-outline {
		border-color: var(--lq-border-strong, #80828a);
		color: var(--lq-text, #111114);
		background: transparent;
	}
	.lq-tone-neutral.lq-btn-subtle {
		background: var(--lq-inset, #f9f9fa);
		color: var(--lq-text, #111114);
	}
	.lq-tone-neutral.lq-btn-ghost {
		background: transparent;
		color: var(--lq-text, #111114);
	}

	.lq-btn:not(:disabled):hover {
		filter: brightness(0.95);
	}
	/* brightness() does not show on an ink fill; lighten it instead. */
	.lq-btn-filled.lq-tone-accent:not(:disabled):hover,
	.lq-btn-filled.lq-tone-info:not(:disabled):hover,
	.lq-btn-filled.lq-tone-warning:not(:disabled):hover {
		filter: none;
		background: color-mix(in srgb, var(--lq-accent, #111114) 82%, white);
	}
</style>
