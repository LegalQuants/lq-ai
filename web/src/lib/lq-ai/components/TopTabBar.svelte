<script context="module" lang="ts">
  import { TABS, isTabVisible, type TabDef, type User, type TabVisibilityOpts } from '../tabs';

  export type TopTabBarUser = User;

  export function visibleTabsFor(user: User | null, opts: TabVisibilityOpts = {}): TabDef[] {
    return TABS.filter((t) => isTabVisible(t.id, user, opts));
  }
</script>

<script lang="ts">
  import { goto } from '$app/navigation';
  import { activeTabFor, isTabAvailable, type TabId } from '../tabs';
  import { preferences } from '$lib/lq-ai/stores/preferences';
  import ComingSoonModal from './ComingSoonModal.svelte';

  export let user: User | null;
  export let pathname: string;

  $: tabs = visibleTabsFor(user, { autonomousEnabled: $preferences.autonomous_enabled });
  $: active = activeTabFor(pathname);

  let comingSoonOpen = false;
  let comingSoonTabId: TabId = 'home';
  let comingSoonWave: string | undefined;

  function handleTabClick(tabId: TabId, route: string, wave: string | undefined) {
    if (isTabAvailable(tabId)) {
      goto(route);
    } else {
      comingSoonTabId = tabId;
      comingSoonWave = wave;
      comingSoonOpen = true;
    }
  }

  function handleTabKeydown(e: KeyboardEvent, idx: number) {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault();
      const delta = e.key === 'ArrowRight' ? 1 : -1;
      const next = (idx + delta + tabs.length) % tabs.length;
      const buttons = (e.currentTarget as HTMLElement)
        .closest('ul')
        ?.querySelectorAll<HTMLButtonElement>('button[role="tab"]');
      buttons?.[next]?.focus();
    }
  }
</script>

<nav class="lq-tabbar" aria-label="Primary">
  <ul role="tablist">
    {#each tabs as tab, tabIndex (tab.id)}
      <li role="presentation">
        <button
          type="button"
          role="tab"
          aria-selected={active === tab.id}
          aria-controls="lq-main"
          class="lq-tab"
          class:lq-tab-active={active === tab.id}
          class:lq-tab-unavailable={!isTabAvailable(tab.id)}
          on:click={() => handleTabClick(tab.id, tab.route, tab.shipsInWave)}
          on:keydown={(e) => handleTabKeydown(e, tabIndex)}
        >
          <span class="lq-tab-icon" aria-hidden="true">{tab.icon}</span>
          <span class="lq-tab-label">{tab.label}</span>
        </button>
      </li>
    {/each}
  </ul>
</nav>

<ComingSoonModal
  open={comingSoonOpen}
  tabId={comingSoonTabId}
  wave={comingSoonWave}
  onClose={() => (comingSoonOpen = false)}
/>

<style>
  .lq-tabbar { border-bottom: 1px solid var(--lq-border); padding: 0 var(--lq-space-4); }
  .lq-tabbar ul { display: flex; gap: var(--lq-space-4); margin: 0; padding: 0; list-style: none; }
  .lq-tab {
    display: inline-flex; align-items: center; gap: var(--lq-space-1);
    background: transparent; border: 0; padding: var(--lq-space-3) var(--lq-space-1);
    font-size: 14px; font-weight: 500; color: var(--lq-text-secondary);
    cursor: pointer; border-bottom: 2px solid transparent;
    transition: color 0.12s ease, border-color 0.12s ease;
  }
  .lq-tab:hover { color: var(--lq-text); }
  .lq-tab-active { color: var(--lq-accent); border-bottom-color: var(--lq-accent); }
  .lq-tab-unavailable { color: var(--lq-text-tertiary); }
  .lq-tab:focus-visible { outline: 2px solid var(--lq-accent); outline-offset: 2px; border-radius: var(--lq-radius-sm); }
  .lq-tab-icon { font-size: 14px; }
</style>
