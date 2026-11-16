<script lang="ts">
	/**
	 * The chat page's own chat list on narrow screens (houfu's ruling on the
	 * sidebar cutover, 11 Nov). Below 1280 px, the shell's one breakpoint
	 * (`NARROW_QUERY`, the same as `CompactPanel` and both sidebars), the list
	 * becomes a sheet over the page, opened by a labelled toggle and closed by
	 * the toggle, Escape, the backdrop or choosing a chat; focus returns to the
	 * toggle. It starts closed, so the conversation and the composer get the
	 * width. On wide screens the wrapper renders as if absent (`display:
	 * contents`) and the toggle is hidden: the list sits beside the chat as
	 * before.
	 *
	 * ChatPanel uses it only outside a matter; a matter page keeps its own
	 * `CompactPanel` toggles (`#matter-chats-toggle`).
	 */
	import { tick } from 'svelte';
	import { IconMessages } from '@tabler/icons-svelte';
	import { drawerKeydown, firstVisibleFocusable } from '../chatListDrawer';

	export let id = 'lq-chat-list';
	/** Off: the wrapper renders as if absent at every width (a matter page). */
	export let enabled = true;
	export let label = 'Chats';
	export let open = false;

	let toggleEl: HTMLButtonElement | undefined;
	let sheetEl: HTMLDivElement | undefined;

	/** Close the sheet; focus returns to the toggle. */
	export async function close(): Promise<void> {
		if (!open) return;
		open = false;
		await tick();
		toggleEl?.focus();
	}

	async function toggle(): Promise<void> {
		if (open) return close();
		open = true;
		await tick();
		// The first control the person can see (the list holds a hidden matter toggle).
		firstVisibleFocusable(sheetEl)?.focus();
	}
</script>

<div class="chat-list-drawer" class:enabled>
	<button
		bind:this={toggleEl}
		id="{id}-toggle"
		type="button"
		class="drawer-toggle"
		aria-expanded={open}
		aria-controls="{id}-sheet"
		data-testid="lq-chat-list-toggle"
		on:click={toggle}
		on:keydown={(event) => drawerKeydown(event, open, () => void close())}
	>
		<IconMessages size={16} stroke={1.75} aria-hidden="true" />
		<span>{label}</span>
	</button>
	{#if open}
		<!-- The backdrop is a pointer convenience; Escape and the toggle close it from the keyboard. -->
		<div class="drawer-backdrop" role="presentation" on:click={() => void close()}></div>
	{/if}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		bind:this={sheetEl}
		id="{id}-sheet"
		class="drawer-sheet"
		class:open
		data-testid="lq-chat-list-sheet"
		on:keydown={(event) => drawerKeydown(event, open, () => void close())}
	>
		<slot />
	</div>
</div>

<style>
	.chat-list-drawer,
	.drawer-sheet {
		display: contents;
	}
	.drawer-toggle,
	.drawer-backdrop {
		display: none;
	}

	@media (max-width: 1279px) {
		.chat-list-drawer.enabled {
			display: block;
			flex-shrink: 0;
			min-width: 0;
		}
		.enabled > .drawer-toggle {
			display: flex;
			align-items: center;
			gap: 8px;
			width: 100%;
			padding: 6px 12px;
			border: 0;
			border-bottom: 1px solid var(--lq-border);
			background: var(--lq-inset);
			color: var(--lq-text);
			font-size: 13px;
			text-align: left;
		}
		.drawer-toggle:focus-visible {
			outline: 2px solid var(--lq-accent);
			outline-offset: -2px;
		}
		.enabled > .drawer-backdrop {
			display: block;
			position: fixed;
			inset: 0;
			z-index: 42;
			background: var(--lq-text);
			opacity: 0.2;
		}
		.enabled > .drawer-sheet {
			display: none;
		}
		.enabled > .drawer-sheet.open {
			display: flex;
			position: fixed;
			top: 0;
			bottom: 0;
			left: 0;
			z-index: 43;
			width: min(320px, calc(100vw - 48px));
			overflow-y: auto;
			background: var(--lq-canvas);
			border-right: 1px solid var(--lq-border);
		}
		.enabled > .drawer-sheet.open > :global(*) {
			width: 100%;
		}
	}
</style>
