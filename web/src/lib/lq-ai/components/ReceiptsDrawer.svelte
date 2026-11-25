<script context="module" lang="ts">
  const STORAGE_KEY_PREFIX = 'lq_ai_receipts_drawer_open_';
  export const POLL_INTERVAL_MS = 5000;

  /** Build the localStorage key for a chat's drawer-open state. */
  export function storageKeyForChat(chatId: string): string {
    return `${STORAGE_KEY_PREFIX}${chatId}`;
  }

  /** Read persisted open-state for a chat. */
  export function readPersistedOpen(chatId: string, storage?: Storage): boolean {
    const store = storage ?? (typeof localStorage !== 'undefined' ? localStorage : null);
    if (!store) return false;
    return store.getItem(storageKeyForChat(chatId)) === 'true';
  }

  /** Write persisted open-state for a chat. */
  export function writePersistedOpen(chatId: string, open: boolean, storage?: Storage): void {
    const store = storage ?? (typeof localStorage !== 'undefined' ? localStorage : null);
    if (!store) return;
    store.setItem(storageKeyForChat(chatId), open ? 'true' : 'false');
  }
</script>

<script lang="ts">
  import { onDestroy } from 'svelte';
  import ReceiptsList from './ReceiptsList.svelte';
  import type { ReceiptEvent, ReceiptEventKind } from '../api/receipts';
  import { listChatReceipts, exportChatReceiptsJsonl } from '../api/receipts';
  import { triggerJsonlDownload } from '../lib/receiptsExport';

  export let open: boolean = false;
  export let chatId: string;
  export let onClose: () => void = () => {};
  /**
   * True inside the shell's right sidebar (developer switch, Annex B P1.4):
   * a section of that sidebar instead of its own complementary landmark,
   * at the sidebar's width.
   */
  export let embedded: boolean = false;

  let events: ReceiptEvent[] = [];
  let selectedKinds: ReceiptEventKind[] = [
    'message', 'inference', 'audit', 'skill', 'retrieval', 'error'
  ];
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let loading = false;
  let exporting = false;
  let error: string | null = null;

  async function fetchReceipts() {
    if (!open || !chatId) return;
    loading = true;
    try {
      events = await listChatReceipts(chatId);
      error = null;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loading = false;
    }
  }

  function startPolling() {
    if (pollTimer !== null) return;
    pollTimer = setInterval(fetchReceipts, POLL_INTERVAL_MS);
  }

  function stopPolling() {
    if (pollTimer !== null) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function handleExport() {
    if (exporting) return;
    exporting = true;
    try {
      const { jsonl, filename } = await exportChatReceiptsJsonl(chatId);
      triggerJsonlDownload(jsonl, filename);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      exporting = false;
    }
  }

  $: if (open && chatId) {
    writePersistedOpen(chatId, true);
    fetchReceipts();
    startPolling();
  } else {
    if (chatId) writePersistedOpen(chatId, false);
    stopPolling();
  }

  onDestroy(() => stopPolling());
</script>

{#if open}
<svelte:element
  this={embedded ? 'section' : 'aside'}
  class="receipts-drawer"
  class:embedded
  aria-label="Receipts drawer"
>
  <header>
    <span class="title">📜 Receipts</span>
    <button class="close" on:click={onClose} aria-label="Close receipts drawer">×</button>
  </header>

  {#if error}
    <div class="error" data-testid="error-banner">{error}</div>
  {/if}

  <ReceiptsList
    {events}
    {selectedKinds}
    onFilterChange={(k) => (selectedKinds = k)}
  />

  <footer>
    <button
      class="export"
      on:click={handleExport}
      disabled={exporting || events.length === 0}
      data-testid="export-jsonl"
    >
      {exporting ? 'Exporting…' : '⤓ Export JSONL'}
    </button>
  </footer>
</svelte:element>
{/if}

<style>
  .receipts-drawer {
    width: 240px;
    background: var(--lq-canvas);
    border-left: 1px solid var(--lq-border);
    padding: 10px 8px;
    display: flex;
    flex-direction: column;
    height: 100%;
  }
  .receipts-drawer.embedded {
    width: auto;
    height: auto;
    border-left: 0;
    border-top: 1px solid var(--lq-border);
    padding: 10px 12px;
  }
  header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
  .title { font-weight: 600; font-size: 11px; color: var(--lq-text); }
  .close { background: transparent; border: 0; color: var(--lq-text-tertiary); cursor: pointer; font-size: 16px; padding: 0 4px; }
  .error { background: var(--lq-danger-soft); color: var(--lq-danger); padding: 4px 6px; border-radius: 4px; font-size: 10px; margin-bottom: 4px; }
  footer { padding-top: 6px; border-top: 1px solid var(--lq-border); margin-top: 6px; }
  .export {
    background: transparent; border: 1px solid var(--lq-border-strong);
    padding: 3px 6px; border-radius: var(--lq-radius-pill); color: var(--lq-text-secondary);
    font-size: 9px; cursor: pointer; width: 100%;
  }
  .export:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
