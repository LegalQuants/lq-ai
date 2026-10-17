<script lang="ts">
	import { afterUpdate } from 'svelte';

	import type { OrchestrationChatRun } from '../api/orchestration';
	import type { Message } from '../types';
	import type { PendingGate } from '../chat/toolGate';
	import MessageBubble from './MessageBubble.svelte';

	export let messages: Message[] = [];
	/**
	 * True while New harness is the chat's model. The empty thread then says nothing of
	 * skills, and the thread keeps a few lines when the composer's folds are open.
	 */
	export let newHarness = false;
	export let streamingMessageId: string | null = null;
	export let onAppliedSkillClicked: ((name: string) => void) | undefined = undefined;

	// ADR 0038 D1 — a governed run in the thread reached a finished state. ChatPanel
	// reads that message row again; MessageList only passes the callback through.
	export let onRunSettled: ((message: Message, run: OrchestrationChatRun) => void) | undefined =
		undefined;
	// Every read of a run in the thread, for the composer's active-run notice.
	export let onRunUpdate: ((message: Message, run: OrchestrationChatRun) => void) | undefined =
		undefined;

	// Wave D.1 T15 — refusal-bubble forwarding. ChatPanel owns the modal +
	// re-run state; MessageList is a pure pass-through so the bubble can fire
	// the three callbacks per refusal row.
	export let currentUserRole: 'admin' | 'member' | 'viewer' = 'member';
	export let onRefusalRerun: (msg: Message) => void = () => {};
	export let onRefusalOverrideRequested: (msg: Message) => void = () => {};
	export let onRefusalExplainerRequested: (msg: Message) => void = () => {};

	// Wave D.1 T20 follow-on — map of enhanced-prompt content → original
	// prompt text the user typed before clicking "Use enhanced". Session
	// scope only (server stores only the enhanced text; the original is
	// not currently persisted — see EnhancedDiffModal docstring). Empty
	// map is fine: MessageBubble renders a graceful fallback.
	export let enhancementOriginals: Record<string, string> = {};

	// PR6b — governed tool-loop gate. ChatPanel owns the pending gate + the
	// resume/connect handlers; MessageList is a pure pass-through, rendering the
	// gate card only on the assistant message whose turn paused.
	export let pendingGate: PendingGate | null = null;
	export let gateBusy = false;
	export let onGateApprove: () => void = () => {};
	export let onGateDeny: () => void = () => {};
	export let onGateConnect: () => void = () => {};

	let scroller: HTMLDivElement;

	afterUpdate(() => {
		// Stick to bottom while messages stream in. The user can still scroll
		// up; this is a lightweight auto-scroll that re-anchors on each
		// message append.
		if (scroller) {
			scroller.scrollTop = scroller.scrollHeight;
		}
	});
</script>

<div
	bind:this={scroller}
	class="flex-1 overflow-y-auto px-4 py-4 flex flex-col"
	style:min-height={newHarness ? '4rem' : null}
	data-testid="lq-ai-message-list"
>
	{#each messages as msg (msg.id)}
		<MessageBubble
			message={msg}
			isStreaming={streamingMessageId === msg.id}
			{onAppliedSkillClicked}
			{currentUserRole}
			{onRefusalRerun}
			{onRefusalOverrideRequested}
			{onRefusalExplainerRequested}
			originalEnhancedPrompt={enhancementOriginals[msg.content]}
			gateForMessage={pendingGate && pendingGate.assistantId === msg.id ? pendingGate : null}
			{gateBusy}
			{onGateApprove}
			{onGateDeny}
			{onGateConnect}
			{onRunSettled}
			{onRunUpdate}
		/>
	{/each}

	{#if messages.length === 0}
		<div class="flex-1 flex items-center justify-center text-gray-400 text-sm italic">
			{#if newHarness}
				No messages yet. Type a request and send it. New harness answers a request that needs
				nothing read, and otherwise proposes a plan for you to approve.
			{:else}
				No messages yet. Attach a skill, optionally upload a file, and send a message.
			{/if}
		</div>
	{/if}
</div>
