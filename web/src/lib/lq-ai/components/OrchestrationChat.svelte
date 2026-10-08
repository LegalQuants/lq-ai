<script lang="ts">
	/**
	 * The receipt view of a governed run (ADR 0038 D1).
	 *
	 * Runs start from a chat inside a matter, with the Run control beside the model
	 * picker, and live in that chat's thread. This page remains for runs that have no
	 * chat, and as a stable address for any run's receipts: it shows the same run
	 * components the thread does, without a chat around them. The intake form that used
	 * to live here is gone.
	 */
	import { page } from '$app/stores';
	import type { OrchestrationChatRun } from '$lib/lq-ai/api/orchestration';
	import { chatHref } from '$lib/lq-ai/run/links';
	import RunMessage from './run/RunMessage.svelte';

	let run: OrchestrationChatRun | null = null;

	$: id = $page.params.id ?? '';
</script>

<div class="receipt-page">
	<header>
		<a href="/lq-ai/autonomous">Autonomous sessions</a>
		<div class="heading">
			<h1 class="lq-text-page-h">{id ? 'Run receipt' : 'Governed runs'}</h1>
			<span class="tag">Experimental</span>
		</div>
		{#if id}
			<p>
				A governed run as recorded: the plan, each task’s steps and files, and the receipts. Task
				answers and the combined answer are model output.
			</p>
		{/if}
	</header>

	{#if !id}
		<section class="panel" data-testid="lq-ai-run-receipt-notice" aria-label="Where runs start">
			<h2>Runs now start from a chat</h2>
			<p>
				Open a chat inside a matter and use the <strong>Run</strong> control beside the model picker.
				The run then appears in that chat’s thread, where you review and approve its plan and follow
				its progress.
			</p>
			<p class="links">
				<a href="/lq-ai/matters">Open a matter</a>
				<a href="/lq-ai/chats">Open chats</a>
			</p>
		</section>
	{:else}
		{#key id}
			<RunMessage rootId={id} mode="receipt" bind:run />
		{/key}
		{#if run?.chat_id}
			<p class="open-chat">
				<a href={chatHref(run.chat_id)} data-testid="lq-ai-run-open-chat"
					>Open this run in its chat</a
				>
			</p>
		{/if}
	{/if}
</div>

<style>
	.receipt-page {
		max-width: 960px;
		margin: 0 auto;
		padding: 2rem 1.5rem 4rem;
		color: var(--lq-text);
	}
	header {
		margin-bottom: 1.5rem;
	}
	.heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.8rem;
		flex-wrap: wrap;
	}
	h1 {
		margin: 0.6rem 0;
	}
	h2 {
		margin: 0 0 0.5rem;
		font-size: 1.05rem;
		font-weight: 600;
	}
	p {
		margin: 0.5rem 0;
		line-height: 1.6;
	}
	a {
		color: var(--lq-accent);
		text-decoration: underline;
	}
	.tag {
		padding: 0.2rem 0.6rem;
		border: 1px solid var(--lq-border);
		border-radius: 999px;
		font-size: 0.75rem;
	}
	.panel {
		border: 1px solid var(--lq-border);
		border-radius: 12px;
		padding: 1.25rem;
		margin: 1rem 0;
		background: var(--lq-canvas);
	}
	.links {
		display: flex;
		flex-wrap: wrap;
		gap: 1rem;
	}
	.open-chat {
		margin-top: 1rem;
	}
</style>
