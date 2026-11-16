<script lang="ts">
	/**
	 * What a chat shows in the right sidebar while the developer switch is on
	 * (interface-redesign work plan, Annex B P1.4): the same
	 * `AttachedFilesPanel` (inside the same `CompactPanel` as today) and,
	 * when the receipts toggle has it open, the same `ReceiptsDrawer`, with
	 * the same props ChatPanel passes them with the switch off. Only the place
	 * changes: ChatPanel publishes this component to the shared right sidebar
	 * instead of rendering the two panels beside the chat column.
	 */
	import type { FileMeta } from '../types';
	import AttachedFilesPanel from './AttachedFilesPanel.svelte';
	import CompactPanel from './CompactPanel.svelte';
	import ReceiptsDrawer from './ReceiptsDrawer.svelte';

	export let chatId: string;
	export let chatFiles: FileMeta[] = [];
	export let newHarness = false;
	export let projectFiles: FileMeta[] = [];
	export let uploading = false;
	export let attachLimitReached = false;
	export let onUpload: (file: File) => void = () => undefined;
	export let onDetach: (file: FileMeta) => void = () => undefined;
	/** True in a matter, where ChatPanel collapses its panels on narrow screens. */
	export let compact = false;
	export let receiptsOpen = false;
	export let onCloseReceipts: () => void = () => undefined;
</script>

<div class="lq-chat-details" data-testid="lq-chat-details">
	<CompactPanel id="matter-files" title="Attached files" enabled={compact}>
		<AttachedFilesPanel
			{chatFiles}
			{newHarness}
			{projectFiles}
			{uploading}
			{attachLimitReached}
			{onUpload}
			{onDetach}
		/>
	</CompactPanel>

	{#if receiptsOpen}
		<ReceiptsDrawer open={receiptsOpen} {chatId} onClose={onCloseReceipts} embedded />
	{/if}
</div>

<style>
	.lq-chat-details {
		display: flex;
		flex-direction: column;
		min-height: 0;
	}
	/* The files panel brings its own column width and left border for its
	   place beside the chat; inside the sidebar it takes the sidebar's width. */
	.lq-chat-details :global(.lq-files-panel) {
		width: auto;
		border-left: 0;
		overflow-y: visible;
	}
</style>
