<script lang="ts">
  import { IconX } from '@tabler/icons-svelte';
  import { filesApi, projectsApi } from '$lib/lq-ai/api';
  import type { FileMeta, Project } from '$lib/lq-ai/types';
  import { onMount } from 'svelte';
  import LqText from './shared/LqText.svelte';
  import LqTitle from './shared/LqTitle.svelte';

  export let matter: Project;
  export let onMatterUpdate: (next: Project) => void = () => {};

  // Resolved metadata for currently-attached files
  let attachedFiles: FileMeta[] = [];
  let loadingAttached = false;

  // Picker state
  let pickerOpen = false;
  let availableFiles: FileMeta[] = [];
  let loadingAvailable = false;
  let attachingId: string | null = null;
  let detachingId: string | null = null;
  let attachError: string | null = null;

  async function loadAttachedFiles() {
    const ids = matter.attached_file_ids ?? [];
    if (ids.length === 0) {
      attachedFiles = [];
      return;
    }
    loadingAttached = true;
    try {
      const results = await Promise.all(
        ids.map((id) => filesApi.getFile(id).catch(() => null))
      );
      attachedFiles = results.filter((f): f is FileMeta => f !== null);
    } catch (e) {
      console.error('lq-ai: failed to load attached files', e);
    } finally {
      loadingAttached = false;
    }
  }

  async function openPicker() {
    attachError = null;
    pickerOpen = true;
    loadingAvailable = true;
    try {
      // listFiles is not exposed directly but we can list files by owner_id=me.
      // The API supports GET /api/v1/files?owner_id=me via query params.
      // We use a direct apiRequest since filesApi doesn't export listFiles.
      // However, the files.ts API does not have a listFiles function — fall
      // back to apiRequest from the client.
      const { apiRequest } = await import('$lib/lq-ai/api/client');
      const all = await apiRequest<FileMeta[]>('/files?owner_id=me');
      const attachedIds = new Set(matter.attached_file_ids ?? []);
      availableFiles = all.filter((f) => !attachedIds.has(f.id));
    } catch (e) {
      console.error('lq-ai: failed to load available files', e);
      availableFiles = [];
    } finally {
      loadingAvailable = false;
    }
  }

  function closePicker() {
    pickerOpen = false;
    availableFiles = [];
    attachError = null;
  }

  async function attachFile(file: FileMeta) {
    attachError = null;
    attachingId = file.id;
    try {
      const updated = await projectsApi.attachFile(matter.id, file.id);
      onMatterUpdate(updated);
      // Reflect in local lists
      attachedFiles = [...attachedFiles, file];
      availableFiles = availableFiles.filter((f) => f.id !== file.id);
    } catch (e) {
      attachError = e instanceof Error ? e.message : 'Failed to attach file.';
    } finally {
      attachingId = null;
    }
  }

  async function detachFile(file: FileMeta) {
    attachError = null;
    detachingId = file.id;
    try {
      const updated = await projectsApi.detachFile(matter.id, file.id);
      onMatterUpdate(updated);
      attachedFiles = attachedFiles.filter((f) => f.id !== file.id);
    } catch (e) {
      attachError = e instanceof Error ? e.message : 'Failed to detach file.';
    } finally {
      detachingId = null;
    }
  }

  function formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  // Reload attached files whenever the matter's attached_file_ids change.
  $: matter.attached_file_ids, loadAttachedFiles();

  onMount(loadAttachedFiles);
</script>

<section class="mrf-section" data-testid="matter-rail-files">
  <header class="mrf-header">
    <LqTitle order={3} size="16" weight="semibold" tone="primary" class="mrf-title">Files</LqTitle>
    <button
      type="button"
      class="mrf-btn-attach"
      on:click={pickerOpen ? closePicker : openPicker}
      aria-expanded={pickerOpen}
      aria-controls="mrf-picker"
    >
      {pickerOpen ? 'Done' : '+ Attach'}
    </button>
  </header>

  {#if attachError}
    <p class="mrf-error" role="alert">{attachError}</p>
  {/if}

  {#if loadingAttached}
    <LqText as="p" size="12" tone="tertiary" class="mrf-empty">Loading files…</LqText>
  {:else if attachedFiles.length === 0 && !pickerOpen}
    <LqText as="p" size="12" tone="tertiary" class="mrf-empty">No files attached.</LqText>
  {:else}
    <ul class="mrf-file-list">
      {#each attachedFiles as file (file.id)}
        <li class="mrf-file-row">
          <LqText as="span" size="13.5" tone="primary" class="mrf-file-name" title={file.filename}>{file.filename}</LqText>
          <LqText as="span" size="12" tone="tertiary" class="mrf-file-size">{formatBytes(file.size_bytes)}</LqText>
          <button
            type="button"
            class="mrf-btn-detach"
            aria-label="Detach {file.filename}"
            on:click={() => detachFile(file)}
            disabled={detachingId === file.id}
          >
            {#if detachingId === file.id}…{:else}<IconX size={14} stroke={1.75} aria-hidden="true" />{/if}
          </button>
        </li>
      {/each}
    </ul>
  {/if}

  {#if pickerOpen}
    <div id="mrf-picker" class="mrf-picker" role="listbox" aria-label="Available files to attach">
      {#if loadingAvailable}
        <LqText as="p" size="12" tone="tertiary" class="mrf-empty">Loading your files…</LqText>
      {:else if availableFiles.length === 0}
        <LqText as="p" size="12" tone="tertiary" class="mrf-empty">No files available to attach.</LqText>
      {:else}
        <ul class="mrf-available-list">
          {#each availableFiles as file (file.id)}
            <li role="option" aria-selected="false">
              <button
                type="button"
                class="mrf-available-item"
                on:click={() => attachFile(file)}
                disabled={attachingId === file.id}
              >
                <LqText as="span" size="13.5" tone="primary" class="mrf-file-name">{file.filename}</LqText>
                <LqText as="span" size="12" tone="tertiary" class="mrf-file-size">{formatBytes(file.size_bytes)}</LqText>
                {#if attachingId === file.id}
                  <LqText as="span" size="12" tone="accent" class="mrf-attaching">Attaching…</LqText>
                {/if}
              </button>
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}
</section>

<style>
  @import '$lib/lq-ai/styles/practice.css';

  .mrf-section {
    display: flex;
    flex-direction: column;
    gap: var(--lq-space-2);
  }

  .mrf-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--lq-space-2);
  }

  .mrf-header :global(.mrf-title) {
    margin: 0;
  }

  .mrf-section :global(.mrf-empty) {
    padding: var(--lq-space-1) 0;
  }

  .mrf-error {
    font-size: 12px;
    color: var(--lq-error);
    background: var(--lq-error-soft);
    border: 1px solid var(--lq-error-border);
    border-radius: var(--lq-radius);
    padding: var(--lq-space-1) var(--lq-space-2);
    margin: 0;
  }

  /* Attach / done button */
  .mrf-btn-attach {
    font-size: 12px;
    font-weight: 500;
    color: var(--lq-accent);
    background: transparent;
    border: 1px solid var(--lq-accent-border);
    border-radius: var(--lq-radius-pill);
    padding: 2px 10px;
    cursor: pointer;
    white-space: nowrap;
  }

  .mrf-btn-attach:hover {
    background: var(--lq-accent-soft);
  }

  .mrf-btn-attach:focus-visible {
    outline: 2px solid var(--lq-accent);
    outline-offset: 2px;
  }

  /* Attached file list */
  .mrf-file-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--lq-space-1);
  }

  .mrf-file-row {
    display: flex;
    align-items: center;
    gap: var(--lq-space-2);
    padding: var(--lq-space-1) var(--lq-space-2);
    background: var(--lq-inset);
    border: 1px solid var(--lq-border);
    border-radius: var(--lq-radius);
  }

  .mrf-section :global(.mrf-file-name) {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .mrf-section :global(.mrf-file-size) {
    white-space: nowrap;
    flex-shrink: 0;
  }

  .mrf-btn-detach {
    font-size: 14px;
    font-weight: 500;
    color: var(--lq-text-tertiary);
    background: transparent;
    border: 0;
    cursor: pointer;
    padding: 0 2px;
    line-height: 1;
    flex-shrink: 0;
  }

  .mrf-btn-detach:hover:not(:disabled) {
    color: var(--lq-error);
  }

  .mrf-btn-detach:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .mrf-btn-detach:focus-visible {
    outline: 2px solid var(--lq-accent);
    outline-offset: 2px;
  }

  /* Picker panel */
  .mrf-picker {
    background: var(--lq-inset);
    border: 1px solid var(--lq-border);
    border-radius: var(--lq-radius-lg);
    padding: var(--lq-space-3);
    display: flex;
    flex-direction: column;
    gap: var(--lq-space-1);
    max-height: 200px;
    overflow-y: auto;
  }

  .mrf-available-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--lq-space-1);
  }

  .mrf-available-item {
    display: flex;
    align-items: center;
    gap: var(--lq-space-2);
    width: 100%;
    padding: var(--lq-space-1) var(--lq-space-2);
    background: var(--lq-canvas);
    border: 1px solid var(--lq-border);
    border-radius: var(--lq-radius);
    cursor: pointer;
    text-align: left;
  }

  .mrf-available-item:hover:not(:disabled) {
    border-color: var(--lq-accent-border);
    background: var(--lq-accent-soft);
  }

  .mrf-available-item:disabled {
    opacity: 0.65;
    cursor: not-allowed;
  }

  .mrf-available-item:focus-visible {
    outline: 2px solid var(--lq-accent);
    outline-offset: 2px;
  }

  .mrf-available-item :global(.mrf-attaching) {
    flex-shrink: 0;
  }
</style>
