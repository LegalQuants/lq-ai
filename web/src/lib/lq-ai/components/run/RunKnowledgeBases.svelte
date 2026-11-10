<script lang="ts">
	/**
	 * One line beside the document picker, above the composer, that says which of the matter's
	 * knowledge bases a task of a run started here may search, and how many attached ones a run
	 * leaves out (ADR 0038 D5). They are not picked: a run lists all of them, up to a cap, and its
	 * plan names them for the owner to approve. Nothing is drawn where there are none, which is
	 * every chat outside a matter and every matter with none attached.
	 *
	 * The names are the owner's own text: interpolated, never rendered as markup, and each one
	 * drawn by itself so that it cannot pass for two or reorder the sentence (`RunNamedLine`).
	 */
	import type { RunDocumentsRead } from '$lib/lq-ai/api/orchestration';
	import { knowledgeBasesLineParts } from '$lib/lq-ai/run/composer';
	import RunNamedLine from './RunNamedLine.svelte';

	/** The `run-documents` read for this chat, or null until it has been read. */
	export let read: Pick<RunDocumentsRead, 'knowledge_bases' | 'knowledge_bases_omitted'> | null =
		null;

	$: line = knowledgeBasesLineParts(read);
</script>

{#if line}
	<p class="knowledge-bases" data-testid="lq-ai-run-knowledge-bases"><RunNamedLine {line} /></p>
{/if}

<style>
	.knowledge-bases {
		margin: 0.35rem 0 0;
		font-size: 0.75rem;
		line-height: 1.5;
		color: var(--lq-text-secondary);
		overflow-wrap: anywhere;
	}
</style>
