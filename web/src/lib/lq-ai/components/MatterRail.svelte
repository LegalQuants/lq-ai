<script lang="ts">
  import type { Project, Chat } from '$lib/lq-ai/types';
  import { chatsApi } from '$lib/lq-ai/api';
  import MatterRailMetadata from './MatterRailMetadata.svelte';
  import MatterRailFiles from './MatterRailFiles.svelte';
  import MatterRailKnowledge from './MatterRailKnowledge.svelte';
  import MatterRailSkills from './MatterRailSkills.svelte';
  import { onMount } from 'svelte';
  import LqText from './shared/LqText.svelte';
  import LqTitle from './shared/LqTitle.svelte';

  export let matter: Project;
  export let activeChatId: string | undefined = undefined;
  export let onMatterUpdate: (next: Project) => void = () => {};
  export let onMatterArchived: () => void = () => {};

  let chats: Chat[] = [];
  let loadingChats = false;

  async function loadChats() {
    loadingChats = true;
    try {
      chats = await chatsApi.listAllChats({ project_id: matter.id });
    } catch (e) {
      console.error('lq-ai: failed to load matter chats', e);
    } finally {
      loadingChats = false;
    }
  }

  async function newChat() {
    try {
      const chat = await chatsApi.createChat({ project_id: matter.id });
      chats = [chat, ...chats];
      activeChatId = chat.id;
    } catch (e) {
      console.error('lq-ai: failed to create chat in matter', e);
    }
  }

  onMount(loadChats);

  // Reload chats whenever matter.id changes (e.g., navigation to a different matter).
  let prevMatterId = matter.id;
  $: if (matter && matter.id !== prevMatterId) {
    prevMatterId = matter.id;
    loadChats();
  }
</script>

<aside class="matter-rail">
  <MatterRailMetadata {matter} {onMatterUpdate} {onMatterArchived} />
  <MatterRailFiles {matter} {onMatterUpdate} />
  <MatterRailKnowledge {matter} {onMatterUpdate} />
  <MatterRailSkills {matter} {onMatterUpdate} />

  <section class="rail-section">
    <header class="rail-section-header">
      <LqTitle order={3} size="16" weight="semibold" tone="primary" class="rail-section-title">Chats</LqTitle>
      <button type="button" class="rail-btn-sm" on:click={newChat}>+ New</button>
    </header>

    {#if loadingChats}
      <LqText as="p" size="12" tone="tertiary" class="rail-empty">Loading chats…</LqText>
    {:else if chats.length === 0}
      <LqText as="p" size="12" tone="tertiary" class="rail-empty">No chats yet.</LqText>
    {:else}
      <ul class="rail-chat-list" role="listbox" aria-label="Matter chats">
        {#each chats as chat (chat.id)}
          <li role="option" aria-selected={chat.id === activeChatId}>
            <button
              type="button"
              class="rail-chat-item"
              class:rail-chat-item--active={chat.id === activeChatId}
              on:click={() => (activeChatId = chat.id)}
            >
              <LqText as="span" size="13.5" tone="primary" class="rail-chat-title">{chat.title || 'Untitled chat'}</LqText>
              <LqText as="span" size="12" tone="tertiary" class="rail-chat-date">
                {new Date(chat.updated_at ?? chat.created_at).toLocaleDateString()}
              </LqText>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </section>
</aside>

<style>
  @import '$lib/lq-ai/styles/practice.css';

  .matter-rail {
    width: 320px;
    flex-shrink: 0;
    border-right: 1px solid var(--lq-border);
    background: var(--lq-canvas);
    padding: var(--lq-space-4);
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: var(--lq-space-5);
  }

  @media (max-width: 768px) {
    .matter-rail {
      width: 280px;
    }
  }

  /* Section layout */
  .rail-section {
    display: flex;
    flex-direction: column;
    gap: var(--lq-space-2);
  }

  .rail-section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--lq-space-2);
  }

  .rail-section-header :global(.rail-section-title) {
    margin: 0;
  }

  .rail-section :global(.rail-empty) {
    padding: var(--lq-space-2) 0;
  }

  /* Small action button used in section headers */
  .rail-btn-sm {
    font-size: 12px;
    font-weight: 500;
    color: var(--lq-accent);
    background: transparent;
    border: 1px solid var(--lq-accent-border);
    border-radius: var(--lq-radius-pill);
    padding: 2px 10px;
    cursor: pointer;
    line-height: 1.6;
    white-space: nowrap;
  }

  .rail-btn-sm:hover {
    background: var(--lq-accent-soft);
  }

  .rail-btn-sm:focus-visible {
    outline: 2px solid var(--lq-accent);
    outline-offset: 2px;
  }

  /* Chat list */
  .rail-chat-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--lq-space-1);
  }

  .rail-chat-item {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
    width: 100%;
    padding: var(--lq-space-2) var(--lq-space-3);
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--lq-radius);
    cursor: pointer;
    text-align: left;
  }

  .rail-chat-item:hover {
    background: var(--lq-inset);
    border-color: var(--lq-border);
  }

  .rail-chat-item--active {
    background: var(--lq-accent-soft);
    border-color: var(--lq-accent-border);
  }

  .rail-chat-item:focus-visible {
    outline: 2px solid var(--lq-accent);
    outline-offset: 2px;
  }

  .rail-chat-item :global(.rail-chat-title) {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 100%;
  }
</style>
