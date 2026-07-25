<script lang="ts">
	/**
	 * /lq-ai/skills/[id]/edit — edit an existing user-scope skill (D8 / ADR 0012).
	 *
	 * PATCH-driven: only the fields the user actually changes ride to the
	 * server, so an idempotent re-save writes no audit row. The slug is
	 * shown read-only — renaming a slug is out of scope for D8 (would
	 * require a migration of any chat attaching it; deferred as DE).
	 *
	 * The shadow indicator surfaces on edit too: if this skill's slug
	 * matches a built-in, the warning explains that the user's edits
	 * will continue to shape their chats.
	 */
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';

	import { userSkillsApi, skillsApi, teamsApi } from '$lib/lq-ai/api';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import ColumnEditor from '$lib/lq-ai/components/ColumnEditor.svelte';
	import {
		buildFrontmatterExtra,
		columnsFromRaw,
		modeFromExtra,
		newEditableColumn,
		validateColumns,
		type EditableColumn,
		type SkillOutputMode
	} from '$lib/lq-ai/skills/tableColumns';
	import type { UserSkill, SkillSummary, TeamSummary } from '$lib/lq-ai/types';

	let row: UserSkill | null = null;
	let builtinSlugs = new Set<string>();
	let teamNamesById = new Map<string, string>();
	let loading = true;
	let loadError: string | null = null;

	let displayName = '';
	let description = '';
	let version = '';
	let tagsInput = '';
	let body = '';
	// DE-297 — table-mode authoring state, seeded from frontmatter_extra.
	let outputMode: SkillOutputMode = 'prose';
	let columns: EditableColumn[] = [newEditableColumn()];
	let showColumnErrors = false;

	let submitting = false;
	let submitError: string | null = null;
	let saveOk: string | null = null;
	let actionError: string | null = null;

	$: skillId = $page.params.id;
	$: justCreated = $page.url.searchParams.get('created') === '1';
	$: shadowsBuiltIn = row !== null && builtinSlugs.has(row.slug);

	async function load(): Promise<void> {
		loading = true;
		loadError = null;
		try {
			const [skill, builtins, myTeams] = await Promise.all([
				userSkillsApi.getUserSkill(skillId as string),
				skillsApi.listSkills('builtin'),
				teamsApi.listMyTeams()
			]);
			row = skill;
			builtinSlugs = new Set(builtins.map((s: SkillSummary) => s.name));
			teamNamesById = new Map(
				(myTeams as TeamSummary[]).map((t) => [t.id, t.name])
			);
			displayName = skill.display_name;
			description = skill.description;
			version = skill.version;
			tagsInput = (skill.tags ?? []).join(', ');
			body = skill.body;
			outputMode = modeFromExtra(skill.frontmatter_extra);
			const loadedColumns = columnsFromRaw(skill.frontmatter_extra?.['columns']);
			columns =
				loadedColumns && loadedColumns.length > 0 ? loadedColumns : [newEditableColumn()];
			showColumnErrors = false;
		} catch (e) {
			console.error('user-skills/edit: load failed', e);
			if (e instanceof LQAIApiError && e.status === 404) {
				loadError = 'That skill no longer exists, or it isn\'t one of yours.';
			} else {
				loadError = e instanceof Error ? e.message : 'Failed to load the skill.';
			}
		} finally {
			loading = false;
		}
	}

	function parseTags(raw: string): string[] {
		return raw
			.split(',')
			.map((t) => t.trim())
			.filter((t) => t.length > 0);
	}

	function changeSet(): Partial<{
		display_name: string;
		description: string;
		body: string;
		version: string;
		tags: string[];
		frontmatter_extra: Record<string, unknown>;
	}> {
		if (!row) return {};
		const diff: ReturnType<typeof changeSet> = {};
		const trimmedDisplay = displayName.trim();
		if (trimmedDisplay !== row.display_name) diff.display_name = trimmedDisplay;
		const trimmedDescription = description.trim();
		if (trimmedDescription !== row.description) diff.description = trimmedDescription;
		if (body !== row.body) diff.body = body;
		const trimmedVersion = version.trim();
		if (trimmedVersion && trimmedVersion !== row.version) diff.version = trimmedVersion;
		const newTags = parseTags(tagsInput);
		const oldTags = row.tags ?? [];
		if (
			newTags.length !== oldTags.length ||
			newTags.some((t, i) => oldTags[i] !== t)
		) {
			diff.tags = newTags;
		}
		// DE-297 — table-mode: rebuild the extra block (preserving
		// unrelated keys) and send it only when it actually moved, so an
		// idempotent re-save still writes no audit row.
		const prevExtra = row.frontmatter_extra ?? {};
		const newExtra = buildFrontmatterExtra(prevExtra, outputMode, columns);
		if (JSON.stringify(newExtra) !== JSON.stringify(prevExtra)) {
			diff.frontmatter_extra = newExtra;
		}
		return diff;
	}

	async function save(): Promise<void> {
		if (!row) return;
		// Mirror — never widen — the backend's table-mode validation: a
		// spec the server would 422 never leaves the page (DE-297).
		if (outputMode === 'table' && !validateColumns(columns).valid) {
			showColumnErrors = true;
			submitError = 'Fix the column errors before saving.';
			return;
		}
		const diff = changeSet();
		if (Object.keys(diff).length === 0) {
			saveOk = 'Nothing to save — no changes.';
			return;
		}
		submitting = true;
		submitError = null;
		saveOk = null;
		try {
			const updated = await userSkillsApi.updateUserSkill(row.id, diff);
			row = updated;
			displayName = updated.display_name;
			description = updated.description;
			version = updated.version;
			body = updated.body;
			tagsInput = (updated.tags ?? []).join(', ');
			outputMode = modeFromExtra(updated.frontmatter_extra);
			const savedColumns = columnsFromRaw(updated.frontmatter_extra?.['columns']);
			columns = savedColumns && savedColumns.length > 0 ? savedColumns : [newEditableColumn()];
			showColumnErrors = false;
			saveOk = 'Saved.';
		} catch (e) {
			console.error('user-skills/edit: save failed', e);
			submitError = e instanceof Error ? e.message : 'Failed to save changes.';
		} finally {
			submitting = false;
		}
	}

	async function archive(): Promise<void> {
		if (!row) return;
		const confirmed = window.confirm(
			`Archive "${row.display_name}"? You can recreate at the same slug afterwards.`
		);
		if (!confirmed) return;
		actionError = null;
		try {
			await userSkillsApi.deleteUserSkill(row.id);
			goto('/lq-ai/skills');
		} catch (e) {
			console.error('user-skills/edit: archive failed', e);
			actionError = e instanceof Error ? e.message : 'Failed to archive skill.';
		}
	}

	onMount(() => {
		load();
	});
</script>

<div class="p-4 max-w-3xl mx-auto" data-testid="lq-ai-user-skill-edit">
	<header class="mb-4 flex items-center justify-between">
		<div>
			<h1 class="lq-text-page-h">Edit skill</h1>
			{#if row}
				<p class="lq-text-caption mt-1" style="color: var(--lq-text-tertiary);">
					<code class="font-mono">{row.slug}</code> · v{row.version}
					{#if row.scope === 'team' && row.owner_team_id}
						·
						<span
							class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wide bg-sky-100 text-sky-900 dark:bg-sky-900 dark:text-sky-100"
							data-testid="lq-ai-user-skill-edit-team-chip"
						>
							Team · {teamNamesById.get(row.owner_team_id) ?? 'unknown'}
						</span>
					{:else}
						·
						<span class="text-gray-500">Personal</span>
					{/if}
				</p>
			{/if}
		</div>
		<a
			href="/lq-ai/skills"
			class="lq-btn-secondary lq-text-caption"
		>
			Back
		</a>
	</header>

	{#if justCreated}
		<div
			class="mb-4 p-3 rounded border border-emerald-300 bg-emerald-50 text-emerald-900 text-sm dark:border-emerald-700 dark:bg-emerald-950 dark:text-emerald-100"
			role="status"
		>
			Created. Tweak the body or version and Save to bump.
		</div>
	{/if}
	{#if loadError}
		<div
			class="mb-4 p-3 rounded border border-rose-300 bg-rose-50 text-rose-900 text-sm dark:border-rose-700 dark:bg-rose-950 dark:text-rose-100"
			role="alert"
		>
			{loadError}
		</div>
	{/if}
	{#if loading}
		<p class="lq-text-body" style="color: var(--lq-text-secondary);">Loading…</p>
	{:else if row}
		{#if shadowsBuiltIn}
			<div
				class="mb-4 p-2 rounded border border-amber-300 bg-amber-50 text-amber-900 text-xs dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100"
				role="status"
				data-testid="lq-ai-user-skill-edit-shadow-warning"
			>
				This skill shadows the built-in <code class="font-mono">{row.slug}</code>.
				{#if row.scope === 'team'}
					When any member of this team attaches it to a chat, the team's version shapes the
					system prompt — the built-in is hidden for them. A user-scope shadow at the same slug
					(per-user) would in turn take precedence over the team version.
				{:else}
					When you attach it to a chat, your version shapes the system prompt — the built-in is
					hidden for you. Other users still see the built-in unless they're in a team that also
					shadows this slug.
				{/if}
			</div>
		{/if}
		{#if submitError}
			<div
				class="mb-4 p-3 rounded border border-rose-300 bg-rose-50 text-rose-900 text-sm dark:border-rose-700 dark:bg-rose-950 dark:text-rose-100"
				role="alert"
			>
				{submitError}
			</div>
		{/if}
		{#if actionError}
			<div
				class="mb-4 p-3 rounded border border-rose-300 bg-rose-50 text-rose-900 text-sm dark:border-rose-700 dark:bg-rose-950 dark:text-rose-100"
				role="alert"
			>
				{actionError}
			</div>
		{/if}
		{#if saveOk}
			<div
				class="mb-4 p-3 rounded border border-emerald-300 bg-emerald-50 text-emerald-900 text-sm dark:border-emerald-700 dark:bg-emerald-950 dark:text-emerald-100"
				role="status"
				data-testid="lq-ai-user-skill-edit-saved"
			>
				{saveOk}
			</div>
		{/if}

		<form
			class="space-y-4"
			on:submit|preventDefault={save}
			data-testid="lq-ai-user-skill-edit-form"
		>
			<label class="block">
				<span class="lq-text-label">Slug</span>
				<input
					type="text"
					readonly
					value={row.slug}
					class="mt-1 w-full rounded border-gray-200 dark:border-gray-800 bg-gray-100 dark:bg-gray-900 text-sm font-mono text-gray-600"
				/>
				<p class="lq-text-caption mt-1" style="color: var(--lq-text-tertiary);">
					Slugs are immutable in D8 — archive and recreate if you need a different one.
				</p>
			</label>

			<label class="block">
				<span class="lq-text-label">Display name</span>
				<input
					type="text"
					bind:value={displayName}
					required
					maxlength="200"
					class="mt-1 w-full rounded border-gray-300 dark:border-gray-700 dark:bg-gray-900 text-sm"
				/>
			</label>

			<label class="block">
				<span class="lq-text-label">Description</span>
				<input
					type="text"
					bind:value={description}
					required
					maxlength="2000"
					class="mt-1 w-full rounded border-gray-300 dark:border-gray-700 dark:bg-gray-900 text-sm"
				/>
			</label>

			<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
				<label class="block">
					<span class="lq-text-label">Version</span>
					<input
						type="text"
						bind:value={version}
						maxlength="50"
						class="mt-1 w-full rounded border-gray-300 dark:border-gray-700 dark:bg-gray-900 text-sm font-mono"
					/>
					<p class="lq-text-caption mt-1" style="color: var(--lq-text-tertiary);">Bump on edits; the audit log records before/after.</p>
				</label>
				<label class="block">
					<span class="lq-text-label">Tags (comma-separated)</span>
					<input
						type="text"
						bind:value={tagsInput}
						class="mt-1 w-full rounded border-gray-300 dark:border-gray-700 dark:bg-gray-900 text-sm"
					/>
				</label>
			</div>

			<div class="block">
				<span class="lq-text-label">Output</span>
				<div
					class="mt-1 flex items-center gap-4"
					role="radiogroup"
					aria-label="output mode"
				>
					<label class="flex items-center gap-1.5 text-sm cursor-pointer">
						<input
							type="radio"
							name="lq-ai-user-skill-edit-output-mode"
							value="prose"
							bind:group={outputMode}
							data-testid="lq-ai-user-skill-edit-mode-prose"
						/>
						Prose (default)
					</label>
					<label class="flex items-center gap-1.5 text-sm cursor-pointer">
						<input
							type="radio"
							name="lq-ai-user-skill-edit-output-mode"
							value="table"
							bind:group={outputMode}
							data-testid="lq-ai-user-skill-edit-mode-table"
						/>
						Table
					</label>
				</div>
				<p class="lq-text-caption mt-1" style="color: var(--lq-text-tertiary);">
					Table-mode skills produce a row-per-document grid in the Tabular Review
					wizard; each column defines one extraction query.
				</p>
			</div>

			{#if outputMode === 'table'}
				<ColumnEditor bind:columns showErrors={showColumnErrors} />
			{:else}
				<label class="block">
					<span class="lq-text-label">Body (Markdown system prompt)</span>
					<textarea
						bind:value={body}
						rows="16"
						required
						maxlength="200000"
						class="mt-1 w-full rounded border-gray-300 dark:border-gray-700 dark:bg-gray-900 text-sm font-mono"
					></textarea>
				</label>
			{/if}

			<div class="flex items-center justify-between pt-2">
				<button
					type="button"
					class="lq-btn-danger lq-text-caption"
					on:click={archive}
					data-testid="lq-ai-user-skill-edit-archive-btn"
				>
					Archive
				</button>
				<button
					type="submit"
					disabled={submitting}
					class="lq-btn-primary lq-text-caption"
					data-testid="lq-ai-user-skill-edit-save-btn"
				>
					{submitting ? 'Saving…' : 'Save changes'}
				</button>
			</div>
		</form>
	{/if}
</div>

<style>
	.lq-btn-primary {
		background: var(--lq-accent);
		color: white;
		border: 0;
		border-radius: var(--lq-radius);
		padding: 8px 16px;
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
	}
	.lq-btn-primary:disabled {
		background: var(--lq-text-tertiary);
		cursor: not-allowed;
	}

	.lq-btn-secondary {
		background: transparent;
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: 6px 12px;
		font-size: 12px;
		cursor: pointer;
		text-decoration: none;
		display: inline-flex;
		align-items: center;
	}
	.lq-btn-secondary:hover { background: var(--lq-inset); }

	.lq-btn-danger {
		background: transparent;
		color: var(--lq-error);
		border: 1px solid var(--lq-error);
		border-radius: var(--lq-radius);
		padding: 6px 12px;
		font-size: 12px;
		cursor: pointer;
	}
	.lq-btn-danger:hover { background: var(--lq-error-soft); }
</style>
