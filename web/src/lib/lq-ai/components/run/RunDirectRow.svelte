<script lang="ts">
	/**
	 * The one line of a run the orchestrator answered by itself (ADR 0038 D1): there is no plan, no
	 * task and no approval, so there is no other line. The closed line says what it is and what the
	 * call cost; opened, it says in a sentence what that means, then how the call was set up and the
	 * receipts of that one call. The answer itself is the chat message's own content, drawn beneath
	 * the run panel with the other answers.
	 *
	 * "How this run was set up" reads the root session's trace once the line is open, as it does
	 * under the plan line: the call is the same one, offered the same tool, and chose not to use it.
	 *
	 * Everything on the line comes from the run's records, and the trace and receipts are text from
	 * a model, a document or the owner: interpolated, never rendered as markup.
	 */
	import { orchestrationApi } from '$lib/lq-ai/api/orchestration';
	import type { OrchestrationChatRun, SessionTraceRead } from '$lib/lq-ai/api/orchestration';
	import { DIRECT_NOTE } from '$lib/lq-ai/run/activity';
	import type { ActivityLine } from '$lib/lq-ai/run/activity';
	import { IDLE } from '$lib/lq-ai/run/load';
	import type { Load } from '$lib/lq-ai/run/load';
	import { stepContext } from '$lib/lq-ai/run/renderers';
	import { finishedCalls } from '$lib/lq-ai/run/trace';
	import RunEffectReceipt from './RunEffectReceipt.svelte';
	import RunLine from './RunLine.svelte';
	import RunSetup from './RunSetup.svelte';

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

	// With no plan, the run's own steps are the root's: the one call that answered.
	$: effects = run.effects ?? [];
</script>

<details class="direct-row" bind:open={lineOpen} data-testid="lq-ai-run-direct">
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
		<p class="note" data-testid="lq-ai-run-direct-note">{DIRECT_NOTE}</p>

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

		<details class="fold" data-testid="lq-ai-run-direct-receipts">
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
	.direct-row {
		margin: 0.1rem 0;
		min-width: 0;
	}
	.direct-row > summary {
		cursor: pointer;
		padding: 0.35rem 0;
		list-style: none;
	}
	.direct-row > summary::-webkit-details-marker {
		display: none;
	}
	.direct-row > summary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.body {
		margin: 0.15rem 0 0.5rem 0.55rem;
		padding: 0 0 0.25rem 1rem;
		border-left: 2px solid var(--lq-accent-border);
	}
	/* A sentence to be read, so it is in the secondary text colour and not the faint one. */
	.note {
		margin: 0.25rem 0 0.4rem;
		font-size: 0.85rem;
		line-height: 1.5;
		color: var(--lq-text-secondary);
		overflow-wrap: anywhere;
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
