<script lang="ts">
  import { onMount } from 'svelte';
  import { projectsApi } from '$lib/lq-ai/api';
  import type { Project } from '$lib/lq-ai/types';
  import MatterCard from '$lib/lq-ai/components/MatterCard.svelte';
  import NewMatterModal from '$lib/lq-ai/components/NewMatterModal.svelte';
  import LqText from '$lib/lq-ai/components/shared/LqText.svelte';
  import LqTitle from '$lib/lq-ai/components/shared/LqTitle.svelte';

  let matters: Project[] = [];
  let loading = true;
  let error: string | null = null;
  let showNewModal = false;
  let archivedFilter = false;

  async function refresh() {
    loading = true;
    try {
      matters = await projectsApi.listProjects(archivedFilter ? { archived: true } : {});
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load matters';
    } finally {
      loading = false;
    }
  }

  onMount(refresh);

  function openNewModal() {
    showNewModal = true;
  }
</script>

<main class="mtr-page">
  <header class="mtr-header">
    <LqTitle order={1} size="20" weight="bold" tone="primary">Matters</LqTitle>
    <div class="mtr-header__actions">
      <LqText as="label" size="12" tone="secondary" class="mtr-archived-toggle">
        <input type="checkbox" bind:checked={archivedFilter} on:change={refresh} />
        Show archived
      </LqText>
      <button type="button" class="mtr-btn-primary" on:click={openNewModal}>
        + New matter
      </button>
    </div>
  </header>

  {#if loading}
    <LqText as="p" size="14" tone="secondary" class="mtr-state-msg">Loading matters…</LqText>
  {:else if error}
    <LqText as="p" size="14" tone="danger" class="mtr-state-msg mtr-state-msg--error">
      Couldn't load matters: {error}
    </LqText>
  {:else if matters.length === 0}
    <section class="mtr-empty-state">
      <LqText as="p" size="14" tone="secondary" class="mtr-empty-state__copy">
        {archivedFilter ? 'No archived matters.' : "You don't have any matters yet."}
      </LqText>
      {#if !archivedFilter}
        <button type="button" class="mtr-btn-primary" on:click={openNewModal}>
          + Start your first matter
        </button>
      {/if}
    </section>
  {:else}
    <div class="mtr-grid">
      {#each matters as matter (matter.id)}
        <MatterCard {matter} />
      {/each}
    </div>
  {/if}
</main>

{#if showNewModal}
  <NewMatterModal
    onClose={() => (showNewModal = false)}
    onCreated={() => { showNewModal = false; refresh(); }}
  />
{/if}

<style>
  .mtr-page {
    padding: var(--lq-space-6);
    max-width: 1400px;
    margin: 0 auto;
  }

  .mtr-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: var(--lq-space-5);
    flex-wrap: wrap;
    gap: var(--lq-space-3);
  }

  .mtr-header__actions {
    display: inline-flex;
    gap: var(--lq-space-3);
    align-items: center;
  }

  .mtr-header__actions :global(.mtr-archived-toggle) {
    display: inline-flex;
    gap: var(--lq-space-2);
    align-items: center;
    cursor: pointer;
  }

  .mtr-btn-primary {
    background: var(--lq-accent);
    color: white;
    border: 0;
    border-radius: var(--lq-radius-pill);
    padding: var(--lq-space-2) var(--lq-space-4);
    cursor: pointer;
    font-weight: 500;
    font-size: 14px;
    line-height: 1.5;
  }

  .mtr-btn-primary:hover {
    opacity: 0.85;
  }

  .mtr-btn-primary:focus-visible {
    outline: 2px solid var(--lq-accent);
    outline-offset: 2px;
  }

  .mtr-page :global(.mtr-state-msg) {
    padding: var(--lq-space-4) 0;
  }

  .mtr-empty-state {
    text-align: center;
    padding: var(--lq-space-8) var(--lq-space-4);
  }

  .mtr-empty-state :global(.mtr-empty-state__copy) {
    margin-bottom: var(--lq-space-4);
  }

  .mtr-grid {
    display: grid;
    gap: var(--lq-space-4);
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  }
</style>
