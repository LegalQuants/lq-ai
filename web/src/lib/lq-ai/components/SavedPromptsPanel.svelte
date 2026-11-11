<script lang="ts">
	/**
	 * Saved-prompts panel above the chat input — D7 / DE-013 / Issue 04.
	 *
	 * Three modes:
	 * - List (collapsed): shows count + button to expand.
	 * - List (expanded): shows the user's saved prompts with quick-insert,
	 *   edit/delete, and "Save as SKILL.md" download. New-prompt button
	 *   above the list.
	 * - Edit form: pinned in place; replaces the list while editing.
	 *
	 * Quick-insert appends the prompt body to the composer textarea
	 * (rather than replacing) so users can stack a saved prompt onto an
	 * in-progress message. The parent component owns ``composerText`` and
	 * exposes a setter; we never reach into the DOM.
	 *
	 * Promote-to-Skill (D8 / ADR 0012 — landed): clicking "Promote to skill"
	 * POSTs to ``/api/v1/user-skills`` and navigates the user to the
	 * Skill Creator edit page so they can refine the body before relying
	 * on it. Slug collisions with a filesystem-canonical built-in are
	 * still allowed at the API level (the shadow case); the Skill Creator
	 * page surfaces a warning when that happens.
	 *
	 * The legacy "Export as SKILL.md" download path stays available as a
	 * secondary affordance for users who want to upstream a skill via PR
	 * per ``skills/CONTRIBUTING.md``.
	 */
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	import { savedPromptsApi, userSkillsApi } from '$lib/lq-ai/api';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import type { SavedPrompt } from '$lib/lq-ai/types';

	export let onInsert: (text: string) => void = () => undefined;
	/** When true, the list is always rendered (no Show/Hide toggle) — used
	 *  by the standalone /lq-ai/saved-prompts page. Default keeps the
	 *  in-chat collapse behavior. */
	export let alwaysOpen = false;
	/** Label on the per-prompt insert button. The in-chat panel uses
	 *  "Insert" (append to composer); the standalone page uses "Use in
	 *  chat" (navigate to a fresh chat with the prompt prefilled). */
	export let insertLabel = 'Insert';

	let prompts: SavedPrompt[] = [];
	let panelOpen = alwaysOpen;
	let loading = false;
	let loadError: string | null = null;

	// Edit-form state. ``editing.id`` is the row being updated; ``null`` →
	// the form is in "create new" mode.
	interface EditState {
		id: string | null;
		name: string;
		prompt_text: string;
		tagsInput: string; // comma-separated UI representation
	}
	let editing: EditState | null = null;
	let saving = false;
	let saveError: string | null = null;

	async function refresh(): Promise<void> {
		loading = true;
		loadError = null;
		try {
			prompts = await savedPromptsApi.listSavedPrompts();
		} catch (e) {
			console.error('lq-ai: saved-prompts list failed', e);
			loadError = e instanceof Error ? e.message : 'Failed to load saved prompts';
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		void refresh();
	});

	function openCreate(): void {
		editing = { id: null, name: '', prompt_text: '', tagsInput: '' };
		saveError = null;
		panelOpen = true;
	}

	function openEdit(prompt: SavedPrompt): void {
		editing = {
			id: prompt.id,
			name: prompt.name,
			prompt_text: prompt.prompt_text,
			tagsInput: prompt.tags.join(', ')
		};
		saveError = null;
	}

	function cancelEdit(): void {
		editing = null;
		saveError = null;
	}

	function parseTags(raw: string): string[] {
		return raw
			.split(',')
			.map((t) => t.trim())
			.filter((t) => t.length > 0);
	}

	async function save(): Promise<void> {
		if (!editing) return;
		const name = editing.name.trim();
		const prompt_text = editing.prompt_text;
		if (!name || !prompt_text) {
			saveError = 'Name and prompt text are required.';
			return;
		}
		const tags = parseTags(editing.tagsInput);
		saving = true;
		saveError = null;
		try {
			if (editing.id === null) {
				await savedPromptsApi.createSavedPrompt({ name, prompt_text, tags });
			} else {
				await savedPromptsApi.updateSavedPrompt(editing.id, { name, prompt_text, tags });
			}
			await refresh();
			editing = null;
		} catch (e) {
			console.error('lq-ai: saved-prompt save failed', e);
			saveError = e instanceof Error ? e.message : 'Failed to save prompt';
		} finally {
			saving = false;
		}
	}

	async function remove(prompt: SavedPrompt): Promise<void> {
		if (!confirm(`Delete saved prompt "${prompt.name}"? This cannot be undone.`)) return;
		try {
			await savedPromptsApi.deleteSavedPrompt(prompt.id);
			await refresh();
		} catch (e) {
			console.error('lq-ai: saved-prompt delete failed', e);
			alert(e instanceof Error ? e.message : 'Failed to delete prompt');
		}
	}

	function insert(prompt: SavedPrompt): void {
		onInsert(prompt.prompt_text);
	}

	function slugify(value: string): string {
		const base = value
			.toLowerCase()
			.replace(/[^a-z0-9\s-]/g, '')
			.trim()
			.replace(/\s+/g, '-')
			.replace(/-+/g, '-');
		return base || 'saved-prompt';
	}

	function escapeYamlString(value: string): string {
		// Conservative double-quote escaping. Sufficient for the small
		// frontmatter values we generate (skill name, description).
		return value.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
	}

	let promoting: string | null = null;
	let promoteError: string | null = null;

	/**
	 * POST the saved prompt as a new user-scope skill (D8 / ADR 0012) and
	 * route the user to the Skill Creator edit page so they can refine
	 * the body. Slug-collision-with-built-in is permitted and shows up as
	 * a warning on the edit page rather than blocking creation.
	 */
	async function promoteToSkill(prompt: SavedPrompt): Promise<void> {
		const slug = slugify(prompt.name);
		promoting = prompt.id;
		promoteError = null;
		try {
			const created = await userSkillsApi.createUserSkill({
				slug,
				display_name: prompt.name,
				description: `Promoted from saved prompt "${prompt.name}".`,
				body: prompt.prompt_text,
				version: '0.1.0',
				tags: prompt.tags
			});
			goto(`/lq-ai/skills/${created.id}/edit?created=1`);
		} catch (e) {
			console.error('lq-ai: promote-to-skill failed', e);
			if (e instanceof LQAIApiError && e.status === 409) {
				promoteError =
					`You already have a user-scope skill at slug "${slug}". Open Skills to edit it, or rename this prompt first.`;
			} else {
				promoteError = e instanceof Error ? e.message : 'Failed to promote prompt to skill.';
			}
		} finally {
			promoting = null;
		}
	}

	/**
	 * Render the saved prompt as a SKILL.md draft and trigger a browser
	 * download. Kept as a secondary "Export" path for users who want to
	 * upstream a skill via PR rather than land it in their personal
	 * scope.
	 */
	function downloadAsSkillMd(prompt: SavedPrompt): void {
		const slug = slugify(prompt.name);
		const safeName = escapeYamlString(prompt.name);
		const description = `Promoted from saved prompt "${prompt.name}".`;
		const tagsLine =
			prompt.tags.length > 0
				? `tags: [${prompt.tags.map((t) => `"${escapeYamlString(t)}"`).join(', ')}]\n`
				: '';
		const yaml = [
			'---',
			`name: ${slug}`,
			`title: "${safeName}"`,
			`description: "${escapeYamlString(description)}"`,
			'version: 0.1.0',
			tagsLine ? tagsLine.trimEnd() : '',
			'lq_ai:',
			'  minimum_inference_tier: 2',
			'---',
			''
		]
			.filter((l) => l !== '')
			.join('\n');
		const body = [
			`# ${prompt.name}`,
			'',
			'> Drafted from a saved prompt. Review the frontmatter (name, ' +
				'description, tier) and submit via PR per CONTRIBUTING.md, or ' +
				'drop the file into your local ``skills/`` directory.',
			'',
			prompt.prompt_text,
			''
		].join('\n');
		const blob = new Blob([yaml + '\n' + body], { type: 'text/markdown' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `${slug}.SKILL.md`;
		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
		setTimeout(() => URL.revokeObjectURL(url), 1000);
	}
</script>

<div
	class="lq-panel rounded-md p-3 space-y-2"
	data-testid="lq-ai-saved-prompts"
>
	<div class="flex items-center justify-between">
		<span class="text-sm font-medium lq-label">
			Saved prompts
			{#if !loading && prompts.length > 0}
				<span class="text-xs lq-subtext">({prompts.length})</span>
			{/if}
		</span>
		<div class="flex items-center gap-2">
			<button
				type="button"
				class="lq-btn-secondary disabled:opacity-50"
				on:click={openCreate}
				disabled={editing !== null && editing.id === null}
				data-testid="lq-ai-saved-prompts-new"
			>
				+ New
			</button>
			{#if !alwaysOpen}
				<button
					type="button"
					class="lq-btn-ghost"
					on:click={() => (panelOpen = !panelOpen)}
					data-testid="lq-ai-saved-prompts-toggle"
				>
					{panelOpen ? 'Hide' : 'Show'}
				</button>
			{/if}
		</div>
	</div>

	{#if loadError}
		<div
			class="text-xs lq-t-error lq-t-error-bg border lq-t-error-border rounded px-2 py-1"
			data-testid="lq-ai-saved-prompts-error"
		>
			{loadError}
		</div>
	{/if}

	{#if promoteError}
		<div
			class="text-xs lq-t-error lq-t-error-bg border lq-t-error-border rounded px-2 py-1"
			data-testid="lq-ai-saved-prompt-promote-error"
			role="alert"
		>
			{promoteError}
		</div>
	{/if}

	{#if editing}
		<div
			class="lq-editor-card rounded-md p-2 space-y-2"
			data-testid="lq-ai-saved-prompt-editor"
		>
			<input
				type="text"
				class="w-full text-sm border lq-t-border-strong rounded px-2 py-1"
				placeholder="Name (e.g., Executive summary)"
				bind:value={editing.name}
				maxlength={200}
				data-testid="lq-ai-saved-prompt-name"
			/>
			<textarea
				class="w-full text-sm border lq-t-border-strong rounded px-2 py-1 resize-y"
				rows="4"
				placeholder="Prompt text…"
				bind:value={editing.prompt_text}
				data-testid="lq-ai-saved-prompt-text"
			></textarea>
			<input
				type="text"
				class="w-full text-xs border lq-t-border-strong rounded px-2 py-1"
				placeholder="Tags, comma-separated (optional)"
				bind:value={editing.tagsInput}
				data-testid="lq-ai-saved-prompt-tags"
			/>
			{#if saveError}
				<div class="text-xs lq-t-error">{saveError}</div>
			{/if}
			<div class="flex items-center justify-end gap-2">
				<button
					type="button"
					class="text-xs px-2 py-1 rounded lq-t-text2 lq-t-hover"
					on:click={cancelEdit}
					disabled={saving}
				>
					Cancel
				</button>
				<button
					type="button"
					class="lq-btn-primary disabled:opacity-50"
					on:click={save}
					disabled={saving}
					data-testid="lq-ai-saved-prompt-save"
				>
					{saving ? 'Saving…' : editing.id === null ? 'Create' : 'Update'}
				</button>
			</div>
		</div>
	{/if}

	{#if panelOpen && !editing}
		{#if loading}
			<p class="text-xs italic lq-subtext">Loading…</p>
		{:else if prompts.length === 0}
			<p class="text-xs italic lq-subtext" data-testid="lq-ai-saved-prompts-empty">
				No saved prompts yet. Click <strong>+ New</strong> to create your first one.
			</p>
		{:else}
			<ul class="lq-list-divider max-h-72 overflow-y-auto">
				{#each prompts as prompt (prompt.id)}
					<li class="py-2" data-testid={`lq-ai-saved-prompt-${prompt.id}`}>
						<div class="flex items-start justify-between gap-2">
							<div class="min-w-0 flex-1">
								<div class="text-sm font-medium lq-t-text truncate">
									{prompt.name}
								</div>
								<div class="text-xs lq-t-text2 line-clamp-2">{prompt.prompt_text}</div>
								{#if prompt.tags.length > 0}
									<div class="mt-1 flex flex-wrap gap-1">
										{#each prompt.tags as tag}
											<span
												class="text-[10px] px-1.5 py-0.5 rounded-full lq-t-inset lq-t-text2 border lq-t-border"
											>
												{tag}
											</span>
										{/each}
									</div>
								{/if}
							</div>
							<div class="flex flex-col items-end gap-1 shrink-0">
								<button
									type="button"
									class="lq-btn-secondary"
									on:click={() => insert(prompt)}
									data-testid={`lq-ai-saved-prompt-insert-${prompt.id}`}
								>
									{insertLabel}
								</button>
								<button
									type="button"
									class="text-xs px-2 py-0.5 rounded lq-t-text2 lq-t-hover"
									on:click={() => openEdit(prompt)}
								>
									Edit
								</button>
								<button
									type="button"
									class="text-xs px-2 py-0.5 rounded lq-t-accent lq-t-accent-hover disabled:opacity-50"
									on:click={() => promoteToSkill(prompt)}
									disabled={promoting === prompt.id}
									title="Promote to a user-scope skill (lands in /lq-ai/skills, edit before using)"
									data-testid={`lq-ai-saved-prompt-promote-${prompt.id}`}
								>
									{promoting === prompt.id ? 'Promoting…' : 'Promote to skill'}
								</button>
								<button
									type="button"
									class="text-xs px-2 py-0.5 rounded lq-t-text2 lq-t-hover"
									on:click={() => downloadAsSkillMd(prompt)}
									title="Download as SKILL.md draft to PR into the canonical skills/ directory"
									data-testid={`lq-ai-saved-prompt-export-${prompt.id}`}
								>
									Export
								</button>
								<button
									type="button"
									class="text-xs px-2 py-0.5 rounded lq-t-error lq-t-error-hover"
									on:click={() => remove(prompt)}
								>
									Delete
								</button>
							</div>
						</div>
					</li>
				{/each}
			</ul>
		{/if}
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

	.lq-btn-primary {
		background: var(--lq-accent);
		color: white;
		border: 0;
		border-radius: var(--lq-radius-pill);
		padding: 4px 12px;
		font-size: 12px;
		font-weight: 500;
		cursor: pointer;
	}
	.lq-btn-primary:hover {
		opacity: 0.85;
	}
	.lq-btn-primary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}

	.lq-btn-secondary {
		background: white;
		color: var(--lq-accent);
		border: 1px solid var(--lq-accent-border);
		border-radius: var(--lq-radius-pill);
		padding: 4px 10px;
		font-size: 12px;
		cursor: pointer;
	}
	.lq-btn-secondary:hover {
		background: var(--lq-accent-soft);
	}
	.lq-btn-secondary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}

	.lq-btn-ghost {
		background: transparent;
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-pill);
		padding: 4px 10px;
		font-size: 12px;
		cursor: pointer;
	}
	.lq-btn-ghost:hover {
		background: var(--lq-inset);
	}

	.lq-editor-card {
		border: 1px solid var(--lq-accent-border);
		background: var(--lq-accent-soft);
	}

	.lq-list-divider {
		border-top: 1px solid var(--lq-border);
	}

	/* Colour tokens replacing Tailwind palette utilities (S1-1b). */
	.lq-t-accent {
		color: var(--lq-accent);
	}
	.lq-t-accent-hover:hover {
		background-color: var(--lq-accent-soft);
	}
	.lq-t-border {
		border-color: var(--lq-border);
	}
	.lq-t-border-strong {
		border-color: var(--lq-border-strong);
	}
	.lq-t-error {
		color: var(--lq-error);
	}
	.lq-t-error-bg {
		background-color: var(--lq-error-bg);
	}
	.lq-t-error-border {
		border-color: var(--lq-error-border);
	}
	.lq-t-error-hover:hover {
		background-color: var(--lq-error-bg);
	}
	.lq-t-hover:hover {
		background-color: var(--lq-surface-hover);
	}
	.lq-t-inset {
		background-color: var(--lq-inset);
	}
	.lq-t-text {
		color: var(--lq-text);
	}
	.lq-t-text2 {
		color: var(--lq-text-secondary);
	}
</style>
