<script lang="ts">
	import type { TabularBulkOpItem } from '$lib/lq-ai/types';
	import DraftMarkdown from './DraftMarkdown.svelte';
	export let item: TabularBulkOpItem;
</script>

{#if item.source_rows?.length}
	<section aria-label="Source coverage" data-testid="lq-memo-source-coverage">
		<h3>Source coverage</h3>
		<p>From the selected-column grid. Missing values are unavailable evidence.</p>
		<ul>
			{#each item.source_rows as row}
				<li>
					{row.document_name}: {row.status === 'missing'
						? 'Missing — extraction failed or unavailable'
						: row.value}
				</li>
			{/each}
		</ul>
	</section>
{/if}
{#if item.status === 'failed'}
	<p role="alert">Failed: {item.error ?? 'unknown error'}</p>
{/if}
{#if item.output_text}
	{#if item.status === 'failed'}<p>Partial draft — incomplete; retained for inspection.</p>{/if}
	<DraftMarkdown content={item.output_text} />
{/if}
