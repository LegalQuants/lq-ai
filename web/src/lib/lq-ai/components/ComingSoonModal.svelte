<script context="module" lang="ts">
  /**
   * ComingSoonModal — surfaces when a user clicks a top tab whose
   * destination route hasn't shipped yet. Points at the design spec
   * so community members poking around can find the full roadmap.
   */
  import type { TabId } from '../tabs';

  const TITLE: Record<TabId, string> = {
    home: 'Home',
    chats: 'Chats',
    matters: 'Matters',
    skills: 'Skills',
    knowledge: 'Knowledge',
    playbooks: 'Playbooks',
    tabular: 'Tabular Review',
    'saved-prompts': 'Saved Prompts',
    learn: 'Learn',
    autonomous: 'Autonomous',
    admin: 'Admin'
  };

  export function copyFor(tabId: TabId, wave: string | undefined): { title: string; body: string } {
    const title = TITLE[tabId] ?? tabId;
    const body = wave
      ? `${title} is part of Wave ${wave} of the M1 frontend redesign. See the design spec for the full roadmap and what this surface will do.`
      : `${title} is planned for an upcoming wave of the M1 frontend redesign. See the design spec for what this surface will do.`;
    return { title, body };
  }
</script>

<script lang="ts">
  export let open: boolean;
  export let tabId: TabId;
  export let wave: string | undefined;
  export let onClose: () => void;

  $: ({ title, body } = copyFor(tabId, wave));

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') onClose();
  }
</script>

{#if open}
  <div
    class="lq-modal-backdrop"
    role="dialog"
    aria-modal="true"
    aria-labelledby="coming-soon-title"
    on:click={onClose}
    on:keydown={handleKeydown}
  >
    <div
      class="lq-modal"
      role="document"
      on:click|stopPropagation
    >
      <h2 id="coming-soon-title" class="lq-text-page-h">{title}</h2>
      <p class="lq-text-body" style="margin-top: var(--lq-space-3);">{body}</p>
      <p class="lq-text-caption" style="margin-top: var(--lq-space-3);">
        Design spec:
        <a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/superpowers/specs/2026-05-10-m1-frontend-design.md" target="_blank" rel="noopener noreferrer">
          docs/superpowers/specs/2026-05-10-m1-frontend-design.md
        </a>
      </p>
      <div style="margin-top: var(--lq-space-6); display: flex; justify-content: flex-end;">
        <button type="button" class="lq-btn-primary" on:click={onClose}>Got it</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .lq-modal-backdrop {
    position: fixed; inset: 0;
    background: rgba(0, 0, 0, 0.35);
    display: flex; align-items: center; justify-content: center;
    z-index: 100;
  }
  .lq-modal {
    background: var(--lq-canvas);
    border-radius: var(--lq-radius-lg);
    padding: var(--lq-space-6);
    max-width: 480px;
    width: calc(100% - 32px);
    box-shadow: 0 24px 64px rgba(0, 0, 0, 0.18);
  }
  .lq-btn-primary {
    background: var(--lq-accent); color: white;
    border: 0; border-radius: var(--lq-radius);
    padding: 8px 16px; font-size: 14px; font-weight: 500;
    cursor: pointer;
  }
  .lq-btn-primary:hover { filter: brightness(0.95); }
  .lq-btn-primary:focus-visible { outline: 2px solid var(--lq-accent); outline-offset: 2px; }
</style>
