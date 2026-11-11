<script lang="ts">
  /**
   * AmbientFooter — bottom-of-chat reassurance bar.
   *
   * Renders provider + tier. The static "audit on" pill was removed for
   * v0.1.0 — there's no /api/v1/trust/audit-health endpoint behind it,
   * so the pill was a dishonest signal. When the backend ships an
   * audit-health derivation we can render a real status here.
   */
  import TrustPill from './TrustPill.svelte';

  export let provider: string;
  export let tier: string;
</script>

<footer class="lq-footer" aria-label="Chat status">
  <TrustPill variant="provider" dot label="{provider} · {tier}" />
</footer>

<style>
  .lq-footer {
    display: flex; align-items: center; gap: var(--lq-space-3);
    padding: var(--lq-space-2) var(--lq-space-4);
    border-top: 1px solid var(--lq-border);
    background: var(--lq-inset);
    font-size: 12px;
  }
</style>
