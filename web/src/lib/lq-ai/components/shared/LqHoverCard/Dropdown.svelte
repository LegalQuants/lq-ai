<script lang="ts">
	/**
	 * LqHoverCard.Dropdown — the popover content, shown while `Root`'s hover
	 * region reports `opened`. Visual props (shadow/width/padding) live here
	 * rather than on Root, mirroring Mantine's HoverCard.Dropdown.
	 *
	 * Rendered through bits-ui's `Portal` into `document.body` so it isn't
	 * clipped by an `overflow: hidden`/`auto` ancestor (e.g. the scrolling
	 * message list) — z-index can't rescue an element from being clipped by
	 * an ancestor's overflow, only a portal can. Because it's no longer a DOM
	 * descendant of Root's hover-region div, position is computed from the
	 * anchor's `getBoundingClientRect()` (not CSS `position: absolute`
	 * relative to a parent), and this element needs its own mouseenter/
	 * mouseleave — hovering it no longer implicitly counts as hovering Root's
	 * region the way DOM nesting used to give us for free.
	 */
	import { getContext, onMount } from 'svelte';
	import { Portal } from 'bits-ui';
	import { LQ_GAPS, LQ_GAP_VAR, LQ_SHADOW_VAR, type LqGap, type LqShadow } from '../types';
	import { LQ_HOVERCARD_CONTEXT_KEY, type LqHoverCardContext } from './context';

	export let shadow: LqShadow = 'md';
	export let width: number | string = 'max-content';
	export let padding: LqGap | number | string = 'md';

	const { opened, anchorEl, open, scheduleClose } =
		getContext<LqHoverCardContext>(LQ_HOVERCARD_CONTEXT_KEY);

	let top = 0;
	let left = 0;

	function reposition(): void {
		const el = $anchorEl;
		if (!el) return;
		const rect = el.getBoundingClientRect();
		top = rect.bottom + 4;
		left = rect.left;
	}

	function handleWindowChange(): void {
		if ($opened) reposition();
	}

	$: if ($opened) reposition();

	onMount(() => {
		// `scroll` doesn't bubble, but a capture-phase listener on window
		// still sees it fire on any nested scrollable ancestor.
		window.addEventListener('scroll', handleWindowChange, true);
		window.addEventListener('resize', handleWindowChange);
		return () => {
			window.removeEventListener('scroll', handleWindowChange, true);
			window.removeEventListener('resize', handleWindowChange);
		};
	});

	$: resolvedPadding =
		typeof padding === 'string' && (LQ_GAPS as readonly string[]).includes(padding)
			? LQ_GAP_VAR[padding as LqGap]
			: typeof padding === 'number'
				? `${padding}px`
				: padding;
</script>

{#if $opened}
	<Portal to="body">
		<div
			class="lq-hovercard-dropdown"
			style:top="{top}px"
			style:left="{left}px"
			style:width
			style:padding={resolvedPadding}
			style:box-shadow={LQ_SHADOW_VAR[shadow]}
			role="tooltip"
			on:mouseenter={open}
			on:mouseleave={scheduleClose}
		>
			<slot />
		</div>
	</Portal>
{/if}

<style>
	.lq-hovercard-dropdown {
		position: fixed;
		z-index: 50;
		background: var(--lq-canvas, #fff);
		border: 1px solid var(--lq-border, #e5e7eb);
		border-radius: var(--lq-radius-lg, 8px);
	}
</style>
