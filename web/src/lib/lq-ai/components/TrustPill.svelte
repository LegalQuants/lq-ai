<script context="module" lang="ts">
  /**
   * TrustPill — small ambient-trust indicator used in the LQ.AI chrome.
   *
   * variant determines a default tone (secure→sage, tier→slate,
   * provider→sage, audit→sage, warn→amber, error→red); `tone` prop overrides.
   * Under ADR 0045 sage renders neutral, slate is governance (a neutral pill with
   * an orange dot), amber is neutral ink and red is danger.
   * `display` chooses label vs dot-only rendering for the personalization toggle.
   *
   * Marks (ADR 0045 §5: Tabler line icons, no glyphs). A warn (amber) pill lost its
   * colour, so it carries the warning icon; `lock` draws a privileged matter's lock in
   * the governance colour instead of the dot; `dot` draws a neutral status dot where
   * callers used to put "● " in the label. Every mark is aria-hidden: the label names
   * the pill.
   *
   * The toneClassFor, labelFor and markFor helpers are exported for unit testing.
   */
  export type TrustVariant = 'secure' | 'tier' | 'provider' | 'audit' | 'warn' | 'error';
  export type TrustTone = 'sage' | 'slate' | 'amber' | 'red' | 'neutral';
  export type TrustDisplay = 'label' | 'dot';
  export type TrustMark = 'lock' | 'warning' | 'dot' | null;

  const VARIANT_DEFAULT_TONE: Record<TrustVariant, TrustTone> = {
    secure: 'sage',
    tier: 'slate',
    provider: 'sage',
    audit: 'sage',
    warn: 'amber',
    error: 'red'
  };

  function toneOf(variant: TrustVariant, override: TrustTone | undefined): TrustTone {
    return override ?? VARIANT_DEFAULT_TONE[variant] ?? 'neutral';
  }

  export function toneClassFor(variant: TrustVariant, override: TrustTone | undefined): string {
    return `lq-pill-tone-${toneOf(variant, override)}`;
  }

  /** The visible text: the label, or nothing in dot mode (the mark stands in for it). */
  export function labelFor(label: string, display: TrustDisplay): string {
    if (display === 'dot') return '';
    return label;
  }

  /**
   * The leading mark. The lock and the warning icon win over the dot; slate's governance
   * dot is drawn in CSS, so slate needs no mark here except in dot mode.
   */
  export function markFor(
    variant: TrustVariant,
    override: TrustTone | undefined,
    opts: { lock?: boolean; dot?: boolean; display?: TrustDisplay } = {}
  ): TrustMark {
    if (opts.lock) return 'lock';
    if (toneOf(variant, override) === 'amber') return 'warning';
    if (opts.dot || opts.display === 'dot') return 'dot';
    return null;
  }
</script>

<script lang="ts">
  import { IconLock } from '@tabler/icons-svelte';
  import LqToneIcon from './shared/LqToneIcon.svelte';

  export let variant: TrustVariant;
  export let label: string;
  export let tone: TrustTone | undefined = undefined;
  export let display: TrustDisplay = 'label';
  export let onClick: (() => void) | undefined = undefined;
  /** A privileged matter: a governance lock instead of the dot. */
  export let lock = false;
  /** A neutral status dot before the label. */
  export let dot = false;

  $: toneClass = toneClassFor(variant, tone);
  $: rendered = labelFor(label, display);
  $: mark = markFor(variant, tone, { lock, dot, display });
</script>

<button
  type="button"
  class="lq-pill {toneClass}"
  class:lq-pill-dot={display === 'dot'}
  class:lq-pill-locked={lock}
  class:lq-pill-clickable={!!onClick}
  aria-label={label}
  on:click={onClick}
>
  {#if mark === 'lock'}
    <IconLock size={12} stroke={2} class="lq-pill-lock" aria-hidden="true" />
  {:else if mark === 'warning'}
    <LqToneIcon tone="warning" size={12} />
  {:else if mark === 'dot'}
    <span class="lq-pill-mark" aria-hidden="true"></span>
  {/if}
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
  .lq-pill-dot { padding: 4px 8px; font-size: 10px; min-height: 1.4em; }
  .lq-pill-mark { width: 7px; height: 7px; border-radius: 50%; background: currentColor; flex: none; }

  /* ADR 0045: colour means governance or error. sage (secure, provider, audit) is a
     neutral outline; slate (the tier, and privileged matters by explicit tone) is a
     neutral outline with a governance mark: a dot, or a lock for a privileged matter. */
  .lq-pill-tone-sage    { background: var(--lq-canvas); color: var(--lq-text); border-color: var(--lq-border); }
  .lq-pill-tone-slate   { background: var(--lq-canvas); color: var(--lq-text); border-color: var(--lq-border); }
  .lq-pill-tone-slate:not(.lq-pill-dot):not(.lq-pill-locked)::before { content: ''; width: 7px; height: 7px; border-radius: 50%; background: var(--lq-governance); flex: none; }
  .lq-pill-tone-slate.lq-pill-dot { color: var(--lq-governance); }
  .lq-pill :global(.lq-pill-lock) { color: var(--lq-governance); flex: none; }
  .lq-pill-tone-amber   { background: var(--lq-warn-soft);   color: var(--lq-warn);   border-color: var(--lq-warn-border); }
  .lq-pill-tone-red     { background: var(--lq-error-soft);  color: var(--lq-error);  border-color: var(--lq-error-border); }
  .lq-pill-tone-neutral { background: var(--lq-inset);       color: var(--lq-text-secondary); border-color: var(--lq-border); }

  .lq-pill-clickable:hover { opacity: 0.85; }
  .lq-pill-clickable:focus-visible { outline: 2px solid var(--lq-accent); outline-offset: 2px; }
</style>
