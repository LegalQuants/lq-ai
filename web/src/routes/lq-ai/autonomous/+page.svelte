<script lang="ts">
	/**
	 * /lq-ai/autonomous — M4-C2 Sessions list page.
	 *
	 * Rail landing page: surfaces all autonomous sessions newest-first.
	 * Each row links to /lq-ai/autonomous/sessions/{id} (the receipt page,
	 * Task 11). Running sessions expose an inline Halt button.
	 *
	 * Mirrors the structure of admin/intake-bridges/+page.svelte:
	 *   - onMount(load)
	 *   - load() calls the API client, sets sessions/loading/listError
	 *   - action functions confirm→call→reload with actionError/actionSuccess
	 *   - LQAIApiError for typed error handling
	 *
	 * Run now (§4.4): a header button opens a modal mirroring the New-Schedule
	 * modal minus the cron field. It runs a chosen skill OR playbook once (with
	 * optional KB / matter / cost cap) via autonomousApi.runNow(), then navigates
	 * to the new session's receipt so the operator can see the result before
	 * arming a schedule or watch. The modal markup/state/picker-load pattern is
	 * copied from schedules/+page.svelte.
	 */
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	import { autonomousApi, skillsApi, knowledgeBasesApi, projectsApi } from '$lib/lq-ai/api';
	import * as playbooksApi from '$lib/lq-ai/api/playbooks';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import type { AutonomousSessionRead } from '$lib/lq-ai/api/autonomous';
	import type { Playbook } from '$lib/lq-ai/types';
	import type { SkillSummary } from '$lib/lq-ai/types';
	import type { KnowledgeBase, Project } from '$lib/lq-ai/types';
	import { formatCost, formatCreatedAt, isHaltable, statusPillClass } from './page-helpers';

	let sessions: AutonomousSessionRead[] = [];
	let loading = false;
	let listError: string | null = null;
	let actionError: string | null = null;
	let actionSuccess: string | null = null;
	let pendingHaltId: string | null = null;

	// ---------------------------------------------------------------------------
	// Run-now modal state
	// ---------------------------------------------------------------------------

	let runModalOpen = false;
	let runSubmitting = false;
	let runError: string | null = null;

	let runTargetKind: 'skill' | 'playbook' = 'skill';
	let runSkillRef = '';
	let runPlaybookId = '';
	let runKbId = '';
	let runProjectId = '';
	let runMaxCostUsd = '';

	// Picker lists (loaded on mount, reused by the modal)
	let playbooks: Playbook[] = [];
	let skillSummaries: SkillSummary[] = [];
	let kbs: KnowledgeBase[] = [];
	let projects: Project[] = [];
	let pickerLoading = false;
	let pickerError: string | null = null;

	onMount(() => {
		load();
		loadPickerData();
	});

	async function load(): Promise<void> {
		loading = true;
		listError = null;
		try {
			const resp = await autonomousApi.listSessions();
			sessions = resp.sessions;
		} catch (err) {
			if (err instanceof LQAIApiError && err.status === 403) {
				listError = 'You need to enable autonomous mode to view sessions.';
			} else {
				listError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			loading = false;
		}
	}

	async function haltSession(session: AutonomousSessionRead): Promise<void> {
		const confirmed = confirm(
			`Halt session "${session.id.slice(0, 8)}…" (${session.trigger_kind}, ${session.current_phase})? ` +
				`The agent will stop at the next safe checkpoint. This action is idempotent — ` +
				`sending halt to an already-halted session is harmless.`
		);
		if (!confirmed) return;
		pendingHaltId = session.id;
		actionError = null;
		actionSuccess = null;
		try {
			await autonomousApi.haltSession(session.id);
			actionSuccess = `Halt requested for session ${session.id.slice(0, 8)}….`;
			await load();
		} catch (err) {
			if (err instanceof LQAIApiError) {
				actionError = `Halt failed (${err.status}): ${err.message}`;
			} else {
				actionError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			pendingHaltId = null;
		}
	}

	// ---------------------------------------------------------------------------
	// Run-now: picker load, open/close, submit
	// ---------------------------------------------------------------------------

	async function loadPickerData(): Promise<void> {
		pickerLoading = true;
		pickerError = null;
		try {
			const [pb, sk, kb, pr] = await Promise.allSettled([
				playbooksApi.listPlaybooks(),
				skillsApi.listSkills(),
				knowledgeBasesApi.listKnowledgeBases(),
				projectsApi.listProjects()
			]);
			if (pb.status === 'fulfilled') playbooks = pb.value;
			if (sk.status === 'fulfilled') skillSummaries = sk.value;
			if (kb.status === 'fulfilled') kbs = kb.value;
			if (pr.status === 'fulfilled') projects = pr.value;
			// If all failed, surface a brief error; partial failure is silently degraded.
			if ([pb, sk, kb, pr].every((r) => r.status === 'rejected')) {
				pickerError = 'Could not load picker data. Check your connection.';
			}
		} finally {
			pickerLoading = false;
		}
	}

	async function openRunModal(): Promise<void> {
		// Reset form
		runTargetKind = 'skill';
		runSkillRef = '';
		runPlaybookId = '';
		runKbId = '';
		runProjectId = '';
		runMaxCostUsd = '';
		runError = null;

		runModalOpen = true;
		await loadPickerData();
	}

	function closeRunModal(): void {
		runModalOpen = false;
	}

	function handleRunModalKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape') closeRunModal();
	}

	/** A target is required before the run can be submitted. */
	$: runTargetChosen = runTargetKind === 'skill' ? !!runSkillRef : !!runPlaybookId;

	async function submitRunNow(): Promise<void> {
		runSubmitting = true;
		runError = null;
		try {
			const session = await autonomousApi.runNow({
				...(runTargetKind === 'skill' ? { skill_ref: runSkillRef } : { playbook_id: runPlaybookId }),
				...(runKbId ? { target_kb_id: runKbId } : {}),
				...(runProjectId ? { project_id: runProjectId } : {}),
				...(runMaxCostUsd.trim() !== '' ? { max_cost_usd: runMaxCostUsd.trim() } : {})
			});
			runModalOpen = false;
			await goto(`/lq-ai/autonomous/sessions/${session.id}`);
		} catch (err) {
			runError = err instanceof Error ? err.message : String(err);
		} finally {
			runSubmitting = false;
		}
	}
</script>

<div class="sessions-page">
	<header class="page-header">
		<div class="page-header-row">
			<div>
				<h1 class="lq-text-page-h">Autonomous sessions</h1>
				<p class="page-intro">
					Audit what LQVern did — every autonomous run, its cost, current phase, and terminal
					state. Running sessions can be halted inline. Select a row to view the full receipt.
				</p>
			</div>
			<button type="button" class="new-button" on:click={openRunModal}> Run now </button>
		</div>
	</header>

	{#if listError}
		<div class="error-banner" role="alert">{listError}</div>
	{/if}
	{#if actionError}
		<div class="error-banner" role="alert">{actionError}</div>
	{/if}
	{#if actionSuccess}
		<div class="success-banner" role="status">{actionSuccess}</div>
	{/if}

	{#if loading && sessions.length === 0}
		<p class="loading">Loading sessions…</p>
	{/if}

	{#if !loading && sessions.length === 0 && !listError}
		<p class="empty-state">
			No runs yet. Use <strong>Run now</strong> to run a skill or playbook once, or set up a
			<a class="empty-link" href="/lq-ai/autonomous/schedules">Schedule</a> or
			<a class="empty-link" href="/lq-ai/autonomous/watches">Watch</a>. New here? See
			<a class="empty-link" href="/lq-ai/autonomous/configure">Configure</a>.
		</p>
	{/if}

	{#if sessions.length > 0}
		<table class="sessions-table">
			<thead>
				<tr>
					<th>Status</th>
					<th>Trigger</th>
					<th>Phase</th>
					<th>Cost</th>
					<th>Started</th>
					<th class="sessions-table-actions">Actions</th>
				</tr>
			</thead>
			<tbody>
				{#each sessions as session (session.id)}
					<tr>
						<td>
							<span class="status-pill {statusPillClass(session.status)}">
								{session.status}
							</span>
						</td>
						<td>{session.trigger_kind}</td>
						<td>{session.current_phase}</td>
						<td class="cost-cell">
							{formatCost(session.cost_total_usd, session.max_cost_usd)}
						</td>
						<td class="date-cell">{formatCreatedAt(session.created_at)}</td>
						<td class="sessions-table-actions">
							<a href="/lq-ai/autonomous/sessions/{session.id}" class="action-link">
								View
							</a>
							{#if isHaltable(session.status)}
								<button
									type="button"
									class="action-button danger"
									on:click={() => haltSession(session)}
									disabled={pendingHaltId === session.id}
								>
									{pendingHaltId === session.id ? 'Halting…' : 'Halt'}
								</button>
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>

<!-- ====================================================================== -->
<!-- Run-now Modal                                                           -->
<!-- ====================================================================== -->

{#if runModalOpen}
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		class="modal-backdrop"
		role="dialog"
		aria-modal="true"
		aria-labelledby="run-modal-title"
		tabindex="-1"
		on:click={closeRunModal}
		on:keydown={handleRunModalKeydown}
	>
		<!-- svelte-ignore a11y-no-static-element-interactions -->
		<div class="modal-panel" on:click|stopPropagation on:keydown|stopPropagation>
			<h2 id="run-modal-title" class="lq-text-page-h modal-title">Run a skill or playbook once</h2>
			<p class="modal-hint modal-lede">
				This runs once now so you can see the result before arming a schedule or watch.
			</p>

			<form on:submit|preventDefault={submitRunNow} class="modal-form" novalidate>
				<!-- Target kind radio -->
				<div class="modal-field">
					<span class="modal-label">
						Target <span class="modal-required" aria-hidden="true">*</span>
					</span>
					<div class="radio-group">
						<label class="radio-label">
							<input
								type="radio"
								name="run-target-kind"
								value="skill"
								bind:group={runTargetKind}
								disabled={runSubmitting}
							/>
							Skill
						</label>
						<label class="radio-label">
							<input
								type="radio"
								name="run-target-kind"
								value="playbook"
								bind:group={runTargetKind}
								disabled={runSubmitting}
							/>
							Playbook
						</label>
					</div>

					{#if runTargetKind === 'skill'}
						{#if pickerLoading}
							<p class="picker-loading">Loading skills…</p>
						{:else}
							<select
								class="modal-select"
								bind:value={runSkillRef}
								disabled={runSubmitting}
								aria-label="Select skill"
							>
								<option value="">— Select a skill —</option>
								{#each skillSummaries as sk (sk.name)}
									<option value={sk.name}>{sk.title || sk.name}</option>
								{/each}
							</select>
						{/if}
					{:else}
						{#if pickerLoading}
							<p class="picker-loading">Loading playbooks…</p>
						{:else}
							<select
								class="modal-select"
								bind:value={runPlaybookId}
								disabled={runSubmitting}
								aria-label="Select playbook"
							>
								<option value="">— Select a playbook —</option>
								{#each playbooks as pb (pb.id)}
									<option value={pb.id}>{pb.name}</option>
								{/each}
							</select>
						{/if}
					{/if}
				</div>

				<!-- Optional KB -->
				<div class="modal-field">
					<label class="modal-label" for="run-kb">
						Knowledge base <span class="modal-optional">(optional)</span>
					</label>
					{#if pickerLoading}
						<p class="picker-loading">Loading knowledge bases…</p>
					{:else}
						<select id="run-kb" class="modal-select" bind:value={runKbId} disabled={runSubmitting}>
							<option value="">— None —</option>
							{#each kbs as kb (kb.id)}
								<option value={kb.id}>{kb.name}</option>
							{/each}
						</select>
					{/if}
				</div>

				<!-- Optional project -->
				<div class="modal-field">
					<label class="modal-label" for="run-project">
						Matter / project <span class="modal-optional">(optional)</span>
					</label>
					{#if pickerLoading}
						<p class="picker-loading">Loading projects…</p>
					{:else}
						<select
							id="run-project"
							class="modal-select"
							bind:value={runProjectId}
							disabled={runSubmitting}
						>
							<option value="">— None —</option>
							{#each projects as proj (proj.id)}
								<option value={proj.id}>{proj.name}</option>
							{/each}
						</select>
					{/if}
				</div>

				<!-- Cost cap (optional) -->
				<div class="modal-field">
					<label class="modal-label" for="run-cost-cap">
						Cost cap (USD) <span class="modal-optional">(optional)</span>
					</label>
					<input
						id="run-cost-cap"
						type="number"
						min="0"
						step="0.01"
						class="modal-input"
						bind:value={runMaxCostUsd}
						placeholder="e.g. 1.00 — defaults to the system cap if blank"
						disabled={runSubmitting}
					/>
					<p class="modal-hint">
						The most this run may spend before it halts (R4). Blank uses the system default.
					</p>
				</div>

				{#if pickerError}
					<p class="picker-error" role="alert">{pickerError}</p>
				{/if}

				{#if runError}
					<p class="submit-error" role="alert">{runError}</p>
				{/if}

				<!-- Actions -->
				<div class="modal-actions">
					<button
						type="button"
						class="modal-btn-secondary"
						on:click={closeRunModal}
						disabled={runSubmitting}
					>
						Cancel
					</button>
					<button
						type="submit"
						class="modal-btn-primary"
						disabled={runSubmitting || !runTargetChosen}
					>
						{runSubmitting ? 'Running…' : 'Run now'}
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}

<style>
	.sessions-page {
		padding: var(--lq-space-5);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-5);
	}

	.page-header {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.page-header-row {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--lq-space-4);
		flex-wrap: wrap;
	}

	.page-intro {
		color: var(--lq-text-secondary);
		max-width: 60rem;
		font-size: 14px;
		line-height: 1.5;
	}

	.new-button {
		background: var(--lq-accent);
		color: white;
		border: 0;
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
		white-space: nowrap;
		flex-shrink: 0;
	}

	.new-button:hover:not(:disabled) {
		filter: brightness(0.95);
	}

	.new-button:disabled {
		opacity: 0.65;
		cursor: not-allowed;
	}

	.error-banner {
		padding: var(--lq-space-3) var(--lq-space-4);
		background: var(--lq-error-bg, #fee);
		color: var(--lq-error-text, #800);
		border-radius: 6px;
		border: 1px solid var(--lq-error-border, #fbb);
	}

	.success-banner {
		padding: var(--lq-space-3) var(--lq-space-4);
		background: var(--lq-success-bg, #efe);
		color: var(--lq-success-text, #060);
		border-radius: 6px;
		border: 1px solid var(--lq-success-border, #bfb);
	}

	.loading {
		color: var(--lq-text-secondary);
		padding: var(--lq-space-3);
	}

	.empty-state {
		color: var(--lq-text-secondary);
		font-style: italic;
		margin: 0;
	}

	.empty-link {
		font-style: normal;
		color: var(--lq-accent);
		text-decoration: none;
	}

	.empty-link:hover {
		text-decoration: underline;
	}

	.sessions-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 14px;
	}

	.sessions-table th,
	.sessions-table td {
		text-align: left;
		padding: var(--lq-space-2) var(--lq-space-3);
		border-bottom: 1px solid var(--lq-border);
	}

	.sessions-table th {
		font-weight: 600;
		color: var(--lq-text-secondary);
		font-size: 12px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.sessions-table-actions {
		text-align: right;
		width: 1px;
		white-space: nowrap;
	}

	/* Status pill */
	.status-pill {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 10px;
		font-size: 12px;
		font-weight: 500;
		text-transform: capitalize;
		white-space: nowrap;
	}

	.lq-status--running {
		background: var(--lq-info-bg, #e8f4fd);
		color: var(--lq-info-text, #0a5fa8);
		border: 1px solid var(--lq-info-border, #9ed3f5);
	}

	.lq-status--completed {
		background: var(--lq-success-bg, #efe);
		color: var(--lq-success-text, #060);
		border: 1px solid var(--lq-success-border, #bfb);
	}

	.lq-status--halted {
		background: var(--lq-warning-bg, #fff8e1);
		color: var(--lq-warning-text, #7a5a00);
		border: 1px solid var(--lq-warning-border, #ffe08a);
	}

	.lq-status--failed {
		background: var(--lq-error-bg, #fee);
		color: var(--lq-error-text, #800);
		border: 1px solid var(--lq-error-border, #fbb);
	}

	.cost-cell {
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}

	.date-cell {
		color: var(--lq-text-secondary);
		white-space: nowrap;
	}

	.action-link {
		display: inline-block;
		padding: var(--lq-space-1) var(--lq-space-3);
		border-radius: 6px;
		font-size: 13px;
		color: var(--lq-accent);
		text-decoration: none;
		border: 1px solid var(--lq-border);
	}

	.action-link:hover {
		background: var(--lq-surface-hover, rgba(0, 0, 0, 0.04));
	}

	.action-button {
		padding: var(--lq-space-1) var(--lq-space-3);
		border-radius: 6px;
		font-size: 13px;
		cursor: pointer;
		border: 1px solid var(--lq-border);
		background: transparent;
		color: var(--lq-text);
		margin-left: var(--lq-space-2);
	}

	.action-button.danger {
		color: var(--lq-error-text, #b00);
		border-color: var(--lq-error-border, #fbb);
	}

	.action-button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	/* ------------------------------------------------------------------ */
	/* Run-now modal                                                       */
	/* ------------------------------------------------------------------ */

	.modal-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.35);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
	}

	.modal-panel {
		background: var(--lq-canvas);
		border-radius: var(--lq-radius-lg);
		padding: var(--lq-space-6);
		max-width: 560px;
		width: calc(100% - 32px);
		box-shadow: 0 24px 64px rgba(0, 0, 0, 0.18);
		max-height: calc(100vh - 64px);
		overflow-y: auto;
	}

	.modal-title {
		margin: 0 0 var(--lq-space-2);
	}

	.modal-lede {
		margin: 0 0 var(--lq-space-5);
	}

	.modal-form {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-4);
	}

	.modal-field {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-1);
	}

	.modal-label {
		font-size: 13px;
		font-weight: 500;
		color: var(--lq-text-primary);
	}

	.modal-required {
		color: var(--lq-error);
		margin-left: 2px;
	}

	.modal-optional {
		font-weight: 400;
		color: var(--lq-text-tertiary);
		font-size: 12px;
	}

	.modal-hint {
		font-size: 12px;
		color: var(--lq-text-tertiary);
		margin: 0;
		line-height: 1.4;
	}

	.modal-input,
	.modal-select {
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-3);
		font-size: 14px;
		color: var(--lq-text-primary);
		width: 100%;
		box-sizing: border-box;
		transition: border-color 0.15s ease;
	}

	.modal-input:focus,
	.modal-select:focus {
		outline: none;
		border-color: var(--lq-accent);
		box-shadow: 0 0 0 2px var(--lq-accent-soft);
	}

	.modal-input:disabled,
	.modal-select:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.radio-group {
		display: flex;
		gap: var(--lq-space-4);
		padding: var(--lq-space-1) 0;
	}

	.radio-label {
		display: flex;
		align-items: center;
		gap: var(--lq-space-1);
		font-size: 14px;
		cursor: pointer;
		color: var(--lq-text);
	}

	.picker-loading {
		font-size: 13px;
		color: var(--lq-text-tertiary);
		font-style: italic;
		margin: 0;
	}

	.picker-error {
		font-size: 13px;
		color: var(--lq-error);
		margin: 0;
	}

	.submit-error {
		font-size: 13px;
		color: var(--lq-error);
		background: var(--lq-error-soft, rgba(176, 0, 0, 0.06));
		border: 1px solid var(--lq-error-border, var(--lq-error));
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-3);
		margin: 0;
	}

	.modal-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--lq-space-3);
		padding-top: var(--lq-space-2);
		border-top: 1px solid var(--lq-border);
		margin-top: var(--lq-space-2);
	}

	.modal-btn-primary {
		background: var(--lq-accent);
		color: white;
		border: 0;
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-weight: 500;
		font-size: 14px;
		cursor: pointer;
	}

	.modal-btn-primary:hover:not(:disabled) {
		filter: brightness(0.95);
	}

	.modal-btn-primary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}

	.modal-btn-primary:disabled {
		opacity: 0.65;
		cursor: not-allowed;
	}

	.modal-btn-secondary {
		background: transparent;
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-weight: 500;
		font-size: 14px;
		cursor: pointer;
	}

	.modal-btn-secondary:hover:not(:disabled) {
		background: var(--lq-inset);
	}

	.modal-btn-secondary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}

	.modal-btn-secondary:disabled {
		opacity: 0.65;
		cursor: not-allowed;
	}
</style>
