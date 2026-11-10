<script context="module" lang="ts">
  import type { Project } from '$lib/lq-ai/types';

  export type TierFloor = 1 | 2 | 3 | 4 | 5;

  export interface MetadataFields {
    name: string;
    description: string;
    privileged: boolean;
    minimum_inference_tier: TierFloor | null;
  }

  export interface MetadataValidation {
    valid: boolean;
    nameError: string | null;
    tierError: string | null;
  }

  export function validateMetadata(fields: MetadataFields): MetadataValidation {
    let nameError: string | null = null;
    let tierError: string | null = null;

    if (!fields.name.trim()) {
      nameError = 'Matter name is required.';
    } else if (fields.name.trim().length > 200) {
      nameError = 'Matter name must be 200 characters or fewer.';
    }

    if (fields.privileged && fields.minimum_inference_tier === null) {
      tierError = 'Privileged matters require a minimum tier floor.';
    }

    return {
      valid: nameError === null && tierError === null,
      nameError,
      tierError
    };
  }

  /** Whether a (non-archived) matter can be archived. Always true — exposed for testing. */
  export function canArchive(matter: Project): boolean {
    return !matter.archived_at;
  }
</script>

<script lang="ts">
  import { projectsApi } from '$lib/lq-ai/api';
  import TrustPill from './TrustPill.svelte';

  export let matter: Project;
  export let onMatterUpdate: (next: Project) => void = () => {};
  export let onMatterArchived: () => void = () => {};

  // View/edit state
  let editing = false;

  // Edit form state (initialised when entering edit mode)
  let editName = '';
  let editDescription = '';
  let editPrivileged = false;
  let editTierFloor: TierFloor | null = null;

  // Submission state
  let saving = false;
  let saveError: string | null = null;
  let nameError: string | null = null;
  let tierError: string | null = null;

  // Archive confirm state
  let archiveConfirming = false;
  let archiving = false;
  let archiveError: string | null = null;

  function enterEdit() {
    editName = matter.name;
    editDescription = matter.description ?? '';
    editPrivileged = matter.privileged;
    editTierFloor = matter.minimum_inference_tier ?? null;
    saveError = null;
    nameError = null;
    tierError = null;
    editing = true;
  }

  function cancelEdit() {
    editing = false;
    saveError = null;
    nameError = null;
    tierError = null;
  }

  async function save() {
    nameError = null;
    tierError = null;
    saveError = null;

    const result = validateMetadata({
      name: editName,
      description: editDescription,
      privileged: editPrivileged,
      minimum_inference_tier: editTierFloor
    });
    nameError = result.nameError;
    tierError = result.tierError;
    if (!result.valid) return;

    saving = true;
    try {
      const updated = await projectsApi.patchProject(matter.id, {
        name: editName.trim(),
        description: editDescription.trim() || undefined,
        privileged: editPrivileged,
        minimum_inference_tier: editTierFloor ?? undefined
      });
      onMatterUpdate(updated);
      editing = false;
    } catch (e) {
      saveError = e instanceof Error ? e.message : 'Failed to save. Please try again.';
    } finally {
      saving = false;
    }
  }

  async function confirmArchive() {
    archiveError = null;
    archiving = true;
    try {
      // PATCH archived: true (patchProject accepts Partial<Project>)
      await projectsApi.patchProject(matter.id, { archived_at: new Date().toISOString() } as Parameters<typeof projectsApi.patchProject>[1]);
      onMatterArchived();
    } catch (e) {
      archiveError = e instanceof Error ? e.message : 'Failed to archive matter.';
      archiving = false;
    }
  }

  // Reactive: hide tier floor when privileged is turned off in edit mode
  $: if (!editPrivileged) editTierFloor = null;

  // Under PRD §1.5.2, lower tier number = stronger security.
  // "Tier N or stronger" means the floor is N; tiers 1..N are all allowed.
  $: tierLabel = matter.minimum_inference_tier != null
    ? (matter.minimum_inference_tier === 1 ? 'Tier 1 only' : `Tier ${matter.minimum_inference_tier} or stronger`)
    : null;
  $: isArchived = !!matter.archived_at;

  const TIER_OPTIONS: { value: TierFloor; label: string }[] = [
    { value: 1, label: 'Tier 1 only (local / air-gapped)' },
    { value: 2, label: 'Tier 2 or stronger' },
    { value: 3, label: 'Tier 3 or stronger' },
    { value: 4, label: 'Tier 4 or stronger' },
    { value: 5, label: 'Tier 5 (any tier)' }
  ];
</script>

<section class="mrm-section" data-testid="matter-rail-metadata">
  <header class="mrm-header">
    <h2 class="lq-text-panel-h mrm-title">{matter.name}</h2>
    {#if !editing && !isArchived}
      <button type="button" class="mrm-btn-edit" on:click={enterEdit} aria-label="Edit matter metadata">
        Edit
      </button>
    {/if}
  </header>

  {#if !editing}
    <!-- View mode -->
    <p class="lq-text-caption mrm-slug" title="Matter ID">/{matter.slug}</p>

    <p class="lq-text-body mrm-description">
      {matter.description ?? '(no description)'}
    </p>

    {#if matter.privileged || tierLabel}
      <div class="mrm-badges">
        {#if matter.privileged}
          <TrustPill variant="secure" label="Privileged" />
        {/if}
        {#if tierLabel}
          <TrustPill variant="tier" label={tierLabel} />
        {/if}
        {#if isArchived}
          <TrustPill variant="warn" label="Archived" />
        {/if}
      </div>
    {:else if isArchived}
      <div class="mrm-badges">
        <TrustPill variant="warn" label="Archived" />
      </div>
    {/if}

    {#if !isArchived && canArchive(matter)}
      {#if archiveConfirming}
        <div class="mrm-archive-confirm" role="alert">
          <p class="lq-text-body-sm mrm-archive-msg">
            Archive this matter? Chats inside survive with their project link intact.
          </p>
          {#if archiveError}
            <p class="mrm-error" role="alert">{archiveError}</p>
          {/if}
          <div class="mrm-archive-actions">
            <button
              type="button"
              class="mrm-btn-cancel"
              on:click={() => { archiveConfirming = false; archiveError = null; }}
              disabled={archiving}
            >
              Cancel
            </button>
            <button
              type="button"
              class="mrm-btn-danger"
              on:click={confirmArchive}
              disabled={archiving}
            >
              {archiving ? 'Archiving…' : 'Archive'}
            </button>
          </div>
        </div>
      {:else}
        <button
          type="button"
          class="mrm-btn-danger-ghost"
          on:click={() => (archiveConfirming = true)}
        >
          Archive matter
        </button>
      {/if}
    {/if}
  {:else}
    <!-- Edit mode -->
    <form class="mrm-form" on:submit|preventDefault={save} novalidate>
      <div class="mrm-field">
        <label class="mrm-label" for="mrm-name">Matter name <span class="mrm-required" aria-hidden="true">*</span></label>
        <input
          id="mrm-name"
          type="text"
          bind:value={editName}
          class="mrm-input"
          class:mrm-input--error={!!nameError}
          maxlength="200"
          required
          disabled={saving}
          aria-describedby={nameError ? 'mrm-name-error' : undefined}
        />
        {#if nameError}
          <p id="mrm-name-error" class="mrm-field-error" role="alert">{nameError}</p>
        {/if}
      </div>

      <div class="mrm-field">
        <label class="mrm-label" for="mrm-description">Description <span class="mrm-optional">(optional)</span></label>
        <textarea
          id="mrm-description"
          bind:value={editDescription}
          class="mrm-textarea"
          rows="3"
          maxlength="2000"
          disabled={saving}
        ></textarea>
      </div>

      <div class="mrm-field mrm-field--inline">
        <input
          id="mrm-privileged"
          type="checkbox"
          bind:checked={editPrivileged}
          disabled={saving}
        />
        <label class="mrm-label mrm-label--checkbox" for="mrm-privileged">
          Attorney-client privileged
        </label>
      </div>

      {#if editPrivileged}
        <div class="mrm-field">
          <label class="mrm-label" for="mrm-tier">
            Minimum inference tier <span class="mrm-required" aria-hidden="true">*</span>
          </label>
          <select
            id="mrm-tier"
            class="mrm-select"
            class:mrm-input--error={!!tierError}
            bind:value={editTierFloor}
            disabled={saving}
            aria-describedby={tierError ? 'mrm-tier-error' : undefined}
          >
            <option value={null}>(none)</option>
            {#each TIER_OPTIONS as opt}
              <option value={opt.value}>{opt.label}</option>
            {/each}
          </select>
          {#if tierError}
            <p id="mrm-tier-error" class="mrm-field-error" role="alert">{tierError}</p>
          {/if}
        </div>
      {/if}

      {#if saveError}
        <p class="mrm-error" role="alert">{saveError}</p>
      {/if}

      <div class="mrm-form-actions">
        <button type="button" class="mrm-btn-cancel" on:click={cancelEdit} disabled={saving}>
          Cancel
        </button>
        <button type="submit" class="mrm-btn-save" disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  {/if}
</section>

<style>
  @import '$lib/lq-ai/styles/practice.css';

  .mrm-section {
    display: flex;
    flex-direction: column;
    gap: var(--lq-space-2);
    padding-bottom: var(--lq-space-4);
    border-bottom: 1px solid var(--lq-border);
  }

  .mrm-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--lq-space-2);
  }

  .mrm-title {
    margin: 0;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    flex: 1;
  }

  .mrm-slug {
    color: var(--lq-text-tertiary);
    margin: 0;
  }

  .mrm-description {
    color: var(--lq-text-secondary);
    margin: 0;
  }

  .mrm-badges {
    display: flex;
    flex-wrap: wrap;
    gap: var(--lq-space-2);
    margin-top: var(--lq-space-1);
  }

  /* Edit button */
  .mrm-btn-edit {
    font-size: 12px;
    font-weight: 500;
    color: var(--lq-accent);
    background: transparent;
    border: 1px solid var(--lq-accent-border);
    border-radius: var(--lq-radius-pill);
    padding: 2px 10px;
    cursor: pointer;
    white-space: nowrap;
    flex-shrink: 0;
  }

  .mrm-btn-edit:hover {
    background: var(--lq-accent-soft);
  }

  .mrm-btn-edit:focus-visible {
    outline: 2px solid var(--lq-accent);
    outline-offset: 2px;
  }

  /* Archive controls */
  .mrm-archive-confirm {
    display: flex;
    flex-direction: column;
    gap: var(--lq-space-2);
    background: var(--lq-error-soft);
    border: 1px solid var(--lq-error-border);
    border-radius: var(--lq-radius);
    padding: var(--lq-space-3);
    margin-top: var(--lq-space-2);
  }

  .mrm-archive-msg {
    margin: 0;
    color: var(--lq-text-secondary);
  }

  .mrm-archive-actions {
    display: flex;
    gap: var(--lq-space-2);
    justify-content: flex-end;
  }

  .mrm-btn-danger {
    font-size: 13px;
    font-weight: 500;
    background: var(--lq-error);
    color: white;
    border: 0;
    border-radius: var(--lq-radius-pill);
    padding: var(--lq-space-1) var(--lq-space-3);
    cursor: pointer;
  }

  .mrm-btn-danger:hover:not(:disabled) {
    opacity: 0.85;
  }

  .mrm-btn-danger:disabled {
    opacity: 0.65;
    cursor: not-allowed;
  }

  .mrm-btn-danger-ghost {
    font-size: 13px;
    font-weight: 500;
    color: var(--lq-error);
    background: transparent;
    border: 1px solid var(--lq-error-border);
    border-radius: var(--lq-radius-pill);
    padding: var(--lq-space-1) var(--lq-space-3);
    cursor: pointer;
    margin-top: var(--lq-space-2);
    align-self: flex-start;
  }

  .mrm-btn-danger-ghost:hover {
    background: var(--lq-error-soft);
  }

  .mrm-btn-danger-ghost:focus-visible {
    outline: 2px solid var(--lq-error);
    outline-offset: 2px;
  }

  /* Form */
  .mrm-form {
    display: flex;
    flex-direction: column;
    gap: var(--lq-space-3);
  }

  .mrm-field {
    display: flex;
    flex-direction: column;
    gap: var(--lq-space-1);
  }

  .mrm-field--inline {
    flex-direction: row;
    align-items: center;
    gap: var(--lq-space-2);
  }

  .mrm-label {
    font-size: 13px;
    font-weight: 500;
    color: var(--lq-text);
  }

  .mrm-label--checkbox {
    cursor: pointer;
  }

  .mrm-required {
    color: var(--lq-error);
    margin-left: 2px;
  }

  .mrm-optional {
    font-weight: 400;
    color: var(--lq-text-tertiary);
    font-size: 12px;
  }

  .mrm-input,
  .mrm-textarea,
  .mrm-select {
    background: var(--lq-inset);
    border: 1px solid var(--lq-border-strong);
    border-radius: var(--lq-radius);
    padding: var(--lq-space-2) var(--lq-space-3);
    font-size: 13px;
    color: var(--lq-text);
    width: 100%;
    box-sizing: border-box;
    transition: border-color 0.15s ease;
  }

  .mrm-input:focus,
  .mrm-textarea:focus,
  .mrm-select:focus {
    outline: none;
    border-color: var(--lq-accent);
    box-shadow: 0 0 0 2px var(--lq-accent-soft);
  }

  .mrm-input--error {
    border-color: var(--lq-error);
  }

  .mrm-textarea {
    resize: vertical;
    min-height: 70px;
  }

  .mrm-field-error {
    font-size: 12px;
    color: var(--lq-error);
    margin: 0;
  }

  .mrm-error {
    font-size: 13px;
    color: var(--lq-error);
    background: var(--lq-error-soft);
    border: 1px solid var(--lq-error-border);
    border-radius: var(--lq-radius);
    padding: var(--lq-space-2) var(--lq-space-3);
    margin: 0;
  }

  .mrm-form-actions {
    display: flex;
    gap: var(--lq-space-2);
    justify-content: flex-end;
    padding-top: var(--lq-space-2);
    border-top: 1px solid var(--lq-border);
  }

  .mrm-btn-save {
    font-size: 13px;
    font-weight: 500;
    background: var(--lq-accent);
    color: white;
    border: 0;
    border-radius: var(--lq-radius-pill);
    padding: var(--lq-space-1) var(--lq-space-4);
    cursor: pointer;
  }

  .mrm-btn-save:hover:not(:disabled) {
    opacity: 0.85;
  }

  .mrm-btn-save:disabled {
    opacity: 0.65;
    cursor: not-allowed;
  }

  .mrm-btn-save:focus-visible {
    outline: 2px solid var(--lq-accent);
    outline-offset: 2px;
  }

  .mrm-btn-cancel {
    font-size: 13px;
    font-weight: 500;
    color: var(--lq-text-secondary);
    background: transparent;
    border: 1px solid var(--lq-border);
    border-radius: var(--lq-radius-pill);
    padding: var(--lq-space-1) var(--lq-space-3);
    cursor: pointer;
  }

  .mrm-btn-cancel:hover:not(:disabled) {
    background: var(--lq-inset);
  }

  .mrm-btn-cancel:disabled {
    opacity: 0.65;
    cursor: not-allowed;
  }

  .mrm-btn-cancel:focus-visible {
    outline: 2px solid var(--lq-accent);
    outline-offset: 2px;
  }
</style>
