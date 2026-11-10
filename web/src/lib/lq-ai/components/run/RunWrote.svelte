<script lang="ts">
	/**
	 * "What the model wrote": one reply of a run's session, as it was recorded. The text
	 * the model wrote (or a sentence saying it wrote none), then each tool call it asked
	 * for by name with its arguments exactly as it wrote them.
	 *
	 * The text, the tool names and the arguments are written by a model, which may have
	 * been shown a document or the owner's own words: they are interpolated, so they are
	 * shown as text, never as markup.
	 */
	import type { TurnView } from '$lib/lq-ai/run/trace';

	export let turn: TurnView;
</script>

<details class="wrote" data-testid="lq-ai-run-wrote">
	<summary>What the model wrote</summary>
	<div class="body">
		{#if turn.text !== null}
			<pre class="text" data-testid="lq-ai-run-wrote-text">{turn.text}</pre>
		{:else if turn.empty}
			<p class="muted">{turn.empty}</p>
		{/if}
		{#each turn.toolCalls as call}
			<div class="call" data-testid="lq-ai-run-wrote-call">
				<p class="name">{call.name}</p>
				<pre class="text">{call.arguments}</pre>
			</div>
		{/each}
	</div>
</details>

<style>
	.wrote {
		margin: 0.2rem 0;
		min-width: 0;
	}
	summary {
		cursor: pointer;
		width: fit-content;
		font-size: 0.75rem;
		color: var(--lq-text-secondary);
	}
	summary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.body {
		margin: 0.2rem 0 0.2rem 0.25rem;
		padding-left: 0.75rem;
		border-left: 2px solid var(--lq-border);
	}
	.muted {
		margin: 0.2rem 0;
		font-size: 0.75rem;
		color: var(--lq-text-secondary);
	}
	.call {
		margin-top: 0.4rem;
	}
	.name {
		margin: 0 0 0.15rem;
		font-size: 0.78rem;
		font-weight: 600;
		overflow-wrap: anywhere;
	}
	.text {
		margin: 0.2rem 0;
		padding: 0.5rem 0.6rem;
		max-height: 16rem;
		overflow: auto;
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		background: var(--lq-canvas);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
		font-size: 0.75rem;
		line-height: 1.5;
	}
</style>
