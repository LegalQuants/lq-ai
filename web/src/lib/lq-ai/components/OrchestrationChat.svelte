<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import {
		orchestrationApi,
		orchestrationChatApi,
		shouldPollTree
	} from '$lib/lq-ai/api/orchestration';
	import type {
		ChatCapabilities,
		OrchestrationChatRun,
		WorkspaceFile
	} from '$lib/lq-ai/api/orchestration';

	let caps: ChatCapabilities | null = null;
	let run: OrchestrationChatRun | null = null;
	let goal =
		'Explain our payment obligations, the implementation and support commitments, and how renewal and termination work in this fictional vendor agreement. Divide the questions into independent assessments, then combine the answers and highlight missing information.';
	let requestId = '';
	let error = '';
	let busy = false;
	let ready = false;
	let mounted = false;
	let polls = 0;
	let paused = false;
	let loadedId = '';
	let timer: ReturnType<typeof setTimeout> | undefined;
	let request: AbortController | undefined;
	let openedFile: (WorkspaceFile & { content: string }) | null = null;
	let fileError = '';
	let fileSession = '';
	$: id = $page.params.id ?? '';
	$: tree = run?.tree;
	$: canHalt =
		run &&
		[
			'planning',
			'awaiting_approval',
			'queued',
			'running',
			'waiting_children',
			'uncertain'
		].includes(run.status);
	$: if (mounted && id !== loadedId) {
		loadedId = id;
		run = null;
		openedFile = null;
		fileError = '';
		fileSession = '';
		polls = 0;
		paused = false;
		clearTimeout(timer);
		request?.abort();
		if (id) void refresh();
	}

	onMount(() => {
		mounted = true;
		void orchestrationChatApi
			.capabilities()
			.then((value) => (caps = value))
			.catch((err) => {
				error = err instanceof Error ? err.message : String(err);
			})
			.finally(() => (ready = true));
		return () => {
			mounted = false;
			clearTimeout(timer);
			request?.abort();
		};
	});

	function schedule() {
		clearTimeout(timer);
		if (!mounted || busy || !run || !shouldPollTree(run.status)) return;
		if (polls >= 120) {
			paused = true;
			return;
		}
		timer = setTimeout(() => {
			polls += 1;
			void refresh();
		}, 2000);
	}

	async function refresh(manual = false) {
		if (!id) return;
		clearTimeout(timer);
		request?.abort();
		const controller = new AbortController();
		request = controller;
		const target = id;
		if (manual) {
			polls = 0;
			paused = false;
		}
		try {
			const value = await orchestrationChatApi.read(target, controller.signal);
			if (mounted && target === id && !controller.signal.aborted) {
				run = value;
				error = '';
				schedule();
			}
		} catch (err) {
			if (!controller.signal.aborted) error = err instanceof Error ? err.message : String(err);
		}
	}

	async function start() {
		if (!caps?.project_id || !goal.trim() || busy) return;
		busy = true;
		error = '';
		requestId ||= crypto.randomUUID();
		try {
			const value = await orchestrationChatApi.start({
				request_id: requestId,
				project_id: caps.project_id,
				goal: goal.trim()
			});
			await goto(`/lq-ai/autonomous/orchestration/chat/${value.root_id}`);
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
		} finally {
			busy = false;
			schedule();
		}
	}

	async function act(action: 'approve' | 'reject' | 'halt') {
		if (!run || busy) return;
		busy = true;
		error = '';
		clearTimeout(timer);
		request?.abort();
		try {
			if (action === 'halt') await orchestrationChatApi.halt(run.root_id);
			else if (tree) await orchestrationApi[action](tree);
			await refresh(true);
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
		} finally {
			busy = false;
			schedule();
		}
	}

	async function openFile(session: string, file: WorkspaceFile) {
		if (!run) return;
		fileError = '';
		fileSession = session;
		openedFile = null;
		try {
			openedFile = await orchestrationApi.file(run.root_id, session, file.name);
		} catch (err) {
			fileError = err instanceof Error ? err.message : String(err);
		}
	}
</script>

<div class="chat-demo">
	<header>
		<a href="/lq-ai/autonomous">Autonomous sessions</a>
		<div class="heading">
			<h1 class="lq-text-page-h">Orchestration chat</h1>
			<span class="tag">Experimental</span>
		</div>
		<p>Approve a model-proposed plan, follow independent agents, and inspect their answers.</p>
		<p class="scope">Fictional inputs · Contract QA skill · Unverified model output</p>
	</header>

	{#if error}<p role="alert" class="error">{error}</p>{/if}
	{#if !ready && !run}<p role="status">Checking demonstration availability…</p>{/if}
	{#if caps && !caps.enabled}
		<p class="notice">
			The operator has not enabled model orchestration for your demo project. Retained runs can
			still be inspected and halted.
		</p>
	{/if}

	{#if !id && caps?.enabled}
		<section class="panel" aria-label="Demo configuration">
			<label for="orchestrator">Orchestrator</label>
			<select id="orchestrator"><option>{caps.title}</option></select>
			<p>{caps.project_name} · Model: <strong>{caps.model}</strong></p>
			<p>Each attempt has a {caps.attempt_timeout_seconds}-second limit.</p>
			<p>
				Total accounted cap: <strong>${caps.budget_usd}</strong>. Planning allowance:
				<strong>${caps.planning_allowance_usd}</strong>.
			</p>
			<p>
				Propose plan authorizes one model call. Child work requires your approval afterwards.
				Planning spend is retained if you reject the plan.
			</p>
			<details>
				<summary>Inspect fictional vendor agreement</summary>
				<pre>{caps.packet}</pre>
			</details>
		</section>
		<form class="panel" on:submit|preventDefault={start}>
			<label for="goal">What would you like the agents to examine?</label>
			<textarea
				id="goal"
				bind:value={goal}
				on:input={() => (requestId = '')}
				maxlength="4096"
				rows="5"
				required
				disabled={busy}
			></textarea>
			<p class="muted">
				Use fictional questions about this agreement. This demonstration has no access to your
				matter documents or live sources.
			</p>
			<button class="primary" disabled={busy || !goal.trim()}
				>{busy ? 'Preparing request…' : 'Propose plan'}</button
			>
		</form>
	{/if}

	{#if id && !run}<p role="status">Loading retained conversation…</p>
		<button on:click={() => refresh(true)}>Refresh</button>{/if}
	{#if run}
		<div class="run-bar">
			<span role="status">{run.status.replaceAll('_', ' ')}</span><span
				>Spent ${run.spent_usd} · Reserved ${run.reserved_usd}</span
			><button on:click={() => refresh(true)} disabled={busy}>Refresh</button>{#if canHalt}<button
					class="halt"
					on:click={() => act('halt')}
					disabled={busy}>Halt</button
				>{/if}
		</div>
		{#if run.status === 'uncertain'}<p class="notice">
				A provider call has an unresolved outcome. Execution is stopped and will not retry. Halt
				retains the receipts and any reservation; an operator must reconcile this run before this
				owner can start another.
			</p>{/if}
		{#if run.status === 'rejected'}<p class="notice" role="status">
				Plan rejected. No child work or synthesis will run. You can start a new request; this
				planning receipt remains available.
			</p>{/if}
		{#if run.status === 'halted'}<p class="notice" role="status">
				Run halted. No combined answer was produced. Any completed child answers and their files
				remain available below.
			</p>{/if}
		{#if paused}<p class="notice">
				Automatic refresh paused. Refresh to continue following this run; execution continues on the
				server.
			</p>{/if}
		<section class="message user">
			<p class="eyebrow">Your request</p>
			<p>{run.planning.goal}</p>
		</section>
		<section class="source-reference" aria-label="Agreement reference">
			<div class="heading">
				<div>
					<p class="eyebrow">Agreement reference</p>
					<h2>Fictional vendor agreement</h2>
				</div>
				<span class="tag">Source for this run</span>
			</div>
			{#if run.packet}<details>
					<summary>Read the agreement used by the agents</summary>
					<pre class="source-text">{run.packet}</pre>
				</details>{:else}<p class="muted">
					The agreement text for this run is unavailable. Its pinned digest remains in Run
					provenance.
				</p>{/if}
		</section>
		<section class="message" aria-label="Orchestrator response">
			<p class="eyebrow">Contract Questions Orchestrator · {run.planning.root_skill_version}</p>
			{#if run.status === 'planning'}<p role="status">
					The model is proposing bounded tasks. No child work has been approved.
				</p>{/if}
			{#if !tree && run.status !== 'planning'}<p>
					Planning stopped: {run.stop_reason ?? run.status}. Any completed planning charge and
					receipt are retained.
				</p>{/if}
			{#if tree}
				<h2>Proposed plan</h2>
				<p>
					{tree.plan.children.length} tasks · up to {tree.plan.max_active_children} concurrent children
					· model {run.planning.model}
				</p>
				<p>
					Total cap ${tree.plan.budget_usd} · root allowance ${tree.plan.root_allowance_usd} · deadline
					{new Date(tree.plan.deadline).toLocaleString()}
				</p>
				<p>Attempt limit: {run.planning.attempt_timeout_seconds} seconds.</p>
				<p>Sources: fictional agreement only. No live sources or matter documents selected.</p>
				<ol class="tasks">
					{#each tree.plan.children as task}<li>
							<strong>{task.task.topic}</strong>
							<p>{task.task.question}</p>
							<p class="skill">
								Skill: Contract QA v{run.planning.child_skill_version} · allowance ${task.budget_usd}
							</p>
							<details>
								<summary>Task boundaries and expected output</summary>
								<p>{task.task.boundaries}</p>
								<p>{task.task.output_contract}</p>
								<p>Stops when: {task.task.stopping_condition}</p>
							</details>
						</li>{/each}
				</ol>
				{#if run.status === 'awaiting_approval'}<div class="actions">
						<button
							class="primary"
							on:click={() => act('approve')}
							disabled={busy || !caps?.enabled}>Approve plan</button
						><button on:click={() => act('reject')} disabled={busy}>Reject plan</button>
					</div>
					<p class="muted">
						Approves revision {tree.plan.revision} exactly as shown. Children cannot delegate further.
					</p>{:else if tree.approved}<p class="notice">
						You approved revision {tree.plan.revision}.
					</p>{/if}
			{/if}
		</section>
		{#if tree && tree.approved}
			<section aria-label="Child progress" class="children">
				{#each tree.children as child, index}
					<article class="panel child">
						<div class="heading">
							<h2>{tree.plan.children[index]?.task.topic}</h2>
							<span class="tag">{child.status}</span>
						</div>
						<p class="skill">Contract QA v{run.planning.child_skill_version} · {child.phase}</p>
						<p>Spent ${child.spent_usd} · Reserved ${child.reserved_usd}</p>
						{#if child.outcome}<p>{child.outcome.summary}</p>
							{#each child.outcome.findings as finding}<pre
									class="answer">{finding}</pre>{/each}{/if}
						<details>
							<summary>Skill execution receipt and files</summary>
							<p class="muted">Session {child.session_id}</p>
							{#each child.effects as effect}<div class="receipt">
									<strong>{effect.intent ?? effect.effect_key}</strong> · {effect.status} · ${effect.charged_usd ??
										effect.reserved_usd}{#if effect.skill}<p>
											{effect.skill.name} v{effect.skill.version}
										</p>
										<code>{effect.skill.digest}</code>{/if}{#if effect.accounting}<p>
											{effect.accounting.provider}/{effect.accounting.model} · {effect.accounting
												.basis}
										</p>{/if}
									<p>{effect.created_at ?? ''} → {effect.completed_at ?? 'pending'}</p>
								</div>{/each}{#each child.files as file}<button
									class="file-link"
									type="button"
									on:click={() => openFile(child.session_id, file)}
									>{file.name} · revision {file.revision}{file.shared
										? ' · shared with root'
										: ' · private notes'}</button
								>{/each}
							{#if fileSession === child.session_id && fileError}<p role="alert" class="error">
									{fileError}
								</p>{/if}
							{#if openedFile?.session_id === child.session_id}<div
									class="file-preview"
									role="region"
									aria-label="{openedFile.name} file contents"
								>
									<div class="file-preview-header">
										<div>
											<p class="eyebrow">Saved run file</p>
											<h3>{openedFile.name}</h3>
											<p class="muted">
												Revision {openedFile.revision} · {openedFile.shared
													? 'Shared with orchestrator'
													: 'Private child notes'}
											</p>
										</div>
										<button type="button" on:click={() => (openedFile = null)}>Close file</button>
									</div>
									<pre class="file-content">{openedFile.content}</pre>
								</div>{/if}
						</details>
					</article>
				{/each}
			</section>
		{/if}
		{#if tree?.result || (tree?.partial_summary && !['halted', 'rejected'].includes(run.status))}<section
				class="message result"
				aria-label="Combined result"
			>
				<h2>{tree.result ? 'Combined answer' : 'Retained work overview'}</h2>
				<p class="scope">
					{tree.result
						? 'Model-generated from fictional inputs; unverified'
						: 'No combined model answer was produced. This overview lists stored child outcomes.'}
				</p>
				<pre class="answer">{tree.result?.summary ?? tree.partial_summary}</pre>
			</section>{/if}
		<details class="panel">
			<summary>Run provenance and root receipts</summary>
			<p>Run {run.root_id}</p>
			<p>Model {run.planning.model}</p>
			<p>Packet digest <code>{run.planning.packet_digest}</code></p>
			<p>Gateway configuration <code>{run.planning.gateway_revision}</code></p>
			{#if tree}<p>
					Plan digest <code>{tree.plan_hash}</code>
				</p>{/if}{#each run.effects as effect}<div class="receipt">
					{effect.intent ?? effect.effect_key} · {effect.status} · ${effect.charged_usd ??
						effect.reserved_usd}{#if effect.skill}<p>
							{effect.skill.name} v{effect.skill.version} · <code>{effect.skill.digest}</code>
						</p>{/if}
				</div>{/each}
		</details>
		{#if !canHalt}<a class="new-run" href="/lq-ai/autonomous/orchestration/chat"
				>Start a new request</a
			>{/if}
	{/if}
</div>

<style>
	.chat-demo {
		max-width: 960px;
		margin: 0 auto;
		padding: 2rem 1.5rem 4rem;
		color: var(--lq-text-primary);
	}
	header {
		margin-bottom: 1.5rem;
	}
	.heading,
	.run-bar,
	.actions {
		display: flex;
		align-items: center;
		gap: 0.8rem;
		flex-wrap: wrap;
	}
	.heading {
		justify-content: space-between;
	}
	h1 {
		margin: 0.6rem 0;
	}
	h2 {
		font-size: 1.05rem;
		font-weight: 600;
	}
	p {
		margin: 0.5rem 0;
		line-height: 1.6;
	}
	a {
		color: var(--lq-accent);
		text-decoration: underline;
	}
	.panel,
	.message {
		border: 1px solid var(--lq-border);
		border-radius: 12px;
		padding: 1.25rem;
		margin: 1rem 0;
		background: var(--lq-surface);
	}
	.source-reference {
		border: 1px solid var(--lq-border);
		border-left: 3px solid var(--lq-accent);
		border-radius: 8px;
		padding: 1rem 1.25rem;
		margin: 1rem 0;
		background: var(--lq-bg-secondary, var(--lq-surface));
	}
	.source-reference h2,
	.file-preview h3 {
		margin: 0;
	}
	.source-text {
		max-height: 24rem;
		overflow: auto;
		padding: 0.75rem;
		border: 1px solid var(--lq-border);
		border-radius: 6px;
		background: var(--lq-surface);
	}
	.user {
		margin-left: 2rem;
		background: var(--lq-bg-secondary, var(--lq-surface));
	}
	.eyebrow,
	.skill,
	label {
		font-weight: 600;
		font-size: 0.85rem;
	}
	.scope,
	.muted {
		color: var(--lq-text-secondary);
		font-size: 0.85rem;
	}
	.tag {
		padding: 0.2rem 0.6rem;
		border: 1px solid var(--lq-border);
		border-radius: 999px;
		font-size: 0.75rem;
	}
	label {
		display: block;
		margin-bottom: 0.5rem;
	}
	textarea,
	select {
		width: 100%;
		padding: 0.8rem;
		border: 1px solid var(--lq-border);
		border-radius: 8px;
		background: var(--lq-surface);
		color: inherit;
	}
	button {
		border: 1px solid var(--lq-border);
		padding: 0.5rem 0.85rem;
		border-radius: 7px;
		cursor: pointer;
		margin: 0.25rem 0;
	}
	button:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.primary {
		background: var(--lq-accent, #235cca);
		color: white;
	}
	.halt,
	.error {
		color: var(--lq-danger, #c43b3b);
	}
	.notice {
		padding: 0.75rem;
		border-left: 3px solid var(--lq-accent, #235cca);
	}
	.run-bar {
		padding: 0.75rem 0;
		font-size: 0.85rem;
	}
	.tasks {
		padding-left: 1.25rem;
	}
	.tasks li {
		margin: 1rem 0;
	}
	summary {
		cursor: pointer;
		font-size: 0.9rem;
		padding: 0.5rem 0;
	}
	pre {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		font-size: 0.85rem;
		line-height: 1.7;
		margin: 0.75rem 0;
	}
	.answer {
		font-family: inherit;
	}
	code {
		overflow-wrap: anywhere;
		font-size: 0.75rem;
	}
	.receipt {
		border-top: 1px solid var(--lq-border);
		padding: 0.65rem 0;
		font-size: 0.75rem;
		overflow-wrap: anywhere;
	}
	.file-link {
		color: var(--lq-accent);
		text-align: left;
	}
	.file-preview {
		margin-top: 1rem;
		border: 1px solid var(--lq-accent);
		border-left: 4px solid var(--lq-accent);
		border-radius: 8px;
		background: var(--lq-bg-secondary, var(--lq-surface));
	}
	.file-preview-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 0.75rem;
		padding: 0.75rem 1rem;
	}
	.file-content {
		margin: 0;
		padding: 1rem;
		max-height: 24rem;
		overflow: auto;
		border-top: 1px solid var(--lq-border);
		background: var(--lq-surface);
		font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
		font-size: 0.8rem;
	}
	.children {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr));
		gap: 1rem;
	}
	.child {
		margin: 0;
	}
	.result {
		border-left: 3px solid var(--lq-accent, #235cca);
	}
	.new-run {
		display: inline-block;
		margin-top: 1rem;
	}
</style>
