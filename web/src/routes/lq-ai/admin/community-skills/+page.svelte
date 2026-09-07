<script lang="ts">
	/**
	 * /lq-ai/admin/community-skills — DE-263 community skill installer.
	 *
	 * Catalog list (search + attestation state + installed indication) →
	 * detail panel with the FULL SKILL.md body and raw frontmatter
	 * (transparency principle: the operator reviews the actual work
	 * product before installing) → install with confirm dialog.
	 *
	 * The catalog is served from the local `skills/community` submodule
	 * checkout (ADR 0027) — never a network fetch. Refresh path:
	 * `git submodule update --remote skills/community` on the host.
	 */
	import { onMount } from 'svelte';

	import { communitySkillsApi } from '$lib/lq-ai/api';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import type {
		CommunityCatalogResponse,
		CommunitySkillDetail
	} from '$lib/lq-ai/api/communitySkills';
	import {
		attestationLabel,
		catalogEmptyMessage,
		filterCatalog,
		installButtonState,
		installConfirmMessage,
		shortSha
	} from './page-helpers';

	let catalog: CommunityCatalogResponse | null = null;
	let loading = false;
	let listError: string | null = null;
	let actionError: string | null = null;
	let actionSuccess: string | null = null;

	let query = '';
	let detail: CommunitySkillDetail | null = null;
	let detailError: string | null = null;
	let detailLoadingSlug: string | null = null;
	let pendingInstallSlug: string | null = null;

	$: visibleItems = catalog ? filterCatalog(catalog.items, query) : [];
	$: emptyMessage = catalogEmptyMessage(catalog, visibleItems.length, query);

	onMount(load);

	async function load(): Promise<void> {
		loading = true;
		listError = null;
		try {
			catalog = await communitySkillsApi.listCommunitySkills();
		} catch (err) {
			if (err instanceof LQAIApiError && err.status === 403) {
				listError = 'You need admin access to view the community skill catalog.';
			} else {
				listError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			loading = false;
		}
	}

	async function openDetail(slug: string): Promise<void> {
		detailLoadingSlug = slug;
		detailError = null;
		actionError = null;
		actionSuccess = null;
		try {
			detail = await communitySkillsApi.getCommunitySkill(slug);
		} catch (err) {
			detail = null;
			detailError = err instanceof Error ? err.message : String(err);
		} finally {
			detailLoadingSlug = null;
		}
	}

	function closeDetail(): void {
		detail = null;
		detailError = null;
	}

	async function install(d: CommunitySkillDetail): Promise<void> {
		const confirmed = confirm(installConfirmMessage(d));
		if (!confirmed) return;
		pendingInstallSlug = d.slug;
		actionError = null;
		actionSuccess = null;
		try {
			await communitySkillsApi.installCommunitySkill(d.slug);
			actionSuccess =
				`Installed "${d.title}" as an editable copy owned by you ` +
				`(provenance: ${d.install_ref}). Manage it under your skills.`;
			closeDetail();
			await load();
		} catch (err) {
			actionError = err instanceof Error ? err.message : String(err);
		} finally {
			pendingInstallSlug = null;
		}
	}
</script>

<div class="community-skills-page">
	<header class="page-header">
		<h1 class="lq-text-page-h">Community skills</h1>
		<p class="page-intro">
			Browse and install skills from the community catalog (the local
			<code>skills/community</code> submodule — served from disk, never fetched over the network; see
			ADR 0027). Installing creates an editable copy owned by you with its provenance recorded. Community
			skills are attested at their source repo; this page shows exactly what each SKILL.md declares.
		</p>
		{#if catalog}
			<p class="source-line">
				Catalog: <code>{catalog.source.path}</code> @ <code>{shortSha(catalog.source.sha)}</code>
				— refresh with <code>git submodule update --remote skills/community</code>
			</p>
		{/if}
	</header>

	{#if listError}
		<div class="error-banner" role="alert">{listError}</div>
	{/if}
	{#if actionError}
		<div class="error-banner" role="alert">{actionError}</div>
	{/if}
	{#if actionSuccess}
		<div class="success-banner" role="status">{actionSuccess}</div>
	{/if}

	{#if catalog && catalog.load_errors.length > 0}
		<div class="warn-banner" role="alert">
			<strong
				>{catalog.load_errors.length} catalog entr{catalog.load_errors.length === 1 ? 'y' : 'ies'} failed
				to parse and cannot be installed:</strong
			>
			<ul class="load-error-list">
				{#each catalog.load_errors as err}
					<li><code>{err}</code></li>
				{/each}
			</ul>
		</div>
	{/if}

	{#if loading && catalog === null}
		<p class="loading">Loading community catalog…</p>
	{/if}

	{#if catalog}
		<div class="search-row">
			<input
				type="search"
				class="search-input"
				placeholder="Search by slug, title, description, or tag…"
				aria-label="Search community skills"
				bind:value={query}
			/>
		</div>

		{#if emptyMessage}
			<p class="empty-state">{emptyMessage}</p>
		{/if}

		{#if visibleItems.length > 0}
			<table class="catalog-table">
				<thead>
					<tr>
						<th>Skill</th>
						<th>Version</th>
						<th>Tags</th>
						<th>Attestation</th>
						<th class="catalog-table-actions">Actions</th>
					</tr>
				</thead>
				<tbody>
					{#each visibleItems as item (item.slug)}
						<tr>
							<td>
								<div class="skill-title">
									{item.title}
									{#if item.installed}
										<span class="installed-badge">Installed</span>
									{/if}
								</div>
								<div class="skill-slug"><code>{item.slug}</code></div>
								<div class="skill-description">{item.description}</div>
							</td>
							<td><code>{item.version}</code></td>
							<td>
								{#each item.tags as tag}
									<span class="tag-chip">{tag}</span>
								{/each}
							</td>
							<td class="attestation-cell" class:attestation-none={!item.attested_by}>
								{attestationLabel(item.attested_by)}
							</td>
							<td class="catalog-table-actions">
								<button
									type="button"
									class="action-button"
									on:click={() => openDetail(item.slug)}
									disabled={detailLoadingSlug === item.slug}
								>
									{detailLoadingSlug === item.slug ? 'Loading…' : 'Review'}
								</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	{/if}

	{#if detailError}
		<div class="error-banner" role="alert">{detailError}</div>
	{/if}

	{#if detail}
		<section class="detail-panel" aria-label="Community skill detail">
			<div class="detail-head">
				<div>
					<h2 class="detail-title">
						{detail.title}
						{#if detail.installed}
							<span class="installed-badge">Installed</span>
						{/if}
					</h2>
					<p class="detail-meta">
						<code>{detail.slug}</code> · v{detail.version}
						{#if detail.author}
							· by {detail.author}{/if}
						{#if detail.jurisdiction}
							· jurisdiction: {detail.jurisdiction}{/if}
					</p>
					<p class="detail-meta" class:attestation-none={!detail.attested_by}>
						{attestationLabel(detail.attested_by)}
					</p>
					<p class="detail-meta">Install provenance: <code>{detail.install_ref}</code></p>
				</div>
				<div class="detail-actions">
					<button
						type="button"
						class="install-button"
						on:click={() => detail && install(detail)}
						disabled={installButtonState(detail, pendingInstallSlug).disabled}
					>
						{installButtonState(detail, pendingInstallSlug).label}
					</button>
					<button type="button" class="action-button" on:click={closeDetail}>Close</button>
				</div>
			</div>

			<h3 class="detail-section-title">SKILL.md frontmatter</h3>
			<pre class="skill-source">{detail.content_yaml}</pre>

			<h3 class="detail-section-title">SKILL.md body</h3>
			<pre class="skill-source">{detail.content_md}</pre>
		</section>
	{/if}
</div>

<style>
	.community-skills-page {
		padding: var(--lq-space-5);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-4);
	}

	.page-header {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.page-intro {
		color: var(--lq-text-secondary);
		max-width: 60rem;
		font-size: 14px;
		line-height: 1.5;
	}

	.source-line {
		color: var(--lq-text-secondary);
		font-size: 13px;
	}

	.error-banner {
		padding: var(--lq-space-3) var(--lq-space-4);
		background: var(--lq-error-bg, #fee);
		color: var(--lq-error-text, #800);
		border-radius: 6px;
		border: 1px solid var(--lq-error-border, #fbb);
	}

	.warn-banner {
		padding: var(--lq-space-3) var(--lq-space-4);
		background: var(--lq-warning-bg, #fff8e1);
		color: var(--lq-warning-text, #7a5c00);
		border-radius: 6px;
		border: 1px solid var(--lq-warning-border, #f0d78c);
		font-size: 13px;
	}

	.load-error-list {
		margin: var(--lq-space-2) 0 0;
		padding-left: var(--lq-space-4);
	}

	.success-banner {
		padding: var(--lq-space-3) var(--lq-space-4);
		background: var(--lq-success-bg, #efe);
		color: var(--lq-success-text, #060);
		border-radius: 6px;
		border: 1px solid var(--lq-success-border, #bfb);
	}

	.loading {
		color: var(--lq-text-secondary);
		padding: var(--lq-space-3);
	}

	.search-row {
		display: flex;
	}

	.search-input {
		flex: 1;
		max-width: 32rem;
		padding: var(--lq-space-2) var(--lq-space-3);
		border: 1px solid var(--lq-border);
		border-radius: 6px;
		background: var(--lq-bg, #fff);
		font-size: 14px;
	}

	.empty-state {
		color: var(--lq-text-secondary);
		font-style: italic;
		margin: 0;
	}

	.catalog-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 14px;
	}

	.catalog-table th,
	.catalog-table td {
		text-align: left;
		padding: var(--lq-space-2) var(--lq-space-3);
		border-bottom: 1px solid var(--lq-border);
		vertical-align: top;
	}

	.catalog-table th {
		font-weight: 600;
		color: var(--lq-text-secondary);
		font-size: 12px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.catalog-table-actions {
		text-align: right;
		width: 1px;
		white-space: nowrap;
	}

	.skill-title {
		font-weight: 600;
		display: flex;
		align-items: center;
		gap: var(--lq-space-2);
	}

	.skill-slug {
		font-size: 12px;
		color: var(--lq-text-secondary);
	}

	.skill-description {
		font-size: 13px;
		color: var(--lq-text-secondary);
		max-width: 36rem;
	}

	.tag-chip {
		display: inline-block;
		padding: 1px var(--lq-space-2);
		margin: 1px;
		border-radius: 999px;
		border: 1px solid var(--lq-border);
		font-size: 12px;
		color: var(--lq-text-secondary);
	}

	.attestation-cell {
		font-size: 13px;
		max-width: 16rem;
	}

	.attestation-none {
		color: var(--lq-text-secondary);
		font-style: italic;
	}

	.installed-badge {
		display: inline-block;
		padding: 1px var(--lq-space-2);
		border-radius: 999px;
		background: var(--lq-success-bg, #efe);
		color: var(--lq-success-text, #060);
		border: 1px solid var(--lq-success-border, #bfb);
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.action-button {
		padding: var(--lq-space-1) var(--lq-space-3);
		border-radius: 6px;
		font-size: 13px;
		cursor: pointer;
		border: 1px solid var(--lq-border);
		background: transparent;
		color: var(--lq-text);
	}

	.action-button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.install-button {
		padding: var(--lq-space-2) var(--lq-space-4);
		background: var(--lq-accent);
		color: white;
		border: none;
		border-radius: 6px;
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
	}

	.install-button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.detail-panel {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
		padding: var(--lq-space-4);
		border: 1px solid var(--lq-border);
		border-radius: 8px;
		background: var(--lq-surface);
	}

	.detail-head {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--lq-space-4);
		flex-wrap: wrap;
	}

	.detail-title {
		margin: 0;
		font-size: 18px;
		font-weight: 600;
		display: flex;
		align-items: center;
		gap: var(--lq-space-2);
	}

	.detail-meta {
		margin: var(--lq-space-1) 0 0;
		font-size: 13px;
		color: var(--lq-text-secondary);
	}

	.detail-actions {
		display: flex;
		gap: var(--lq-space-2);
		align-items: center;
	}

	.detail-section-title {
		margin: var(--lq-space-2) 0 0;
		font-size: 14px;
		font-weight: 600;
	}

	.skill-source {
		margin: 0;
		padding: var(--lq-space-3);
		border: 1px solid var(--lq-border);
		border-radius: 6px;
		background: var(--lq-bg, #fff);
		font-size: 12.5px;
		line-height: 1.5;
		white-space: pre-wrap;
		word-break: break-word;
		max-height: 32rem;
		overflow: auto;
	}
</style>
