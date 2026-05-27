<script lang="ts">
	/**
	 * /lq-ai/autonomous/precedents — M4-C2 Precedent board (Task 13).
	 *
	 * Surfaces system-observed cross-matter patterns (recurring counterparty
	 * positions, clause-language patterns) — distinct from per-user memory
	 * (Task 12) and Project context.
	 *
	 * ADR 0013 D5: the agent never writes Project context directly. "Promote"
	 * creates a project_context_proposals row that the user then accepts or
	 * rejects on the Proposals page (Task 14). This page is read-mostly +
	 * dismissable.
	 *
	 * Mirrors sessions / memory pages + admin/intake-bridges:
	 *   onMount(load), loading/error/success banners, LQAIApiError,
	 *   confirm→act→reload pattern.
	 */
	import { onMount } from 'svelte';

	import { autonomousApi, projectsApi } from '$lib/lq-ai/api';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import type { PrecedentEntryRead } from '$lib/lq-ai/api/autonomous';
	import type { Project } from '$lib/lq-ai/types';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let entries: PrecedentEntryRead[] = [];
	let loading = false;
	let listError: string | null = null;
	let actionError: string | null = null;
	let actionSuccess: string | null = null;

	/** True after a successful promote-to-proposal action. */
	let proposalCreated = false;

	/**
	 * Map of entry id → pending action label (e.g. 'dismissing', 'promoting').
	 * Drives per-row disabled state + in-progress button text.
	 */
	let pendingIds: Map<string, string> = new Map();

	/**
	 * Set of entry ids for which the Project picker is currently open.
	 * Allows multiple pickers to be open simultaneously if the user opens
	 * several rows, but in practice only one is expected at a time.
	 */
	let pickerOpenIds: Set<string> = new Set();

	/** Projects available for promotion. Loaded once per page visit. */
	let projects: Project[] = [];
	let projectsLoading = false;
	let projectsError: string | null = null;

	/** Map of entry id → selected project id in its picker <select>. */
	let pickerSelections: Map<string, string> = new Map();

	// ---------------------------------------------------------------------------
	// Load
	// ---------------------------------------------------------------------------

	onMount(load);

	async function load(): Promise<void> {
		loading = true;
		listError = null;
		try {
			const resp = await autonomousApi.listPrecedents();
			// API returns non-dismissed entries only; there is no client-side
			// include_dismissed param, so entries is always the full server result.
			entries = resp.entries;
		} catch (err) {
			if (err instanceof LQAIApiError && err.status === 403) {
				listError = 'You need to enable autonomous mode to view precedents.';
			} else {
				listError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			loading = false;
		}
	}

	async function loadProjects(): Promise<void> {
		if (projects.length > 0 || projectsLoading) return; // already loaded or in flight
		projectsLoading = true;
		projectsError = null;
		try {
			projects = await projectsApi.listProjects();
		} catch (err) {
			projectsError = err instanceof Error ? err.message : String(err);
		} finally {
			projectsLoading = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Actions: Dismiss
	// ---------------------------------------------------------------------------

	async function dismissEntry(entry: PrecedentEntryRead): Promise<void> {
		const confirmed = confirm(
			`Dismiss this precedent? It will be hidden from the default view.`
		);
		if (!confirmed) return;

		pendingIds = new Map(pendingIds).set(entry.id, 'dismissing');
		actionError = null;
		actionSuccess = null;
		proposalCreated = false;
		try {
			await autonomousApi.dismissPrecedent(entry.id);
			actionSuccess = 'Precedent dismissed.';
			await load();
		} catch (err) {
			if (err instanceof LQAIApiError) {
				actionError = `Dismiss failed (${err.status}): ${err.message}`;
			} else {
				actionError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			const next = new Map(pendingIds);
			next.delete(entry.id);
			pendingIds = next;
		}
	}

	// ---------------------------------------------------------------------------
	// Actions: Promote (open picker → confirm selection → call API)
	// ---------------------------------------------------------------------------

	function openPicker(entry: PrecedentEntryRead): void {
		pickerOpenIds = new Set(pickerOpenIds).add(entry.id);
		// Pre-select the first project if none already chosen for this entry.
		if (!pickerSelections.has(entry.id) && projects.length > 0) {
			pickerSelections = new Map(pickerSelections).set(entry.id, projects[0].id);
		}
		loadProjects();
	}

	function closePicker(entryId: string): void {
		const next = new Set(pickerOpenIds);
		next.delete(entryId);
		pickerOpenIds = next;
	}

	function onPickerChange(entryId: string, projectId: string): void {
		pickerSelections = new Map(pickerSelections).set(entryId, projectId);
	}

	async function promoteEntry(entry: PrecedentEntryRead): Promise<void> {
		const projectId = pickerSelections.get(entry.id);
		if (!projectId) {
			actionError = 'Select a project before promoting.';
			return;
		}

		pendingIds = new Map(pendingIds).set(entry.id, 'promoting');
		actionError = null;
		actionSuccess = null;
		proposalCreated = false;
		try {
			await autonomousApi.promotePrecedent(entry.id, projectId);

			// Close picker on success.
			closePicker(entry.id);

			// Surface the proposal-created banner with a link to the Proposals page.
			proposalCreated = true;
		} catch (err) {
			if (err instanceof LQAIApiError) {
				actionError = `Promote failed (${err.status}): ${err.message}`;
			} else {
				actionError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			const next = new Map(pendingIds);
			next.delete(entry.id);
			pendingIds = next;
		}
	}

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function formatDate(iso: string): string {
		try {
			return new Intl.DateTimeFormat('en-US', {
				year: 'numeric',
				month: 'short',
				day: 'numeric'
			}).format(new Date(iso));
		} catch {
			return iso;
		}
	}

	function formatKind(kind: string): string {
		return kind.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
	}

	function pendingLabel(id: string): string | undefined {
		return pendingIds.get(id);
	}

	function isPickerOpen(id: string): boolean {
		return pickerOpenIds.has(id);
	}
</script>

<div class="precedents-page">
	<header class="page-header">
		<h1 class="lq-text-page-h">Precedents</h1>
		<p class="page-intro">
			Patterns LQVern has observed across matters — recurring counterparty positions and
			clause-language signals. Dismiss what is not relevant, or promote a pattern to a Project
			as a context proposal for your review.
		</p>
	</header>

	<!-- ================================================================ -->
	<!-- Banners                                                          -->
	<!-- ================================================================ -->

	{#if listError}
		<div class="error-banner" role="alert">{listError}</div>
	{/if}
	{#if actionError}
		<div class="error-banner" role="alert">{actionError}</div>
	{/if}
	{#if proposalCreated}
		<div class="success-banner" role="status">
			Proposal created — review it under
			<a class="banner-link" href="/lq-ai/autonomous/proposals">Proposals</a>.
		</div>
	{:else if actionSuccess}
		<div class="success-banner" role="status">{actionSuccess}</div>
	{/if}

	<!-- ================================================================ -->
	<!-- Loading + empty states                                           -->
	<!-- ================================================================ -->

	{#if loading && entries.length === 0}
		<p class="loading">Loading precedents…</p>
	{/if}

	{#if !loading && entries.length === 0 && !listError}
		<p class="empty-state">No precedents yet.</p>
	{/if}

	<!-- ================================================================ -->
	<!-- Entry list                                                       -->
	<!-- ================================================================ -->

	{#if entries.length > 0}
		<ul class="entry-list" aria-label="Precedent entries">
			{#each entries as entry (entry.id)}
				{@const pending = pendingLabel(entry.id)}
				{@const pickerOpen = isPickerOpen(entry.id)}
				{@const isDismissed = entry.dismissed_at !== null}

				<li class="entry-card" class:entry-card--dismissed={isDismissed}>
					<!-- Meta row: kind badge + observation count + date -->
					<div class="entry-meta">
						<span class="entry-kind">{formatKind(entry.pattern_kind)}</span>
						{#if entry.observed_count > 1}
							<span class="entry-count" title="Times observed">
								{entry.observed_count}×
							</span>
						{/if}
						{#if isDismissed}
							<span class="entry-dismissed-badge">Dismissed</span>
						{/if}
						<span class="entry-date">{formatDate(entry.created_at)}</span>
					</div>

					<!-- Pattern summary -->
					<p class="entry-summary">{entry.summary}</p>

					<!-- Action row -->
					<div class="entry-actions">
						{#if !isDismissed}
							<!-- Dismiss -->
							<button
								type="button"
								class="action-button danger"
								on:click={() => dismissEntry(entry)}
								disabled={!!pending}
							>
								{pending === 'dismissing' ? 'Dismissing…' : 'Dismiss'}
							</button>
						{/if}

						<!-- Promote (available on all entries, including dismissed) -->
						{#if !pickerOpen}
							<button
								type="button"
								class="action-button primary"
								on:click={() => openPicker(entry)}
								disabled={!!pending}
							>
								Promote to Project…
							</button>
						{:else}
							<!-- Inline project picker -->
							<div class="picker-inline" role="group" aria-label="Select project to promote to">
								{#if projectsLoading}
									<span class="picker-loading">Loading projects…</span>
								{:else if projectsError}
									<span class="picker-error">{projectsError}</span>
								{:else if projects.length === 0}
									<span class="picker-empty">No projects available.</span>
								{:else}
									<select
										class="picker-select"
										aria-label="Choose project"
										value={pickerSelections.get(entry.id) ?? projects[0].id}
										on:change={(e) =>
											onPickerChange(entry.id, (e.currentTarget as HTMLSelectElement).value)}
									>
										{#each projects as project (project.id)}
											<option value={project.id}>{project.name}</option>
										{/each}
									</select>
								{/if}

								<button
									type="button"
									class="action-button primary"
									on:click={() => promoteEntry(entry)}
									disabled={!!pending || projectsLoading || projects.length === 0}
								>
									{pending === 'promoting' ? 'Promoting…' : 'Promote'}
								</button>

								<button
									type="button"
									class="action-button"
									on:click={() => closePicker(entry.id)}
									disabled={!!pending}
								>
									Cancel
								</button>
							</div>
						{/if}
					</div>
				</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.precedents-page {
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

	.banner-link {
		color: inherit;
		font-weight: 600;
		text-decoration: underline;
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

	/* ------------------------------------------------------------------ */
	/* Entry list                                                          */
	/* ------------------------------------------------------------------ */

	.entry-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
	}

	.entry-card {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
		padding: var(--lq-space-4);
		border: 1px solid var(--lq-border);
		border-radius: 8px;
		background: var(--lq-surface);
	}

	.entry-card--dismissed {
		opacity: 0.65;
	}

	.entry-meta {
		display: flex;
		align-items: center;
		gap: var(--lq-space-3);
		flex-wrap: wrap;
	}

	.entry-kind {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 10px;
		font-size: 12px;
		font-weight: 500;
		background: var(--lq-info-bg, #e8f4fd);
		color: var(--lq-info-text, #0a5fa8);
		border: 1px solid var(--lq-info-border, #9ed3f5);
		white-space: nowrap;
	}

	.entry-count {
		font-size: 12px;
		font-weight: 600;
		color: var(--lq-text-secondary);
		background: var(--lq-surface-hover, rgba(0, 0, 0, 0.05));
		padding: 2px 6px;
		border-radius: 10px;
		white-space: nowrap;
	}

	.entry-dismissed-badge {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 10px;
		font-size: 12px;
		font-weight: 500;
		background: var(--lq-surface-hover, rgba(0, 0, 0, 0.06));
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
		white-space: nowrap;
	}

	.entry-date {
		color: var(--lq-text-secondary);
		font-size: 12px;
		white-space: nowrap;
		margin-left: auto;
	}

	.entry-summary {
		margin: 0;
		font-size: 14px;
		line-height: 1.6;
		color: var(--lq-text);
		white-space: pre-wrap;
		word-break: break-word;
	}

	/* ------------------------------------------------------------------ */
	/* Action row + picker                                                 */
	/* ------------------------------------------------------------------ */

	.entry-actions {
		display: flex;
		gap: var(--lq-space-2);
		flex-wrap: wrap;
		align-items: center;
		margin-top: var(--lq-space-1);
	}

	.picker-inline {
		display: flex;
		gap: var(--lq-space-2);
		align-items: center;
		flex-wrap: wrap;
	}

	.picker-select {
		padding: var(--lq-space-1) var(--lq-space-2);
		border: 1px solid var(--lq-border);
		border-radius: 6px;
		background: var(--lq-bg, #fff);
		color: var(--lq-text);
		font-size: 13px;
		min-width: 180px;
		cursor: pointer;
	}

	.picker-select:focus {
		outline: 2px solid var(--lq-accent);
		outline-offset: 1px;
	}

	.picker-loading,
	.picker-error,
	.picker-empty {
		font-size: 13px;
		color: var(--lq-text-secondary);
	}

	.picker-error {
		color: var(--lq-error-text, #800);
	}

	/* ------------------------------------------------------------------ */
	/* Buttons                                                             */
	/* ------------------------------------------------------------------ */

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

	.action-button.primary {
		background: var(--lq-accent);
		color: white;
		border-color: var(--lq-accent);
	}

	.action-button.primary:hover:not(:disabled) {
		opacity: 0.9;
		background: var(--lq-accent);
	}

	.action-button.danger {
		color: var(--lq-error-text, #b00);
		border-color: var(--lq-error-border, #fbb);
	}

	.action-button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
