<script context="module" lang="ts">
  import type { Project } from '../types';

  /** Derive badge visibility flags from a Project. Exported for unit tests. */
  export function matterBadges(matter: Project): {
    showPrivileged: boolean;
    showTier: boolean;
    tierLabel: string | null;
    isArchived: boolean;
    fileCount: number;
    skillCount: number;
  } {
    // Under PRD §1.5.2, lower tier number = stronger security.
    // "Tier N or stronger" means the floor is N; tiers 1..N are all allowed.
    const t = matter.minimum_inference_tier;
    return {
      showPrivileged: matter.privileged,
      showTier: t != null,
      tierLabel: t != null ? (t === 1 ? 'Tier 1 only' : `Tier ${t} or stronger`) : null,
      isArchived: !!matter.archived_at,
      fileCount: matter.attached_file_ids?.length ?? 0,
      skillCount: matter.attached_skill_names?.length ?? 0
    };
  }
</script>

<script lang="ts">
  import TrustPill from './TrustPill.svelte';
  import LqText from './shared/LqText.svelte';
  import LqTitle from './shared/LqTitle.svelte';

  export let matter: Project;

  $: badges = matterBadges(matter);
</script>

<a
  href="/lq-ai/matters/{matter.id}"
  class="matter-card"
  class:matter-card--archived={badges.isArchived}
  aria-label="Open matter: {matter.name}"
>
  <div class="matter-card__body">
    <div class="matter-card__title-row">
      <LqTitle order={3} size="16" weight="semibold" tone="primary" class="matter-card__title">{matter.name}</LqTitle>
      {#if badges.isArchived}
        <span class="matter-card__archived-badge">Archived</span>
      {/if}
    </div>

    <LqText as="p" size="14" tone="secondary" class="matter-card__description">
      {matter.description ?? '(no description)'}
    </LqText>

    {#if badges.showPrivileged || badges.showTier}
      <div class="matter-card__badges">
        {#if badges.showPrivileged}
          <TrustPill variant="secure" tone="slate" lock label="Privileged" />
        {/if}
        {#if badges.showTier && badges.tierLabel}
          <TrustPill variant="tier" label={badges.tierLabel} />
        {/if}
      </div>
    {/if}
  </div>

  <div class="matter-card__footer">
    <LqText as="span" size="12" tone="tertiary" class="matter-card__stats">
      {badges.fileCount} {badges.fileCount === 1 ? 'file' : 'files'} · {badges.skillCount} {badges.skillCount === 1 ? 'skill' : 'skills'}
    </LqText>
    <span class="matter-card__open" aria-hidden="true">Open →</span>
  </div>
</a>

<style>
  .matter-card {
    display: flex;
    flex-direction: column;
    background: var(--lq-canvas);
    border: 1px solid var(--lq-border);
    border-radius: var(--lq-radius-lg);
    padding: var(--lq-space-5);
    text-decoration: none;
    color: inherit;
    cursor: pointer;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
    min-height: 160px;
  }

  .matter-card:hover {
    border-color: var(--lq-accent-border);
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  }

  .matter-card:focus-visible {
    outline: 2px solid var(--lq-accent);
    outline-offset: 2px;
  }

  .matter-card--archived {
    opacity: 0.65;
  }

  .matter-card__body {
    flex: 1;
  }

  .matter-card__title-row {
    display: flex;
    align-items: flex-start;
    gap: var(--lq-space-2);
    margin-bottom: var(--lq-space-2);
  }

  .matter-card__title-row :global(.matter-card__title) {
    margin: 0;
    /* 2-line clamp */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    flex: 1;
  }

  .matter-card__archived-badge {
    font-size: 11px;
    font-weight: 500;
    color: var(--lq-text-tertiary);
    background: var(--lq-inset);
    border: 1px solid var(--lq-border);
    border-radius: var(--lq-radius-pill);
    padding: 2px 8px;
    white-space: nowrap;
    flex-shrink: 0;
  }

  .matter-card__body :global(.matter-card__description) {
    /* 3-line clamp */
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    margin: 0 0 var(--lq-space-3);
  }

  .matter-card__badges {
    display: flex;
    flex-wrap: wrap;
    gap: var(--lq-space-2);
    margin-bottom: var(--lq-space-3);
  }

  .matter-card__footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding-top: var(--lq-space-3);
    border-top: 1px solid var(--lq-border);
    margin-top: auto;
  }

  .matter-card__open {
    font-size: 13px;
    font-weight: 500;
    color: var(--lq-accent);
  }
</style>
