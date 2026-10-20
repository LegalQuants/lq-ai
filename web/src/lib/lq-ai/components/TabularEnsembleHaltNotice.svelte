<script lang="ts">
	import type { TabularResults } from '$lib/lq-ai/types';

	export let results: TabularResults | null = null;
	$: count = results?.ensemble_halted_cells ?? 0;
	$: hasCount = Number.isInteger(count) && count > 0;
</script>

{#if results?.ensemble_halted_at_ceiling}
	<p class="lq-ensemble-halt" role="status" data-testid="lq-tabres-ensemble-halt">
		Ensemble verification stopped at the estimated cost backstop.
		{#if hasCount}
			Verification was skipped for {count} eligible {count === 1 ? 'cell' : 'cells'}.
		{/if}
		Extraction continued; review the grid for individual failures. Final charges may exceed the estimate.
	</p>
{/if}

<style>
	.lq-ensemble-halt {
		margin: 0.75rem 0 0;
		font-size: 0.875rem;
		line-height: 1.5;
		color: var(--lq-text);
	}
</style>
