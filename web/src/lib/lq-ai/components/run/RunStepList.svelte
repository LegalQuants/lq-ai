<script lang="ts">
	/**
	 * A task's steps, in plain language, through the renderer registry. A step kind
	 * this client has never seen renders through the generic fallback (its label or
	 * a humanised kind, its summary key/values and its reason), never as nothing.
	 *
	 * The model's stated reason, file names and summary values are text from the
	 * run's records: they are interpolated, never rendered as HTML.
	 *
	 * `turns` is what the model wrote at each step, one slot per effect and null for a step
	 * that made no reply (`run/trace.ts` matches them by effect key). A step with a reply
	 * gets a fold, "What the model wrote", under it.
	 *
	 * `context` is what the run says of itself that a step does not: whether its plan is handed over
	 * by a tool call (the first call is then described as the model being asked how to respond, not
	 * asked for a plan), and whether the plan lists documents and knowledge bases (a call that has
	 * not settled has no note saying whether it read or searched). A step does not know the run it
	 * is in, so the list that has the run says so.
	 */
	import type { RunEffect } from '$lib/lq-ai/api/orchestration';
	import { describeEffects } from '$lib/lq-ai/run/renderers';
	import type { StepContext } from '$lib/lq-ai/run/renderers';
	import type { TurnView } from '$lib/lq-ai/run/trace';
	import RunWrote from './RunWrote.svelte';

	export let effects: RunEffect[] = [];
	export let turns: (TurnView | null)[] = [];
	export let context: StepContext = {};

	$: views = describeEffects(effects, context);
</script>

{#if views.length === 0}
	<p class="empty">No steps recorded yet.</p>
{:else}
	<ol class="steps">
		{#each views as view, at}
			{@const turn = turns[at] ?? null}
			<li
				class="step {view.tone}"
				data-testid="lq-ai-run-step"
				data-kind={view.kind}
				data-tone={view.tone}
			>
				<span class="text">{view.text}</span>
				{#if view.cost}<span class="cost">{view.cost}</span>{/if}
				{#each view.facts as fact}<span class="fact">{fact}</span>{/each}
				{#if view.reason}<span class="reason">The model’s stated reason: {view.reason}</span>{/if}
				{#if turn}<div class="reply"><RunWrote {turn} /></div>{/if}
			</li>
		{/each}
	</ol>
{/if}

<style>
	.steps {
		list-style: none;
		margin: 0.25rem 0 0;
		padding: 0;
	}
	.step {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 0 0.5rem;
		padding: 0.3rem 0 0.3rem 0.75rem;
		border-left: 2px solid var(--lq-accent-border);
		font-size: 0.8rem;
		line-height: 1.5;
		overflow-wrap: anywhere;
	}
	.step + .step {
		margin-top: 0.15rem;
	}
	.text {
		color: var(--lq-text);
	}
	.cost,
	.fact,
	.reason {
		color: var(--lq-text-secondary);
		font-size: 0.75rem;
	}
	.reason {
		flex-basis: 100%;
		font-style: italic;
	}
	.reply {
		flex-basis: 100%;
	}
	.refused {
		border-left-color: var(--lq-warn);
	}
	.uncertain {
		border-left-color: var(--lq-error);
	}
	.closed {
		border-left-color: var(--lq-border-strong);
	}
	.working {
		border-left-color: var(--lq-accent);
	}
	.empty {
		margin: 0.25rem 0;
		font-size: 0.8rem;
		color: var(--lq-text-secondary);
	}
</style>
