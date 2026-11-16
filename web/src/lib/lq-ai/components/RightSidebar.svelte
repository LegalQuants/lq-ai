<script lang="ts">
	/**
	 * The contextual right sidebar of the redesigned LQ.AI shell
	 * (interface-redesign work plan, Annex B P1.4; proposed ADR 0045 C6, C19),
	 * rendered by `routes/lq-ai/+layout.svelte` on signed-in routes.
	 *
	 * It shows what the current page published (`$lib/lq-ai/rightSidebar`):
	 * one shared frame (a 340 px column with a heading row and a close button)
	 * around the page's own component. It is absent when nothing is published
	 * and when the person closed it, so the middle column widens. Below
	 * 1280 px it is a sheet over the page. Escape or the close button closes
	 * it and returns focus to the header's toggle.
	 *
	 * Shell content (the notification list, P1.3b) can show over the page's
	 * own (`showRightSidebarOverlay`). Closing it only dismisses it, returning
	 * focus to the control that opened it; the page's content and remembered
	 * state come back untouched. Moving to another page dismisses it too.
	 */
	import { onMount } from 'svelte';
	import { IconX } from '@tabler/icons-svelte';
	import {
		RIGHT_SIDEBAR_ID,
		NARROW_QUERY,
		clearRightSidebarOverlay,
		closeRightSidebar,
		focusRightSidebarOpener,
		handleRightSidebarKeydown,
		rightSidebarContent,
		rightSidebarMode,
		rightSidebarNarrow,
		rightSidebarOpen,
		rightSidebarOverlayLabel,
		syncRightSidebarForPage
	} from '../rightSidebar';

	/** The current page; the open or closed state is remembered per page. */
	export let pathname: string;

	onMount(() => {
		const query = window.matchMedia?.(NARROW_QUERY);
		const apply = () => rightSidebarNarrow.set(!!query?.matches);
		apply();
		query?.addEventListener?.('change', apply);
		return () => query?.removeEventListener?.('change', apply);
	});

	// A shell overlay belongs to the page it was opened on.
	let overlayPage = pathname;
	$: if (pathname !== overlayPage) {
		overlayPage = pathname;
		clearRightSidebarOverlay();
	}

	$: syncRightSidebarForPage(pathname, $rightSidebarNarrow);

	$: mode = rightSidebarMode({
		hasContent: !!$rightSidebarContent,
		open: $rightSidebarOverlayLabel !== null || $rightSidebarOpen,
		narrow: $rightSidebarNarrow
	});

	function close(): void {
		const closed = closeRightSidebar(pathname, $rightSidebarNarrow);
		if (closed.overlay && closed.opener?.isConnected) closed.opener.focus();
		else focusRightSidebarOpener();
	}

	function onKeydown(event: KeyboardEvent): void {
		handleRightSidebarKeydown(event, close);
	}
</script>

{#if (mode === 'open' || mode === 'sheet') && $rightSidebarContent}
	<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
	<aside
		id={RIGHT_SIDEBAR_ID}
		class="lq-right-sidebar"
		class:lq-right-sidebar-sheet={mode === 'sheet'}
		aria-label={$rightSidebarContent.label}
		data-testid="lq-right-sidebar"
		data-mode={mode}
		on:keydown={onKeydown}
	>
		<div class="lq-right-sidebar-head">
			<h2 class="lq-right-sidebar-title">{$rightSidebarContent.label}</h2>
			<button
				type="button"
				class="lq-right-sidebar-close"
				aria-label={`Close ${$rightSidebarContent.label.toLowerCase()}`}
				title="Close"
				data-right-sidebar-close
				data-testid="lq-right-sidebar-close"
				on:click={close}
			>
				<IconX size={16} aria-hidden="true" />
			</button>
		</div>
		<div class="lq-right-sidebar-body">
			<svelte:component this={$rightSidebarContent.component} {...$rightSidebarContent.props} />
		</div>
	</aside>
{/if}

<style>
	.lq-right-sidebar {
		width: 340px;
		min-width: 0;
		min-height: 0;
		display: flex;
		flex-direction: column;
		background: var(--lq-inset);
		border-left: 1px solid var(--lq-border);
		color: var(--lq-text);
	}
	.lq-right-sidebar-head {
		height: 52px;
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--lq-space-2);
		padding: 0 var(--lq-space-2) 0 var(--lq-space-4);
		border-bottom: 1px solid var(--lq-border);
	}
	.lq-right-sidebar-title {
		margin: 0;
		font-size: 13px;
		font-weight: 600;
		/* Secondary, not tertiary: tertiary fails 4.5:1 at this size on --lq-inset. */
		color: var(--lq-text-secondary);
	}
	.lq-right-sidebar-close {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		border: 0;
		border-radius: var(--lq-radius-pill);
		background: transparent;
		color: var(--lq-text-secondary);
		cursor: pointer;
	}
	.lq-right-sidebar-close:hover {
		background: var(--lq-surface-hover);
		color: var(--lq-text);
	}
	.lq-right-sidebar-close:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.lq-right-sidebar-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
	}
	/* Narrow screens: a sheet over the page, from the right edge. */
	.lq-right-sidebar-sheet {
		position: fixed;
		top: 0;
		right: 0;
		bottom: 0;
		z-index: 40;
		width: min(340px, 100vw);
		border-left: 1px solid var(--lq-border);
	}
</style>
