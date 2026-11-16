<script context="module" lang="ts">
  /**
   * TrustPill — small ambient-trust indicator used in the LQ.AI chrome.
   *
   * variant determines a default tone (secure→sage, tier→slate,
   * provider→sage, audit→sage, warn→amber, error→red); `tone` prop overrides.
   * `display` chooses label vs dot-only rendering for the personalization toggle.
   *
   * The toneClassFor + labelFor helpers are exported for unit testing.
   */
  export type TrustVariant = 'secure' | 'tier' | 'provider' | 'audit' | 'warn' | 'error';
  export type TrustTone = 'sage' | 'slate' | 'amber' | 'red' | 'neutral';
  export type TrustDisplay = 'label' | 'dot';

  const VARIANT_DEFAULT_TONE: Record<TrustVariant, TrustTone> = {
    secure: 'sage',
    tier: 'slate',
    provider: 'sage',
    audit: 'sage',
    warn: 'amber',
    error: 'red'
  };

  export function toneClassFor(variant: TrustVariant, override: TrustTone | undefined): string {
    const tone = override ?? VARIANT_DEFAULT_TONE[variant] ?? 'neutral';
    return `lq-pill-tone-${tone}`;
  }

  export function labelFor(label: string, display: TrustDisplay): string {
    if (display === 'dot') return '●';
    return label;
  }
</script>

<script lang="ts">
  export let variant: TrustVariant;
  export let label: string;
  export let tone: TrustTone | undefined = undefined;
  export let display: TrustDisplay = 'label';
  export let onClick: (() => void) | undefined = undefined;

  $: toneClass = toneClassFor(variant, tone);
  $: rendered = labelFor(label, display);
</script>

<button
  type="button"
  class="lq-pill {toneClass}"
  class:lq-pill-dot={display === 'dot'}
  class:lq-pill-clickable={!!onClick}
  aria-label={label}
  on:click={onClick}
>
  {rendered}
</button>

<style>
  .lq-pill {
    display: inline-flex;
    align-items: center;
    gap: var(--lq-space-1);
    padding: 2px 10px;
    border-radius: var(--lq-radius-pill);
    font-size: 12px;
    font-weight: 500;
    line-height: 1.4;
    border: 1px solid transparent;
    background: transparent;
    cursor: default;
  }
  .lq-pill-clickable { cursor: pointer; }
  .lq-pill-dot { padding: 4px 8px; font-size: 10px; }

  .lq-pill-tone-sage    { background: var(--lq-accent-soft); color: var(--lq-accent); border-color: var(--lq-accent-border); }
  .lq-pill-tone-slate   { background: var(--lq-tier-soft);   color: var(--lq-tier);   border-color: var(--lq-tier-border); }
  .lq-pill-tone-amber   { background: var(--lq-warn-soft);   color: var(--lq-warn);   border-color: var(--lq-warn-border); }
  .lq-pill-tone-red     { background: var(--lq-error-soft);  color: var(--lq-error);  border-color: var(--lq-error-border); }
  .lq-pill-tone-neutral { background: var(--lq-inset);       color: var(--lq-text-secondary); border-color: var(--lq-border); }

  .lq-pill-clickable:hover { opacity: 0.85; }
  .lq-pill-clickable:focus-visible { outline: 2px solid var(--lq-accent); outline-offset: 2px; }
</style>
