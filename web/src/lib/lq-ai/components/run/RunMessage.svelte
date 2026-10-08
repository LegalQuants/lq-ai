<script lang="ts">
	/**
	 * A governed run, presented as a turn in the chat thread (ADR 0038 D1, D2).
	 *
	 * Drives only from stored state: the thread message names the run
	 * (`autonomous_session_id`) and the run read does the rest, so reloading the page
	 * restores everything. The panel opens on the plain-language progress list with
	 * the current step. The plan card, the tasks, the receipts and the digests sit
	 * beneath it; receipts and accounting are folded, one action away, never removed.
	 *
	 * `mode="thread"`: the answer, once delivered, is the message's own content and
	 * is rendered by the message bubble beneath this panel with the assistant
	 * treatment (skill chips, tier badge, citations, ledger). Its Markdown keeps its
	 * structure, but raw HTML is shown as text and no image is loaded (`run/answer.ts`).
	 * `mode="receipt"`: no thread around it, so the panel shows the answer itself, as text.
	 *
	 * Every model- or document-derived string below (the goal, task text, reasons,
	 * findings, file names and contents, summaries) is rendered with Svelte
	 * interpolation. None of it is ever rendered as HTML.
	 */
	import { createEventDispatcher, onMount } from 'svelte';
	import { orchestrationApi, orchestrationChatApi } from '$lib/lq-ai/api/orchestration';
	import type { OrchestrationChatRun } from '$lib/lq-ai/api/orchestration';
	import type { Message } from '$lib/lq-ai/types';
	import { availableActions } from '$lib/lq-ai/run/actions';
	import { CLOSE_RUN_NOTE } from '$lib/lq-ai/run/composer';
	import { showsEvidence } from '$lib/lq-ai/run/evidence';
	import { RunFollower } from '$lib/lq-ai/run/follow';
	import { planState, planView } from '$lib/lq-ai/run/plan';
	import { currentSteps, runProgress } from '$lib/lq-ai/run/progress';
	import {
		isActiveStatus,
		runDetail,
		runHeadline,
		shouldAnnounceSettled
	} from '$lib/lq-ai/run/status';
	import RunAnswerNote from './RunAnswerNote.svelte';
	import RunChildCard from './RunChildCard.svelte';
	import RunPlanCard from './RunPlanCard.svelte';
	import RunProgressList from './RunProgressList.svelte';
	import RunReceipts from './RunReceipts.svelte';

	/** The thread message that holds this run. Omit it on the receipt view. */
	export let message: Message | null = null;
	/** The run's root session. Defaults to the message's `autonomous_session_id`. */
	export let rootId: string | null = null;
	export let mode: 'thread' | 'receipt' = 'thread';
	/**
	 * The run as last read. Bindable, so a parent can see what the panel is showing;
	 * a run passed in is shown at once and replaced by the first read from the server.
	 */
	export let run: OrchestrationChatRun | null = null;

	const dispatch = createEventDispatcher<{
		/** The run reached a finished state; the message row should be read again. */
		settled: { run: OrchestrationChatRun };
		/** Every read of the run. */
		update: { run: OrchestrationChatRun };
	}>();

	let error = '';
	let actionError = '';
	let busy = false;
	let mounted = false;
	let followed = '';
	let follower: RunFollower | null = null;
	let previousStatus: string | null = null;
	let settledFor = '';
	let seenMessage: Message | null = message;

	$: id = rootId ?? message?.autonomous_session_id ?? '';
	$: tree = run?.tree ?? null;
	$: actions = run ? availableActions(run) : { approve: false, reject: false, halt: false, close: false };
	$: headline = run ? runHeadline(run) : '';
	$: detail = run ? runDetail(run) : null;
	$: progress = run ? runProgress(run) : [];
	$: now = run ? currentSteps(run) : [];
	$: plan = run ? planView(run) : null;
	$: shownPlanState = run ? planState(run) : 'proposed';
	$: showOverview =
		!!tree &&
		!tree.result &&
		!!tree.partial_summary &&
		!['halted', 'rejected'].includes(run?.status ?? '');
	$: testId = `lq-ai-run-message-${message?.id ?? run?.message_id ?? 'receipt'}`;

	$: if (mounted && id !== followed) restart(id);

	// A fresh copy of the message (the thread was read again) is a chance to catch up
	// on a run still shown as active, for example one closed from the composer.
	$: if (message !== seenMessage) {
		seenMessage = message;
		if (follower && run && isActiveStatus(run.status)) void follower.refresh();
	}

	onMount(() => {
		mounted = true;
		return () => {
			mounted = false;
			follower?.stop();
			follower = null;
		};
	});

	function describeError(err: unknown): string {
		const status = (err as { status?: unknown } | null)?.status;
		if (status === 404) return 'This run is no longer available.';
		return err instanceof Error ? err.message : String(err);
	}

	function restart(next: string) {
		follower?.stop();
		followed = next;
		follower = null;
		previousStatus = null;
		error = '';
		actionError = '';
		if (!next) return;
		if (run && run.root_id !== next) run = null;
		follower = new RunFollower({
			load: (signal) => orchestrationChatApi.read(next, signal),
			onRun: (value) => {
				if (next !== followed) return;
				run = value;
				error = '';
				announce(value);
				dispatch('update', { run: value });
			},
			onError: (err, info) => {
				if (next !== followed) return;
				error = info.fatal ? describeError(err) : `Could not refresh the run: ${describeError(err)}`;
			}
		});
		follower.start();
	}

	function announce(value: OrchestrationChatRun) {
		const settle = shouldAnnounceSettled({
			previous: previousStatus,
			current: value.status,
			messageHasContent: !!message?.content?.trim()
		});
		previousStatus = value.status;
		if (settle && settledFor !== value.root_id) {
			settledFor = value.root_id;
			dispatch('settled', { run: value });
		}
	}

	async function refresh() {
		error = '';
		if (follower) await follower.refresh();
		else if (id) restart(id);
	}

	async function act(kind: 'approve' | 'reject' | 'halt' | 'close', shown?: { revision: number; planHash: string }) {
		if (!run || busy) return;
		busy = true;
		actionError = '';
		try {
			if (kind === 'halt') {
				await orchestrationChatApi.halt(run.root_id);
			} else if (kind === 'close') {
				await orchestrationChatApi.close(run.root_id);
			} else {
				// Act on exactly the plan the owner was shown, never a later one.
				const current = run.tree;
				if (
					!current ||
					!shown ||
					current.plan.revision !== shown.revision ||
					current.plan_hash !== shown.planHash
				) {
					actionError = 'The plan changed while you were reading it. Review the new revision, then decide.';
				} else if (kind === 'approve') {
					await orchestrationApi.approve(current);
				} else {
					await orchestrationApi.reject(current);
				}
			}
		} catch (err) {
			actionError = describeError(err);
		} finally {
			busy = false;
		}
		await follower?.refresh();
	}
</script>

<section
	class="run"
	data-testid={testId}
	data-status={run?.status ?? 'loading'}
	data-mode={mode}
	aria-label="Governed run"
>
	<header class="head">
		<span class="title">{run?.profile_title ?? 'Governed run'}</span>
		<button type="button" class="link" on:click={refresh} disabled={busy}>Refresh</button>
	</header>

	{#if error}<p role="alert" class="error">{error}</p>{/if}
	{#if actionError}<p role="alert" class="error">{actionError}</p>{/if}

	{#if !id}
		<p class="muted">This message is not linked to a run.</p>
	{:else if !run}
		{#if !error}<p role="status" class="muted">Loading the run…</p>{/if}
	{:else}
		{#if mode === 'receipt'}
			<section class="request" aria-label="Your request">
				<p class="eyebrow">Your request</p>
				<p class="goal">{run.planning.goal}</p>
			</section>
		{/if}

		<p class="status" role="status" data-testid="lq-ai-run-status" data-status={run.status}>
			{headline}
		</p>
		{#if detail}<p class="detail" class:warn={run.status === 'uncertain'}>{detail}</p>{/if}

		<RunProgressList items={progress} {now} />

		{#if actions.halt || actions.close}
			<div class="controls">
				{#if actions.close}
					<button
						type="button"
						class="close"
						data-testid="lq-ai-run-close"
						disabled={busy}
						on:click={() => act('close')}
					>
						Close run
					</button>
					<span class="hint">{CLOSE_RUN_NOTE}</span>
				{/if}
				{#if actions.halt}
					<button
						type="button"
						class="halt"
						data-testid="lq-ai-run-halt"
						disabled={busy}
						title={run.status === 'uncertain'
							? 'Stops any remaining work. It does not free your run allowance; closing the run does.'
							: 'Stop the run. Work that has finished stays readable.'}
						on:click={() => act('halt')}
					>
						Halt
					</button>
				{/if}
			</div>
		{/if}

		{#if plan}
			<RunPlanCard
				view={plan}
				state={shownPlanState}
				awaiting={actions.approve}
				{busy}
				on:approve={(event) => act('approve', event.detail)}
				on:reject={(event) => act('reject', event.detail)}
			/>
		{/if}

		{#if tree && tree.approved && tree.children.length > 0}
			<section class="children" aria-label="Task progress">
				{#each tree.children as child, position (child.session_id)}
					<RunChildCard
						rootId={run.root_id}
						index={position + 1}
						topic={plan?.tasks[position]?.topic ?? `Task ${position + 1}`}
						skill={plan?.tasks[position]?.skill ?? 'Skill not recorded'}
						{child}
					/>
				{/each}
			</section>
		{/if}

		{#if mode === 'receipt' && tree?.result}
			<section class="answer" aria-label="Combined answer">
				<h3>Combined answer</h3>
				<pre class="answer-text">{tree.result.summary}</pre>
			</section>
		{/if}

		{#if showOverview && tree}
			<section class="overview" aria-label="Retained work overview">
				<h3>Retained work overview</h3>
				<p class="muted">
					No combined model answer was produced. This overview lists stored task outcomes.
				</p>
				<pre class="answer-text">{tree.partial_summary}</pre>
			</section>
		{/if}

		{#if mode === 'receipt'}
			{#if showsEvidence(run)}<RunAnswerNote {run} />{/if}
			<RunReceipts {run} />
		{:else}
			<RunReceipts {run} />
			{#if showsEvidence(run)}<RunAnswerNote {run} />{/if}
		{/if}
	{/if}
</section>

<style>
	@import '../../styles/practice.css';

	.run {
		width: 100%;
		min-width: 0;
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-lg);
		padding: 0.75rem 0.9rem;
		background: var(--lq-canvas);
		color: var(--lq-text);
		margin-bottom: 0.5rem;
	}
	.head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	.title {
		font-size: 0.8rem;
		font-weight: 600;
		letter-spacing: 0.03em;
		color: var(--lq-text-secondary);
		overflow-wrap: anywhere;
	}
	.link {
		background: none;
		border: 0;
		padding: 0.1rem 0.25rem;
		font-size: 0.75rem;
		color: var(--lq-accent);
		cursor: pointer;
		text-decoration: underline;
	}
	.link:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.status {
		margin: 0.35rem 0 0.15rem;
		font-size: 1rem;
		font-weight: 600;
		line-height: 1.4;
		overflow-wrap: anywhere;
	}
	.detail {
		margin: 0.15rem 0 0.5rem;
		font-size: 0.85rem;
		line-height: 1.55;
		color: var(--lq-text-secondary);
	}
	.detail.warn {
		padding: 0.6rem 0.75rem;
		border-left: 3px solid var(--lq-warn);
		background: var(--lq-warn-soft);
		color: var(--lq-text);
		border-radius: 0 var(--lq-radius) var(--lq-radius) 0;
	}
	.muted {
		margin: 0.25rem 0;
		font-size: 0.8rem;
		color: var(--lq-text-secondary);
	}
	.error {
		margin: 0.35rem 0;
		padding: 0.4rem 0.6rem;
		font-size: 0.82rem;
		color: var(--lq-error);
		background: var(--lq-error-soft);
		border: 1px solid var(--lq-error-border);
		border-radius: var(--lq-radius);
		overflow-wrap: anywhere;
	}
	.request {
		margin: 0.5rem 0;
		padding: 0.5rem 0.75rem;
		border-left: 3px solid var(--lq-accent-border);
		background: var(--lq-inset);
		border-radius: 0 var(--lq-radius) var(--lq-radius) 0;
	}
	.request p {
		margin: 0;
	}
	.eyebrow {
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--lq-text-secondary);
	}
	.goal {
		font-size: 0.9rem;
		line-height: 1.5;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.controls {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem 0.75rem;
		margin: 0.5rem 0;
	}
	.hint {
		flex: 1 1 14rem;
		font-size: 0.78rem;
		line-height: 1.5;
		color: var(--lq-text-secondary);
	}
	button {
		border-radius: var(--lq-radius);
		padding: 0.4rem 0.85rem;
		font-size: 0.85rem;
		cursor: pointer;
	}
	button:disabled {
		opacity: 0.5;
		cursor: default;
	}
	button:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.halt {
		background: var(--lq-canvas);
		color: var(--lq-error);
		border: 1px solid var(--lq-error-border);
	}
	.close {
		background: var(--lq-accent);
		color: white;
		border: 1px solid var(--lq-accent);
	}
	.children {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr));
		gap: 0.75rem;
		margin: 0.75rem 0;
	}
	.answer,
	.overview {
		margin: 0.75rem 0;
		padding: 0.5rem 0.75rem;
		border-left: 3px solid var(--lq-accent);
		background: var(--lq-inset);
		border-radius: 0 var(--lq-radius) var(--lq-radius) 0;
	}
	h3 {
		margin: 0;
		font-size: 0.9rem;
		font-weight: 600;
	}
	.answer-text {
		margin: 0.5rem 0 0;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		font-family: inherit;
		font-size: 0.88rem;
		line-height: 1.65;
	}
</style>
