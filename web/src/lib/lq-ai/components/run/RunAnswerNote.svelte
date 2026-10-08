<script lang="ts">
	/**
	 * The evidence line for a delivered answer: how far to rely on it.
	 *
	 * A profile either produces model-generated text that nothing has checked, or an
	 * answer whose quotations were matched against the documents the owner selected,
	 * reported in counts. The citation chips and ledger under the answer show each
	 * individual result. This line never calls an answer verified, correct or advice.
	 */
	import type { OrchestrationChatRun } from '$lib/lq-ai/api/orchestration';
	import {
		evidenceGate,
		evidenceHint,
		evidenceState,
		evidenceStatement
	} from '$lib/lq-ai/run/evidence';

	export let run: Pick<OrchestrationChatRun, 'evidence' | 'evidence_result'>;

	$: state = evidenceState(run);
	$: statement = evidenceStatement(run);
	$: hint = evidenceHint(run);
	$: gate = evidenceGate(run);
</script>

<div class="evidence {state}">
	<p
		class="statement"
		data-testid="lq-ai-run-answer-evidence"
		data-evidence={run.evidence ?? 'unverified'}
		data-state={state}
		data-gate={gate ?? undefined}
	>
		{statement}
	</p>
	{#if hint}<p class="hint">{hint}</p>{/if}
</div>

<style>
	.evidence {
		margin: 0.75rem 0 0.25rem;
		padding: 0.5rem 0.75rem;
		border-left: 3px solid var(--lq-border-strong);
		background: var(--lq-inset);
		border-radius: 0 var(--lq-radius) var(--lq-radius) 0;
	}
	.evidence.matched {
		border-left-color: var(--lq-accent);
	}
	.evidence.unmatched,
	.evidence.incomplete,
	.evidence.unchecked {
		border-left-color: var(--lq-warn);
	}
	p {
		margin: 0;
		font-size: 0.85rem;
		line-height: 1.5;
	}
	.statement {
		font-weight: 600;
		color: var(--lq-text);
	}
	.hint {
		margin-top: 0.15rem;
		font-size: 0.8rem;
		color: var(--lq-text-secondary);
	}
</style>
