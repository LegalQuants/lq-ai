<script lang="ts">
	/**
	 * The plan the owner is asked to approve, exactly as it will run.
	 *
	 * For every task: the skill and version, the tools it may call, the documents it
	 * may read (numbered, and marked when accepting the run attached them to the
	 * matter) and its budget. For the plan: the total cap, the root allowance, the
	 * deadline, the attempt limit and how many tasks run at once. Approve and Reject
	 * send back the revision and hash of the plan shown here, and the parent refuses
	 * them if the run no longer holds that revision.
	 *
	 * Task text, file names and the goal come from the model or the owner and are
	 * rendered as text only.
	 */
	import { createEventDispatcher } from 'svelte';
	import { formatDeadline, formatDuration, pluralise } from '$lib/lq-ai/run/format';
	import { approvalSentence, type PlanView } from '$lib/lq-ai/run/plan';

	export let view: PlanView;
	/** `proposed` until approved; `rejected` once the owner rejected it. */
	export let state: 'proposed' | 'approved' | 'rejected' = 'proposed';
	/** True while the run is waiting for the owner's decision. */
	export let awaiting = false;
	export let busy = false;

	const dispatch = createEventDispatcher<{
		approve: { revision: number; planHash: string };
		reject: { revision: number; planHash: string };
	}>();

	$: title =
		state === 'approved' ? 'Approved plan' : state === 'rejected' ? 'Rejected plan' : 'Proposed plan';
</script>

<details
	class="plan"
	open={awaiting}
	data-testid="lq-ai-run-plan-card"
	data-revision={view.revision}
	data-state={state}
>
	<summary>
		<span class="title">{title}</span>
		<span class="meta">
			revision {view.revision} · {pluralise(view.tasks.length, 'task')} · total cap {view.totalCap}
		</span>
	</summary>

	<div class="body">
		<dl class="limits">
			<div><dt>Total cap</dt><dd>{view.totalCap}</dd></div>
			<div><dt>Combining the answers</dt><dd>{view.rootAllowance}</dd></div>
			{#if view.planningAllowance}
				<div><dt>Planning allowance</dt><dd>{view.planningAllowance}</dd></div>
			{/if}
			<div><dt>Deadline</dt><dd>{formatDeadline(view.deadline)}</dd></div>
			{#if view.attemptLimitSeconds}
				<div>
					<dt>Attempt limit</dt>
					<dd>{formatDuration(view.attemptLimitSeconds)} per attempt</dd>
				</div>
			{/if}
			<div><dt>At the same time</dt><dd>up to {view.maxActive}</dd></div>
			{#if view.model}
				<div><dt>Model</dt><dd>{view.model}</dd></div>
			{/if}
		</dl>

		{#if view.reads}<p class="reads"><strong>May read:</strong> {view.reads}</p>{/if}

		<ol class="tasks">
			{#each view.tasks as task}
				<li class="task" data-testid="lq-ai-run-plan-task">
					<p class="topic">{task.topic}</p>
					<p class="question">{task.question}</p>
					<dl class="facts">
						<div><dt>Skill</dt><dd>{task.skill}</dd></div>
						<div>
							<dt>Tools it may call</dt>
							<dd data-testid="lq-ai-run-plan-tools">
								{#if task.tools.length > 0}{task.tools.join(', ')}{:else}none{/if}
							</dd>
						</div>
						<div>
							<dt>Documents it may read</dt>
							<dd data-testid="lq-ai-run-plan-documents">
								{#if task.documents.length > 0}
									<ul class="docs">
										{#each task.documents as doc}
											<li>
												<span class="num">[{doc.number}]</span>
												{doc.filename}{#if doc.addedForRun}<span class="added"
														>{' · added to this matter for this run'}</span
													>{/if}
											</li>
										{/each}
									</ul>
								{:else}
									none listed
								{/if}
							</dd>
						</div>
						<div>
							<dt>Budget</dt>
							<dd>
								{task.budget}{#if task.turnLimit}{` · up to ${pluralise(task.turnLimit, 'tool turn')}, then one answer`}{/if}
							</dd>
						</div>
					</dl>
					<details class="fold">
						<summary>Task boundaries and expected output</summary>
						<p>{task.boundaries}</p>
						<p>{task.outputContract}</p>
						<p>Stops when: {task.stoppingCondition}</p>
					</details>
				</li>
			{/each}
		</ol>

		{#if awaiting}
			<div class="actions">
				<button
					type="button"
					class="primary"
					data-testid="lq-ai-run-approve"
					disabled={busy}
					on:click={() =>
						dispatch('approve', { revision: view.revision, planHash: view.planHash })}
				>
					Approve plan
				</button>
				<button
					type="button"
					class="secondary"
					data-testid="lq-ai-run-reject"
					disabled={busy}
					on:click={() =>
						dispatch('reject', { revision: view.revision, planHash: view.planHash })}
				>
					Reject plan
				</button>
			</div>
			<p class="note">{approvalSentence(view.revision)} Tasks cannot start further tasks.</p>
			{#if view.planningCharge}
				<p class="note">
					Planning is already charged ({view.planningCharge}) and stays in the receipts if you reject.
				</p>
			{/if}
		{:else if state === 'approved'}
			<p class="note">You approved revision {view.revision}.</p>
		{/if}
	</div>
</details>

<style>
	.plan {
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-lg);
		background: var(--lq-canvas);
		margin: 0.75rem 0;
	}
	summary {
		cursor: pointer;
		padding: 0.6rem 0.9rem;
		display: flex;
		flex-wrap: wrap;
		gap: 0.25rem 0.75rem;
		align-items: baseline;
	}
	.title {
		font-weight: 600;
		font-size: 0.95rem;
	}
	.meta {
		font-size: 0.78rem;
		color: var(--lq-text-secondary);
	}
	.body {
		padding: 0 0.9rem 0.9rem;
	}
	dl {
		margin: 0;
	}
	dt {
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--lq-text-secondary);
	}
	dd {
		margin: 0;
		font-size: 0.85rem;
		overflow-wrap: anywhere;
	}
	.limits {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
		gap: 0.5rem 1rem;
		padding: 0.5rem 0;
		border-bottom: 1px solid var(--lq-border);
	}
	.reads {
		margin: 0.5rem 0;
		font-size: 0.85rem;
		line-height: 1.5;
		overflow-wrap: anywhere;
	}
	.tasks {
		margin: 0.5rem 0;
		padding-left: 1.25rem;
	}
	.task {
		margin: 0.75rem 0;
		padding-left: 0.25rem;
	}
	.topic {
		margin: 0;
		font-weight: 600;
		font-size: 0.9rem;
		overflow-wrap: anywhere;
	}
	.question {
		margin: 0.15rem 0 0.4rem;
		font-size: 0.85rem;
		line-height: 1.5;
		overflow-wrap: anywhere;
	}
	.facts {
		display: grid;
		gap: 0.35rem;
		padding: 0.5rem 0.75rem;
		background: var(--lq-inset);
		border-radius: var(--lq-radius);
	}
	.docs {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.num {
		color: var(--lq-text-secondary);
	}
	.added {
		color: var(--lq-accent);
	}
	.fold {
		margin-top: 0.25rem;
	}
	.fold summary {
		display: block;
		padding: 0.25rem 0;
		font-size: 0.8rem;
		color: var(--lq-text-secondary);
	}
	.fold p {
		margin: 0.25rem 0;
		font-size: 0.8rem;
		line-height: 1.5;
		overflow-wrap: anywhere;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		margin-top: 0.75rem;
	}
	button {
		border: 1px solid var(--lq-accent-border);
		border-radius: var(--lq-radius);
		padding: 0.45rem 0.9rem;
		font-size: 0.85rem;
		cursor: pointer;
	}
	button:disabled {
		opacity: 0.5;
		cursor: default;
	}
	button:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.primary {
		background: var(--lq-accent);
		color: white;
		border-color: var(--lq-accent);
	}
	.secondary {
		background: var(--lq-canvas);
		color: var(--lq-text);
		border-color: var(--lq-border-strong);
	}
	.note {
		margin: 0.5rem 0 0;
		font-size: 0.78rem;
		color: var(--lq-text-secondary);
		line-height: 1.5;
	}
</style>
