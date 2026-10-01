<script lang="ts">
	import type { LqVariant, LqTone, LqSize } from './types';

	export let variant: LqVariant = 'filled';
	export let tone: LqTone = 'sage';
	export let size: LqSize = 'md';
	export let disabled = false;
	export let type: 'button' | 'submit' | 'reset' = 'button';
</script>

<button
	{type}
	{disabled}
	{...$$restProps}
	class="lq-btn lq-btn-{variant} lq-btn-{size} lq-tone-{tone}"
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
		border-radius: var(--lq-radius, 6px);
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
		outline: 2px solid var(--lq-accent, #1f7a6b);
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

	/* tone: sage */
	.lq-tone-sage.lq-btn-filled {
		background: var(--lq-accent, #1f7a6b);
		color: white;
	}
	.lq-tone-sage.lq-btn-outline {
		border-color: var(--lq-accent, #1f7a6b);
		color: var(--lq-accent, #1f7a6b);
		background: transparent;
	}
	.lq-tone-sage.lq-btn-subtle {
		background: var(--lq-accent-soft, #e8f4ec);
		color: var(--lq-accent, #1f7a6b);
	}
	.lq-tone-sage.lq-btn-ghost {
		background: transparent;
		color: var(--lq-accent, #1f7a6b);
	}

	/* tone: slate */
	.lq-tone-slate.lq-btn-filled {
		background: var(--lq-tier, #355a82);
		color: white;
	}
	.lq-tone-slate.lq-btn-outline {
		border-color: var(--lq-tier, #355a82);
		color: var(--lq-tier, #355a82);
		background: transparent;
	}
	.lq-tone-slate.lq-btn-subtle {
		background: var(--lq-tier-soft, #e8eff7);
		color: var(--lq-tier, #355a82);
	}
	.lq-tone-slate.lq-btn-ghost {
		background: transparent;
		color: var(--lq-tier, #355a82);
	}

	/* tone: amber */
	.lq-tone-amber.lq-btn-filled {
		background: var(--lq-warn, #a16e1f);
		color: white;
	}
	.lq-tone-amber.lq-btn-outline {
		border-color: var(--lq-warn, #a16e1f);
		color: var(--lq-warn, #a16e1f);
		background: transparent;
	}
	.lq-tone-amber.lq-btn-subtle {
		background: var(--lq-warn-soft, #fdf3e2);
		color: var(--lq-warn, #a16e1f);
	}
	.lq-tone-amber.lq-btn-ghost {
		background: transparent;
		color: var(--lq-warn, #a16e1f);
	}

	/* tone: red */
	.lq-tone-red.lq-btn-filled {
		background: var(--lq-error, #b54848);
		color: white;
	}
	.lq-tone-red.lq-btn-outline {
		border-color: var(--lq-error, #b54848);
		color: var(--lq-error, #b54848);
		background: transparent;
	}
	.lq-tone-red.lq-btn-subtle {
		background: var(--lq-error-soft, #fbeaea);
		color: var(--lq-error, #b54848);
	}
	.lq-tone-red.lq-btn-ghost {
		background: transparent;
		color: var(--lq-error, #b54848);
	}

	/* tone: neutral */
	.lq-tone-neutral.lq-btn-filled {
		background: var(--lq-text-secondary, #4b5563);
		color: white;
	}
	.lq-tone-neutral.lq-btn-outline {
		border-color: var(--lq-border-strong, #d4d4d4);
		color: var(--lq-text, #1a1a1a);
		background: transparent;
	}
	.lq-tone-neutral.lq-btn-subtle {
		background: var(--lq-inset, #fafbfa);
		color: var(--lq-text, #1a1a1a);
	}
	.lq-tone-neutral.lq-btn-ghost {
		background: transparent;
		color: var(--lq-text, #1a1a1a);
	}

	.lq-btn:not(:disabled):hover {
		filter: brightness(0.95);
	}
</style>
