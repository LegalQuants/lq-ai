<script lang="ts">
	/**
	 * The page header of the redesigned LQ.AI shell (interface-redesign work
	 * plan, Annex B P1.4; proposed ADR 0045 C14): a 52 px row over the main
	 * column only, not over either sidebar. Rendered by
	 * `routes/lq-ai/+layout.svelte` only while the developer switch is on, and
	 * only when the current page published a title (`$lib/lq-ai/rightSidebar`).
	 *
	 * When the page also published right-sidebar content, the header carries
	 * the toggle that shows and hides it. The toggle is where focus returns
	 * when the sidebar closes.
	 */
	import { tick } from 'svelte';
	import { IconLayoutSidebarRight } from '@tabler/icons-svelte';
	import {
		RIGHT_SIDEBAR_ID,
		closeRightSidebar,
		focusRightSidebar,
		pageHeaderContent,
		rightSidebarContent,
		rightSidebarNarrow,
		rightSidebarOpen,
		rightSidebarOverlayLabel,
		setRightSidebarOpen
	} from '../rightSidebar';

	/** The current page; the sidebar's state is remembered per page. */
	export let pathname: string;

	$: label = $rightSidebarContent?.label.toLowerCase() ?? '';
	// Shell content shown over the page's own (the notification list) is always open.
	$: shown = $rightSidebarOverlayLabel !== null || $rightSidebarOpen;

	async function toggle(): Promise<void> {
		if (shown) {
			closeRightSidebar(pathname, $rightSidebarNarrow);
			return;
		}
		setRightSidebarOpen(pathname, true, $rightSidebarNarrow);
		await tick();
		focusRightSidebar();
	}
</script>

{#if $pageHeaderContent}
	<header class="lq-page-header" data-testid="lq-page-header">
		<h1 class="lq-page-header-title">{$pageHeaderContent.title}</h1>
		{#if $rightSidebarContent}
			<button
				type="button"
				class="lq-page-header-toggle"
				aria-controls={RIGHT_SIDEBAR_ID}
				aria-expanded={shown}
				aria-label={shown ? `Hide ${label}` : `Show ${label}`}
				title={shown ? `Hide ${label}` : `Show ${label}`}
				data-testid="lq-page-header-sidebar-toggle"
				on:click={toggle}
			>
				<IconLayoutSidebarRight size={18} aria-hidden="true" />
			</button>
		{/if}
	</header>
{/if}

<style>
	.lq-page-header {
		height: 52px;
		box-sizing: border-box;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--lq-space-3);
		padding: 0 var(--lq-space-4) 0 var(--lq-space-6);
		border-bottom: 1px solid var(--lq-border);
		background: var(--lq-canvas);
		min-width: 0;
	}
	.lq-page-header-title {
		margin: 0;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 14.5px;
		font-weight: 600;
		color: var(--lq-text);
	}
	.lq-page-header-toggle {
		flex-shrink: 0;
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
	.lq-page-header-toggle:hover {
		background: var(--lq-surface-hover);
		color: var(--lq-text);
	}
	.lq-page-header-toggle[aria-expanded='true'] {
		color: var(--lq-text);
	}
	.lq-page-header-toggle:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
</style>
