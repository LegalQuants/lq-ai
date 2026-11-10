<script lang="ts">
	/**
	 * Skill-selection panel above the chat input.
	 *
	 * Multi-skill in a single message is allowed (PRD §3.4); attach order
	 * is preserved on the wire.
	 *
	 * When a skill is attached, its declared inputs render as a form via
	 * `SkillInputForm`. Required inputs the user hasn't filled block submit
	 * (a required document input is also satisfied by an attached file).
	 *
	 * Project context inheritance: `projectAttachedSkills` are surfaced as
	 * already-attached and read-only; the user can still attach additional
	 * per-message skills.
	 */
	import type { Skill, SkillSummary } from '../types';
	import SkillInputForm from './SkillInputForm.svelte';
	import InfoTip from './InfoTip.svelte';

	export let availableSkills: SkillSummary[] = [];
	export let selectedSkillNames: string[] = [];
	export let projectAttachedSkills: string[] = [];
	export let skillDetails: Record<string, Skill> = {};
	export let skillInputs: Record<string, Record<string, unknown>> = {};
	/** The chat's attached files that are ready; they satisfy a required document input. */
	export let readyFileNames: string[] = [];
	/** The chat's attached files still being ingested. */
	export let processingFileNames: string[] = [];
	/** Attached skills whose detail or input schema failed to load. */
	export let failedSkillNames: string[] = [];

	export let onAttach: (name: string) => void = () => undefined;
	export let onDetach: (name: string) => void = () => undefined;
	export let onRetry: (name: string) => void = () => undefined;
	export let onUpdateInputs: (name: string, values: Record<string, unknown>) => void = () =>
		undefined;

	let pickerOpen = false;
	let searchTerm = '';

	$: filteredAvailable = availableSkills
		.filter(
			(s) =>
				!selectedSkillNames.includes(s.name) &&
				!projectAttachedSkills.includes(s.name) &&
				(searchTerm === '' ||
					s.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
					s.title.toLowerCase().includes(searchTerm.toLowerCase()))
		)
		.sort((a, b) => a.title.localeCompare(b.title));
</script>

<div class="lq-panel rounded-md p-3 space-y-2" data-testid="lq-ai-skill-picker">
	<div class="flex items-center justify-between">
		<span class="text-sm font-medium lq-label inline-flex items-center gap-1">
			Skills
			<InfoTip
				content="Skills are reusable structured prompts the AI uses to shape its answer. You can attach one or many per message; each skill's source is readable and forkable. Built-in skills ship with the app; community skills come from LegalQuants/lq-skills; user skills are yours."
				placement="bottom"
			/>
		</span>
		<button
			type="button"
			class="lq-btn-secondary"
			on:click={() => (pickerOpen = !pickerOpen)}
			data-testid="lq-ai-skill-picker-toggle"
		>
			{pickerOpen ? 'Close' : '+ Skills'}
		</button>
	</div>

	{#if projectAttachedSkills.length > 0}
		<div class="text-xs text-gray-500">
			From project (auto-attached):
			<span class="space-x-1">
				{#each projectAttachedSkills as name}
					<span
						class="inline-block px-2 py-0.5 rounded-full bg-gray-100 text-gray-700 text-xs border border-gray-200"
						title="Inherited from this chat's Project"
					>
						{name}
					</span>
				{/each}
			</span>
		</div>
	{/if}

	{#if selectedSkillNames.length > 0}
		<div class="space-y-2">
			{#each selectedSkillNames as name (name)}
				<div class="lq-attached-skill rounded p-2">
					<div class="flex items-center justify-between">
						<span class="text-sm font-medium lq-attached-skill-title">
							{skillDetails[name]?.title ?? name}
						</span>
						<button
							type="button"
							class="text-xs text-rose-600 hover:underline"
							on:click={() => onDetach(name)}
							data-testid={`lq-ai-skill-detach-${name}`}
						>
							Detach
						</button>
					</div>
					{#if skillDetails[name]}
						<div class="mt-1">
							<SkillInputForm
								skillName={name}
								inputs={skillDetails[name].inputs ?? []}
								values={skillInputs[name] ?? {}}
								{readyFileNames}
								{processingFileNames}
								onChange={(next) => onUpdateInputs(name, next)}
							/>
						</div>
					{:else if failedSkillNames.includes(name)}
						<p class="lq-load-error text-xs mt-1" data-testid={`lq-ai-skill-load-error-${name}`}>
							Couldn't load this skill's inputs.
							<button type="button" class="underline" on:click={() => onRetry(name)}>Retry</button>
						</p>
					{:else}
						<p class="text-xs text-gray-500 italic mt-1">Loading skill details…</p>
					{/if}
				</div>
			{/each}
		</div>
	{/if}

	{#if pickerOpen}
		<div class="lq-picker-dropdown pt-2">
			<input
				type="text"
				placeholder="Search skills…"
				class="lq-search-input w-full text-sm rounded px-2 py-1"
				bind:value={searchTerm}
				data-testid="lq-ai-skill-picker-search"
			/>
			<ul class="mt-2 max-h-48 overflow-y-auto divide-y lq-divider">
				{#each filteredAvailable as s (s.name)}
					<li>
						<button
							type="button"
							class="w-full text-left px-2 py-1.5 lq-skill-option"
							on:click={() => onAttach(s.name)}
							data-testid={`lq-ai-skill-attach-${s.name}`}
						>
							<div class="text-sm font-medium lq-label">
								{s.title}
							</div>
							{#if s.description}
								<div class="text-xs lq-subtext">{s.description}</div>
							{/if}
						</button>
					</li>
				{:else}
					<li class="text-xs italic px-2 py-2 lq-subtext">No matching skills.</li>
				{/each}
			</ul>
		</div>
	{/if}
</div>

<style>
	@import '../styles/practice.css';

	.lq-panel {
		border: 1px solid var(--lq-border);
		background: var(--lq-canvas);
	}

	.lq-label {
		color: var(--lq-text);
	}

	.lq-subtext {
		color: var(--lq-text-tertiary);
	}

	.lq-btn-secondary {
		background: white;
		color: var(--lq-accent);
		border: 1px solid var(--lq-accent-border);
		border-radius: var(--lq-radius);
		padding: 4px 10px;
		font-size: 13px;
		cursor: pointer;
	}
	.lq-btn-secondary:hover {
		background: var(--lq-accent-soft);
	}
	.lq-btn-secondary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}

	.lq-attached-skill {
		border: 1px solid var(--lq-accent-border);
		background: var(--lq-accent-soft);
	}

	.lq-attached-skill-title {
		color: var(--lq-accent);
	}

	.lq-load-error {
		color: var(--lq-error);
	}
	.lq-load-error button {
		background: transparent;
		border: 0;
		color: inherit;
		cursor: pointer;
	}

	.lq-picker-dropdown {
		border-top: 1px solid var(--lq-border);
	}

	.lq-search-input {
		border: 1px solid var(--lq-border);
		color: var(--lq-text);
		background: var(--lq-canvas);
	}
	.lq-search-input:focus {
		border-color: var(--lq-accent);
		outline: none;
	}

	.lq-divider {
		border-color: var(--lq-border);
	}

	.lq-skill-option {
		background: transparent;
		border: 0;
		cursor: pointer;
	}
	.lq-skill-option:hover {
		background: var(--lq-accent-soft);
	}
</style>
