<script lang="ts">
	import { onMount } from 'svelte';
	import { listTabularBulkOps } from '$lib/lq-ai/api/tabular';
	import type { TabularBulkOp } from '$lib/lq-ai/types';
	let reports: TabularBulkOp[] = [];
	let loading = false;
	let error = '';
	let more = true;
	async function load(): Promise<void> {
		loading = true;
		error = '';
		try {
			const next = await listTabularBulkOps(reports.length);
			reports = [...reports, ...next];
			more = next.length === 50;
		} catch (err) {
			error = err instanceof Error ? err.message : 'Cannot load reports.';
		} finally {
			loading = false;
		}
	}
	onMount(load);
</script>

<svelte:head><title>Saved reports and memos · LQ.AI</title></svelte:head>
<section class="reports">
	<a href="/lq-ai/tabular">Tabular Review</a>
	<h1>Saved reports and memos</h1>
	<p>Draft outputs remain here even when their source review is deleted.</p>
	{#if error}<p role="alert">{error}</p>{/if}
	{#if !loading && reports.length === 0}<p>No saved reports or memos yet.</p>{/if}
	<ul>
		{#each reports as report (report.id)}
			<li>
				<a href={`/lq-ai/tabular/bulk-ops/${report.id}`}>
					{report.kind === 'redline_rows' ? 'Draft revisions' : 'Summary memo'} · {report.params
						.column_name}
				</a>
				· {report.status} · {new Date(report.created_at).toLocaleString()}
			</li>
		{/each}
	</ul>
	{#if more}<button type="button" disabled={loading} on:click={load}
			>{loading ? 'Loading…' : 'Load more'}</button
		>{/if}
</section>

<style>
	.reports {
		padding: 1.5rem;
		max-width: 70rem;
		margin: auto;
	}
	h1 {
		font-size: 1.5rem;
	}
	li {
		margin: 1rem 0;
	}
</style>
