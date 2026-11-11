<script lang="ts">
  import { skillsApi, projectsApi } from '$lib/lq-ai/api';
  import type { Project, SkillSummary } from '$lib/lq-ai/types';
  import TrustPill from './TrustPill.svelte';

  export let matter: Project;
  export let onMatterUpdate: (next: Project) => void = () => {};

  // Picker state
  let pickerOpen = false;
  let availableSkills: SkillSummary[] = [];
  let loadingAvailable = false;
  let attachingName: string | null = null;
  let detachingName: string | null = null;
  let attachError: string | null = null;

  async function openPicker() {
    attachError = null;
    pickerOpen = true;
    loadingAvailable = true;
    try {
      const all = await skillsApi.listSkills();
      const attachedSet = new Set(matter.attached_skill_names ?? []);
      availableSkills = all.filter((s) => !attachedSet.has(s.name));
    } catch (e) {
      console.error('lq-ai: failed to load available skills', e);
      availableSkills = [];
    } finally {
      loadingAvailable = false;
    }
  }

  function closePicker() {
    pickerOpen = false;
    availableSkills = [];
    attachError = null;
  }

  async function attachSkill(skill: SkillSummary) {
    attachError = null;
    attachingName = skill.name;
    try {
      const updated = await projectsApi.attachSkill(matter.id, skill.name);
      onMatterUpdate(updated);
      // Remove from picker; the updated matter prop will re-drive attached list reactively.
      availableSkills = availableSkills.filter((s) => s.name !== skill.name);
    } catch (e) {
      attachError = e instanceof Error ? e.message : 'Failed to attach skill.';
    } finally {
      attachingName = null;
    }
  }

  async function detachSkill(name: string) {
    attachError = null;
    detachingName = name;
    try {
      const updated = await projectsApi.detachSkill(matter.id, name);
      onMatterUpdate(updated);
    } catch (e) {
      attachError = e instanceof Error ? e.message : 'Failed to detach skill.';
    } finally {
      detachingName = null;
    }
  }

  $: attachedNames = matter.attached_skill_names ?? [];
</script>

<section class="mrs-section" data-testid="matter-rail-skills">
  <header class="mrs-header">
    <h3 class="lq-text-panel-h mrs-title">Skills</h3>
    <button
      type="button"
      class="mrs-btn-attach"
      on:click={pickerOpen ? closePicker : openPicker}
      aria-expanded={pickerOpen}
      aria-controls="mrs-picker"
    >
      {pickerOpen ? 'Done' : '+ Attach'}
    </button>
  </header>

  {#if attachError}
    <p class="mrs-error" role="alert">{attachError}</p>
  {/if}

  {#if attachedNames.length === 0 && !pickerOpen}
    <p class="lq-text-caption mrs-empty">No skills attached.</p>
  {:else}
    <div class="mrs-chips">
      {#each attachedNames as name (name)}
        <div class="mrs-chip-row">
          <TrustPill variant="secure" label={name} />
          <button
            type="button"
            class="mrs-btn-detach"
            aria-label="Detach skill {name}"
            on:click={() => detachSkill(name)}
            disabled={detachingName === name}
          >
            {detachingName === name ? '…' : '×'}
          </button>
        </div>
      {/each}
    </div>
  {/if}

  {#if pickerOpen}
    <div id="mrs-picker" class="mrs-picker" role="listbox" aria-label="Available skills to attach">
      {#if loadingAvailable}
        <p class="lq-text-caption mrs-empty">Loading skills…</p>
      {:else if availableSkills.length === 0}
        <p class="lq-text-caption mrs-empty">No skills available to attach.</p>
      {:else}
        <ul class="mrs-available-list">
          {#each availableSkills as skill (skill.name)}
            <li role="option" aria-selected="false">
              <button
                type="button"
                class="mrs-available-item"
                on:click={() => attachSkill(skill)}
                disabled={attachingName === skill.name}
              >
                <span class="lq-text-body-sm mrs-skill-name">{skill.title || skill.name}</span>
                {#if skill.description}
                  <span class="lq-text-caption mrs-skill-desc">{skill.description}</span>
                {/if}
                {#if attachingName === skill.name}
                  <span class="lq-text-caption mrs-attaching">Attaching…</span>
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

  .mrs-section {
    display: flex;
    flex-direction: column;
    gap: var(--lq-space-2);
  }

  .mrs-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--lq-space-2);
  }

  .mrs-title {
    margin: 0;
  }

  .mrs-empty {
    color: var(--lq-text-tertiary);
    padding: var(--lq-space-1) 0;
  }

  .mrs-error {
    font-size: 12px;
    color: var(--lq-error);
    background: var(--lq-error-soft);
    border: 1px solid var(--lq-error-border);
    border-radius: var(--lq-radius);
    padding: var(--lq-space-1) var(--lq-space-2);
    margin: 0;
  }

  /* Attach / done button */
  .mrs-btn-attach {
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

  .mrs-btn-attach:hover {
    background: var(--lq-accent-soft);
  }

  .mrs-btn-attach:focus-visible {
    outline: 2px solid var(--lq-accent);
    outline-offset: 2px;
  }

  /* Attached skill chips */
  .mrs-chips {
    display: flex;
    flex-direction: column;
    gap: var(--lq-space-1);
  }

  .mrs-chip-row {
    display: flex;
    align-items: center;
    gap: var(--lq-space-2);
  }

  .mrs-btn-detach {
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

  .mrs-btn-detach:hover:not(:disabled) {
    color: var(--lq-error);
  }

  .mrs-btn-detach:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .mrs-btn-detach:focus-visible {
    outline: 2px solid var(--lq-accent);
    outline-offset: 2px;
  }

  /* Picker panel */
  .mrs-picker {
    background: var(--lq-inset);
    border: 1px solid var(--lq-border);
    border-radius: var(--lq-radius-lg);
    padding: var(--lq-space-3);
    display: flex;
    flex-direction: column;
    gap: var(--lq-space-1);
    max-height: 220px;
    overflow-y: auto;
  }

  .mrs-available-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--lq-space-1);
  }

  .mrs-available-item {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
    width: 100%;
    padding: var(--lq-space-2) var(--lq-space-2);
    background: var(--lq-canvas);
    border: 1px solid var(--lq-border);
    border-radius: var(--lq-radius);
    cursor: pointer;
    text-align: left;
  }

  .mrs-available-item:hover:not(:disabled) {
    border-color: var(--lq-accent-border);
    background: var(--lq-accent-soft);
  }

  .mrs-available-item:disabled {
    opacity: 0.65;
    cursor: not-allowed;
  }

  .mrs-available-item:focus-visible {
    outline: 2px solid var(--lq-accent);
    outline-offset: 2px;
  }

  .mrs-skill-name {
    color: var(--lq-text);
    font-weight: 500;
  }

  .mrs-skill-desc {
    color: var(--lq-text-secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 100%;
  }

  .mrs-attaching {
    color: var(--lq-accent);
  }
</style>
