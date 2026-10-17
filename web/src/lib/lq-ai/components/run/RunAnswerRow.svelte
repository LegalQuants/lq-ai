<script lang="ts">
	/**
	 * The answer line of the run column: a closed one-line summary of the combining step,
	 * which opens on the orchestrator's own steps. Under it, "How this run was set up"
	 * reads the root session's trace once the line is open and shows what the combine call
	 * was opened with; the synthesis step carries a fold with what the model wrote.
	 *
	 * Steps, summaries and the model's reply are text from the run's records and the
	 * model: they are interpolated, never rendered as markup.
	 */
	import { orchestrationApi } from '$lib/lq-ai/api/orchestration';
	import type { OrchestrationChatRun, SessionTraceRead } from '$lib/lq-ai/api/orchestration';
	import type { ActivityLine } from '$lib/lq-ai/run/activity';
	import { IDLE, shown } from '$lib/lq-ai/run/load';
	import type { Load } from '$lib/lq-ai/run/load';
	import { stepContext } from '$lib/lq-ai/run/renderers';
	import { finishedCalls, matchTurns, traceCall } from '$lib/lq-ai/run/trace';
	import RunLine from './RunLine.svelte';
	import RunSetup from './RunSetup.svelte';
	import RunStepList from './RunStepList.svelte';

	export let run: OrchestrationChatRun;
	/** The closed line. */
	export let line: ActivityLine;
	/** Open while the run is being read as a receipt. */
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

	$: effects = run.tree?.root.effects ?? [];
	// This line shows the combine call's reply and no other: the planning reply is the plan line's.
	$: combine = traceCall(shown(traceState), 'combine');
	$: turns = matchTurns(effects, shown(traceState), combine ? [combine.effect_key] : []);
</script>

<details class="answer-row" bind:open={lineOpen} data-testid="lq-ai-run-answer-row">
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
			step="combine"
			{lineOpen}
			{refreshKey}
			calls={finishedCalls(effects)}
			{fetchTrace}
			bind:state={traceState}
		/>
		<!-- The orchestrator's steps include its first call, which reads by how the run hands its plan over. -->
		<RunStepList {effects} {turns} context={stepContext(run)} />
	</div>
</details>

<style>
	.answer-row {
		margin: 0.1rem 0;
	}
	.answer-row > summary {
		cursor: pointer;
		padding: 0.35rem 0;
		list-style: none;
	}
	.answer-row > summary::-webkit-details-marker {
		display: none;
	}
	.answer-row > summary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.body {
		margin: 0.15rem 0 0.5rem 0.55rem;
		padding: 0 0 0.25rem 1rem;
		border-left: 2px solid var(--lq-accent-border);
	}
</style>
