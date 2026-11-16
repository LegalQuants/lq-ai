<script lang="ts">
  import { IconX } from '@tabler/icons-svelte';
  /**
   * MatterRailKnowledge — the rail's Knowledge section.
   *
   * Surfaces the currently-attached KBs as a compact list and exposes a
   * "+ Attach KB" affordance that mounts the shared {@link AttachKBModal}.
   * On successful attach or detach, fetches a fresh Project so the rail's
   * KB list updates in-place — matches the `MatterRailFiles` /
   * `MatterRailSkills` shape and keeps the parent matter object in sync.
   *
   * KB *names* aren't carried on the Project row (only ids), so we resolve
   * them via `knowledgeBasesApi.getKnowledgeBase` on mount + whenever
   * `attached_knowledge_base_ids` changes. Best-effort: a 404 (KB deleted
   * out-of-band) is dropped silently and the row falls back to "untitled".
   */
  import { knowledgeBasesApi, projectsApi } from '$lib/lq-ai/api';
  import { detachKnowledgeBase } from '$lib/lq-ai/api/projectKnowledgeBases';
  import type { KnowledgeBase, Project } from '$lib/lq-ai/types';
  import { onMount } from 'svelte';
  import AttachKBModal from './AttachKBModal.svelte';
  import LqText from './shared/LqText.svelte';
  import LqTitle from './shared/LqTitle.svelte';

  export let matter: Project;
  export let onMatterUpdate: (next: Project) => void = () => {};

  // Resolved metadata for currently-attached KBs.
  let attachedKBs: KnowledgeBase[] = [];
  let loadingAttached = false;

  let modalOpen = false;
  let detachingId: string | null = null;
  let detachError: string | null = null;

  async function loadAttachedKBs() {
    const ids = matter.attached_knowledge_base_ids ?? [];
    if (ids.length === 0) {
      attachedKBs = [];
      return;
    }
    loadingAttached = true;
    try {
      const results = await Promise.all(
        ids.map((id) => knowledgeBasesApi.getKnowledgeBase(id).catch(() => null))
      );
      attachedKBs = results.filter((kb): kb is KnowledgeBase => kb !== null);
    } catch (e) {
      console.error('lq-ai: failed to load attached KBs', e);
    } finally {
      loadingAttached = false;
    }
  }

  async function refreshMatter() {
    try {
      const next = await projectsApi.getProject(matter.id);
      onMatterUpdate(next);
    } catch (e) {
      console.error('lq-ai: failed to refresh matter after KB change', e);
    }
  }

  function openModal() {
    detachError = null;
    modalOpen = true;
  }

  function closeModal() {
    modalOpen = false;
  }

  async function handleAttached(_newKbIds: string[]) {
    modalOpen = false;
    await refreshMatter();
  }

  async function handleModalDetach(kbId: string) {
    // Detach was performed inside the modal against the same endpoint; we
    // just need to refresh the matter so both the rail and the modal's
    // "currently attached" set reflect the new state.
    await refreshMatter();
    // Drop the row locally too so the rail updates before the prop change propagates.
    attachedKBs = attachedKBs.filter((kb) => kb.id !== kbId);
  }

  async function detachFromRail(kbId: string) {
    detachError = null;
    detachingId = kbId;
    try {
      await detachKnowledgeBase(matter.id, kbId);
      attachedKBs = attachedKBs.filter((kb) => kb.id !== kbId);
      await refreshMatter();
    } catch (e) {
      detachError = e instanceof Error ? e.message : 'Failed to detach knowledge base.';
    } finally {
      detachingId = null;
    }
  }

  // Reload attached KBs whenever the matter's attached_knowledge_base_ids change.
  $: matter.attached_knowledge_base_ids, loadAttachedKBs();

  onMount(loadAttachedKBs);
</script>

<section class="mrk-section" data-testid="matter-rail-knowledge">
  <header class="mrk-header">
    <LqTitle order={3} size="16" weight="semibold" tone="primary" class="mrk-title">Knowledge</LqTitle>
    <button
      type="button"
      class="mrk-btn-attach"
      on:click={openModal}
      data-testid="matter-rail-attach-kb-btn"
    >
      + Attach KB
    </button>
  </header>

  {#if detachError}
    <p class="mrk-error" role="alert">{detachError}</p>
  {/if}

  {#if loadingAttached}
    <LqText as="p" size="12" tone="tertiary" class="mrk-empty">Loading knowledge bases…</LqText>
  {:else if attachedKBs.length === 0}
    <LqText as="p" size="12" tone="tertiary" class="mrk-empty">No knowledge bases attached.</LqText>
  {:else}
    <ul class="mrk-kb-list">
      {#each attachedKBs as kb (kb.id)}
        <li class="mrk-kb-row">
          <LqText as="span" size="13.5" tone="primary" class="mrk-kb-name" title={kb.name}>{kb.name}</LqText>
          <LqText as="span" size="12" tone="tertiary" class="mrk-kb-meta">
            {kb.file_count ?? 0} {kb.file_count === 1 ? 'doc' : 'docs'}
          </LqText>
          <button
            type="button"
            class="mrk-btn-detach"
            aria-label="Detach {kb.name}"
            on:click={() => detachFromRail(kb.id)}
            disabled={detachingId === kb.id}
          >
            {#if detachingId === kb.id}…{:else}<IconX size={14} stroke={1.75} aria-hidden="true" />{/if}
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</section>

{#if modalOpen}
  <AttachKBModal
    bind:open={modalOpen}
    projectId={matter.id}
    attachedKbIds={matter.attached_knowledge_base_ids ?? []}
    onClose={closeModal}
    onAttach={handleAttached}
    onDetach={handleModalDetach}
  />
{/if}

<style>
  @import '$lib/lq-ai/styles/practice.css';

  .mrk-section {
    display: flex;
    flex-direction: column;
    gap: var(--lq-space-2);
  }

  .mrk-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--lq-space-2);
  }

  .mrk-header :global(.mrk-title) {
    margin: 0;
  }

  .mrk-section :global(.mrk-empty) {
    padding: var(--lq-space-1) 0;
  }

  .mrk-error {
    font-size: 12px;
    color: var(--lq-error);
    background: var(--lq-error-soft);
    border: 1px solid var(--lq-error-border);
    border-radius: var(--lq-radius);
    padding: var(--lq-space-1) var(--lq-space-2);
    margin: 0;
  }

  .mrk-btn-attach {
    font-size: 12px;
    font-weight: 500;
    color: var(--lq-accent);
    background: transparent;
    border: 1px solid var(--lq-accent-border);
    border-radius: var(--lq-radius-pill);
    padding: 2px 10px;
    cursor: pointer;
    white-space: nowrap;
  }

  .mrk-btn-attach:hover {
    background: var(--lq-accent-soft);
  }

  .mrk-btn-attach:focus-visible {
    outline: 2px solid var(--lq-accent);
    outline-offset: 2px;
  }

  .mrk-kb-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--lq-space-1);
  }

  .mrk-kb-row {
    display: flex;
    align-items: center;
    gap: var(--lq-space-2);
    padding: var(--lq-space-1) var(--lq-space-2);
    background: var(--lq-inset);
    border: 1px solid var(--lq-border);
    border-radius: var(--lq-radius);
  }

  .mrk-kb-row :global(.mrk-kb-name) {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .mrk-kb-row :global(.mrk-kb-meta) {
    white-space: nowrap;
    flex-shrink: 0;
  }

  .mrk-btn-detach {
    font-size: 14px;
    font-weight: 500;
    color: var(--lq-text-tertiary);
    background: transparent;
    border: 0;
    cursor: pointer;
    padding: 0 2px;
    line-height: 1;
    flex-shrink: 0;
  }

  .mrk-btn-detach:hover:not(:disabled) {
    color: var(--lq-error);
  }

  .mrk-btn-detach:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .mrk-btn-detach:focus-visible {
    outline: 2px solid var(--lq-accent);
    outline-offset: 2px;
  }
</style>
