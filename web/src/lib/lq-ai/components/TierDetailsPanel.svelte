<script lang="ts">
	/**
	 * Tier details display panel — D2.
	 *
	 * The transparency principle (PRD §1.3 + ADR 0011) requires every
	 * user to be able to answer "what just ran?" for any assistant
	 * message. This panel surfaces:
	 *
	 *   • Routed Inference Tier (1-5) + a one-line description.
	 *   • Resolved provider + model.
	 *   • Token usage + cost estimate (when populated).
	 *
	 * Pure display — no backdrop, no close button, no keyboard/click
	 * handling, no dispatched events. It's rendered as-is by whatever
	 * container the caller chooses (a modal, a hover popover, an inline
	 * panel); this component owns none of that presentation.
	 */
	import { TIER_DESCRIPTIONS } from '../chat/tierDescriptions';

	export let tier: 1 | 2 | 3 | 4 | 5 | null | undefined = null;
	export let provider: string | null | undefined = null;
	export let model: string | null | undefined = null;
	/**
	 * The model the user originally requested — alias (e.g. `smart`) or
	 * `provider/model` direct dispatch. ADR 0011 follow-on: when this
	 * differs from the routed pair, the panel surfaces the resolution
	 * step so users can answer "what did I ask for vs what ran?".
	 */
	export let requestedModel: string | null | undefined = null;
	export let promptTokens: number | null | undefined = null;
	export let completionTokens: number | null | undefined = null;
	export let costEstimate: number | null | undefined = null;

	$: tierInfo = tier ? TIER_DESCRIPTIONS[tier] : null;
	$: routedPair = provider && model ? `${provider}/${model}` : null;
	$: providerModelLine =
		provider && model
			? `${provider} / ${model}`
			: provider
				? provider
				: model
					? model
					: 'Provider/model not recorded for this message.';
	/**
	 * Show the requested-vs-routed line only when the user's original
	 * request differed from the routed pair — i.e. an alias was resolved.
	 * Direct `provider/model` dispatch produces identical strings; surfacing
	 * "Requested: anthropic-prod/claude-opus-4-7 → routed to
	 * anthropic-prod/claude-opus-4-7" is noise.
	 */
	$: showRequestedDelta =
		requestedModel != null && requestedModel !== '' && requestedModel !== routedPair;
	$: showTokens = promptTokens != null || completionTokens != null;
	$: showCost = costEstimate != null && costEstimate > 0;
</script>

<div
	class="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 max-w-md p-4 space-y-3"
	data-testid="lq-ai-tier-details-panel"
>
	<h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100">
		{tierInfo?.label ?? 'Inference details'}
	</h3>

	{#if tierInfo}
		<p class="text-xs text-gray-600 dark:text-gray-300">{tierInfo.blurb}</p>
	{:else}
		<p class="text-xs text-gray-600 dark:text-gray-300">
			This message did not record a routed inference tier. Older messages
			and messages from before D1 / B5 do not carry this metadata.
		</p>
	{/if}

	{#if showRequestedDelta}
		<div class="border-t border-gray-200 dark:border-gray-800 pt-2">
			<div class="text-[10px] uppercase tracking-wide text-gray-500">Requested</div>
			<div
				class="text-sm font-mono text-gray-800 dark:text-gray-100"
				data-testid="lq-ai-tier-details-requested-model"
			>
				{requestedModel}
			</div>
			<div class="text-[10px] text-gray-500 italic mt-0.5">
				Resolved server-side per ADR 0011.
			</div>
		</div>
	{/if}

	<div class="border-t border-gray-200 dark:border-gray-800 pt-2">
		<div class="text-[10px] uppercase tracking-wide text-gray-500">
			{showRequestedDelta ? 'Routed to' : 'Provider / model'}
		</div>
		<div
			class="text-sm font-mono text-gray-800 dark:text-gray-100"
			data-testid="lq-ai-tier-details-provider-model"
		>
			{providerModelLine}
		</div>
	</div>

	{#if showTokens || showCost}
		<div class="border-t border-gray-200 dark:border-gray-800 pt-2 grid grid-cols-2 gap-2">
			{#if promptTokens != null}
				<div>
					<div class="text-[10px] uppercase tracking-wide text-gray-500">Prompt tokens</div>
					<div class="text-sm font-mono text-gray-800 dark:text-gray-100">{promptTokens}</div>
				</div>
			{/if}
			{#if completionTokens != null}
				<div>
					<div class="text-[10px] uppercase tracking-wide text-gray-500">Completion tokens</div>
					<div class="text-sm font-mono text-gray-800 dark:text-gray-100">{completionTokens}</div>
				</div>
			{/if}
			{#if showCost}
				<div class="col-span-2">
					<div class="text-[10px] uppercase tracking-wide text-gray-500">Cost estimate</div>
					<div class="text-sm font-mono text-gray-800 dark:text-gray-100">
						${costEstimate?.toFixed(4)}
					</div>
				</div>
			{/if}
		</div>
	{/if}

	<div class="border-t border-gray-200 dark:border-gray-800 pt-2">
		<p class="text-[11px] text-gray-500 italic">
			Per the transparency principle (PRD §1.3): every artifact that shapes
			your output is visible. The router decision behind this message is one
			of those artifacts.
		</p>
	</div>
</div>
