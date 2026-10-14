<script lang="ts">
	/**
	 * The plan line of a run that stopped before it had a plan, and did not answer by itself: the
	 * model's reply was not a plan that could be used, the plan could not be funded, or the run was
	 * halted, expired, closed or left uncertain while the first call was out. There is no plan to
	 * open, but the call that was meant to make one is on record, and it is the whole of what the
	 * run did. Opened, the line shows that call: how it was set up, what the model wrote, and its
	 * receipts, the same three things the plan line shows for a plan that was made.
	 *
	 * The closed line is the one it always was: what the run did not produce, and why. Opening it
	 * adds nothing to what the run says of itself; it is there so that a reply the page calls
	 * unusable can be read.
	 *
	 * "How this run was set up" reads the root session's trace once the line is open, as it does
	 * under the plan line and the direct line. The trace and the receipts are text from a model, a
	 * document or the owner: interpolated, never rendered as markup.
	 */
	import { orchestrationApi } from '$lib/lq-ai/api/orchestration';
	import type { OrchestrationChatRun, SessionTraceRead } from '$lib/lq-ai/api/orchestration';
	import type { ActivityLine } from '$lib/lq-ai/run/activity';
	import { IDLE, shown } from '$lib/lq-ai/run/load';
	import type { Load } from '$lib/lq-ai/run/load';
	import { stepContext } from '$lib/lq-ai/run/renderers';
	import { finishedCalls, replyTo, traceCall } from '$lib/lq-ai/run/trace';
	import RunEffectReceipt from './RunEffectReceipt.svelte';
	import RunLine from './RunLine.svelte';
	import RunSetup from './RunSetup.svelte';
	import RunWrote from './RunWrote.svelte';

	export let run: OrchestrationChatRun;
	/** The closed line. */
	export let line: ActivityLine;
	/** Open while the run is being read as a receipt. Bound only to a value that does not change on a poll. */
	export let expanded = false;
	/** The read of the root's trace; the real API unless a test passes a stub. */
	export let fetchTrace: typeof orchestrationApi.trace = orchestrationApi.trace;
	/** Changes when Refresh is pressed on the run message: an open line reads its trace again. */
	export let refreshKey = 0;
	/** The trace as read so far. Handed in only to show a state without running the read. */
	export let traceState: Load<SessionTraceRead> = IDLE;

	// Whether this line is open now. It starts as it is drawn and then is the reader's: the
	// element is bound to it, so nothing that follows the run can open or close the line.
	let lineOpen = expanded;

	// With no plan, the run's own steps are the root's: the one call that was meant to make one.
	$: effects = run.effects ?? [];
	$: trace = shown(traceState);
	$: reply = replyTo(trace, traceCall(trace, 'plan'));
</script>

<details
	class="noplan-row"
	bind:open={lineOpen}
	data-testid="lq-ai-run-noplan"
	data-status={run.status}
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
		<RunSetup
			rootId={run.root_id}
			sessionId={run.root_id}
			step="plan"
			{lineOpen}
			{refreshKey}
			calls={finishedCalls(effects)}
			{fetchTrace}
			bind:state={traceState}
		/>
		{#if reply}<RunWrote turn={reply} />{/if}

		<details class="fold" data-testid="lq-ai-run-noplan-receipts">
			<summary>Receipts</summary>
			{#if effects.length === 0}
				<p class="muted">No receipts yet.</p>
			{/if}
			{#each effects as effect}
				<RunEffectReceipt {effect} context={stepContext(run)} />
			{/each}
		</details>
	</div>
</details>

<style>
	.noplan-row {
		margin: 0.1rem 0;
		min-width: 0;
	}
	.noplan-row > summary {
		cursor: pointer;
		padding: 0.35rem 0;
		list-style: none;
	}
	.noplan-row > summary::-webkit-details-marker {
		display: none;
	}
	.noplan-row > summary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.body {
		margin: 0.15rem 0 0.5rem 0.55rem;
		padding: 0 0 0.25rem 1rem;
		border-left: 2px solid var(--lq-accent-border);
	}
	.muted {
		margin: 0.25rem 0;
		font-size: 0.75rem;
		color: var(--lq-text-secondary);
	}
	.fold {
		margin-top: 0.4rem;
	}
	.fold > summary {
		cursor: pointer;
		width: fit-content;
		font-size: 0.8rem;
		padding: 0.25rem 0;
		color: var(--lq-text-secondary);
	}
	.fold > summary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
</style>
