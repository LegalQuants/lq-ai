<script lang="ts">
	/**
	 * /lq-ai/autonomous/watches — M4-C2 Task 16.
	 *
	 * Lists KB-watch triggers for the current user. A watch fires the configured
	 * playbook or skill whenever a new document arrives in the watched Knowledge
	 * Base. The KB is required at creation and immutable — re-targeting requires
	 * a new watch.
	 *
	 * Structure mirrors schedules/+page.svelte (Task 15):
	 *   onMount → load(), loading/error/success banners, LQAIApiError, per-row pending.
	 *
	 * Row actions:
	 *   - Enable/disable toggle  → updateWatch(id, { enabled: !enabled }) → reload
	 *   - Delete                 → confirm → deleteWatch(id) → reload
	 *
	 * New watch button → in-page modal:
	 *   - KB picker (required — <select> from knowledgeBasesApi.listKnowledgeBases())
	 *   - Target: radio between "Playbook" and "Skill"
	 *       Playbook: <select> from playbooksApi.listPlaybooks()
	 *       Skill:    <select> from skillsApi.listSkills()
	 *   - Optional project: <select> from projectsApi.listProjects()
	 *   - Submit → createWatch({ knowledge_base_id, playbook_id|skill_ref, project_id?, enabled: true })
	 *
	 * Key difference from schedules: NO cron field; KB picker is REQUIRED and
	 * rendered as the first form field; AutonomousWatchUpdate does NOT include
	 * knowledge_base_id (immutable after creation).
	 */
	import { onMount } from 'svelte';

	import { autonomousApi, skillsApi, knowledgeBasesApi, projectsApi } from '$lib/lq-ai/api';
	import * as playbooksApi from '$lib/lq-ai/api/playbooks';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import type { AutonomousWatchRead } from '$lib/lq-ai/api/autonomous';
	import type { Playbook } from '$lib/lq-ai/types';
	import type { SkillSummary } from '$lib/lq-ai/types';
	import type { KnowledgeBase, Project } from '$lib/lq-ai/types';

	// ---------------------------------------------------------------------------
	// List state
	// ---------------------------------------------------------------------------

	let watches: AutonomousWatchRead[] = [];
	let loading = false;
	let listError: string | null = null;
	let actionError: string | null = null;
	let actionSuccess: string | null = null;
	/** Map of watch id → pending action label. */
	let pendingIds: Map<string, string> = new Map();

	/** KB id → name map, populated alongside the watch list. */
	let kbNameMap: Map<string, string> = new Map();

	// ---------------------------------------------------------------------------
	// Modal state
	// ---------------------------------------------------------------------------

	let modalOpen = false;
	let submitting = false;

	// Form fields
	let formKbId: string = '';
	let formTargetKind: 'playbook' | 'skill' = 'playbook';
	let formPlaybookId: string = '';
	let formSkillRef: string = '';
	let formProjectId: string = '';
	let formMaxCostUsd: string = '';

	// Form errors
	let kbError: string | null = null;
	let targetError: string | null = null;
	let submitError: string | null = null;

	// Picker lists (loaded when modal opens)
	let playbooks: Playbook[] = [];
	let skillSummaries: SkillSummary[] = [];
	let kbs: KnowledgeBase[] = [];
	let projects: Project[] = [];
	let pickerLoading = false;
	let pickerError: string | null = null;

	// ---------------------------------------------------------------------------
	// Load
	// ---------------------------------------------------------------------------

	onMount(() => {
		load();
		// Load picker lists up front so list rows can resolve playbook/skill ids
		// to names without waiting for the modal to be opened.
		loadPickerData();
	});

	async function load(): Promise<void> {
		loading = true;
		listError = null;
		try {
			const [watchResp, kbResp] = await Promise.allSettled([
				autonomousApi.listWatches(),
				knowledgeBasesApi.listKnowledgeBases()
			]);

			if (watchResp.status === 'fulfilled') {
				watches = watchResp.value.watches;
			} else {
				const err = watchResp.reason;
				if (err instanceof LQAIApiError && err.status === 403) {
					listError = 'You need to enable autonomous mode to view watches.';
				} else {
					listError = err instanceof Error ? err.message : String(err);
				}
			}

			// Build kb name map (best-effort — partial failure still shows IDs)
			if (kbResp.status === 'fulfilled') {
				kbNameMap = new Map(kbResp.value.map((kb) => [kb.id, kb.name]));
			}
		} finally {
			loading = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Row actions
	// ---------------------------------------------------------------------------

	async function toggleEnabled(watch: AutonomousWatchRead): Promise<void> {
		pendingIds = new Map(pendingIds).set(watch.id, 'toggling');
		actionError = null;
		actionSuccess = null;
		try {
			await autonomousApi.updateWatch(watch.id, { enabled: !watch.enabled });
			actionSuccess = `Watch on "${kbLabel(watch.knowledge_base_id)}" ${!watch.enabled ? 'enabled' : 'disabled'}.`;
			await load();
		} catch (err) {
			if (err instanceof LQAIApiError) {
				actionError = `Update failed (${err.status}): ${err.message}`;
			} else {
				actionError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			const next = new Map(pendingIds);
			next.delete(watch.id);
			pendingIds = next;
		}
	}

	async function handleDeleteWatch(watch: AutonomousWatchRead): Promise<void> {
		const confirmed = confirm(
			`Delete watch on "${kbLabel(watch.knowledge_base_id)}"? This is a soft-delete — ` +
				`it stops triggering and will no longer appear in this list.`
		);
		if (!confirmed) return;
		pendingIds = new Map(pendingIds).set(watch.id, 'deleting');
		actionError = null;
		actionSuccess = null;
		try {
			await autonomousApi.deleteWatch(watch.id);
			actionSuccess = `Watch on "${kbLabel(watch.knowledge_base_id)}" deleted.`;
			await load();
		} catch (err) {
			if (err instanceof LQAIApiError) {
				actionError = `Delete failed (${err.status}): ${err.message}`;
			} else {
				actionError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			const next = new Map(pendingIds);
			next.delete(watch.id);
			pendingIds = next;
		}
	}

	// ---------------------------------------------------------------------------
	// Modal open / close
	// ---------------------------------------------------------------------------

	async function openModal(): Promise<void> {
		// Reset form
		formKbId = '';
		formTargetKind = 'playbook';
		formPlaybookId = '';
		formSkillRef = '';
		formProjectId = '';
		formMaxCostUsd = '';
		kbError = null;
		targetError = null;
		submitError = null;

		modalOpen = true;
		await loadPickerData();
	}

	function closeModal(): void {
		modalOpen = false;
	}

	function handleModalKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape') closeModal();
	}

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

	// ---------------------------------------------------------------------------
	// Modal submit
	// ---------------------------------------------------------------------------

	async function handleSubmit(): Promise<void> {
		kbError = null;
		targetError = null;
		submitError = null;

		// Validate KB (required)
		if (!formKbId) {
			kbError = 'A knowledge base is required.';
			return;
		}

		// Validate target
		if (formTargetKind === 'playbook' && !formPlaybookId) {
			targetError = 'Select a playbook, or switch to the Skill target.';
			return;
		}
		if (formTargetKind === 'skill' && !formSkillRef) {
			targetError = 'Select a skill, or switch to the Playbook target.';
			return;
		}

		submitting = true;
		try {
			await autonomousApi.createWatch({
				knowledge_base_id: formKbId,
				playbook_id: formTargetKind === 'playbook' ? formPlaybookId || undefined : undefined,
				skill_ref: formTargetKind === 'skill' ? formSkillRef || undefined : undefined,
				project_id: formProjectId || undefined,
				enabled: true,
				...(formMaxCostUsd.trim() !== '' ? { max_cost_usd: formMaxCostUsd.trim() } : {})
			});
			const kbName = kbs.find((kb) => kb.id === formKbId)?.name ?? formKbId;
			actionSuccess = `Watch on "${kbName}" created.`;
			closeModal();
			await load();
		} catch (err) {
			if (err instanceof LQAIApiError) {
				submitError = `Create failed (${err.status}): ${err.message}`;
			} else {
				submitError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			submitting = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Display helpers
	// ---------------------------------------------------------------------------

	function kbLabel(kbId: string): string {
		return kbNameMap.get(kbId) ?? kbId;
	}

	/** Resolve a playbook id to its name, falling back to the id when unknown. */
	function playbookName(id: string | null): string {
		if (!id) return '';
		return playbooks.find((p) => p.id === id)?.name ?? id;
	}

	/** Resolve a skill ref to its title, falling back to the ref when unknown. */
	function skillName(ref: string | null): string {
		if (!ref) return '';
		return skillSummaries.find((s) => s.name === ref)?.title || ref;
	}

	function targetSummary(w: AutonomousWatchRead): string {
		const parts: string[] = [];
		if (w.playbook_id) parts.push(`Playbook: ${playbookName(w.playbook_id)}`);
		if (w.skill_ref) parts.push(`Skill: ${skillName(w.skill_ref)}`);
		return parts.join(' · ') || '—';
	}

	function pendingLabel(id: string): string | undefined {
		return pendingIds.get(id);
	}
</script>

<div class="watches-page">
	<header class="page-header">
		<div class="page-header-row">
			<div>
				<h1 class="lq-text-page-h">Watches</h1>
				<p class="page-intro">
					Document-arrival triggers. When a new file lands in a watched Knowledge Base, LQVern runs
					the assigned playbook or skill automatically. The Knowledge Base is set at creation and
					cannot be changed — create a new watch to re-target.
				</p>
			</div>
			<button type="button" class="new-button" on:click={openModal}> New watch </button>
		</div>
	</header>

	<!-- ================================================================ -->
	<!-- Banners                                                           -->
	<!-- ================================================================ -->

	{#if listError}
		<div class="error-banner" role="alert">{listError}</div>
	{/if}
	{#if actionError}
		<div class="error-banner" role="alert">{actionError}</div>
	{/if}
	{#if actionSuccess}
		<div class="success-banner" role="status">{actionSuccess}</div>
	{/if}

	<!-- ================================================================ -->
	<!-- Loading + empty states                                           -->
	<!-- ================================================================ -->

	{#if loading && watches.length === 0}
		<p class="loading">Loading watches…</p>
	{/if}

	{#if !loading && watches.length === 0 && !listError}
		<p class="empty-state">
			No watches yet. Use <strong>New watch</strong> to trigger a run when documents arrive in a
			Knowledge Base. See
			<a class="empty-link" href="/lq-ai/autonomous/configure">Configure</a> to learn how.
		</p>
	{/if}

	<!-- ================================================================ -->
	<!-- Watch table                                                       -->
	<!-- ================================================================ -->

	{#if watches.length > 0}
		<table class="watch-table">
			<thead>
				<tr>
					<th>Knowledge base</th>
					<th>Target</th>
					<th>Status</th>
					<th class="watch-table-actions">Actions</th>
				</tr>
			</thead>
			<tbody>
				{#each watches as watch (watch.id)}
					{@const pending = pendingLabel(watch.id)}
					<tr class:row--disabled={!watch.enabled}>
						<td>
							<span class="kb-name">{kbLabel(watch.knowledge_base_id)}</span>
							<span class="kb-id-secondary">{watch.knowledge_base_id}</span>
						</td>
						<td class="watch-target">{targetSummary(watch)}</td>
						<td>
							<span
								class="status-badge"
								class:status-badge--enabled={watch.enabled}
								class:status-badge--disabled={!watch.enabled}
							>
								{watch.enabled ? 'Enabled' : 'Disabled'}
							</span>
						</td>
						<td class="watch-table-actions">
							<div class="action-group">
								<button
									type="button"
									class="action-button"
									on:click={() => toggleEnabled(watch)}
									disabled={!!pending}
									aria-label={watch.enabled
										? `Disable watch on ${kbLabel(watch.knowledge_base_id)}`
										: `Enable watch on ${kbLabel(watch.knowledge_base_id)}`}
								>
									{#if pending === 'toggling'}
										{watch.enabled ? 'Disabling…' : 'Enabling…'}
									{:else}
										{watch.enabled ? 'Disable' : 'Enable'}
									{/if}
								</button>
								<button
									type="button"
									class="action-button danger"
									on:click={() => handleDeleteWatch(watch)}
									disabled={!!pending}
									aria-label={`Delete watch on ${kbLabel(watch.knowledge_base_id)}`}
								>
									{pending === 'deleting' ? 'Deleting…' : 'Delete'}
								</button>
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>

<!-- ====================================================================== -->
<!-- New Watch Modal                                                         -->
<!-- ====================================================================== -->

{#if modalOpen}
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		class="modal-backdrop"
		role="dialog"
		aria-modal="true"
		aria-labelledby="watch-modal-title"
		tabindex="-1"
		on:click={closeModal}
		on:keydown={handleModalKeydown}
	>
		<!-- svelte-ignore a11y-no-static-element-interactions -->
		<div class="modal-panel" on:click|stopPropagation on:keydown|stopPropagation>
			<h2 id="watch-modal-title" class="lq-text-page-h modal-title">New watch</h2>

			<form on:submit|preventDefault={handleSubmit} class="modal-form" novalidate>
				<!-- Knowledge base (required + immutable after creation) -->
				<div class="modal-field">
					<label class="modal-label" for="watch-kb">
						Knowledge base <span class="modal-required" aria-hidden="true">*</span>
					</label>
					{#if pickerLoading}
						<p class="picker-loading">Loading knowledge bases…</p>
					{:else}
						<select
							id="watch-kb"
							class="modal-select"
							class:modal-select--error={!!kbError}
							bind:value={formKbId}
							disabled={submitting}
							aria-label="Select knowledge base"
						>
							<option value="">— Select a knowledge base —</option>
							{#each kbs as kb (kb.id)}
								<option value={kb.id}>{kb.name}</option>
							{/each}
						</select>
					{/if}
					{#if kbError}
						<p class="modal-field-error" role="alert">{kbError}</p>
					{/if}
					<p class="modal-hint">
						The Knowledge Base cannot be changed after creation. To watch a different KB, create a
						new watch.
					</p>
				</div>

				<!-- Target kind radio -->
				<div class="modal-field">
					<span class="modal-label">
						Target <span class="modal-required" aria-hidden="true">*</span>
					</span>
					<div class="radio-group">
						<label class="radio-label">
							<input
								type="radio"
								name="target-kind"
								value="playbook"
								bind:group={formTargetKind}
								disabled={submitting}
							/>
							Playbook
						</label>
						<label class="radio-label">
							<input
								type="radio"
								name="target-kind"
								value="skill"
								bind:group={formTargetKind}
								disabled={submitting}
							/>
							Skill
						</label>
					</div>

					{#if formTargetKind === 'playbook'}
						{#if pickerLoading}
							<p class="picker-loading">Loading playbooks…</p>
						{:else}
							<select
								class="modal-select"
								class:modal-select--error={!!targetError}
								bind:value={formPlaybookId}
								disabled={submitting}
								aria-label="Select playbook"
							>
								<option value="">— Select a playbook —</option>
								{#each playbooks as pb (pb.id)}
									<option value={pb.id}>{pb.name}</option>
								{/each}
							</select>
						{/if}
					{:else}
						{#if pickerLoading}
							<p class="picker-loading">Loading skills…</p>
						{:else}
							<select
								class="modal-select"
								class:modal-select--error={!!targetError}
								bind:value={formSkillRef}
								disabled={submitting}
								aria-label="Select skill"
							>
								<option value="">— Select a skill —</option>
								{#each skillSummaries as sk (sk.name)}
									<option value={sk.name}>{sk.title || sk.name}</option>
								{/each}
							</select>
						{/if}
					{/if}

					{#if targetError}
						<p class="modal-field-error" role="alert">{targetError}</p>
					{/if}
				</div>

				<!-- Optional project -->
				<div class="modal-field">
					<label class="modal-label" for="watch-project">
						Matter / project <span class="modal-optional">(optional)</span>
					</label>
					{#if pickerLoading}
						<p class="picker-loading">Loading projects…</p>
					{:else}
						<select
							id="watch-project"
							class="modal-select"
							bind:value={formProjectId}
							disabled={submitting}
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
					<label class="modal-label" for="watch-cost-cap">
						Cost cap (USD) <span class="modal-optional">(optional)</span>
					</label>
					<input
						id="watch-cost-cap"
						type="number"
						min="0"
						step="0.01"
						class="modal-input"
						bind:value={formMaxCostUsd}
						placeholder="e.g. 1.00 — defaults to the system cap if blank"
						disabled={submitting}
					/>
					<p class="modal-hint">
						The most this run may spend before it halts (R4). Blank uses the system default.
					</p>
				</div>

				{#if pickerError}
					<p class="picker-error" role="alert">{pickerError}</p>
				{/if}

				<!-- Generic submit error -->
				{#if submitError}
					<p class="submit-error" role="alert">{submitError}</p>
				{/if}

				<!-- Actions -->
				<div class="modal-actions">
					<button
						type="button"
						class="modal-btn-secondary"
						on:click={closeModal}
						disabled={submitting}
					>
						Cancel
					</button>
					<button type="submit" class="modal-btn-primary" disabled={submitting}>
						{submitting ? 'Creating…' : 'Create watch'}
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}

<style>
	/* ------------------------------------------------------------------ */
	/* Page layout                                                         */
	/* ------------------------------------------------------------------ */

	.watches-page {
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

	/* ------------------------------------------------------------------ */
	/* Banners                                                             */
	/* ------------------------------------------------------------------ */

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
		color: var(--lq-accent);
		text-decoration: none;
		font-style: normal;
	}

	.empty-link:hover {
		text-decoration: underline;
	}

	/* ------------------------------------------------------------------ */
	/* New watch button                                                    */
	/* ------------------------------------------------------------------ */

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

	/* ------------------------------------------------------------------ */
	/* Watch table                                                         */
	/* ------------------------------------------------------------------ */

	.watch-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 14px;
	}

	.watch-table th,
	.watch-table td {
		text-align: left;
		padding: var(--lq-space-2) var(--lq-space-3);
		border-bottom: 1px solid var(--lq-border);
		vertical-align: middle;
	}

	.watch-table th {
		font-weight: 600;
		color: var(--lq-text-secondary);
		font-size: 12px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		white-space: nowrap;
	}

	.watch-table-actions {
		text-align: right;
		width: 1px;
		white-space: nowrap;
	}

	.row--disabled td {
		opacity: 0.6;
	}

	.kb-name {
		font-weight: 500;
		display: block;
	}

	.kb-id-secondary {
		display: block;
		font-size: 11px;
		font-family: var(--font-mono, monospace);
		color: var(--lq-text-tertiary);
		margin-top: 2px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 20rem;
	}

	.watch-target {
		color: var(--lq-text-secondary);
		font-size: 13px;
		max-width: 18rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.status-badge {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 10px;
		font-size: 12px;
		font-weight: 500;
		white-space: nowrap;
	}

	.status-badge--enabled {
		background: var(--lq-success-bg, #efe);
		color: var(--lq-success-text, #060);
		border: 1px solid var(--lq-success-border, #bfb);
	}

	.status-badge--disabled {
		background: var(--lq-inset, rgba(0, 0, 0, 0.04));
		color: var(--lq-text-tertiary);
		border: 1px solid var(--lq-border);
	}

	.action-group {
		display: flex;
		gap: var(--lq-space-2);
		justify-content: flex-end;
	}

	.action-button {
		padding: var(--lq-space-1) var(--lq-space-3);
		border-radius: 6px;
		font-size: 13px;
		cursor: pointer;
		border: 1px solid var(--lq-border);
		background: transparent;
		color: var(--lq-text);
		transition: background 0.1s;
		white-space: nowrap;
	}

	.action-button:hover:not(:disabled) {
		background: var(--lq-surface-hover, rgba(0, 0, 0, 0.04));
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
	/* Modal                                                               */
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

	.modal-select--error {
		border-color: var(--lq-error);
	}

	.modal-field-error {
		font-size: 12px;
		color: var(--lq-error);
		margin: 0;
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
