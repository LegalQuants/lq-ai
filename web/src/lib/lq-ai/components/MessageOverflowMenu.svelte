<script lang="ts">
  import { IconDots, IconNotes } from '@tabler/icons-svelte';
  /**
   * MessageOverflowMenu — generic ⋯ menu rendered on assistant message
   * footers (Wave D.2 Task 5.3). Composable by intent: callers pass in an
   * `onCapture` handler and toggle `captureInOverflow` to surface (or omit)
   * the "Capture as skill" item depending on whether the inline 📝 button
   * is already showing in the parent's action row.
   *
   * Trigger is hidden when no items would render — by default the inline
   * 📝 button covers the only currently-implemented action, so the overflow
   * trigger only appears when the user has demoted capture into the menu
   * (settings → "Show inline on AI messages" off). Copy markdown / Retry
   * are deferred to a future release and intentionally NOT rendered as
   * placeholder items — surfacing them as greyed-out controls reads as
   * broken UI rather than coming-soon. They land here when implemented.
   *
   * No unit tests — pure UI-state component; behavior covered by Wave 8
   * Cypress via the data-testids.
   *
   * A11y posture: this is a "disclosure widget" (expandable button group),
   * not a WAI-ARIA menu. The full menu pattern (arrow-key navigation,
   * roving tabindex, focus management) is deferred until Copy/Retry
   * placeholders wake up — track as a DE candidate. We keep `aria-expanded`
   * on the trigger because that correctly describes a disclosure.
   *
   * Notes for reviewers:
   *   - Scoped style block uses the same token vocabulary as
   *     `CaptureSkillModal.svelte` / `AttachKBModal.svelte`. There is NO
   *     `--lq-surface-tinted` token; hover uses `--lq-inset` (the
   *     subtle-surface neutral) which already shipped in `practice.css`.
   *   - Close-on-blur uses a microtask defer (requestAnimationFrame) so a
   *     click on a menu item registers BEFORE the focusout handler tears
   *     the menu down — the naive `e.relatedTarget` check fires before the
   *     button receives focus on some browsers and swallows the click.
   *   - data-testid hooks anchor Cypress (Wave 8): `lq-ai-message-overflow-trigger`
   *     and `lq-ai-message-overflow-capture`.
   */
  import { tick } from 'svelte';

  export let onCapture: () => void;
  export let captureInOverflow = false;
  export let captureDisabled = false;

  let open = false;
  let rootEl: HTMLDivElement;
  let triggerEl: HTMLButtonElement;

  // Currently the only implemented item is Capture (gated by
  // `captureInOverflow`). When that's off too, the menu would only contain
  // future-release items, so we hide the trigger entirely rather than
  // present an empty / "broken" menu.
  $: hasItems = captureInOverflow;

  function toggle(): void {
    open = !open;
  }

  /**
   * On focusout we defer a frame: clicking a menu button briefly removes
   * focus from the previously focused element BEFORE the new focus target
   * registers, so `relatedTarget` can be `null` even when the click landed
   * inside the menu. Re-checking `document.activeElement` after the next
   * paint avoids the false-positive close. Falls back to immediate close
   * when focus genuinely left the menu.
   */
  async function handleFocusout(): Promise<void> {
    await tick();
    requestAnimationFrame(() => {
      if (!rootEl) return;
      if (!rootEl.contains(document.activeElement)) {
        open = false;
      }
    });
  }

  function handleKeydown(e: KeyboardEvent): void {
    if (open && e.key === 'Escape') {
      open = false;
      triggerEl?.focus();
    }
  }

  function handleCapture(): void {
    open = false;
    // Briefly restore focus to the trigger before the modal grabs it.
    // For future sync menuitems (Copy/Retry), focus correctly returns to
    // the trigger and no follow-up wiring is needed.
    triggerEl?.focus();
    onCapture();
  }
</script>

<svelte:window on:keydown={handleKeydown} />

{#if hasItems}
  <!-- svelte-ignore a11y-no-static-element-interactions -->
  <div class="overflow" bind:this={rootEl} on:focusout={handleFocusout}>
    <button
      type="button"
      class="trigger"
      aria-label="More actions"
      aria-expanded={open}
      data-testid="lq-ai-message-overflow-trigger"
      bind:this={triggerEl}
      on:click={toggle}
    ><IconDots size={16} stroke={1.75} aria-hidden="true" /></button>
    {#if open}
      <ul class="menu">
        {#if captureInOverflow}
          <li>
            <button
              type="button"
              disabled={captureDisabled}
              data-testid="lq-ai-message-overflow-capture"
              on:click={handleCapture}
            ><IconNotes size={14} stroke={1.75} aria-hidden="true" /> Capture as skill</button>
          </li>
        {/if}
      </ul>
    {/if}
  </div>
{/if}

<style>
  @import '$lib/lq-ai/styles/practice.css';

  .overflow {
    position: relative;
    display: inline-block;
  }

  .trigger {
    background: transparent;
    border: 0;
    padding: 4px 8px;
    cursor: pointer;
    color: var(--lq-text-tertiary);
    font-size: 16px;
    line-height: 1;
    border-radius: var(--lq-radius-pill);
  }

  .trigger:hover {
    background: var(--lq-inset);
    color: var(--lq-text-secondary);
  }

  .menu {
    list-style: none;
    padding: 4px 0;
    margin: 0;
    position: absolute;
    right: 0;
    top: 100%;
    background: var(--lq-canvas);
    border: 1px solid var(--lq-border);
    border-radius: var(--lq-radius);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
    min-width: 180px;
    z-index: 10;
  }

  .menu button {
    width: 100%;
    text-align: left;
    padding: 6px 12px;
    background: transparent;
    border: 0;
    font-size: 14px;
    cursor: pointer;
    color: inherit;
    font-family: inherit;
  }

  .menu button:hover:not(:disabled) {
    background: var(--lq-inset);
  }

  .menu button:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
</style>
