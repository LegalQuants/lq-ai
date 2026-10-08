<script lang="ts">
	/**
	 * One task of an approved plan: its status, the step it is on, what it concluded,
	 * its steps through the renderer registry, the files it saved with a content
	 * preview, and its receipts. Steps open while the task is still working; files and
	 * receipts are folded and one action away.
	 *
	 * Findings, file names and file contents come from the model and the run's own
	 * working files. They are rendered as text only.
	 */
	import { orchestrationApi } from '$lib/lq-ai/api/orchestration';
	import type { RunProgress, WorkspaceFile } from '$lib/lq-ai/api/orchestration';
	import { formatUsd } from '$lib/lq-ai/run/format';
	import { outcomeSummary, taskLatestStep, taskStatusLabel } from '$lib/lq-ai/run/progress';
	import RunEffectReceipt from './RunEffectReceipt.svelte';
	import RunStepList from './RunStepList.svelte';

	export let rootId: string;
	/** 1-based, as the plan card numbers its tasks. */
	export let index: number;
	export let topic: string;
	/** The pinned skill and version, e.g. `contract-qa v1.0.0`. */
	export let skill: string;
	export let child: RunProgress;

	// Decided once, when the card first appears: a task that is still working shows
	// its steps. Later updates do not fight the owner folding or unfolding them.
	let stepsOpen = ['pending', 'queued', 'running'].includes(child.status);

	let opened: (WorkspaceFile & { content: string }) | null = null;
	let fileError = '';
	let reading = 0;

	$: latest = taskLatestStep(child);
	$: summary = outcomeSummary(child.outcome);
	$: files = child.files ?? [];
	$: effects = child.effects ?? [];
	$: allowance = formatUsd(child.allocation_usd);

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

<article class="child" data-testid={`lq-ai-run-child-${index}`} data-status={child.status}>
	<div class="head">
		<h3><span class="n">{index}.</span> {topic}</h3>
		<span class="tag {child.status}">{taskStatusLabel(child.status)}</span>
	</div>
	<p class="meta">
		{skill} · spent {formatUsd(child.spent_usd)} of {allowance}
		{#if Number(child.reserved_usd) > 0}· {formatUsd(child.reserved_usd)} reserved{/if}
	</p>
	{#if latest}<p class="latest"><span class="label">Latest step:</span> {latest}</p>{/if}

	{#if child.outcome}
		<div class="outcome {child.outcome.status}">
			{#if summary}<p class="summary">{summary}</p>{/if}
			{#each child.outcome.findings as finding}
				<pre class="finding">{finding}</pre>
			{/each}
			<p class="note">Model-generated; unverified.</p>
		</div>
	{/if}

	<details class="fold" open={stepsOpen}>
		<summary>Steps ({effects.length})</summary>
		<RunStepList {effects} />
	</details>

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
			<RunEffectReceipt {effect} />
		{/each}
	</details>
</article>

<style>
	.child {
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-lg);
		padding: 0.75rem 0.9rem;
		background: var(--lq-canvas);
		min-width: 0;
	}
	.head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	h3 {
		margin: 0;
		font-size: 0.95rem;
		font-weight: 600;
		overflow-wrap: anywhere;
	}
	.n {
		color: var(--lq-text-tertiary);
	}
	.tag {
		padding: 0.1rem 0.55rem;
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-pill);
		font-size: 0.72rem;
		color: var(--lq-text-secondary);
		white-space: nowrap;
	}
	.tag.running {
		border-color: var(--lq-accent-border);
		background: var(--lq-accent-soft);
		color: var(--lq-accent);
	}
	.tag.completed {
		border-color: var(--lq-accent-border);
		color: var(--lq-accent);
	}
	.tag.failed {
		border-color: var(--lq-error-border);
		background: var(--lq-error-soft);
		color: var(--lq-error);
	}
	.meta,
	.muted {
		margin: 0.25rem 0;
		font-size: 0.75rem;
		color: var(--lq-text-secondary);
		overflow-wrap: anywhere;
	}
	.latest {
		margin: 0.35rem 0;
		font-size: 0.85rem;
		overflow-wrap: anywhere;
	}
	.label {
		font-weight: 600;
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
	.note {
		margin: 0.25rem 0 0;
		font-size: 0.72rem;
		color: var(--lq-text-tertiary);
	}
	.fold {
		margin-top: 0.4rem;
	}
	summary {
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
