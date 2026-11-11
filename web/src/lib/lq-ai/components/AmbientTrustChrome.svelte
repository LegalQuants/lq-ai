<script lang="ts">
  /**
   * AmbientTrustChrome — right side of the top bar.
   *
   * At Wave A: self-hosted pill + ⌘K hint. Tier pill is rendered by the
   * Workspace shell in Wave C (it's chat-scoped, not global). User menu
   * stays where the existing layout puts it.
   *
   * Personalization toggle "Trust pills → Dots" (spec §4.3) plumbs through
   * the `display` prop in a later wave; Wave A always renders labels.
   */
  import TrustPill from './TrustPill.svelte';
</script>

<div class="lq-chrome">
  <TrustPill variant="secure" dot label="self-hosted" />
  <span class="lq-kbd" aria-hidden="true">⌘K</span>
</div>

<style>
  .lq-chrome { display: inline-flex; align-items: center; gap: var(--lq-space-2); }
  .lq-kbd {
    font-family: var(--lq-font-sans);
    font-size: 11px; color: var(--lq-text-tertiary);
    border: 1px solid var(--lq-border); border-radius: var(--lq-radius-sm);
    padding: 1px 6px; background: var(--lq-inset);
  }
</style>
