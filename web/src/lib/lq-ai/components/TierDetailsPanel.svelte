<script lang="ts">
	/**
	 * Click-for-details panel that opens from TierBadge — D2.
	 *
	 * The transparency principle (PRD §1.3 + ADR 0011) requires every
	 * user to be able to answer "what just ran?" for any assistant
	 * message. This panel surfaces:
	 *
	 *   • Routed Inference Tier (1-5) + a one-line description.
	 *   • Resolved provider + model.
	 *   • Token usage + cost estimate (when populated).
	 *
	 * The panel is a focus-trapped modal — small + intentionally
	 * lightweight. Clicking outside or pressing Esc closes it. The
	 * close button has data-testid for the D2 e2e smoke.
	 */
	import { createEventDispatcher } from 'svelte';
	import { onMount } from 'svelte';
	import { tierDescriptionFor } from '../chat/tierDescriptions';

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

	const dispatch = createEventDispatcher<{ close: void }>();

	$: tierInfo = tierDescriptionFor(tier);
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

	function handleKeydown(event: KeyboardEvent): void {
		if (event.key === 'Escape') dispatch('close');
	}

	function handleBackdropClick(event: MouseEvent): void {
		// Only the backdrop (not the panel itself) dispatches close.
		if (event.target === event.currentTarget) dispatch('close');
	}

	onMount(() => {
		document.addEventListener('keydown', handleKeydown);
		return () => document.removeEventListener('keydown', handleKeydown);
	});
</script>

<div
	class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
	on:click={handleBackdropClick}
	on:keydown={handleKeydown}
	role="dialog"
	aria-modal="true"
	aria-labelledby="lq-ai-tier-details-title"
	tabindex="-1"
	data-testid="lq-ai-tier-details-backdrop"
>
	<div
		class="bg-white dark:bg-gray-900 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 max-w-md w-full p-4 space-y-3"
		data-testid="lq-ai-tier-details-panel"
	>
		<div class="flex items-start justify-between gap-2">
			<h3
				id="lq-ai-tier-details-title"
				class="text-sm font-semibold text-gray-900 dark:text-gray-100"
			>
				{tierInfo?.label ?? 'Inference details'}
			</h3>
			<button
				type="button"
				class="text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 text-lg leading-none"
				on:click={() => dispatch('close')}
				aria-label="Close"
				data-testid="lq-ai-tier-details-close"
			>
				&times;
			</button>
		</div>

		{#if tierInfo}
			<p class="text-xs text-gray-600 dark:text-gray-300">{tierInfo.blurb}</p>
		{:else}
			<p class="text-xs text-gray-600 dark:text-gray-300">
				This message did not record a routed inference tier. Older messages and messages from before
				D1 / B5 do not carry this metadata.
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
				Per the transparency principle (PRD §1.3): every artifact that shapes your output is
				visible. The router decision behind this message is one of those artifacts.
			</p>
		</div>
	</div>
</div>
