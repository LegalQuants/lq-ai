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
	export let tone: LqTone = 'accent';
	export let onCheckedChange: ((checked: boolean) => void) | undefined = undefined;
	let klass = '';
	export { klass as class };
</script>

<Switch.Root
	{...$$restProps}
	bind:checked
	{disabled}
	{onCheckedChange}
	class="lq-switch lq-switch-tone-{tone} {klass}"
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
		background: var(--lq-border, #e4e4e7);
		cursor: pointer;
		transition: background 120ms ease;
	}
	:global(.lq-switch:disabled) {
		cursor: not-allowed;
		opacity: 0.5;
	}
	:global(.lq-switch:focus-visible) {
		outline: 2px solid var(--lq-accent, #111114);
		outline-offset: 2px;
	}

	:global(.lq-switch-tone-accent[data-state='checked']) {
		background: var(--lq-accent, #111114);
	}
	:global(.lq-switch-tone-governance[data-state='checked']) {
		background: var(--lq-governance, #a34a00);
	}
	:global(.lq-switch-tone-info[data-state='checked']) {
		background: var(--lq-info, #111114);
	}
	:global(.lq-switch-tone-warning[data-state='checked']) {
		background: var(--lq-warning, #111114);
	}
	:global(.lq-switch-tone-danger[data-state='checked']) {
		background: var(--lq-danger, #b42318);
	}
	:global(.lq-switch-tone-neutral[data-state='checked']) {
		background: var(--lq-text-secondary, #4f5158);
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
