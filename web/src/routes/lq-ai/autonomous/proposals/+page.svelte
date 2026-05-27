<script lang="ts">
	/**
	 * /lq-ai/autonomous/proposals — M4-C2 Project-context proposal review (Task 14).
	 *
	 * The "other half" of the precedent promote loop (Task 13): promoting a
	 * precedent creates a project_context_proposals row; here the user reviews
	 * it and either:
	 *   Accept → appends suggested_md to the target Project's context_md
	 *   Reject → discards the proposal (does not touch Project context)
	 *
	 * ADR 0013 D5: the agent never writes Project context directly. The user
	 * owns the Project; this page is the one authorized write path.
	 *
	 * State tabs: Pending (default) | All
	 *   Pending — shows only 'proposed' proposals; Accept + Reject buttons.
	 *   All     — shows every proposal with its state badge; no action buttons
	 *             for already-resolved rows.
	 *
	 * Mirrors sessions / memory / precedents pages + admin/intake-bridges:
	 *   onMount(load), loading/error/success banners, LQAIApiError,
	 *   confirm→act→reload, per-row pending guard.
	 */
	import { onMount } from 'svelte';

	import { autonomousApi, projectsApi } from '$lib/lq-ai/api';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import type { ProjectContextProposalRead, ProposalState } from '$lib/lq-ai/api/autonomous';
	import type { Project } from '$lib/lq-ai/types';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	/** All proposals returned by the current load (server-filtered by tab). */
	let proposals: ProjectContextProposalRead[] = [];
	let loading = false;
	let listError: string | null = null;
	let actionError: string | null = null;
	let actionSuccess: string | null = null;

	/**
	 * Currently active view tab.
	 *   'pending' → listProposals(state='proposed')
	 *   'all'     → listProposals() (no state filter)
	 */
	type Tab = 'pending' | 'all';
	let activeTab: Tab = 'pending';

	/**
	 * Map of proposal id → pending action label (e.g. 'accepting', 'rejecting').
	 * Drives per-row disabled state + in-progress button text.
	 */
	let pendingIds: Map<string, string> = new Map();

	/**
	 * Project map: id → Project. Populated once on first load.
	 * Used to resolve project_id → project name for display.
	 */
	let projectMap: Map<string, Project> = new Map();
	let projectsLoaded = false;

	// ---------------------------------------------------------------------------
	// Load
	// ---------------------------------------------------------------------------

	onMount(load);

	async function load(): Promise<void> {
		loading = true;
		listError = null;
		try {
			const stateFilter: ProposalState | undefined =
				activeTab === 'pending' ? 'proposed' : undefined;
			const resp = await autonomousApi.listProposals(stateFilter);
			proposals = resp.proposals;

			// Load project names once; refresh only if we encounter an unknown id.
			if (!projectsLoaded) {
				await loadProjects();
			}
		} catch (err) {
			if (err instanceof LQAIApiError && err.status === 403) {
				listError = 'You need to enable autonomous mode to view proposals.';
			} else {
				listError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			loading = false;
		}
	}

	async function loadProjects(): Promise<void> {
		try {
			const list = await projectsApi.listProjects();
			const next = new Map<string, Project>();
			for (const p of list) next.set(p.id, p);
			projectMap = next;
			projectsLoaded = true;
		} catch {
			// Non-fatal: project names fall back to id display.
		}
	}

	function switchTab(tab: Tab): void {
		if (tab === activeTab) return;
		activeTab = tab;
		actionError = null;
		actionSuccess = null;
		acceptedMatterHref = null;
		load();
	}

	// ---------------------------------------------------------------------------
	// Actions: Accept
	// ---------------------------------------------------------------------------

	async function acceptProposal(proposal: ProjectContextProposalRead): Promise<void> {
		const projectName = resolveProjectName(proposal.project_id);
		pendingIds = new Map(pendingIds).set(proposal.id, 'accepting');
		actionError = null;
		actionSuccess = null;
		acceptedMatterHref = null;
		try {
			await autonomousApi.acceptProposal(proposal.id);
			actionSuccess = `Added to ${projectName} context.`;
			acceptedMatterHref = matterHref(proposal.project_id);
			await load();
		} catch (err) {
			if (err instanceof LQAIApiError) {
				actionError = `Accept failed (${err.status}): ${err.message}`;
			} else {
				actionError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			const next = new Map(pendingIds);
			next.delete(proposal.id);
			pendingIds = next;
		}
	}

	// ---------------------------------------------------------------------------
	// Actions: Reject
	// ---------------------------------------------------------------------------

	async function rejectProposal(proposal: ProjectContextProposalRead): Promise<void> {
		const projectName = resolveProjectName(proposal.project_id);
		const confirmed = confirm(
			`Reject this proposal for ${projectName}? The suggested context will be discarded.`
		);
		if (!confirmed) return;

		pendingIds = new Map(pendingIds).set(proposal.id, 'rejecting');
		actionError = null;
		actionSuccess = null;
		acceptedMatterHref = null;
		try {
			await autonomousApi.rejectProposal(proposal.id);
			actionSuccess = 'Proposal rejected.';
			await load();
		} catch (err) {
			if (err instanceof LQAIApiError) {
				actionError = `Reject failed (${err.status}): ${err.message}`;
			} else {
				actionError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			const next = new Map(pendingIds);
			next.delete(proposal.id);
			pendingIds = next;
		}
	}

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	/**
	 * Returns the project name if known, otherwise returns a truncated version
	 * of the project_id so the UX is readable even without a name lookup.
	 */
	function resolveProjectName(projectId: string): string {
		return projectMap.get(projectId)?.name ?? `project ${projectId.slice(0, 8)}…`;
	}

	/**
	 * Returns the matters route for a given project id if we have the project,
	 * otherwise null. Used to link to /lq-ai/matters/{id} from success banners.
	 */
	function matterHref(projectId: string): string | null {
		return projectMap.has(projectId) ? `/lq-ai/matters/${projectId}` : null;
	}

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

	function stateLabel(state: string): string {
		switch (state) {
			case 'proposed':
				return 'Pending';
			case 'accepted':
				return 'Accepted';
			case 'rejected':
				return 'Rejected';
			default:
				return state;
		}
	}

	function pendingLabel(id: string): string | undefined {
		return pendingIds.get(id);
	}

	/**
	 * Set directly in the accept handler on success; cleared on any action reset
	 * or tab switch. Decouples the "View matter" link from the banner copy string.
	 */
	let acceptedMatterHref: string | null = null;
</script>

<div class="proposals-page">
	<header class="page-header">
		<h1 class="lq-text-page-h">Proposals</h1>
		<p class="page-intro">
			Context proposals generated when a precedent is promoted to a project. Accept to append
			the suggested text to the project's context, or reject to discard it. The agent never
			writes project context directly — that decision is yours.
		</p>
	</header>

	<!-- ================================================================ -->
	<!-- Tabs                                                             -->
	<!-- ================================================================ -->

	<nav class="tab-bar" aria-label="Proposal view">
		<button
			type="button"
			class="tab-button"
			class:tab-button--active={activeTab === 'pending'}
			on:click={() => switchTab('pending')}
		>
			Pending
		</button>
		<button
			type="button"
			class="tab-button"
			class:tab-button--active={activeTab === 'all'}
			on:click={() => switchTab('all')}
		>
			All
		</button>
	</nav>

	<!-- ================================================================ -->
	<!-- Banners                                                          -->
	<!-- ================================================================ -->

	{#if listError}
		<div class="error-banner" role="alert">{listError}</div>
	{/if}
	{#if actionError}
		<div class="error-banner" role="alert">{actionError}</div>
	{/if}
	{#if actionSuccess}
		<div class="success-banner" role="status">
			{actionSuccess}
			{#if acceptedMatterHref}
				<a class="banner-link" href={acceptedMatterHref}>View matter →</a>
			{/if}
		</div>
	{/if}

	<!-- ================================================================ -->
	<!-- Loading + empty states                                           -->
	<!-- ================================================================ -->

	{#if loading && proposals.length === 0}
		<p class="loading">Loading proposals…</p>
	{/if}

	{#if !loading && proposals.length === 0 && !listError}
		<p class="empty-state">
			{activeTab === 'pending' ? 'No pending proposals.' : 'No proposals yet.'}
		</p>
	{/if}

	<!-- ================================================================ -->
	<!-- Proposal list                                                    -->
	<!-- ================================================================ -->

	{#if proposals.length > 0}
		<ul class="proposal-list" aria-label="Project context proposals">
			{#each proposals as proposal (proposal.id)}
				{@const pending = pendingLabel(proposal.id)}
				{@const isPending = proposal.state === 'proposed'}
				{@const projectName = resolveProjectName(proposal.project_id)}
				{@const href = matterHref(proposal.project_id)}

				<li class="proposal-card">
					<!-- Meta row: project + state badge + date -->
					<div class="proposal-meta">
						<span class="proposal-project">
							{#if href}
								<a class="project-link" {href}>{projectName}</a>
							{:else}
								{projectName}
							{/if}
						</span>

						<span
							class="state-badge"
							class:state-badge--pending={proposal.state === 'proposed'}
							class:state-badge--accepted={proposal.state === 'accepted'}
							class:state-badge--rejected={proposal.state === 'rejected'}
						>
							{stateLabel(proposal.state)}
						</span>

						<span class="proposal-date">{formatDate(proposal.created_at)}</span>
					</div>

					<!-- Proposed context text -->
					<div class="proposed-md">
						<p class="proposed-md-text">{proposal.suggested_md}</p>
					</div>

					<!-- Precedent source note -->
					<p class="proposal-source">
						Source precedent: <code class="proposal-id">{proposal.precedent_id.slice(0, 8)}…</code>
					</p>

					<!-- Action row — only for pending proposals -->
					{#if isPending}
						<div class="proposal-actions">
							<button
								type="button"
								class="action-button primary"
								on:click={() => acceptProposal(proposal)}
								disabled={!!pending}
							>
								{pending === 'accepting' ? 'Accepting…' : 'Accept'}
							</button>

							<button
								type="button"
								class="action-button danger"
								on:click={() => rejectProposal(proposal)}
								disabled={!!pending}
							>
								{pending === 'rejecting' ? 'Rejecting…' : 'Reject'}
							</button>
						</div>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.proposals-page {
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
	/* Tabs                                                                */
	/* ------------------------------------------------------------------ */

	.tab-bar {
		display: flex;
		gap: var(--lq-space-1);
		border-bottom: 1px solid var(--lq-border);
		padding-bottom: 0;
	}

	.tab-button {
		padding: var(--lq-space-2) var(--lq-space-3);
		background: transparent;
		border: none;
		border-bottom: 2px solid transparent;
		margin-bottom: -1px;
		font-size: 14px;
		cursor: pointer;
		color: var(--lq-text-secondary);
		transition: color 0.1s, border-color 0.1s;
	}

	.tab-button:hover {
		color: var(--lq-text);
	}

	.tab-button--active {
		color: var(--lq-accent);
		border-bottom-color: var(--lq-accent);
		font-weight: 500;
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
		display: flex;
		align-items: center;
		gap: var(--lq-space-3);
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
		white-space: nowrap;
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
	/* Proposal list                                                       */
	/* ------------------------------------------------------------------ */

	.proposal-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
	}

	.proposal-card {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
		padding: var(--lq-space-4);
		border: 1px solid var(--lq-border);
		border-radius: 8px;
		background: var(--lq-surface);
	}

	/* ------------------------------------------------------------------ */
	/* Meta row                                                            */
	/* ------------------------------------------------------------------ */

	.proposal-meta {
		display: flex;
		align-items: center;
		gap: var(--lq-space-3);
		flex-wrap: wrap;
	}

	.proposal-project {
		font-size: 13px;
		font-weight: 600;
		color: var(--lq-text);
	}

	.project-link {
		color: var(--lq-accent);
		text-decoration: none;
	}

	.project-link:hover {
		text-decoration: underline;
	}

	.state-badge {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 10px;
		font-size: 12px;
		font-weight: 500;
		white-space: nowrap;
		border: 1px solid transparent;
	}

	.state-badge--pending {
		background: var(--lq-warning-bg, #fef9e7);
		color: var(--lq-warning-text, #8a5c00);
		border-color: var(--lq-warning-border, #f5d77e);
	}

	.state-badge--accepted {
		background: var(--lq-success-bg, #efe);
		color: var(--lq-success-text, #060);
		border-color: var(--lq-success-border, #bfb);
	}

	.state-badge--rejected {
		background: var(--lq-surface-hover, rgba(0, 0, 0, 0.05));
		color: var(--lq-text-secondary);
		border-color: var(--lq-border);
	}

	.proposal-date {
		color: var(--lq-text-secondary);
		font-size: 12px;
		white-space: nowrap;
		margin-left: auto;
	}

	/* ------------------------------------------------------------------ */
	/* Proposed context text                                               */
	/* ------------------------------------------------------------------ */

	.proposed-md {
		padding: var(--lq-space-3);
		background: var(--lq-surface-hover, rgba(0, 0, 0, 0.03));
		border-radius: 6px;
		border-left: 3px solid var(--lq-accent);
	}

	.proposed-md-text {
		margin: 0;
		font-size: 14px;
		line-height: 1.6;
		color: var(--lq-text);
		white-space: pre-wrap;
		word-break: break-word;
	}

	/* ------------------------------------------------------------------ */
	/* Source note                                                          */
	/* ------------------------------------------------------------------ */

	.proposal-source {
		margin: 0;
		font-size: 12px;
		color: var(--lq-text-secondary);
	}

	.proposal-id {
		font-family: var(--lq-font-mono, monospace);
		font-size: 11px;
		background: var(--lq-surface-hover, rgba(0, 0, 0, 0.05));
		padding: 1px 4px;
		border-radius: 3px;
	}

	/* ------------------------------------------------------------------ */
	/* Action row                                                          */
	/* ------------------------------------------------------------------ */

	.proposal-actions {
		display: flex;
		gap: var(--lq-space-2);
		flex-wrap: wrap;
		align-items: center;
		margin-top: var(--lq-space-1);
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
