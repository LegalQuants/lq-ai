<script lang="ts">
	/**
	 * /lq-ai/skills — Skill Creator landing page (D8 / D8.1c / ADR 0012).
	 *
	 * Lists the caller's DB-backed user- and team-scope skills with edit /
	 * archive affordances. Team-scope rows are restricted to teams where
	 * the caller is a team-admin (members read team skills in the chat
	 * picker, not here). Empty state nudges toward "New skill". A skill
	 * at the same slug as a built-in shadows the built-in for the
	 * relevant scope (per ADR 0012 + D8.1b resolver: user > team >
	 * built-in); the shadow indicator surfaces here so the user can see
	 * which slugs they're overriding.
	 */
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';

	import { userSkillsApi, skillsApi, teamsApi } from '$lib/lq-ai/api';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import type { UserSkill, SkillSummary, TeamSummary } from '$lib/lq-ai/types';
	import TrustPill from '$lib/lq-ai/components/TrustPill.svelte';
	import {
		FORMAT_ALL,
		FORMAT_PROSE,
		formatChips,
		formatFilterFromParam,
		matchesFormat,
		normalizeFormat,
		sortFromParam,
		sortSkillRows,
		type SkillSort
	} from '$lib/lq-ai/skills/builtinsBrowser';

	let rows: UserSkill[] = [];
	let builtinSlugs = new Set<string>();
	let builtins: SkillSummary[] = [];
	let recentSlugs: string[] = [];
	let teamNamesById = new Map<string, string>();
	let loading = false;
	let listError: string | null = null;
	let actionError: string | null = null;

	async function load(): Promise<void> {
		loading = true;
		listError = null;
		try {
			const [mine, builtinList, myTeams, recents] = await Promise.all([
				userSkillsApi.listUserSkills('all'),
				skillsApi.listSkills('builtin'),
				teamsApi.listMyTeams(),
				// DE-298 — per-user recents (messages.applied_skills ordering)
				// via the autocomplete endpoint's empty-query mode. Tolerant:
				// a recents failure degrades to alphabetical, never blocks the page.
				skillsApi
					.autocompleteSkills('', 25)
					.then((r) => r.results.map((item) => item.slug))
					.catch((e) => {
						console.warn('user-skills: recents load failed', e);
						return [] as string[];
					})
			]);
			rows = mine;
			builtins = builtinList;
			builtinSlugs = new Set(builtinList.map((s: SkillSummary) => s.name));
			recentSlugs = recents;
			teamNamesById = new Map(
				(myTeams as TeamSummary[]).map((t) => [t.id, t.name])
			);
		} catch (e) {
			console.error('user-skills: load failed', e);
			listError =
				e instanceof LQAIApiError
					? e.message
					: e instanceof Error
						? e.message
						: 'Failed to load your skills.';
		} finally {
			loading = false;
		}
	}

	async function archive(row: UserSkill): Promise<void> {
		const confirmed = window.confirm(
			`Archive "${row.display_name}"? You can recreate at the same slug afterwards.`
		);
		if (!confirmed) return;
		actionError = null;
		try {
			await userSkillsApi.deleteUserSkill(row.id);
			rows = rows.filter((r) => r.id !== row.id);
		} catch (e) {
			console.error('user-skills: archive failed', e);
			actionError = e instanceof Error ? e.message : 'Failed to archive skill.';
		}
	}

	function shortDate(iso: string): string {
		try {
			return new Date(iso).toLocaleString();
		} catch {
			return iso;
		}
	}

	// DE-298 — output-format chip filter + recently-used sort, both
	// persisted in the URL (?format= / ?sort=) so a filtered view
	// survives refresh and is deep-linkable.
	function userSkillFormat(row: UserSkill): string | undefined {
		const v = row.frontmatter_extra?.['output_format'];
		return typeof v === 'string' ? v : undefined;
	}

	$: chips = formatChips([
		...builtins.map((b) => b.output_format),
		...rows.map((r) => userSkillFormat(r))
	]);
	$: activeFormat = formatFilterFromParam($page.url.searchParams.get('format'), chips);
	$: activeSort = sortFromParam($page.url.searchParams.get('sort'));
	$: visibleBuiltins = sortSkillRows(
		builtins.filter((b) => matchesFormat(b.output_format, activeFormat)),
		activeSort,
		recentSlugs,
		(b) => b.name,
		(b) => b.title ?? b.name
	);
	$: visibleRows = sortSkillRows(
		rows.filter((r) => matchesFormat(userSkillFormat(r), activeFormat)),
		activeSort,
		recentSlugs,
		(r) => r.slug,
		(r) => r.display_name
	);

	function setParam(key: string, value: string | null): void {
		const url = new URL($page.url);
		if (value === null) {
			url.searchParams.delete(key);
		} else {
			url.searchParams.set(key, value);
		}
		// replaceState: filter/sort tweaks shouldn't pollute history the
		// way the detail page's tab navigation deliberately does.
		void goto(url.pathname + url.search, {
			replaceState: true,
			keepFocus: true,
			noScroll: true
		});
	}

	function setFormat(f: string): void {
		setParam('format', f === FORMAT_ALL ? null : f);
	}

	function setSort(s: SkillSort): void {
		setParam('sort', s === 'recent' ? null : s);
	}

	function chipLabel(chip: string): string {
		if (chip === FORMAT_ALL) return 'All';
		if (chip === FORMAT_PROSE) return 'Prose';
		return chip.charAt(0).toUpperCase() + chip.slice(1);
	}

	onMount(() => {
		load();
	});
</script>

<div class="p-4 max-w-5xl mx-auto" data-testid="lq-ai-user-skills">
	<header class="mb-4 flex items-center justify-between">
		<div>
			<h1 class="lq-text-page-h">My skills</h1>
			<p class="lq-text-caption mt-1" style="color: var(--lq-text-tertiary);">
				Skills you can edit — your personal skills, plus team skills for any team where you're an
				admin. A skill at the same slug as a built-in shadows the built-in for the relevant scope.
			</p>
		</div>
		<div class="flex gap-2">
			<a
				href="/lq-ai"
				class="lq-btn-secondary text-xs"
			>
				Back to chat
			</a>
			<a
				href="/lq-ai/skills/new"
				class="lq-btn-primary text-xs"
				data-testid="lq-ai-user-skills-new-link"
			>
				+ New skill
			</a>
		</div>
	</header>

	{#if listError}
		<div
			class="mb-4 p-3 rounded border border-rose-300 bg-rose-50 text-rose-900 text-sm dark:border-rose-700 dark:bg-rose-950 dark:text-rose-100"
			role="alert"
		>
			{listError}
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

	{#if !loading && (builtins.length > 0 || rows.length > 0)}
		<!-- DE-298 — output-format chips + sort toggle, URL-param persisted. -->
		<div class="lq-browser-toolbar mb-4" data-testid="lq-ai-skills-toolbar">
			<div class="lq-chip-row" role="group" aria-label="Filter by output format">
				{#each chips as chip (chip)}
					<button
						type="button"
						class="lq-chip"
						data-active={chip === activeFormat}
						data-testid="lq-ai-format-chip"
						data-format={chip}
						aria-pressed={chip === activeFormat}
						on:click={() => setFormat(chip)}
					>
						{chipLabel(chip)}
					</button>
				{/each}
			</div>
			<div class="lq-chip-row" role="group" aria-label="Sort skills">
				<span class="lq-text-caption" style="color: var(--lq-text-tertiary);">Sort:</span>
				<button
					type="button"
					class="lq-chip"
					data-active={activeSort === 'recent'}
					data-testid="lq-ai-sort-recent"
					aria-pressed={activeSort === 'recent'}
					on:click={() => setSort('recent')}
				>
					Recently used
				</button>
				<button
					type="button"
					class="lq-chip"
					data-active={activeSort === 'name'}
					data-testid="lq-ai-sort-name"
					aria-pressed={activeSort === 'name'}
					on:click={() => setSort('name')}
				>
					A–Z
				</button>
			</div>
		</div>
	{/if}

	{#if !loading && builtins.length > 0}
		<section class="mb-6" data-testid="lq-ai-builtin-table-skills">
			<h2 class="lq-text-h4 mb-2">Built-in skills</h2>
			<p class="lq-text-caption mb-3" style="color: var(--lq-text-secondary);">
				Read-only skills that ship with LQ.AI. Open one to read its description
				(and column spec for table-mode skills), run it from the
				<a href="/lq-ai/tabular/new" class="lq-link">Tabular Review wizard</a>,
				or fork it into an editable copy of your own.
			</p>
			{#if visibleBuiltins.length === 0}
				<p class="lq-text-caption" style="color: var(--lq-text-tertiary);" data-testid="lq-ai-builtin-empty-filtered">
					No built-in skills match the "{chipLabel(activeFormat)}" filter.
				</p>
			{:else}
				<ul class="lq-table-skill-list">
					{#each visibleBuiltins as s (s.name)}
						<li class="lq-table-skill-card" data-testid="lq-ai-builtin-table-skill">
							<div class="flex items-start justify-between gap-3">
								<div class="min-w-0">
									<div class="flex items-center gap-2 flex-wrap">
										<a
											href={`/lq-ai/skills/${encodeURIComponent(s.name)}`}
											class="font-medium lq-text-body lq-link"
											data-testid="lq-ai-builtin-skill-link"
										>
											{s.title ?? s.name}
										</a>
										{#if normalizeFormat(s.output_format) !== FORMAT_PROSE}
											<span data-testid="lq-ai-table-badge">
												<TrustPill variant="tier" label={chipLabel(normalizeFormat(s.output_format))} />
											</span>
										{/if}
									</div>
									<code class="lq-text-caption font-mono" style="color: var(--lq-text-secondary);">{s.name}</code>
									{#if s.description}
										<p class="lq-text-caption mt-1 line-clamp-2" style="color: var(--lq-text-tertiary);">{s.description}</p>
									{/if}
								</div>
							</div>
						</li>
					{/each}
				</ul>
			{/if}
		</section>
	{/if}

	{#if loading}
		<p class="lq-text-body" style="color: var(--lq-text-secondary);">Loading…</p>
	{:else if rows.length === 0}
		<div
			class="lq-empty-state p-6 text-center"
		>
			<p class="lq-text-body" style="color: var(--lq-text-secondary);">You haven't created any skills yet.</p>
			<p class="mt-2 lq-text-body">
				<a href="/lq-ai/skills/new" class="lq-link">
					Create your first skill
				</a>
				, or fork a built-in from the picker.
			</p>
		</div>
	{:else if visibleRows.length === 0}
		<p
			class="lq-text-caption"
			style="color: var(--lq-text-tertiary);"
			data-testid="lq-ai-user-skills-empty-filtered"
		>
			None of your skills match the "{chipLabel(activeFormat)}" filter.
		</p>
	{:else}
		<div class="lq-table-wrap overflow-x-auto">
			<table class="min-w-full lq-text-body-sm">
				<thead class="lq-thead">
					<tr>
						<th class="text-left px-3 py-2 lq-text-label">Title</th>
						<th class="text-left px-3 py-2 lq-text-label">Slug</th>
						<th class="text-left px-3 py-2 lq-text-label">Scope</th>
						<th class="text-left px-3 py-2 lq-text-label">Version</th>
						<th class="text-left px-3 py-2 lq-text-label">Updated</th>
						<th class="text-right px-3 py-2 lq-text-label">Actions</th>
					</tr>
				</thead>
				<tbody class="lq-tbody">
					{#each visibleRows as row (row.id)}
						<tr data-testid="lq-ai-user-skill-row" data-scope={row.scope}>
							<td class="px-3 py-2" style="color: var(--lq-text);">
								<a
									href={`/lq-ai/skills/${encodeURIComponent(row.slug)}`}
									class="font-medium lq-link hover:underline"
								>
									{row.display_name}
								</a>
								{#if row.description}
									<div class="lq-text-caption mt-0.5 line-clamp-1" style="color: var(--lq-text-tertiary);">{row.description}</div>
								{/if}
							</td>
							<td class="px-3 py-2">
								<code class="lq-text-caption font-mono" style="color: var(--lq-text-secondary);">{row.slug}</code>
								{#if builtinSlugs.has(row.slug)}
									<span class="ml-2" data-testid="lq-ai-user-skill-shadow-chip">
										<TrustPill
											variant="tier"
											label="Shadows built-in"
										/>
									</span>
								{/if}
							</td>
							<td class="px-3 py-2">
								{#if row.scope === 'team'}
									<span data-testid="lq-ai-user-skill-team-chip" title="Team-scope skill — visible to every member of this team.">
										<TrustPill
											variant="tier"
											label={`Team · ${row.owner_team_id ? (teamNamesById.get(row.owner_team_id) ?? 'unknown') : 'unknown'}`}
										/>
									</span>
								{:else}
									<span class="lq-scope-personal" data-testid="lq-ai-user-skill-personal-chip">
										Personal
									</span>
								{/if}
							</td>
							<td class="px-3 py-2 lq-tabular lq-text-caption" style="color: var(--lq-text-secondary);">{row.version}</td>
							<td class="px-3 py-2 lq-text-caption" style="color: var(--lq-text-tertiary);">{shortDate(row.updated_at)}</td>
							<td class="px-3 py-2 text-right whitespace-nowrap">
								<a
									href={`/lq-ai/skills/${row.id}/edit`}
									class="lq-btn-secondary lq-text-caption"
								>
									Edit
								</a>
								<button
									type="button"
									class="ml-1 lq-btn-danger lq-text-caption"
									on:click={() => archive(row)}
									data-testid="lq-ai-user-skill-archive-btn"
								>
									Archive
								</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>

<style>
	/* DE-298 — filter / sort toolbar */
	.lq-browser-toolbar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem 1rem;
	}
	.lq-chip-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.375rem;
	}
	.lq-chip {
		padding: 2px 10px;
		border-radius: var(--lq-radius-pill);
		border: 1px solid var(--lq-border);
		background: var(--lq-surface);
		color: var(--lq-text-secondary);
		font-size: 12px;
		font-weight: 500;
		cursor: pointer;
	}
	.lq-chip:hover {
		background: var(--lq-inset);
	}
	.lq-chip[data-active='true'] {
		background: var(--lq-accent-soft, var(--lq-inset));
		border-color: var(--lq-accent, var(--lq-border));
		color: var(--lq-text);
	}

	.lq-table-skill-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: 0.5rem;
	}
	.lq-table-skill-card {
		padding: 0.75rem;
		border: 1px solid var(--lq-border);
		border-radius: 0.5rem;
		background: var(--lq-surface);
	}
	.lq-btn-primary {
		background: var(--lq-accent);
		color: white;
		border: 0;
		border-radius: var(--lq-radius);
		padding: 8px 16px;
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
		text-decoration: none;
		display: inline-flex;
		align-items: center;
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

	.lq-link {
		color: var(--lq-accent);
		text-decoration: none;
	}
	.lq-link:hover { text-decoration: underline; }

	.lq-empty-state {
		border-radius: var(--lq-radius-lg);
		border: 1px dashed var(--lq-border);
		padding: var(--lq-space-6);
	}

	.lq-table-wrap {
		border-radius: var(--lq-radius-lg);
		border: 1px solid var(--lq-border);
	}

	.lq-thead {
		background: var(--lq-inset);
	}

	.lq-tbody tr {
		border-top: 1px solid var(--lq-border);
	}

	.lq-scope-personal {
		display: inline-flex;
		align-items: center;
		padding: 2px 8px;
		border-radius: var(--lq-radius-pill);
		font-size: 11px;
		font-weight: 500;
		background: var(--lq-inset);
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
	}
</style>
