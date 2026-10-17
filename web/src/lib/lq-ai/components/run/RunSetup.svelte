<script lang="ts">
	/**
	 * "How this run was set up": under a line of the run column, what one model call was
	 * opened with. The system message it was pinned to (and its text), the opening message
	 * the application sent, the tools it offered, and whether the rebuilt opening still
	 * matches the digest recorded when the call went out (ADR 0038 D3).
	 *
	 * This owns the read of the session's trace. It is read when the line this sits under
	 * is open (a line that starts open, as on the receipt page, is read at once), and read
	 * again while the line is open when one more model call of the session finishes
	 * (`calls`) or Refresh is pressed on the run message. A closed line reads nothing; if a
	 * call finished or Refresh was pressed meanwhile, the trace is brought up to date when
	 * the line is opened again (`traceReadDue`). A line nobody opens costs the server
	 * nothing. The parent binds `state` to show the model's replies from the same read: it
	 * never reads twice.
	 *
	 * A failed read is said beside the fold, not inside it: the fold is closed, and what is
	 * inside a closed fold is neither seen nor announced.
	 *
	 * `fetchTrace` is the read, the real API unless a test passes a stub. `state` is the
	 * read as it stands (idle, loading, loaded, failed); it can be handed in to show a
	 * state without running the read.
	 *
	 * The system text, the opening, the tool names, descriptions and schemas and the note
	 * are written by a model, a document or the owner. They are interpolated: shown as
	 * text, never as markup.
	 */
	import { onDestroy, onMount } from 'svelte';
	import { orchestrationApi } from '$lib/lq-ai/api/orchestration';
	import type { SessionTraceRead, TraceStepName } from '$lib/lq-ai/api/orchestration';
	import { IDLE, LazyLoad, shown, traceReadDue } from '$lib/lq-ai/run/load';
	import type { Load } from '$lib/lq-ai/run/load';
	import { CALL_NOT_MADE, setupView, traceCall } from '$lib/lq-ai/run/trace';

	export let rootId: string;
	/** The root's own id for the plan and the answer; a task's session id for a task. */
	export let sessionId: string;
	export let step: TraceStepName;
	/** Whether the line this sits under is open. An open line has its trace read. */
	export let lineOpen = false;
	/** Changes when Refresh is pressed on the run message. */
	export let refreshKey = 0;
	/**
	 * How many model calls this session has finished (`finishedCalls`). When it grows while
	 * the line is open, the trace has a reply the read does not have yet, so it is read
	 * again: once per finished call, never on every poll of the run.
	 */
	export let calls = 0;
	export let fetchTrace: typeof orchestrationApi.trace = orchestrationApi.trace;
	export let state: Load<SessionTraceRead> = IDLE;

	const loader = new LazyLoad<SessionTraceRead>(
		(signal) => fetchTrace(rootId, sessionId, signal),
		(next) => (state = next),
		state
	);
	onDestroy(() => loader.stop());

	// Nothing is read until the component is on a page: drawing it, on a server or in a
	// test, never reads. A line that starts open is read as soon as it is mounted.
	let mounted = false;
	onMount(() => {
		mounted = true;
	});

	let seenRefresh = refreshKey;
	// How many model calls the session had finished when the trace was last asked for; null
	// when it has not been asked for since it went out of date.
	let readAt: number | null = null;

	/** Bring the trace up to date. Only ever called for a line that is open. */
	function bringUpToDate(finished: number): void {
		const due = traceReadDue({ status: state.status, readAt, calls: finished });
		if (!due) return;
		readAt = finished;
		if (due === 'open') loader.open();
		else loader.reload();
	}

	function tryAgain(): void {
		readAt = calls;
		loader.reload();
	}

	// Runs when the line is opened, and while it is open each time `calls` changes.
	$: if (mounted && lineOpen) bringUpToDate(calls);
	$: if (refreshKey !== seenRefresh) {
		seenRefresh = refreshKey;
		// Out of date from now, whether or not the line is open to be read again.
		readAt = null;
		if (mounted && lineOpen) bringUpToDate(calls);
	}

	$: trace = shown(state);
	$: call = traceCall(trace, step);
	$: view = call ? setupView(call) : null;

	// Opening this fold reads too, for a parent that does not say whether its line is open.
	function onToggle(event: Event): void {
		if ((event.currentTarget as HTMLDetailsElement).open && mounted) bringUpToDate(calls);
	}
</script>

{#if state.status === 'failed'}
	<p class="note error" role="alert" data-testid="lq-ai-run-setup-failed">
		Could not read how this call was set up: {state.message}
		<button type="button" class="again" on:click={tryAgain}>Try again</button>
	</p>
{/if}
<details class="setup" data-testid="lq-ai-run-setup" data-step={step} on:toggle={onToggle}>
	<summary
		>How this run was set up{#if view?.check?.warn}<span
				class="flag"
				data-testid="lq-ai-run-setup-flag"
			>
				· does not match what was recorded</span
			>{/if}</summary
	>
	<div class="body">
		{#if state.status === 'loading' && !trace}
			<p class="note" role="status">Reading how this call was set up…</p>
		{:else if state.status === 'loading'}
			<p class="note" role="status">Reading it again…</p>
		{/if}

		{#if trace && view}
			<p class="system" data-testid="lq-ai-run-setup-system">
				{view.system}{#if view.digest}<span class="digest">
						· digest <code>{view.digest}</code></span
					>{/if}
			</p>
			{#if view.systemText !== null}
				<details class="inner">
					<summary>{view.systemFold}</summary>
					<pre class="text" data-testid="lq-ai-run-setup-system-text">{view.systemText}</pre>
				</details>
			{:else}
				<p class="note">{view.systemMissing}</p>
			{/if}

			<p class="heading">Opening message</p>
			{#if view.opening !== null}
				<pre class="text" data-testid="lq-ai-run-setup-opening">{view.opening}</pre>
			{:else}
				<p class="note">{view.openingMissing}</p>
			{/if}

			<p class="heading">Tools offered</p>
			{#if view.tools.length === 0}
				<p class="note">{view.noTools}</p>
			{:else}
				<ul class="tools">
					{#each view.tools as tool}
						<li class="tool" data-testid="lq-ai-run-setup-tool">
							<span class="tool-name">{tool.name}</span>
							{#if tool.description}<span class="tool-description">{tool.description}</span>{/if}
							{#if tool.schema !== null}
								<details class="inner">
									<summary>Schema</summary>
									<pre class="text">{tool.schema}</pre>
								</details>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}

			{#if view.check}
				<p class="check" class:warn={view.check.warn} data-testid="lq-ai-run-setup-check">
					{view.check.text}
				</p>
			{/if}
			{#if trace.note}<p class="small" data-testid="lq-ai-run-setup-note">{trace.note}</p>{/if}
		{:else if trace}
			<p class="note" data-testid="lq-ai-run-setup-missing">{CALL_NOT_MADE}</p>
		{/if}
	</div>
</details>

<style>
	.setup {
		margin: 0.3rem 0;
		min-width: 0;
	}
	.setup > summary {
		cursor: pointer;
		width: fit-content;
		font-size: 0.8rem;
		color: var(--lq-text-secondary);
	}
	.inner > summary {
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
	.system {
		margin: 0.25rem 0 0.1rem;
		font-size: 0.82rem;
		font-weight: 600;
		overflow-wrap: anywhere;
	}
	.digest {
		font-weight: 400;
		color: var(--lq-text-secondary);
	}
	code {
		font-size: 0.72rem;
	}
	.heading {
		margin: 0.5rem 0 0.1rem;
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--lq-text-secondary);
	}
	.note {
		margin: 0.2rem 0;
		font-size: 0.75rem;
		color: var(--lq-text-secondary);
		overflow-wrap: anywhere;
	}
	.error {
		color: var(--lq-error);
	}
	.again {
		margin-left: 0.35rem;
		padding: 0;
		border: 0;
		background: none;
		font: inherit;
		color: var(--lq-accent);
		text-decoration: underline;
		cursor: pointer;
	}
	.again:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.flag {
		color: var(--lq-warn);
		font-weight: 600;
	}
	/* Says what this fold is and is not: a sentence to be read, so not in the faint colour. */
	.small {
		margin: 0.5rem 0 0.1rem;
		font-size: 0.72rem;
		line-height: 1.5;
		color: var(--lq-text-secondary);
	}
	.check {
		margin: 0.5rem 0 0.1rem;
		font-size: 0.78rem;
		line-height: 1.5;
		color: var(--lq-text-secondary);
	}
	.check.warn {
		padding: 0.4rem 0.6rem;
		border-left: 3px solid var(--lq-warn);
		background: var(--lq-warn-soft);
		color: var(--lq-text);
		border-radius: 0 var(--lq-radius) var(--lq-radius) 0;
	}
	.tools {
		list-style: none;
		margin: 0.1rem 0;
		padding: 0;
	}
	.tool {
		margin: 0.25rem 0;
		font-size: 0.78rem;
		line-height: 1.5;
		overflow-wrap: anywhere;
	}
	.tool-name {
		font-weight: 600;
	}
	.tool-description {
		margin-left: 0.4rem;
		color: var(--lq-text-secondary);
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
