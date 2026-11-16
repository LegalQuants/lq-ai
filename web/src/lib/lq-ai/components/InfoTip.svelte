<script context="module" lang="ts">
	/**
	 * Helpers exported for unit tests — accessible without
	 * @testing-library/svelte (mirrors the AttachKBModal / NewMatterModal
	 * pattern; per CLAUDE.md "Don't add libraries without justification").
	 */

	/** Build a stable id for `aria-describedby` wiring. */
	export function infoTipId(seed: string): string {
		// Strip non-alphanumeric so the id is selector-safe.
		return `infotip-${seed.replace(/[^a-z0-9]/gi, '').slice(0, 20) || 'x'}-${Math.floor(Math.random() * 1e6)}`;
	}

	/**
	 * Resolve the accessible name shown in `aria-label` and the visible
	 * trigger title. Falls back to a generic phrase when no label is
	 * supplied so screen readers still hear something meaningful.
	 */
	export function infoTipAccessibleName(label: string | undefined): string {
		const trimmed = (label ?? '').trim();
		return trimmed ? `More info about ${trimmed}` : 'More info';
	}
</script>

<script lang="ts">
	/**
	 * InfoTip — small ⓘ trigger with a hover/focus/click tooltip.
	 *
	 * Designed for non-technical-user-facing surfaces where a short
	 * explanation aids comprehension without committing the user to
	 * clicking through a separate detail panel. Use sparingly — one
	 * InfoTip per labelled control or section header, not one per pill.
	 *
	 * Accessibility:
	 *   - The trigger is a real <button> so it's keyboard-focusable.
	 *   - The tooltip carries `role="tooltip"` and is wired to the
	 *     trigger via `aria-describedby` when visible.
	 *   - Esc closes the tooltip when focus is inside the component.
	 *   - Hover, focus, and click each open the tooltip; click also
	 *     toggles so touch users have a tap-to-pin path.
	 *
	 * No external dependencies — pure CSS positioning, single Svelte
	 * component. Use LQ.AI design tokens so the tooltip styling
	 * matches the rest of the ambient chrome.
	 */

	/** Explanatory text shown inside the tooltip. Plain text only. */
	export let content: string;

	/** Optional visible label rendered before the ⓘ icon. */
	export let label: string = '';

	/** Where the tooltip pops relative to the trigger. */
	export let placement: 'top' | 'bottom' = 'top';

	/** Stable id used by aria-describedby — generated per-instance. */
	const tooltipId = infoTipId(label || content.slice(0, 8));

	let show = false;

	function open() {
		show = true;
	}
	function close() {
		show = false;
	}
	function toggle() {
		show = !show;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			show = false;
		}
	}
</script>

<!--
  Wrapper <span> stays inline so callers can drop the InfoTip next to a
  label, a checkbox, or another inline control without breaking layout.
-->
<!-- svelte-ignore a11y-no-static-element-interactions -->
<span class="lq-infotip" on:keydown={handleKeydown}>
	{#if label}<span class="lq-infotip-label">{label}</span>{/if}
	<button
		type="button"
		class="lq-infotip-trigger"
		aria-label={infoTipAccessibleName(label)}
		aria-describedby={show ? tooltipId : undefined}
		aria-expanded={show}
		data-testid="lq-infotip-trigger"
		on:mouseenter={open}
		on:mouseleave={close}
		on:focus={open}
		on:blur={close}
		on:click|stopPropagation={toggle}
	>
		<svg
			aria-hidden="true"
			focusable="false"
			width="14"
			height="14"
			viewBox="0 0 14 14"
			fill="currentColor"
		>
			<path
				d="M7 0a7 7 0 100 14A7 7 0 007 0zm0 1.4A5.6 5.6 0 117 12.6 5.6 5.6 0 017 1.4zm-.7 8.4h1.4v-3H6.3v3zm.7-4.55a.875.875 0 100-1.75.875.875 0 000 1.75z"
			/>
		</svg>
	</button>
	{#if show}
		<span
			id={tooltipId}
			role="tooltip"
			class="lq-infotip-content lq-infotip-{placement}"
			data-testid="lq-infotip-content"
		>
			{content}
		</span>
	{/if}
</span>

<style>
	.lq-infotip {
		position: relative;
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}
	/* .lq-infotip-label intentionally inherits parent font — no explicit rule. */
	.lq-infotip-trigger {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 16px;
		height: 16px;
		padding: 0;
		border: 0;
		background: transparent;
		color: var(--lq-text-tertiary);
		cursor: help;
		border-radius: 50%;
		transition: color 0.15s ease;
	}
	.lq-infotip-trigger:hover,
	.lq-infotip-trigger:focus-visible {
		color: var(--lq-accent);
		outline: none;
	}
	.lq-infotip-trigger:focus-visible {
		box-shadow: 0 0 0 2px var(--lq-accent-soft);
	}
	.lq-infotip-content {
		position: absolute;
		z-index: 50;
		min-width: 200px;
		max-width: 320px;
		padding: 8px 10px;
		background: var(--lq-canvas);
		color: var(--lq-text-primary);
		border: 1px solid var(--lq-border);
		border-radius: 6px;
		box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
		font-size: 12px;
		line-height: 1.5;
		text-align: left;
		pointer-events: none;
	}
	.lq-infotip-top {
		bottom: calc(100% + 6px);
		left: 50%;
		transform: translateX(-50%);
	}
	.lq-infotip-bottom {
		top: calc(100% + 6px);
		left: 50%;
		transform: translateX(-50%);
	}
</style>
