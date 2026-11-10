<script lang="ts">
	/**
	 * One effect's receipt: what was recorded for a model call, a tool call or a
	 * file write, with its charge, the skill or prompt file pin and the provider accounting.
	 * Everything here is text; digests and keys are shown as code, never as HTML.
	 *
	 * `context` is what the run says of itself that a step does not: how its plan is handed over,
	 * and what the plan lists for its tasks to read and search (see `RunStepList`).
	 */
	import type { RunEffect } from '$lib/lq-ai/api/orchestration';
	import { describeEffect } from '$lib/lq-ai/run/renderers';
	import type { StepContext } from '$lib/lq-ai/run/renderers';
	import { formatUsd } from '$lib/lq-ai/run/format';
	import { receiptPin } from '$lib/lq-ai/run/plan';

	export let effect: RunEffect;
	export let context: StepContext = {};

	$: view = describeEffect(effect, context);
	$: charge = effect.charged_usd ?? effect.reserved_usd;
</script>

<div class="receipt" data-testid="lq-ai-run-effect-receipt" data-status={effect.status}>
	<p class="line">
		<strong>{view.text}</strong>
		<span class="muted">· {effect.status}</span>
		<span class="muted">· {formatUsd(charge)}{effect.charged_usd === null ? ' reserved' : ''}</span>
	</p>
	<p class="muted key">
		<code>{effect.effect_key}</code>{#if effect.intent}{` · ${effect.intent}`}{/if}
	</p>
	{#if effect.skill}
		<p class="muted">
			{receiptPin(effect.skill)}
			<code>{effect.skill.digest}</code>
		</p>
	{/if}
	{#if effect.accounting}
		<p class="muted">
			{effect.accounting.provider}/{effect.accounting.model} · {effect.accounting.basis} · about
			{effect.accounting.estimated_prompt_tokens} prompt tokens
		</p>
	{/if}
	<p class="muted">{effect.created_at ?? ''} → {effect.completed_at ?? 'not completed'}</p>
</div>

<style>
	.receipt {
		border-top: 1px solid var(--lq-border);
		padding: 0.5rem 0;
		font-size: 0.75rem;
		overflow-wrap: anywhere;
	}
	.receipt p {
		margin: 0.15rem 0;
		line-height: 1.5;
	}
	.line {
		font-size: 0.8rem;
	}
	.muted {
		color: var(--lq-text-secondary);
	}
	code {
		font-size: 0.7rem;
		overflow-wrap: anywhere;
	}
</style>
