<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { getTabularBulkOp } from '$lib/lq-ai/api/tabular';
	import type { TabularBulkOp } from '$lib/lq-ai/types';
	import BulkDraftContent from '$lib/lq-ai/components/BulkDraftContent.svelte';
	let report: TabularBulkOp | null = null;
	let error = '';
	let timer: ReturnType<typeof setTimeout> | undefined;
	let stopped = false;
	$: instructions = report?.provenance.skill_snapshot as
		| { version?: string; content_hash?: string; content_md?: string }
		| undefined;
	async function load(): Promise<void> {
		try {
			const id = $page.params.opId;
			if (!id) return;
			report = await getTabularBulkOp(id);
			if (!stopped && ['pending', 'running'].includes(report.status))
				timer = setTimeout(load, 3000);
		} catch (err) {
			error = err instanceof Error ? err.message : 'Cannot load report.';
		}
	}
	onMount(load);
	onDestroy(() => {
		stopped = true;
		clearTimeout(timer);
	});
</script>

<svelte:head><title>Saved draft · LQ.AI</title></svelte:head>
<section class="report">
	<a href="/lq-ai/tabular/bulk-ops">Saved reports and memos</a>
	{#if error}<p role="alert">{error}</p>{/if}
	{#if report}
		<h1>
			{report.kind === 'redline_rows' ? 'Draft clause revisions' : 'Summary memo'} · {report.params
				.column_name}
		</h1>
		<p>Draft for professional review. Suggested language does not change your source documents.</p>
		<p>Skill: {report.params.skill_name} · {instructions?.version ?? 'version unavailable'}</p>
		<p>Source review: {report.source_execution_id}</p>
		{#if instructions?.content_md}
			<details>
				<summary>Drafting instructions used</summary>
				<p>Instruction hash: {instructions.content_hash}</p>
				<pre>{instructions.content_md}</pre>
			</details>
		{/if}
		{#if report.execution_id}<a href={`/lq-ai/tabular/${report.execution_id}`}
				>Open source review, if available</a
			>
		{:else}<p>
				The source review has been deleted. This output and its source identity were retained.
			</p>{/if}
		<p>
			Processing: {report.status}. {report.results?.summary.failed_items ?? 0} failed or incomplete item(s).
			Finished processing does not mean every draft is complete.
		</p>
		{#if report.error_text}<p role="alert">{report.error_text}</p>{/if}
		{#each report.results?.items ?? [] as item, index (index)}
			<article>
				<h2>{item.document_name ?? 'Comparative memo'}</h2>
				<BulkDraftContent {item} />
			</article>
		{/each}
	{:else if !error}<p>Loading…</p>{/if}
</section>

<style>
	.report {
		padding: 1.5rem;
		max-width: 70rem;
		margin: auto;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	h1 {
		font-size: 1.5rem;
	}
	article {
		margin: 1rem 0;
	}
	pre {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
</style>
