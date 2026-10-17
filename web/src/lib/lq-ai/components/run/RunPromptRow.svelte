<script lang="ts">
	/**
	 * One of the engine's own system prompts, in the strip above the composer: its label
	 * ("Orchestrator prompt, version 1") closed, and its full text one opening away. The
	 * text is fetched the first time the row is opened, and not before, so a person who
	 * never looks costs the server nothing. Opening it again does not read it again; if the
	 * read failed, opening it again tries once more.
	 *
	 * The prompt is a file the engine ships, but it is shown as text like any other string
	 * from the server: interpolated, never as markup.
	 *
	 * `fetchPrompt` is the read, the real API unless a test passes a stub. `state` is the
	 * read as it stands: idle until opened, then loading, then loaded or failed. It can be
	 * handed in to show a state without running the read.
	 */
	import { onDestroy } from 'svelte';
	import { orchestrationApi } from '$lib/lq-ai/api/orchestration';
	import type { PromptRead } from '$lib/lq-ai/api/orchestration';
	import { IDLE, LazyLoad, shown } from '$lib/lq-ai/run/load';
	import type { Load } from '$lib/lq-ai/run/load';

	/** The prompt's name, `<family>/<role>.v<N>`, which is what the read takes. */
	export let name: string;
	export let label: string;
	export let fetchPrompt: typeof orchestrationApi.prompt = orchestrationApi.prompt;
	export let state: Load<PromptRead> = IDLE;

	const loader = new LazyLoad<PromptRead>(
		(signal) => fetchPrompt(name, signal),
		(next) => (state = next),
		state
	);
	onDestroy(() => loader.stop());

	$: prompt = shown(state);

	function onToggle(event: Event): void {
		if ((event.currentTarget as HTMLDetailsElement).open) loader.open();
	}
</script>

<details class="prompt" data-testid="lq-ai-run-prompt" on:toggle={onToggle}>
	<summary>{label}</summary>
	{#if state.status === 'loading' && !prompt}
		<p class="note" role="status">Loading the prompt…</p>
	{/if}
	{#if state.status === 'failed'}
		<p class="note error" role="alert">Could not read the prompt: {state.message}</p>
	{/if}
	{#if prompt}
		<pre class="text" data-testid="lq-ai-run-prompt-text">{prompt.text}</pre>
	{/if}
</details>

<style>
	.prompt {
		min-width: 0;
	}
	summary {
		cursor: pointer;
		width: fit-content;
		font-size: 0.78rem;
		color: var(--lq-accent);
	}
	summary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.note {
		margin: 0.2rem 0;
		font-size: 0.75rem;
		color: var(--lq-text-secondary);
	}
	.error {
		color: var(--lq-error);
	}
	.text {
		margin: 0.25rem 0;
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
