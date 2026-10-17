<script lang="ts">
	/**
	 * One task of an approved plan, as a line in the run's column. The closed line is
	 * a live summary (topic, latest step, spend); opened, it shows the task's skill and
	 * spend, its steps through the renderer registry, what it concluded, the files it
	 * saved with a content preview, and its receipts.
	 *
	 * Findings, file names and file contents come from the model and the run's own
	 * working files. They are rendered as text only, and only under the fold.
	 *
	 * Under the line, "How this run was set up" reads the task's own trace once the line is
	 * open, and the steps that were a model's reply carry a fold with what it wrote.
	 */
	import { orchestrationApi } from '$lib/lq-ai/api/orchestration';
	import type { RunProgress, SessionTraceRead, WorkspaceFile } from '$lib/lq-ai/api/orchestration';
	import type { ActivityLine } from '$lib/lq-ai/run/activity';
	import { formatUsd } from '$lib/lq-ai/run/format';
	import { IDLE, shown } from '$lib/lq-ai/run/load';
	import type { Load } from '$lib/lq-ai/run/load';
	import { outcomeSummary } from '$lib/lq-ai/run/progress';
	import type { StepContext } from '$lib/lq-ai/run/renderers';
	import { finishedCalls, matchTurns } from '$lib/lq-ai/run/trace';
	import RunEffectReceipt from './RunEffectReceipt.svelte';
	import RunLine from './RunLine.svelte';
	import RunSetup from './RunSetup.svelte';
	import RunStepList from './RunStepList.svelte';

	export let rootId: string;
	/** 1-based, as the plan card numbers its tasks. */
	export let index: number;
	export let topic: string;
	/** The pinned skill and version, e.g. `contract-qa v1.0.0`. */
	export let skill: string;
	export let child: RunProgress;
	/**
	 * What the run says of itself that a step does not: what its plan lists for the tasks to read
	 * and search. A call that has not settled has no note saying which it was.
	 */
	export let context: StepContext = {};
	/** The closed line. */
	export let line: ActivityLine;
	/** Open while the run is being read as a receipt. Bound only to a value that does not change on a poll. */
	export let expanded = false;
	/** The read of this task's trace; the real API unless a test passes a stub. */
	export let fetchTrace: typeof orchestrationApi.trace = orchestrationApi.trace;
	/** Changes when Refresh is pressed on the run message: an open line reads its trace again. */
	export let refreshKey = 0;
	/** The trace as read so far. Handed in only to show a state without running the read. */
	export let traceState: Load<SessionTraceRead> = IDLE;

	let opened: (WorkspaceFile & { content: string }) | null = null;
	let fileError = '';
	let reading = 0;
	// Whether this line is open now. It starts as it is drawn and then is the reader's: the
	// element is bound to it, so nothing that follows the run can open or close the line.
	let lineOpen = expanded;

	$: summary = outcomeSummary(child.outcome);
	$: files = child.files ?? [];
	$: effects = child.effects ?? [];
	$: allowance = formatUsd(child.allocation_usd);
	$: turns = matchTurns(effects, shown(traceState));

	async function openFile(file: WorkspaceFile) {
		const ticket = ++reading;
		fileError = '';
		opened = null;
		try {
			const value = await orchestrationApi.file(rootId, child.session_id, file.name);
			if (ticket === reading) opened = value;
		} catch (err) {
			if (ticket === reading) fileError = err instanceof Error ? err.message : String(err);
		}
	}

	function closeFile() {
		reading += 1;
		opened = null;
	}
</script>

<details
	class="child"
	bind:open={lineOpen}
	data-testid={`lq-ai-run-child-${index}`}
	data-status={child.status}
>
	<summary>
		<RunLine
			state={line.state}
			label={line.label}
			summary={line.summary}
			meta={line.meta}
			foldable
		/>
	</summary>

	<div class="body">
		<p class="topic"><span class="n">{index}.</span> {topic}</p>
		<p class="meta">
			{skill} · spent {formatUsd(child.spent_usd)} of {allowance}
			{#if Number(child.reserved_usd) > 0}· {formatUsd(child.reserved_usd)} reserved{/if}
		</p>

		<RunSetup
			{rootId}
			sessionId={child.session_id}
			step="task"
			{lineOpen}
			{refreshKey}
			calls={finishedCalls(effects)}
			{fetchTrace}
			bind:state={traceState}
		/>

		<RunStepList {effects} {turns} {context} />

		{#if child.outcome}
			<div class="outcome {child.outcome.status}">
				{#if summary}<p class="summary">{summary}</p>{/if}
				{#each child.outcome.findings as finding}
					<pre class="finding">{finding}</pre>
				{/each}
				<p class="note">Model-generated; unverified.</p>
			</div>
		{/if}

		{#if files.length > 0}
			<details class="fold">
				<summary>Files ({files.length})</summary>
				<ul class="files">
					{#each files as file}
						<li>
							<button
								class="file-link"
								type="button"
								data-testid="lq-ai-run-file"
								on:click={() => openFile(file)}
							>
								{file.name} · revision {file.revision}{file.shared
									? ' · shared with the orchestrator'
									: ' · private notes'}
							</button>
						</li>
					{/each}
				</ul>
				{#if fileError}<p role="alert" class="error">{fileError}</p>{/if}
				{#if opened}
					<div
						class="preview"
						role="region"
						aria-label="{opened.name} file contents"
						data-testid="lq-ai-run-file-preview"
					>
						<div class="preview-head">
							<div>
								<p class="eyebrow">Saved run file</p>
								<h4>{opened.name}</h4>
								<p class="muted">
									Revision {opened.revision} · {opened.shared
										? 'Shared with the orchestrator'
										: 'Private task notes'}
								</p>
							</div>
							<button type="button" class="plain" on:click={closeFile}>Close file</button>
						</div>
						<pre class="file-content">{opened.content}</pre>
					</div>
				{/if}
			</details>
		{/if}

		<details class="fold" data-testid={`lq-ai-run-child-${index}-receipts`}>
			<summary>Receipts</summary>
			<p class="muted">Session <code>{child.session_id}</code></p>
			{#if effects.length === 0}
				<p class="muted">No receipts yet.</p>
			{/if}
			{#each effects as effect}
				<RunEffectReceipt {effect} {context} />
			{/each}
		</details>
	</div>
</details>

<style>
	.child {
		margin: 0.1rem 0;
		min-width: 0;
	}
	.child > summary {
		cursor: pointer;
		padding: 0.35rem 0;
		list-style: none;
	}
	.child > summary::-webkit-details-marker {
		display: none;
	}
	.child > summary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.body {
		margin: 0.15rem 0 0.5rem 0.55rem;
		padding: 0 0 0.25rem 1rem;
		border-left: 2px solid var(--lq-accent-border);
	}
	.topic {
		margin: 0;
		font-size: 0.9rem;
		font-weight: 600;
		overflow-wrap: anywhere;
	}
	.n {
		color: var(--lq-text-tertiary);
	}
	.meta,
	.muted {
		margin: 0.25rem 0;
		font-size: 0.75rem;
		color: var(--lq-text-secondary);
		overflow-wrap: anywhere;
	}
	.outcome {
		margin: 0.5rem 0;
		padding: 0.5rem 0.75rem;
		border-left: 3px solid var(--lq-accent-border);
		background: var(--lq-inset);
		border-radius: 0 var(--lq-radius) var(--lq-radius) 0;
	}
	.outcome.failed {
		border-left-color: var(--lq-error-border);
	}
	.summary {
		margin: 0 0 0.25rem;
		font-size: 0.85rem;
		font-weight: 600;
		line-height: 1.5;
		overflow-wrap: anywhere;
	}
	.finding {
		margin: 0.4rem 0;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		font-family: inherit;
		font-size: 0.85rem;
		line-height: 1.6;
	}
	/* "Model-generated; unverified." is a label to be read, so not in the faint colour. */
	.note {
		margin: 0.25rem 0 0;
		font-size: 0.72rem;
		color: var(--lq-text-secondary);
	}
	.fold {
		margin-top: 0.4rem;
	}
	.fold > summary {
		cursor: pointer;
		font-size: 0.8rem;
		padding: 0.25rem 0;
		color: var(--lq-text-secondary);
	}
	.files {
		list-style: none;
		margin: 0.25rem 0;
		padding: 0;
	}
	.file-link {
		background: none;
		border: 0;
		padding: 0.2rem 0;
		color: var(--lq-accent);
		text-align: left;
		cursor: pointer;
		font-size: 0.8rem;
		overflow-wrap: anywhere;
	}
	.file-link:hover {
		text-decoration: underline;
	}
	.preview {
		margin-top: 0.5rem;
		border: 1px solid var(--lq-accent-border);
		border-left: 4px solid var(--lq-accent);
		border-radius: var(--lq-radius-lg);
		background: var(--lq-inset);
	}
	.preview-head {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 0.75rem;
		padding: 0.5rem 0.75rem;
	}
	.preview h4,
	.preview p {
		margin: 0;
	}
	.eyebrow {
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--lq-text-secondary);
	}
	.file-content {
		margin: 0;
		padding: 0.75rem;
		max-height: 18rem;
		overflow: auto;
		border-top: 1px solid var(--lq-border);
		background: var(--lq-canvas);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
		font-size: 0.78rem;
	}
	.plain {
		background: var(--lq-canvas);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: 0.25rem 0.6rem;
		font-size: 0.75rem;
		cursor: pointer;
	}
	.error {
		color: var(--lq-error);
		font-size: 0.8rem;
	}
	code {
		font-size: 0.7rem;
		overflow-wrap: anywhere;
	}
</style>
