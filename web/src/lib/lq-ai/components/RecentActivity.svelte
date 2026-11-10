<script lang="ts">
  import { onMount } from 'svelte';
  import { chatsApi, projectsApi } from '$lib/lq-ai/api';
  import type { Chat, Project } from '$lib/lq-ai/types';
  import LqText from './shared/LqText.svelte';

  let chats: Chat[] = [];
  let loadingChats = true;
  let errorChats = false;

  let matters: Project[] = [];
  let loadingMatters = true;

  // Keep the old `loading` / `error` names alive for the chats section
  // (template references them via the new aliases below; aliases are local).
  $: loading = loadingChats;
  $: error = errorChats;

  onMount(async () => {
    // Chats
    try {
      // /chats/search requires minLength=1 for q; use listChats instead
      // for the recent-activity view which needs no query term.
      const page = await chatsApi.listChats({ limit: 5 });
      chats = page.items;
    } catch {
      errorChats = true;
    } finally {
      loadingChats = false;
    }

    // Matters — silent error: RecentActivity should never break the dashboard
    try {
      const all = await projectsApi.listProjects({ archived: false });
      matters = all.slice(0, 5);
    } catch {
      // fall through — matters stays []
    } finally {
      loadingMatters = false;
    }
  });

  function formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }
</script>

<section data-testid="lq-ai-recent-activity" aria-busy={loadingChats || loadingMatters} style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--lq-space-4); margin-bottom: var(--lq-space-6);">
  <!-- Recent chats -->
  <div class="activity-card">
    <LqText as="p" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" style="margin-bottom: var(--lq-space-3);">Recent chats</LqText>

    {#if loading}
      <LqText as="p" size="13.5" tone="secondary">Loading…</LqText>
    {:else if error}
      <LqText as="p" size="13.5" tone="tertiary">Could not load recent chats.</LqText>
    {:else if chats.length === 0}
      <LqText as="p" size="13.5" tone="tertiary">No chats yet. <a href="/lq-ai/chats" style="color: var(--lq-accent); text-decoration: underline;">Start one →</a></LqText>
    {:else}
      <ul class="chat-list">
        {#each chats as chat (chat.id)}
          <li>
            <a href="/lq-ai/chats" class="chat-row">
              <LqText as="span" size="13.5" class="chat-title">{chat.title || 'Untitled chat'}</LqText>
              <LqText as="span" size="12" tone="tertiary" class="chat-date">{formatDate(chat.updated_at)}</LqText>
            </a>
          </li>
        {/each}
      </ul>
      <LqText as="a" size="13.5" tone="accent" href="/lq-ai/chats" class="view-all">View all chats →</LqText>
    {/if}
  </div>

  <!-- Recent matters -->
  <div class="activity-card">
    <LqText as="p" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" style="margin-bottom: var(--lq-space-3);">Recent matters</LqText>

    {#if loadingMatters}
      <LqText as="p" size="13.5" tone="secondary">Loading…</LqText>
    {:else if matters.length === 0}
      <LqText as="p" size="13.5" tone="tertiary">No matters yet. <a href="/lq-ai/matters" style="color: var(--lq-accent); text-decoration: underline;">+ Start a matter</a></LqText>
    {:else}
      <ul class="chat-list">
        {#each matters as matter (matter.id)}
          <li>
            <a href="/lq-ai/matters/{matter.id}" class="chat-row">
              <LqText as="span" size="13.5" class="chat-title">{matter.name}</LqText>
              <LqText as="span" size="12" tone="tertiary" class="chat-date">{formatDate(matter.updated_at)}</LqText>
            </a>
          </li>
        {/each}
      </ul>
      <LqText as="a" size="13.5" tone="accent" href="/lq-ai/matters" class="view-all">View all matters →</LqText>
    {/if}
  </div>
</section>

<style>
  .activity-card {
    background: var(--lq-canvas);
    border: 1px solid var(--lq-border);
    border-radius: var(--lq-radius-lg);
    padding: var(--lq-space-4);
  }

  .chat-list {
    list-style: none;
    margin: 0 0 var(--lq-space-3) 0;
    padding: 0;
  }

  .chat-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--lq-space-2);
    padding: var(--lq-space-2) 0;
    border-bottom: 1px solid var(--lq-border);
    text-decoration: none;
    color: var(--lq-text);
  }
  .chat-list li:last-child .chat-row { border-bottom: none; }
  .chat-row:hover :global(.chat-title) { color: var(--lq-accent); }

  .chat-row :global(.chat-title) {
    flex: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--lq-text);
  }

  .chat-row :global(.chat-date) {
    flex-shrink: 0;
  }

  .activity-card :global(.view-all) {
    text-decoration: none;
  }
  .activity-card :global(.view-all:hover) { text-decoration: underline; }

  @media (max-width: 640px) {
    section {
      grid-template-columns: 1fr;
    }
  }
</style>
