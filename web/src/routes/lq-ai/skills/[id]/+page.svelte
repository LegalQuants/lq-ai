<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { skillsApi } from '$lib/lq-ai/api';
	import type { Skill } from '$lib/lq-ai/types';
	import { toolUsageNote } from '$lib/lq-ai/skills/toolUsageNote';
	import SkillDetailTabs from '$lib/lq-ai/components/SkillDetailTabs.svelte';
	import SkillSourceView from '$lib/lq-ai/components/SkillSourceView.svelte';
	import SkillTryItTab from '$lib/lq-ai/components/SkillTryItTab.svelte';
	import SkillVersionsTab from '$lib/lq-ai/components/SkillVersionsTab.svelte';

	type Tab = 'use' | 'source' | 'try' | 'versions';
	const VALID: Tab[] = ['use', 'source', 'try', 'versions'];

	let skill: Skill | null = null;
	let error: string | null = null;

	$: skillName = $page.params.id;
	// Wave D.2 Task 6.4 — drive activeTab from ?tab= so deep links land on
	// the right tab and back/forward navigation walks the tab history.
	$: activeTab = (
		VALID.includes($page.url.searchParams.get('tab') as Tab)
			? ($page.url.searchParams.get('tab') as Tab)
			: 'use'
	) as Tab;
	// C5 (PR6d) — derive tool-usage note reactively; never blocks UI.
	$: usageNote = toolUsageNote(skill?.tool_usage, skill?.unavailable_tool_usage);

	onMount(async () => {
		if (!skillName) return;
		try {
			skill = await skillsApi.getSkill(skillName);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load skill';
		}
	});

	function setTab(t: Tab): void {
		const url = new URL($page.url);
		url.searchParams.set('tab', t);
		// keepFocus preserves the focused tab button across the navigation;
		// replaceState:false adds a history entry so back/forward walks tabs.
		void goto(url.pathname + url.search, { keepFocus: true, replaceState: false });
	}
</script>

<main style="padding: var(--lq-space-6); max-width: 1100px; margin: 0 auto;">
	{#if error}
		<p class="lq-text-body" style="color: var(--lq-error);">Couldn't load skill: {error}</p>
	{:else if skill}
		<header style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: var(--lq-space-4);">
			<div>
				<h1 class="lq-text-page-h">{skill.title ?? skill.name}</h1>
				<p class="lq-text-caption" style="color: var(--lq-text-tertiary); margin-top: var(--lq-space-1);">
					{skill.name}{skill.version ? ` · v${skill.version}` : ''}
				</p>
			</div>
			<div style="display: flex; gap: 8px;">
				<a
					href={`/lq-ai/skills/new?fork=${encodeURIComponent(skill.name)}`}
					class="lq-btn-ghost"
					aria-label={`Fork ${skill.title ?? skill.name} as my own`}
				>🔱 Fork as my own</a>
				{#if skill.scope !== 'builtin'}
					<a href={`/lq-ai/skills/${encodeURIComponent(skill.name)}/edit`} class="lq-btn-primary">Edit</a>
				{/if}
			</div>
		</header>

		<SkillDetailTabs {activeTab} onTabChange={setTab} />

		<div style="margin-top: var(--lq-space-4);">
			{#if activeTab === 'use'}
				<article class="lq-text-body" style="white-space: pre-wrap;">
					{skill.description ?? '(no description)'}
				</article>
				{#if usageNote.uses.length > 0}
					<div class="lq-tool-usage" data-testid="skill-tool-usage">
						<span class="lq-tool-usage-label">Uses:</span> {usageNote.uses.join(', ')}
						{#if usageNote.warning}
							<p class="lq-tool-usage-warning" data-testid="skill-tool-usage-warning">⚠ {usageNote.warning}</p>
						{/if}
					</div>
				{/if}
			{:else if activeTab === 'source'}
				<SkillSourceView
					slug={skill.name}
					contentMd={skill.content_md}
					contentYaml={skill.content_yaml}
				/>
			{:else if activeTab === 'try'}
				<SkillTryItTab skillSlug={skill.name} />
			{:else if activeTab === 'versions'}
				<SkillVersionsTab {skill} />
			{/if}
		</div>
	{:else}
		<p class="lq-text-body" style="color: var(--lq-text-secondary);">Loading skill…</p>
	{/if}
</main>

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
		text-decoration: none;
		display: inline-flex;
		align-items: center;
	}
	.lq-btn-primary:hover {
		opacity: 0.9;
	}
	.lq-btn-ghost {
		background: transparent;
		color: #1f2937;
		border: 1px solid var(--lq-border, #e5e7eb);
		border-radius: var(--lq-radius);
		padding: 8px 16px;
		font-size: 14px;
		font-weight: 500;
		text-decoration: none;
		display: inline-flex;
		align-items: center;
	}
	.lq-btn-ghost:hover {
		background: var(--lq-accent-soft, #e8f4ec);
	}
	/* C5 (PR6d) — tool-usage metadata row */
	.lq-tool-usage {
		margin-top: var(--lq-space-3, 12px);
		font-size: 13px;
		color: var(--lq-text-secondary, #6b7280);
	}
	.lq-tool-usage-label {
		font-weight: 500;
		color: var(--lq-text-primary, #111827);
	}
	.lq-tool-usage-warning {
		margin-top: var(--lq-space-2, 8px);
		padding: 6px 10px;
		border-radius: var(--lq-radius, 6px);
		background: var(--lq-warning-soft, #fffbeb);
		border: 1px solid var(--lq-warning-border, #fcd34d);
		color: var(--lq-warning-text, #92400e);
		font-size: 13px;
	}
</style>
