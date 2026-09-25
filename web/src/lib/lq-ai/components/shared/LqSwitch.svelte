<script lang="ts">
	/**
	 * LqSwitch — styled wrapper around bits-ui's headless Switch.
	 *
	 * bits-ui supplies behavior/accessibility (role="switch", keyboard
	 * toggling, data-state) with zero visual opinion; this component supplies
	 * the tone-based look, same pattern LqHoverCard uses for bits-ui's
	 * Portal. Only the switch control itself — no label. Compose a label via
	 * `LqGroup` + `LqText` alongside it, same as any other primitive.
	 */
	import { Switch } from 'bits-ui';
	import type { LqTone } from './types';

	export let checked = false;
	export let disabled = false;
	export let tone: LqTone = 'sage';
	export let onCheckedChange: ((checked: boolean) => void) | undefined = undefined;
</script>

<Switch.Root
	bind:checked
	{disabled}
	{onCheckedChange}
	class="lq-switch lq-switch-tone-{tone}"
>
	<Switch.Thumb class="lq-switch-thumb" />
</Switch.Root>

<style>
	:global(.lq-switch) {
		all: unset;
		box-sizing: border-box;
		display: inline-flex;
		align-items: center;
		width: 32px;
		height: 18px;
		padding: 2px;
		border-radius: 999px;
		background: var(--lq-border, #e5e7eb);
		cursor: pointer;
		transition: background 120ms ease;
	}
	:global(.lq-switch:disabled) {
		cursor: not-allowed;
		opacity: 0.5;
	}
	:global(.lq-switch:focus-visible) {
		outline: 2px solid var(--lq-accent, #1f7a6b);
		outline-offset: 2px;
	}

	:global(.lq-switch-tone-sage[data-state='checked']) {
		background: var(--lq-accent, #1f7a6b);
	}
	:global(.lq-switch-tone-slate[data-state='checked']) {
		background: var(--lq-tier, #355a82);
	}
	:global(.lq-switch-tone-amber[data-state='checked']) {
		background: var(--lq-warn, #a16e1f);
	}
	:global(.lq-switch-tone-red[data-state='checked']) {
		background: var(--lq-error, #b54848);
	}
	:global(.lq-switch-tone-neutral[data-state='checked']) {
		background: var(--lq-text-secondary, #4b5563);
	}

	:global(.lq-switch-thumb) {
		width: 14px;
		height: 14px;
		border-radius: 999px;
		background: white;
		transition: transform 120ms ease;
	}
	:global(.lq-switch-thumb[data-state='checked']) {
		transform: translateX(14px);
	}
</style>
