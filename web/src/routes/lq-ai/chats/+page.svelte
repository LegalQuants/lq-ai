<script lang="ts">
	/**
	 * /lq-ai/chats — thin route wrapper around <ChatPanel>.
	 *
	 * The chat composition was extracted into a reusable component in
	 * Wave C Task 0 so /lq-ai/matters/[id] can mount the same surface
	 * inside the matter workspace. URL query params:
	 *
	 *   ?id={chatId}       — auto-selects that chat on load
	 *   ?project_id={id}   — filters chat list to that project
	 *
	 * PR6b — MCP connect-on-demand return. When a tool-gate "Connect" redirect
	 * (ChatPanel.connectMcp → gateway authorize URL) completes, PR4d lands back
	 * here with `?mcp_connected` (or `?mcp_error&server=`). We surface a banner
	 * with a Continue button that re-sends the last user message so the paused
	 * turn resumes, then strip the query so a refresh doesn't re-trigger it.
	 */
	import { onMount } from 'svelte';
	import { get } from 'svelte/store';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import ChatPanel from '$lib/lq-ai/components/ChatPanel.svelte';
	import { parseOAuthReturn } from '$lib/lq-ai/chat/toolGate';

	$: initialChatId = $page.url.searchParams.get('id') ?? undefined;
	$: projectIdFilter = $page.url.searchParams.get('project_id') ?? undefined;

	let chatPanel: ChatPanel | null = null;
	let mcpReturn: { status: 'connected' | 'error'; server: string | null } | null = null;

	onMount(() => {
		const r = parseOAuthReturn(get(page).url.searchParams);
		if (r.status === 'none') return;
		mcpReturn = { status: r.status, server: r.server };
		// Strip the OAuth-return params so a refresh doesn't re-trigger the banner.
		const url = new URL(get(page).url);
		url.searchParams.delete('mcp_connected');
		url.searchParams.delete('mcp_error');
		url.searchParams.delete('server');
		void goto(url.pathname + url.search, {
			replaceState: true,
			noScroll: true,
			keepFocus: true
		});
	});

	function continueAfterConnect(): void {
		chatPanel?.resendLastUserMessage();
		mcpReturn = null;
	}
</script>

{#if mcpReturn?.status === 'connected'}
	<div
		class="flex items-center gap-3 px-4 py-2 text-sm bg-emerald-50 border-b border-emerald-200 text-emerald-800"
		data-testid="mcp-return-connected"
	>
		<span>Connected{mcpReturn.server ? ` to ${mcpReturn.server}` : ''}.</span>
		<button
			type="button"
			class="lq-banner-primary"
			data-testid="mcp-continue"
			on:click={continueAfterConnect}
		>
			Continue
		</button>
		<button type="button" class="lq-banner-dismiss" on:click={() => (mcpReturn = null)}>
			Dismiss
		</button>
	</div>
{:else if mcpReturn?.status === 'error'}
	<div
		class="flex items-center gap-3 px-4 py-2 text-sm bg-rose-50 border-b border-rose-200 text-rose-800"
		data-testid="mcp-return-error"
	>
		<span>Couldn't connect{mcpReturn.server ? ` ${mcpReturn.server}` : ''} — try again.</span>
		<button type="button" class="lq-banner-dismiss" on:click={() => (mcpReturn = null)}>
			Dismiss
		</button>
	</div>
{/if}

<ChatPanel bind:this={chatPanel} {projectIdFilter} {initialChatId} />

<style>
	.lq-banner-primary {
		background: #059669;
		color: #fff;
		border: 0;
		padding: 3px 10px;
		border-radius: 4px;
		cursor: pointer;
		font-size: 12px;
	}
	.lq-banner-primary:hover {
		filter: brightness(0.95);
	}
	.lq-banner-dismiss {
		background: transparent;
		color: inherit;
		border: 0;
		padding: 3px 8px;
		cursor: pointer;
		font-size: 12px;
		text-decoration: underline;
	}
</style>
