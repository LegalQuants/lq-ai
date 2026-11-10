<script lang="ts">
	/**
	 * The run as one column of lines that flow like the chat: the plan, a line per
	 * task, and the answer. Each line is a native `<details>` whose `<summary>` is a
	 * live one-line summary of what is under it; click to open the trace. The lines
	 * stay after the answer is delivered.
	 *
	 * Open state: in the chat every line is closed except the plan while it awaits
	 * approval (the owner approves the exact plan shown); on the receipt page every
	 * line is open. Each line keeps its own open state and binds its element to it, so
	 * neither a poll nor the run moving on re-opens or re-closes a line the reader has
	 * toggled. An element drawn as `open={prop}` beside attributes that follow the run
	 * is assigned `open` again whenever one of those changes, which shut an open line.
	 *
	 * A run that stopped before it had a plan has a plan line that cannot show one. It opens to the
	 * call that was meant to make one (`RunNoPlanRow`), unless it is still being answered, or the
	 * run is one of the earlier demonstration, which has no trace to read: then it is a static line.
	 *
	 * A request the orchestrator answered by itself has no plan, task or approval, so its column is
	 * one line, `direct`. The files a run's searches found are listed under the answer line, not
	 * inside its fold: the answer cites them by number, where it is read.
	 *
	 * Topics and every other string come from the run's records or the model and are
	 * rendered as text only.
	 *
	 * `fetchTrace` and `refreshKey` are for the folds under each line that read how that
	 * part of the run was set up: the real API, and a number that changes when Refresh is
	 * pressed on the run message.
	 */
	import { createEventDispatcher } from 'svelte';
	import { orchestrationApi } from '$lib/lq-ai/api/orchestration';
	import type { OrchestrationChatRun } from '$lib/lq-ai/api/orchestration';
	import { runActivity } from '$lib/lq-ai/run/activity';
	import type { PlanView } from '$lib/lq-ai/run/plan';
	import { planState } from '$lib/lq-ai/run/plan';
	import { stepContext } from '$lib/lq-ai/run/renderers';
	import RunAnswerRow from './RunAnswerRow.svelte';
	import RunChildCard from './RunChildCard.svelte';
	import RunDirectRow from './RunDirectRow.svelte';
	import RunLine from './RunLine.svelte';
	import RunNoPlanRow from './RunNoPlanRow.svelte';
	import RunPlanCard from './RunPlanCard.svelte';
	import RunSources from './RunSources.svelte';

	export let run: OrchestrationChatRun;
	export let plan: PlanView | null = null;
	export let mode: 'thread' | 'receipt' = 'thread';
	/** True while the run waits for the owner's decision on the plan shown. */
	export let awaiting = false;
	export let busy = false;
	export let fetchTrace: typeof orchestrationApi.trace = orchestrationApi.trace;
	export let refreshKey = 0;

	const dispatch = createEventDispatcher<{
		approve: { revision: number; planHash: string };
		reject: { revision: number; planHash: string };
	}>();

	$: rows = runActivity(run);
	$: receipt = mode === 'receipt';
	$: tree = run.tree;
</script>

<ol class="activity" data-testid="lq-ai-run-activity" aria-label="Run activity">
	{#each rows as row (row.id)}
		<li class="row {row.kind}" data-row={row.kind} data-state={row.state}>
			{#if row.kind === 'plan' && plan}
				<RunPlanCard
					view={plan}
					line={row}
					state={planState(run)}
					{awaiting}
					expanded={receipt || row.openByDefault}
					{busy}
					rootId={run.root_id}
					{fetchTrace}
					{refreshKey}
					on:approve={(event) => dispatch('approve', event.detail)}
					on:reject={(event) => dispatch('reject', event.detail)}
				/>
			{:else if row.kind === 'task' && tree}
				{@const child = tree.children[(row.index ?? 1) - 1]}
				{#if child}
					<RunChildCard
						rootId={run.root_id}
						index={row.index ?? 1}
						topic={row.label}
						skill={plan?.tasks[(row.index ?? 1) - 1]?.skill ?? 'Skill not recorded'}
						{child}
						context={stepContext(run)}
						line={row}
						expanded={receipt}
						{fetchTrace}
						{refreshKey}
					/>
				{/if}
			{:else if row.kind === 'direct'}
				<RunDirectRow {run} line={row} expanded={receipt} {fetchTrace} {refreshKey} />
			{:else if row.kind === 'plan' && !tree && row.openable}
				<!-- Stopped before a plan: nothing to approve, but the call that made none can be read. -->
				<RunNoPlanRow {run} line={row} expanded={receipt} {fetchTrace} {refreshKey} />
			{:else if row.kind === 'answer' && row.openable && tree}
				<RunAnswerRow {run} line={row} expanded={receipt} {fetchTrace} {refreshKey} />
			{:else}
				<div class="static">
					<RunLine state={row.state} label={row.label} summary={row.summary} meta={row.meta} />
				</div>
			{/if}
			{#if row.kind === 'answer'}
				<RunSources {run} />
			{/if}
		</li>
	{/each}
</ol>

<style>
	.activity {
		list-style: none;
		margin: 0.5rem 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.row {
		min-width: 0;
	}
	/* The shell's stylesheet draws a paragraph inside a list item inline (`li p`). The
	   lines of this column are list items, and what they hold is laid out in blocks:
	   without this every paragraph under a line runs into the next one. */
	.row :global(p) {
		display: block;
	}
	.static {
		padding: 0.35rem 0;
	}
</style>
