<script lang="ts">
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { projectsApi, autonomousApi, preferencesApi } from '$lib/lq-ai/api';
	import type { ProjectContextProposalRead } from '$lib/lq-ai/api/autonomous';
	import type { Project } from '$lib/lq-ai/types';
	import MatterRail from '$lib/lq-ai/components/MatterRail.svelte';
	import ChatPanel from '$lib/lq-ai/components/ChatPanel.svelte';
	import { bannerVisible } from './proposal-helpers';
	import { createProposalInbox } from './proposal-inbox';

	let matter: Project | null = null;
	let loading = true;
	let error: string | null = null;
	let activeChatId: string | undefined = undefined;
	let mounted = false;
	let matterRequest = 0;
	$: matterId = $page.params.id;

	const inbox = createProposalInbox({
		getOptIn: async () => {
			// The shared initializer retains cache on failure; this inbox requires fresh opt-in.
			return (await preferencesApi.getPreferences()).autonomous_enabled;
		},
		list: (id, limit, offset) => autonomousApi.listProposals('proposed', id, limit, offset),
		accept: autonomousApi.acceptProposal,
		reject: autonomousApi.rejectProposal,
		onAccepted: async (id, isCurrent) => {
			const refreshed = await projectsApi.getProject(id);
			if (mounted && isCurrent() && matterId === id) matter = refreshed;
		}
	});
	$: proposals = $inbox.proposals;
	$: proposalError = $inbox.error;
	$: proposalSuccess = $inbox.success;
	$: proposalPendingIds = new Map(Object.entries($inbox.pending));
	$: showProposalBanner = bannerVisible(
		$inbox.enabled,
		$inbox.totalCount,
		proposalError !== null || proposalSuccess !== null
	);

	async function loadMatter(id: string | undefined) {
		if (!id) return;
		const request = ++matterRequest;
		loading = true;
		error = null;
		if (matter?.id !== id) activeChatId = undefined;
		try {
			const next = await projectsApi.getProject(id);
			if (mounted && request === matterRequest && matterId === id) matter = next;
		} catch (e) {
			if (mounted && request === matterRequest && matterId === id) {
				error = e instanceof Error ? e.message : 'Failed to load matter';
			}
		} finally {
			if (mounted && request === matterRequest && matterId === id) loading = false;
		}
	}

	function handleMatterUpdate(next: Project) {
		matter = next;
	}

	async function handleMatterArchived() {
		await goto('/lq-ai/matters');
	}

	function handleRejectProposal(proposal: ProjectContextProposalRead) {
		if (proposalPendingIds.has(proposal.id)) return;
		if (confirm('Reject this proposal? The suggested context will be discarded.')) {
			void inbox.reject(proposal.id);
		}
	}

	// The page is reused on A → B navigation. Reset both loaders for every id.
	$: if (mounted && matterId) {
		void loadMatter(matterId);
		void inbox.setMatter(matterId);
	}
	onMount(() => {
		mounted = true;
		return () => {
			mounted = false;
			++matterRequest;
			inbox.destroy();
		};
	});
</script>

{#if loading}
	<p class="lq-text-body" style="padding: var(--lq-space-6); color: var(--lq-text-secondary);">
		Loading matter...
	</p>
{:else if error || !matter}
	<p class="lq-text-body" style="padding: var(--lq-space-6); color: var(--lq-error, #b91c1c);">
		{error ?? 'Matter not found'}
	</p>
{:else}
	<div class="matter-page">
		{#if showProposalBanner}
			<section class="proposal-banner" aria-label="Context proposals">
				<header class="proposal-banner-header">
					<h2 class="lq-text-panel-h proposal-banner-title">Context proposals</h2>
					{#if proposals.length > 0}
						<span class="lq-text-caption proposal-banner-count">
							{$inbox.totalCount} pending — showing {proposals.length}. Accept to append to this
							matter's context, or reject to discard.
						</span>
					{/if}
				</header>

				{#if proposalError}
					<div class="proposal-message proposal-message--error" role="alert">{proposalError}</div>
				{/if}
				{#if proposalSuccess}
					<div class="proposal-message proposal-message--success" role="status">
						{proposalSuccess}
					</div>
				{/if}

				{#if proposals.length > 0}
					<ul class="proposal-list" aria-label="Pending context proposals">
						{#each proposals as proposal (proposal.id)}
							{@const pending = proposalPendingIds.get(proposal.id)}
							<li class="proposal-row">
								<div class="proposal-body">
									<p class="proposal-text">{proposal.suggested_md}</p>
									<span class="lq-text-caption proposal-date">
										Proposed {new Date(proposal.created_at).toLocaleDateString()}
									</span>
								</div>
								<div class="proposal-actions">
									<button
										type="button"
										class="proposal-button proposal-button--primary"
										on:click={() => inbox.accept(proposal.id)}
										disabled={!!pending}
									>
										{pending === 'accepting' ? 'Accepting...' : 'Accept'}
									</button>
									<button
										type="button"
										class="proposal-button proposal-button--danger"
										on:click={() => handleRejectProposal(proposal)}
										disabled={!!pending}
									>
										{pending === 'rejecting' ? 'Rejecting...' : 'Reject'}
									</button>
								</div>
							</li>
						{/each}
					</ul>
				{/if}
				{#if $inbox.nextOffset < $inbox.totalCount}
					<button
						type="button"
						class="proposal-button"
						disabled={$inbox.loading ||
							$inbox.loadingMore ||
							Object.keys($inbox.pending).length > 0}
						on:click={() => inbox.loadMore()}
					>
						{$inbox.loadingMore ? 'Loading...' : 'Load more proposals'}
					</button>
				{/if}
			</section>
		{/if}

		<div class="matter-workspace">
			<MatterRail
				{matter}
				bind:activeChatId
				onMatterUpdate={handleMatterUpdate}
				onMatterArchived={handleMatterArchived}
			/>
			<div class="matter-chat-pane">
				<ChatPanel
					projectIdFilter={matter.id}
					initialChatId={activeChatId}
					on:kbsAttached={() => loadMatter(matterId)}
				/>
			</div>
		</div>
	</div>
{/if}

<style>
	.matter-page {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
	}

	.matter-workspace {
		display: flex;
		flex: 1;
		min-height: 0;
	}

	.matter-chat-pane {
		flex: 1;
		min-width: 0;
		min-height: 0;
		display: flex;
	}

	/* Match the outer layout's overflow-y: auto on main — the rail scrolls
     within itself if it overflows; the chat panel manages its own scroll
     internally. */

	/* ------------------------------------------------------------------ */
	/* DE-323 — context-proposal inbox banner                             */
	/* ------------------------------------------------------------------ */

	.proposal-banner {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
		padding: var(--lq-space-3) var(--lq-space-4);
		border-bottom: 1px solid var(--lq-border);
		background: var(--lq-surface);
		flex-shrink: 0;
		max-height: min(40vh, 24rem);
		overflow-y: auto;
	}

	.proposal-banner-header {
		display: flex;
		align-items: baseline;
		gap: var(--lq-space-3);
		flex-wrap: wrap;
	}

	.proposal-banner-title {
		margin: 0;
	}

	.proposal-banner-count {
		color: var(--lq-text-secondary);
	}

	.proposal-message {
		padding: var(--lq-space-2) var(--lq-space-3);
		border-radius: 6px;
		font-size: 13px;
	}

	.proposal-message--error {
		background: var(--lq-error-bg, #fee);
		color: var(--lq-error-text, #800);
		border: 1px solid var(--lq-error-border, #fbb);
	}

	.proposal-message--success {
		background: var(--lq-success-bg, #efe);
		color: var(--lq-success-text, #060);
		border: 1px solid var(--lq-success-border, #bfb);
	}

	.proposal-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.proposal-row {
		display: flex;
		align-items: flex-start;
		gap: var(--lq-space-3);
		padding: var(--lq-space-2) var(--lq-space-3);
		border: 1px solid var(--lq-border);
		border-left: 3px solid var(--lq-accent);
		border-radius: 6px;
		background: var(--lq-surface-hover, rgba(0, 0, 0, 0.03));
	}

	.proposal-body {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-1);
	}

	.proposal-text {
		margin: 0;
		font-size: 13px;
		line-height: 1.5;
		color: var(--lq-text);
		white-space: pre-wrap;
		word-break: break-word;
	}

	.proposal-date {
		color: var(--lq-text-secondary);
	}

	.proposal-actions {
		display: flex;
		gap: var(--lq-space-2);
		flex-shrink: 0;
	}

	.proposal-button {
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

	.proposal-button:hover:not(:disabled) {
		background: var(--lq-surface-hover, rgba(0, 0, 0, 0.04));
	}

	.proposal-button--primary {
		background: var(--lq-accent);
		color: white;
		border-color: var(--lq-accent);
	}

	.proposal-button--primary:hover:not(:disabled) {
		opacity: 0.9;
		background: var(--lq-accent);
	}

	.proposal-button--danger {
		color: var(--lq-error-text, #b00);
		border-color: var(--lq-error-border, #fbb);
	}

	.proposal-button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
