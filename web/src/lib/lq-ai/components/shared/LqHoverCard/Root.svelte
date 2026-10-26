<script lang="ts">
	/**
	 * LqHoverCard.Root — owns hover/focus-open state, shared via context so
	 * `LqHoverCard.Target` and `LqHoverCard.Dropdown` (nested anywhere in the
	 * default slot) don't need the state wired through manually. Assembled
	 * onto one namespaced export in `./index.ts` — usage is:
	 *
	 *   <LqHoverCard>
	 *     <LqHoverCard.Target>...</LqHoverCard.Target>
	 *     <LqHoverCard.Dropdown>...</LqHoverCard.Dropdown>
	 *   </LqHoverCard>
	 *
	 * Modeled on Mantine's HoverCard / HoverCard.Target / HoverCard.Dropdown.
	 * Opens on mouseenter/focusin, closes on mouseleave/focusout after
	 * `closeDelay` — the delay (and the fact both Target and Dropdown live
	 * inside this same hover region) keeps it open while the pointer moves
	 * from the target into the dropdown. Focus events (not just hover) keep
	 * this reachable by keyboard, not just mouse.
	 */
	import { onDestroy, setContext } from 'svelte';
	import { writable } from 'svelte/store';
	import { LQ_HOVERCARD_CONTEXT_KEY, type LqHoverCardContext } from './context';

	export let closeDelay = 100;

	const opened = writable(false);
	const anchorEl = writable<HTMLElement | null>(null);
	let closeTimer: ReturnType<typeof setTimeout> | undefined;
	let wrapperEl: HTMLDivElement;

	function open(): void {
		clearTimeout(closeTimer);
		opened.set(true);
	}

	function scheduleClose(): void {
		clearTimeout(closeTimer);
		closeTimer = setTimeout(() => opened.set(false), closeDelay);
	}

	function handleKeydown(event: KeyboardEvent): void {
		if ($opened && event.key === 'Escape') {
			clearTimeout(closeTimer);
			opened.set(false);
		}
	}

	onDestroy(() => clearTimeout(closeTimer));

	const context: LqHoverCardContext = { opened, anchorEl, open, scheduleClose };
	setContext(LQ_HOVERCARD_CONTEXT_KEY, context);

	$: anchorEl.set(wrapperEl ?? null);
	let klass = '';
	export { klass as class };
</script>

<svelte:window on:keydown={handleKeydown} />

<div
	{...$$restProps}
	class="lq-hovercard-wrapper {klass}"
	role="group"
	bind:this={wrapperEl}
	on:mouseenter={open}
	on:mouseleave={scheduleClose}
	on:focusin={open}
	on:focusout={scheduleClose}
>
	<slot />
</div>

<style>
	.lq-hovercard-wrapper {
		position: relative;
		display: inline-block;
	}
</style>
