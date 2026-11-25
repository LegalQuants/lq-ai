<script lang="ts">
  import TrustPill from './TrustPill.svelte';
  import LqText from './shared/LqText.svelte';
  // Tier is shown as static "default" on the dashboard.
  // Per-message dynamic tier lives in AmbientFooter (Wave A).
  // The /inference/current-tier endpoint requires provider + model params that
  // are not cached at dashboard-load time — pragmatic static fallback here.
  // V2-FALLBACK: wire to inferenceTierApi.getCurrentTier() once provider/model
  // are persisted in the preferences store or a dedicated endpoint exposes
  // a session-less "last used" tier.
</script>

<section
  style="
    background: var(--lq-inset-secure);
    border: 1px solid var(--lq-border);
    border-radius: var(--lq-radius-lg);
    padding: var(--lq-space-4);
    margin-bottom: var(--lq-space-6);
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--lq-space-3);
  "
>
  <div>
    <LqText as="p" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide">Your data</LqText>
    <LqText as="p" size="14" tone="primary" style="margin-top: var(--lq-space-1);">
      In your firm's stack · audit on · tier: default
    </LqText>
  </div>
  <div style="display: inline-flex; gap: var(--lq-space-2); align-items: center;">
    <TrustPill variant="secure" label="● self-hosted" />
    <LqText
      as="a"
      size="14"
      tone="governance"
      href="/lq-ai/trust"
      style="text-decoration: none;"
    >View detail →</LqText>
  </div>
</section>
