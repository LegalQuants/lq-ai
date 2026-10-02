<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { skillWorkspacesApi, type SavedSkillWorkspace } from '$lib/lq-ai/api/skillWorkspaces';

	let workspaces: SavedSkillWorkspace[] = [];
	let loading = true;
	let error = '';
	let more = false;
	let preview: { name: string; content: string } | null = null;
	let generation = 0;
	let alive = true;
	let loadGeneration = 0;
	let deleting = false;

	async function load(append = false) {
		const ticket = ++loadGeneration;
		loading = true;
		error = '';
		try {
			const rows = await skillWorkspacesApi.list(append ? workspaces.length : 0);
			if (!alive || ticket !== loadGeneration) return;
			workspaces = append ? [...workspaces, ...rows] : rows;
			more = rows.length === 50;
		} catch {
			if (alive && ticket === loadGeneration) error = 'Saved work could not be loaded.';
		} finally {
			if (alive && ticket === loadGeneration) loading = false;
		}
	}

	async function read(workspace: SavedSkillWorkspace, name: string) {
		const request = ++generation;
		preview = null;
		error = '';
		try {
			const file = await skillWorkspacesApi.read(workspace.id, name);
			if (alive && request === generation) preview = { name, content: file.content };
		} catch {
			if (alive && request === generation) error = 'This saved file could not be loaded.';
		}
	}

	async function reset(workspace: SavedSkillWorkspace) {
		if (deleting) return;
		if (
			!window.confirm(
				`Delete all saved work for ${workspace.skill_name} in ${workspace.project_name ?? 'your personal workspace'}?`
			)
		)
			return;
		++generation;
		++loadGeneration;
		deleting = true;
		preview = null;
		try {
			await skillWorkspacesApi.reset(workspace.id);
			if (alive) await load();
		} catch {
			if (alive) error = 'Saved work could not be deleted.';
		} finally {
			if (alive) deleting = false;
		}
	}

	onMount(() => {
		void load();
	});
	onDestroy(() => {
		alive = false;
		++generation;
	});
</script>

<svelte:head><title>Saved skill work — LQ.AI</title></svelte:head>

<main class="mx-auto max-w-5xl p-6" data-testid="skill-workspaces">
	<a href="/lq-ai/skills" class="text-sm underline">Back to skills</a>
	<h1 class="lq-text-page-h mt-4">Saved skill work</h1>
	<p class="mt-2 text-sm">
		Skills can optionally save notes for later use. Each skill keeps separate work for each matter.
		These are working notes and may be unverified.
	</p>
	{#if error}<p class="mt-4" role="alert">{error}</p>{/if}
	{#if !loading && workspaces.length === 0}<p class="mt-6">No skill has saved work yet.</p>{/if}
	<div class="mt-6 space-y-4">
		{#each workspaces as workspace (workspace.id)}
			<section class="rounded-lg border p-4">
				<div class="flex items-start justify-between gap-4">
					<div>
						<h2 class="font-semibold">{workspace.skill_name}</h2>
						<p class="text-sm">{workspace.project_name ?? 'Personal workspace'}</p>
					</div>
					<button class="text-sm underline" disabled={deleting} on:click={() => reset(workspace)}
						>Delete saved work</button
					>
				</div>
				<ul class="mt-3 space-y-2">
					{#each workspace.files as file (file.name)}
						<li>
							<button class="underline" on:click={() => read(workspace, file.name)}
								>{file.name}</button
							><span class="ml-3 text-sm">Updated {new Date(file.updated_at).toLocaleString()}</span
							>
						</li>
					{/each}
				</ul>
			</section>
		{/each}
	</div>
	{#if loading}<p class="mt-4" role="status">Loading saved work…</p>{/if}
	{#if more && !loading}<button class="mt-4 underline" on:click={() => load(true)}>Load more</button
		>{/if}
	{#if preview}
		<section class="mt-6 rounded-lg border p-4" aria-label="Saved file preview">
			<h2 class="font-semibold">{preview.name}</h2>
			<pre
				class="mt-3 overflow-auto whitespace-pre-wrap break-words text-sm">{preview.content}</pre>
		</section>
	{/if}
</main>
