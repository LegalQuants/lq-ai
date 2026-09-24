<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { projectsApi, autonomousApi } from '$lib/lq-ai/api';
  import { LQAIApiError } from '$lib/lq-ai/api/client';
  import type { ProjectContextProposalRead } from '$lib/lq-ai/api/autonomous';
  import type { Project } from '$lib/lq-ai/types';
  import { preferences, initPreferences } from '$lib/lq-ai/stores/preferences';
  import MatterRail from '$lib/lq-ai/components/MatterRail.svelte';
  import ChatPanel from '$lib/lq-ai/components/ChatPanel.svelte';
  import { pendingProposalsFor, removeProposal, bannerVisible } from './proposal-helpers';

  let matter: Project | null = null;
  let loading = true;
  let error: string | null = null;
  let activeChatId: string | undefined = undefined;

  // -------------------------------------------------------------------------
  // DE-323 — context-proposal inbox banner (autonomous opt-in users only).
  // The matter-local surface of /lq-ai/autonomous/proposals: pending
  // proposals targeting THIS project, with inline Accept/Reject. Accept is
  // the user-authorized context_md write (ADR 0013 D5) — the agent never
  // writes Project context directly.
  // -------------------------------------------------------------------------
  let proposals: ProjectContextProposalRead[] = [];
  let proposalError: string | null = null;
  let proposalSuccess: string | null = null;
  /** proposal id → 'accepting' | 'rejecting'; drives per-row disabled state. */
  let proposalPendingIds: Map<string, string> = new Map();

  $: matterId = $page.params.id;
  $: showProposalBanner = bannerVisible(
    $preferences.autonomous_enabled,
    proposals.length,
    proposalError !== null || proposalSuccess !== null
  );

  async function loadMatter() {
    if (!matterId) return;
    loading = true;
    try {
      matter = await projectsApi.getProject(matterId);
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load matter';
    } finally {
      loading = false;
    }
  }

  /**
   * Re-fetch the matter WITHOUT toggling the page-level loading flag, so the
   * workspace (and the proposal banner's success message) stays mounted.
   * Used after an accepted proposal appends to the matter's context_md.
   */
  async function refreshMatter() {
    if (!matterId) return;
    try {
      matter = await projectsApi.getProject(matterId);
    } catch (e) {
      // Keep the stale matter on refresh failure — the accept itself succeeded.
      console.error('lq-ai: failed to refresh matter after proposal accept', e);
    }
  }

  async function loadProposals() {
    if (!matterId) return;
    try {
      const resp = await autonomousApi.listProposals('proposed', matterId);
      proposals = pendingProposalsFor(resp.proposals, matterId);
    } catch (e) {
      if (e instanceof LQAIApiError && e.status === 403) {
        // Not opted in server-side — keep the banner hidden, no error.
        return;
      }
      // Best-effort: a proposals fetch failure must not degrade the matter page.
      console.error('lq-ai: failed to load context proposals', e);
    }
  }

  async function handleAcceptProposal(proposal: ProjectContextProposalRead) {
    proposalPendingIds = new Map(proposalPendingIds).set(proposal.id, 'accepting');
    proposalError = null;
    proposalSuccess = null;
    try {
      await autonomousApi.acceptProposal(proposal.id);
      proposals = removeProposal(proposals, proposal.id);
      proposalSuccess = 'Added to matter context.';
      await refreshMatter();
    } catch (e) {
      if (e instanceof LQAIApiError) {
        proposalError = `Accept failed (${e.status}): ${e.message}`;
      } else {
        proposalError = e instanceof Error ? e.message : String(e);
      }
    } finally {
      const next = new Map(proposalPendingIds);
      next.delete(proposal.id);
      proposalPendingIds = next;
    }
  }

  async function handleRejectProposal(proposal: ProjectContextProposalRead) {
    const confirmed = confirm(
      'Reject this proposal? The suggested context will be discarded.'
    );
    if (!confirmed) return;

    proposalPendingIds = new Map(proposalPendingIds).set(proposal.id, 'rejecting');
    proposalError = null;
    proposalSuccess = null;
    try {
      await autonomousApi.rejectProposal(proposal.id);
      proposals = removeProposal(proposals, proposal.id);
      proposalSuccess = 'Proposal rejected.';
    } catch (e) {
      if (e instanceof LQAIApiError) {
        proposalError = `Reject failed (${e.status}): ${e.message}`;
      } else {
        proposalError = e instanceof Error ? e.message : String(e);
      }
    } finally {
      const next = new Map(proposalPendingIds);
      next.delete(proposal.id);
      proposalPendingIds = next;
    }
  }

  function handleMatterUpdate(next: Project) {
    matter = next;
  }

  async function handleMatterArchived() {
    // Archive flow already completed by MatterRailMetadata; navigate away.
    await goto('/lq-ai/matters');
  }

  onMount(() => {
    loadMatter();
    // Proposals are gated on the autonomous opt-in preference; resolve it
    // first (server-synced with localStorage cache), then fetch best-effort.
    void (async () => {
      await initPreferences();
      if ($preferences.autonomous_enabled) {
        await loadProposals();
      }
    })();
  });
</script>

{#if loading}
  <p class="lq-text-body" style="padding: var(--lq-space-6); color: var(--lq-text-secondary);">Loading matter…</p>
{:else if error || !matter}
  <p class="lq-text-body" style="padding: var(--lq-space-6); color: var(--lq-error, #b91c1c);">{error ?? 'Matter not found'}</p>
{:else}
  <div class="matter-page">
    {#if showProposalBanner}
      <section class="proposal-banner" aria-label="Context proposals">
        <header class="proposal-banner-header">
          <h2 class="lq-text-panel-h proposal-banner-title">Context proposals</h2>
          {#if proposals.length > 0}
            <span class="lq-text-caption proposal-banner-count">
              {proposals.length} pending — accept to append to this matter's context, or reject to discard.
            </span>
          {/if}
        </header>

        {#if proposalError}
          <div class="proposal-message proposal-message--error" role="alert">{proposalError}</div>
        {/if}
        {#if proposalSuccess}
          <div class="proposal-message proposal-message--success" role="status">{proposalSuccess}</div>
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
                    on:click={() => handleAcceptProposal(proposal)}
                    disabled={!!pending}
                  >
                    {pending === 'accepting' ? 'Accepting…' : 'Accept'}
                  </button>
                  <button
                    type="button"
                    class="proposal-button proposal-button--danger"
                    on:click={() => handleRejectProposal(proposal)}
                    disabled={!!pending}
                  >
                    {pending === 'rejecting' ? 'Rejecting…' : 'Reject'}
                  </button>
                </div>
              </li>
            {/each}
          </ul>
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
          on:kbsAttached={loadMatter}
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
