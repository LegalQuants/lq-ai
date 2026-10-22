<script lang="ts">
	/**
	 * The files a run's searches found, under the answer line: one row for each, with the number a
	 * quotation's `(Source: [N])` marker carries, so a reader gets from `[27]` in the answer to a
	 * file name, and to the task whose search found it. Nothing is drawn for a run that found none.
	 *
	 * It is not inside the answer line's fold: the numbers in the answer are cited where the answer
	 * is read, and a list that had to be opened first would not be where they are explained.
	 *
	 * File names are the owner's own text: interpolated, never rendered as markup.
	 */
	import type { OrchestrationChatRun } from '$lib/lq-ai/api/orchestration';
	import { SOURCES_TITLE, runSources } from '$lib/lq-ai/run/sources';

	export let run: Pick<OrchestrationChatRun, 'sources' | 'tree'>;

	$: rows = runSources(run);
</script>

{#if rows.length > 0}
	<section class="sources" aria-label={SOURCES_TITLE} data-testid="lq-ai-run-sources">
		<h4 class="title">{SOURCES_TITLE}</h4>
		<ul class="list">
			{#each rows as row}
				<li class="source" data-testid="lq-ai-run-source">{row.text}</li>
			{/each}
		</ul>
	</section>
{/if}

<style>
	.sources {
		margin: 0.1rem 0 0.4rem 0.55rem;
		padding: 0 0 0.1rem 1rem;
		border-left: 2px solid var(--lq-border);
		min-width: 0;
	}
	.title {
		margin: 0.25rem 0 0.1rem;
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--lq-text-secondary);
	}
	.list {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.source {
		margin: 0.1rem 0;
		font-size: 0.8rem;
		line-height: 1.5;
		overflow-wrap: anywhere;
	}
</style>
