<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { orchestrationApi, shouldPollTree } from '$lib/lq-ai/api/orchestration';
	import type { OrchestrationTree } from '$lib/lq-ai/api/orchestration';

	let tree: OrchestrationTree | null = null;
	let loading = false;
	let acting = false;
	let error = '';
	let pollPaused = false;
	let timer: ReturnType<typeof setTimeout> | undefined;
	let controller: AbortController | undefined;
	let mounted = false;
	let loadedId = '';
	let polls = 0;
	let generation = 0;
	let fileController: AbortController | undefined;
	let openedFile: { session: string; name: string; revision: number; content: string } | null =
		null;
	let fileError = '';
	let fileLoading = false;
	let demoAvailability: 'checking' | 'enabled' | 'disabled' | 'unavailable' = 'checking';

	async function loadDemoAvailability() {
		try {
			const caps = await orchestrationApi.capabilities();
			demoAvailability = caps.enabled ? 'enabled' : 'disabled';
		} catch {
			demoAvailability = 'unavailable';
		}
	}

	async function openFile(session: string, name: string) {
		fileController?.abort();
		const request = new AbortController();
		fileController = request;
		const root = loadedId;
		openedFile = null;
		fileError = '';
		fileLoading = true;
		try {
			const file = await orchestrationApi.file(root, session, name, request.signal);
			if (mounted && root === loadedId && fileController === request)
				openedFile = { session, name, revision: file.revision, content: file.content };
		} catch (err) {
			if (mounted && root === loadedId && fileController === request && !request.signal.aborted)
				fileError = err instanceof Error ? err.message : String(err);
		} finally {
			if (fileController === request) fileLoading = false;
		}
	}

	function stopPolling() {
		clearTimeout(timer);
		controller?.abort();
		generation += 1;
	}
	function schedule() {
		clearTimeout(timer);
		if (!mounted || acting || !tree || !shouldPollTree(tree.status)) return;
		if (polls >= 60) {
			pollPaused = true;
			return;
		}
		timer = setTimeout(() => {
			polls += 1;
			void refresh();
		}, 2000);
	}
	async function refresh(manual = false) {
		stopPolling();
		if (manual) {
			polls = 0;
			pollPaused = false;
			void loadDemoAvailability();
		}
		const requestGeneration = generation;
		const id = loadedId;
		controller = new AbortController();
		loading = true;
		error = '';
		try {
			const response = await orchestrationApi.tree(id, controller.signal);
			if (mounted && requestGeneration === generation && id === loadedId) tree = response;
		} catch (err) {
			if (mounted && requestGeneration === generation)
				error = err instanceof Error ? err.message : String(err);
		} finally {
			if (mounted && requestGeneration === generation) {
				loading = false;
				schedule();
			}
		}
	}
	async function act(action: 'approve' | 'reject' | 'halt') {
		if (!tree || (action === 'approve' && demoAvailability !== 'enabled')) return;
		stopPolling();
		acting = true;
		loading = false;
		error = '';
		const id = loadedId;
		try {
			const response =
				action === 'halt' ? await orchestrationApi.halt(id) : await orchestrationApi[action](tree);
			if (mounted && id === loadedId) tree = response;
		} catch (err) {
			if (mounted && id === loadedId) {
				error = err instanceof Error ? err.message : String(err);
				// Stale approval stays visible; refresh is explicit and never retries consent.
			}
		} finally {
			acting = false;
			if (!error) {
				polls = 0;
				schedule();
			}
		}
	}
	onMount(() => {
		mounted = true;
		void loadDemoAvailability();
		return () => {
			mounted = false;
			stopPolling();
			fileController?.abort();
		};
	});
	$: if (mounted && $page.params.id && $page.params.id !== loadedId) {
		loadedId = $page.params.id;
		fileController?.abort();
		openedFile = null;
		fileError = '';
		tree = null;
		polls = 0;
		pollPaused = false;
		void refresh();
	}
</script>

<div class="mx-auto max-w-4xl space-y-6 p-6">
	<a href="/lq-ai/autonomous/orchestration" class="underline">New demonstration</a>
	<div class="flex items-center justify-between gap-4">
		<h1 class="lq-text-page-h">Plan and progress</h1>
		<button
			on:click={() => refresh(true)}
			disabled={loading || acting}
			class="rounded border px-4 py-2">Refresh</button
		>
	</div>
	<p>Orchestration demonstration · Sample findings · Unverified</p>
	{#if demoAvailability === 'disabled'}
		<p role="status">The operator has disabled the demonstration. Existing plans and results remain available.</p>
	{:else if demoAvailability === 'unavailable'}
		<p role="status">Demonstration availability is unavailable. Approval is disabled until it can be checked.</p>
	{/if}
	<p class="text-sm">
		Working files belong to this run. Shared findings are available to the parent; private notes
		remain with their child. Files are not reused by future runs of the skill.
	</p>
	{#if error}<p role="alert" class="text-red-700 dark:text-red-300">{error}</p>{/if}
	{#if loading && !tree}<p role="status">Loading plan…</p>{/if}
	{#if pollPaused}<p>
			Automatic refresh paused after two minutes. Select Refresh to continue.
		</p>{/if}
	{#if tree}
		<section class="space-y-3 rounded border p-5" aria-label="Plan">
			<h2 class="text-xl font-semibold">{tree.plan.goal}</h2>
			<p role="status">Status: {tree.status.replaceAll('_', ' ')}</p>
			<p>
				Plan revision {tree.plan.revision} · Up to {tree.plan.max_active_children} children at once
			</p>
			<p class="text-sm">Deadline: {new Date(tree.plan.deadline).toLocaleString()}</p>
			<p class="text-sm">Skill: {tree.plan.root.skill.name} · pinned to this plan</p>
			<p>
				Budget ${tree.plan.budget_usd} · Spent ${tree.spent_usd} · Reserved ${tree.reserved_usd} · Root
				allowance ${tree.plan.root_allowance_usd}
			</p>
			{#if tree.status === 'awaiting_approval'}
				<p>
					Review the topics below. Approval starts this batch with the displayed scope and limits.
				</p>
				<div class="flex gap-3">
					<button
						disabled={acting || demoAvailability !== 'enabled'}
						on:click={() => act('approve')}
						class="rounded bg-blue-700 px-4 py-2 text-white">Approve plan</button
					>
					<button disabled={acting} on:click={() => act('reject')} class="rounded border px-4 py-2"
						>Reject plan</button
					>
				</div>
			{:else if shouldPollTree(tree.status)}
				<button
					disabled={acting}
					on:click={() => act('halt')}
					class="rounded border border-red-600 px-4 py-2">Halt run</button
				>
			{/if}
		</section>
		<section class="space-y-4" aria-label="Topic progress">
			<h2 class="text-xl font-semibold">Topics</h2>
			{#each tree.plan.children as child, index}
				{@const progress = tree.children[index]}
				<article class="space-y-2 rounded border p-5">
					<h3 class="font-semibold">{index + 1}. {child.task.topic}</h3>
					<p>{child.task.question}</p>
					<p class="text-sm">{child.task.boundaries}</p>
					<p class="text-sm">Stop: {child.task.stopping_condition}</p>
					<p>
						Status: {progress.status} · Phase: {progress.phase.replaceAll('_', ' ')} · Spent ${progress.spent_usd}
						· Reserved ${progress.reserved_usd}
					</p>
					{#if progress.outcome}
						<p>{progress.outcome.summary}</p>
						<ul class="list-disc pl-5">
							{#each progress.outcome.findings as finding}<li>{finding}</li>{/each}
						</ul>
					{/if}
					{#if progress.files?.length}
						<div aria-label="Working files" class="space-y-2">
							<p class="font-semibold">Working files</p>
							{#each progress.files as file}
								<button
									class="block text-sm underline"
									on:click={() => openFile(progress.session_id, file.name)}
								>
									{file.name} · revision {file.revision} · {file.shared
										? 'Shared with parent'
										: 'Private working file'}
								</button>
							{/each}
						</div>
					{/if}
					{#if progress.effects.length}
						<details>
							<summary>Effect receipts ({progress.effects.length})</summary>
							<ul class="space-y-1 pt-2">
								{#each progress.effects as effect}<li>
										{effect.effect_key}: {effect.status}, charged ${effect.charged_usd ?? 'pending'}
									</li>{/each}
							</ul>
						</details>
					{/if}
					{#if progress.status !== 'pending'}<a
							class="text-sm underline"
							href={`/lq-ai/autonomous/sessions/${child.dispatch_id}`}>Child receipt</a
						>{/if}
				</article>
			{/each}
		</section>
		{#if fileLoading}<p role="status">Loading working file…</p>{/if}
		{#if fileError}<p role="alert">{fileError}</p>{/if}
		{#if openedFile}
			<section class="space-y-3 rounded border p-5" aria-label="Working file content">
				<h2 class="text-xl font-semibold">{openedFile.name} · revision {openedFile.revision}</h2>
				<p class="text-sm">
					Saved work from this run. This preview shows the revision loaded when you selected the
					file.
				</p>
				<pre class="whitespace-pre-wrap break-words text-sm">{openedFile.content}</pre>
			</section>
		{/if}
		{#if tree.result || tree.partial_summary}
			<section class="space-y-3 rounded border p-5" aria-label="Synthesis">
				<h2 class="text-xl font-semibold">
					{tree.partial_summary ? 'Available results' : 'Synthesis'}
				</h2>
				{#if tree.result}<p>
						Topic coverage: {tree.result.coverage} · Verification: unverified
					</p>{/if}
				<p class="whitespace-pre-wrap">{tree.partial_summary ?? tree.result?.summary}</p>
			</section>
		{/if}
	{/if}
</div>
