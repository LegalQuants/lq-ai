<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { projectsApi } from '$lib/lq-ai/api';
	import { orchestrationApi } from '$lib/lq-ai/api/orchestration';
	import type { Project } from '$lib/lq-ai/types';

	let projects: Project[] = [];
	let projectId = '';
	let goal = '';
	let topicText = 'Scope\nFindings\nOpen questions';
	let concurrency = 2;
	let loading = true;
	let enabled = false;
	let capacity: number | null = null;
	let submitting = false;
	let error = '';
	$: topics = topicText
		.split('\n')
		.map((topic) => topic.trim())
		.filter(Boolean);

	onMount(() => {
		(async () => {
			try {
				const [caps, choices] = await Promise.all([
					orchestrationApi.capabilities(),
					projectsApi.listProjects()
				]);
				enabled = caps.enabled;
				capacity = caps.deployment_children;
				projects = choices;
			} catch (err) {
				error = err instanceof Error ? err.message : String(err);
			} finally {
				loading = false;
			}
		})();
	});

	async function prepare() {
		submitting = true;
		error = '';
		try {
			const tree = await orchestrationApi.prepare({
				project_id: projectId,
				goal: goal.trim(),
				topics,
				max_active_children: concurrency
			});
			await goto(`/lq-ai/autonomous/orchestration/${tree.root_id}`);
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
		} finally {
			submitting = false;
		}
	}
</script>

<div class="mx-auto max-w-3xl space-y-6 p-6">
	<a href="/lq-ai/autonomous" class="underline">Autonomous sessions</a>
	<h1 class="lq-text-page-h">Orchestration demonstration</h1>
	<p>
		Prepare a plan, approve parallel topics and follow their findings into a combined result. This
		demonstration uses local sample responses. Findings remain unverified.
	</p>
	{#if error}<p role="alert" class="text-red-700 dark:text-red-300">{error}</p>{/if}
	{#if loading}
		<p role="status">Loading configuration…</p>
	{:else if !enabled}
		<p>The operator has not enabled the orchestration demonstration.</p>
	{:else}
		<p class="text-sm">
			Shared capacity: {capacity} children. Sample execution costs $0 and uses no live providers.
		</p>
		<form on:submit|preventDefault={prepare} class="space-y-5">
			<label class="block"
				>Matter
				<select
					bind:value={projectId}
					required
					class="mt-1 w-full rounded border p-2 dark:bg-gray-900"
				>
					<option value="">Choose a matter</option>
					{#each projects as project}<option value={project.id}>{project.name}</option>{/each}
				</select>
			</label>
			<label class="block"
				>Goal
				<textarea
					bind:value={goal}
					required
					maxlength="4096"
					rows="3"
					class="mt-1 w-full rounded border p-2 dark:bg-gray-900"
				></textarea>
			</label>
			<label class="block"
				>Topics (one per line, up to four)
				<textarea
					bind:value={topicText}
					required
					maxlength="1027"
					rows="4"
					class="mt-1 w-full rounded border p-2 dark:bg-gray-900"
				></textarea>
			</label>
			<label class="block"
				>Children running at once
				<select bind:value={concurrency} class="ml-3 rounded border p-2 dark:bg-gray-900">
					{#each [1, 2, 3, 4] as count}<option value={count}>{count}</option>{/each}
				</select>
			</label>
			<button
				class="rounded bg-blue-700 px-4 py-2 text-white disabled:opacity-50"
				disabled={submitting ||
					!projectId ||
					!goal.trim() ||
					topics.length < 1 ||
					topics.length > 4 ||
					topics.some((topic) => topic.length > 256)}
			>
				{submitting ? 'Preparing…' : 'Prepare plan'}
			</button>
		</form>
	{/if}
</div>
