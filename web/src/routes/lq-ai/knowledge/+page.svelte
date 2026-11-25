<script context="module" lang="ts">
	/**
	 * Pure helpers for the Knowledge list page — exported so vitest can
	 * exercise them without @testing-library/svelte (per CLAUDE.md "don't
	 * add libraries without justification").
	 */
	import type { KnowledgeBase } from '$lib/lq-ai/types';

	export type KBListStatus = 'indexed' | 'indexing' | 'empty' | 'failed';

	/**
	 * Roll-up status per the M1 frontend design spec ("✓ indexed / ⏳
	 * indexing N% / ⚠ failed"). Backend's KnowledgeBase row carries an
	 * optional `ingestion_status` (M1 best-effort, may be unset for many
	 * KBs); when absent we derive: `chunk_count > 0` → indexed,
	 * `file_count === 0` → empty, otherwise indexing.
	 *
	 * The "indexing N%" percentage is a v1.1+ refinement — the backend
	 * doesn't surface a per-KB progress fraction today (would require
	 * tracking `chunks_done / chunks_total` across files). We render the
	 * indicator without the percentage; the gap is documented here so a
	 * future Wave can wire it up without re-deriving the contract.
	 */
	export function kbListStatus(kb: KnowledgeBase): KBListStatus {
		if (kb.ingestion_status === 'failed') return 'failed';
		if (kb.ingestion_status === 'ready') return 'indexed';
		if (kb.ingestion_status === 'processing' || kb.ingestion_status === 'pending') {
			return 'indexing';
		}
		if ((kb.file_count ?? 0) === 0) return 'empty';
		return (kb.chunk_count ?? 0) > 0 ? 'indexed' : 'indexing';
	}

	export function kbStatusLabel(s: KBListStatus): string {
		switch (s) {
			case 'indexed':
				return '✓ indexed';
			case 'indexing':
				return '⏳ indexing';
			case 'failed':
				return '⚠ failed';
			case 'empty':
				return 'empty';
		}
	}
</script>

<script lang="ts">
	/**
	 * /lq-ai/knowledge — Knowledge surface list page (Wave C of the M1
	 * frontend redesign per docs/superpowers/specs/2026-05-10-m1-frontend-design.md).
	 *
	 * Card grid of the caller's knowledge bases with per-KB status pills,
	 * counts, and an inline "+ New KB" affordance. Empty state nudges
	 * toward creating the first KB. Each card links to `/lq-ai/knowledge/[id]`
	 * for the detail page (file list + upload + archive / delete).
	 */
	import { onMount } from 'svelte';

	import {
		listKnowledgeBases,
		createKnowledgeBase
	} from '$lib/lq-ai/api/knowledgeBases';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	// `KnowledgeBase` is imported in the module script above; Svelte merges
	// the two script blocks at compile time, so re-importing here would
	// duplicate-identifier under svelte-check (matches AttachKBModal pattern).

	let kbs: KnowledgeBase[] = [];
	let loading = false;
	let listError: string | null = null;

	let creating = false;
	let createError: string | null = null;
	let showCreateForm = false;
	let newName = '';
	let newDescription = '';

	async function load(): Promise<void> {
		loading = true;
		listError = null;
		try {
			kbs = await listKnowledgeBases();
		} catch (e) {
			console.error('lq-ai/knowledge: load failed', e);
			listError =
				e instanceof LQAIApiError
					? e.message
					: e instanceof Error
						? e.message
						: 'Failed to load knowledge bases.';
		} finally {
			loading = false;
		}
	}

	function shortDate(iso: string): string {
		try {
			return new Date(iso).toLocaleDateString();
		} catch {
			return iso;
		}
	}

	function truncate(s: string | null | undefined, max = 120): string {
		if (!s) return '';
		return s.length > max ? `${s.slice(0, max - 1)}…` : s;
	}

	function openCreate(): void {
		createError = null;
		newName = '';
		newDescription = '';
		showCreateForm = true;
	}

	function closeCreate(): void {
		showCreateForm = false;
	}

	async function handleCreate(): Promise<void> {
		const name = newName.trim();
		if (!name) {
			createError = 'Name is required.';
			return;
		}
		creating = true;
		createError = null;
		try {
			const created = await createKnowledgeBase({
				name,
				description: newDescription.trim() || null
			});
			kbs = [created, ...kbs];
			closeCreate();
		} catch (e) {
			console.error('lq-ai/knowledge: create failed', e);
			createError =
				e instanceof LQAIApiError
					? e.message
					: e instanceof Error
						? e.message
						: 'Failed to create knowledge base.';
		} finally {
			creating = false;
		}
	}

	onMount(load);
</script>

<main class="lq-knowledge-page" data-testid="lq-ai-knowledge-page">
	<header class="lq-page-header">
		<div>
			<h1 class="lq-text-page-h">Knowledge bases</h1>
			<p class="lq-text-body lq-page-intro">
				Curated collections of documents your matters can search alongside the
				prompt. Upload PDFs, attach them to a KB, and the hybrid retrieval
				surface (vector + full-text) handles the rest.
			</p>
		</div>
		<div class="lq-header-actions">
			<a href="/lq-ai" class="lq-btn-secondary">Back to chat</a>
			<button
				type="button"
				class="lq-btn-primary"
				on:click={openCreate}
				data-testid="lq-ai-knowledge-new-btn"
			>
				+ New KB
			</button>
		</div>
	</header>

	{#if showCreateForm}
		<section
			class="lq-create-card"
			aria-label="Create knowledge base"
			data-testid="lq-ai-knowledge-create-form"
		>
			<h2 class="lq-text-section-h">New knowledge base</h2>
			<label class="lq-field">
				<span class="lq-text-label">Name</span>
				<input
					type="text"
					bind:value={newName}
					placeholder="e.g. NDA precedent"
					maxlength="200"
					data-testid="lq-ai-knowledge-create-name"
				/>
			</label>
			<label class="lq-field">
				<span class="lq-text-label">Description (optional)</span>
				<textarea
					bind:value={newDescription}
					placeholder="What's in this KB? Where should it be used?"
					rows="2"
					maxlength="2000"
					data-testid="lq-ai-knowledge-create-description"
				></textarea>
			</label>
			{#if createError}
				<p class="lq-error" role="alert">{createError}</p>
			{/if}
			<div class="lq-create-actions">
				<button
					type="button"
					class="lq-btn-secondary"
					on:click={closeCreate}
					disabled={creating}
				>Cancel</button>
				<button
					type="button"
					class="lq-btn-primary"
					on:click={handleCreate}
					disabled={creating || !newName.trim()}
					data-testid="lq-ai-knowledge-create-submit"
				>
					{creating ? 'Creating…' : 'Create knowledge base'}
				</button>
			</div>
		</section>
	{/if}

	{#if listError}
		<p class="lq-error" role="alert">{listError}</p>
	{/if}

	{#if loading}
		<p class="lq-text-body" style="color: var(--lq-text-secondary);">Loading…</p>
	{:else if kbs.length === 0}
		<div class="lq-empty-state" data-testid="lq-ai-knowledge-empty">
			<p class="lq-text-body" style="color: var(--lq-text-secondary);">
				No knowledge bases yet. Create one to start collecting documents.
			</p>
			{#if !showCreateForm}
				<button
					type="button"
					class="lq-btn-primary"
					on:click={openCreate}
				>+ Create your first KB</button>
			{/if}
		</div>
	{:else}
		<div class="lq-kb-grid" data-testid="lq-ai-knowledge-grid">
			{#each kbs as kb (kb.id)}
				{@const status = kbListStatus(kb)}
				<a
					class="lq-kb-card"
					class:lq-kb-card--archived={!!kb.archived_at}
					href={`/lq-ai/knowledge/${encodeURIComponent(kb.id)}`}
					data-testid="lq-ai-knowledge-card"
					data-kb-status={status}
				>
					<header class="lq-kb-card-head">
						<h3 class="lq-kb-card-name">{kb.name}</h3>
						<span class="lq-kb-status lq-kb-status--{status}">
							{kbStatusLabel(status)}
						</span>
					</header>
					{#if kb.description}
						<p class="lq-kb-card-desc">{truncate(kb.description)}</p>
					{/if}
					<footer class="lq-kb-card-foot">
						<span class="lq-kb-meta">
							{kb.file_count} {kb.file_count === 1 ? 'doc' : 'docs'}
							·
							{kb.chunk_count} {kb.chunk_count === 1 ? 'chunk' : 'chunks'}
						</span>
						<span class="lq-kb-date">Updated {shortDate(kb.updated_at)}</span>
						{#if kb.archived_at}
							<span class="lq-kb-archived-pill">Archived</span>
						{/if}
					</footer>
				</a>
			{/each}
		</div>
	{/if}
</main>

<style>
	.lq-knowledge-page {
		padding: var(--lq-space-6);
		max-width: 1100px;
		margin: 0 auto;
	}

	.lq-page-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--lq-space-4);
		margin-bottom: var(--lq-space-5);
	}

	.lq-page-intro {
		color: var(--lq-text-secondary);
		margin-top: var(--lq-space-2);
		max-width: 64ch;
	}

	.lq-header-actions {
		display: flex;
		gap: var(--lq-space-2);
		flex-shrink: 0;
	}

	.lq-create-card {
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-lg);
		padding: var(--lq-space-4);
		margin-bottom: var(--lq-space-5);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
	}

	.lq-field {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-1);
	}

	.lq-field input,
	.lq-field textarea {
		background: var(--lq-canvas);
		border: 1px solid var(--lq-border-strong);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-3);
		font-size: 14px;
		color: var(--lq-text);
		font-family: inherit;
		resize: vertical;
	}

	.lq-field input:focus,
	.lq-field textarea:focus {
		outline: none;
		border-color: var(--lq-accent);
		box-shadow: 0 0 0 2px var(--lq-accent-soft);
	}

	.lq-create-actions {
		display: flex;
		gap: var(--lq-space-2);
		justify-content: flex-end;
	}

	.lq-error {
		color: var(--lq-error);
		background: var(--lq-error-soft);
		border: 1px solid var(--lq-error-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-3);
		font-size: 13px;
		margin: 0 0 var(--lq-space-3) 0;
	}

	.lq-empty-state {
		border-radius: var(--lq-radius-lg);
		border: 1px dashed var(--lq-border);
		padding: var(--lq-space-6);
		text-align: center;
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
		align-items: center;
	}

	.lq-kb-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: var(--lq-space-3);
	}

	.lq-kb-card {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
		padding: var(--lq-space-4);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-lg);
		background: var(--lq-canvas);
		text-decoration: none;
		color: var(--lq-text);
		transition: border-color 0.15s ease, transform 0.05s ease, box-shadow 0.15s ease;
	}

	.lq-kb-card:hover {
		border-color: var(--lq-accent);
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
	}

	.lq-kb-card:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}

	.lq-kb-card--archived {
		opacity: 0.65;
	}

	.lq-kb-card-head {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--lq-space-2);
	}

	.lq-kb-card-name {
		margin: 0;
		font-size: 15px;
		font-weight: 600;
		color: var(--lq-text);
	}

	.lq-kb-card-desc {
		margin: 0;
		font-size: 13px;
		color: var(--lq-text-secondary);
		line-height: 1.4;
	}

	.lq-kb-card-foot {
		display: flex;
		gap: var(--lq-space-2);
		flex-wrap: wrap;
		align-items: center;
		margin-top: auto;
		padding-top: var(--lq-space-2);
		font-size: 12px;
		color: var(--lq-text-tertiary);
	}

	.lq-kb-meta {
		color: var(--lq-text-secondary);
	}

	.lq-kb-date {
		margin-left: auto;
	}

	.lq-kb-archived-pill {
		background: var(--lq-inset);
		color: var(--lq-text-tertiary);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-pill);
		padding: 1px 8px;
		font-size: 11px;
	}

	.lq-kb-status {
		font-size: 11px;
		padding: 2px 8px;
		border-radius: var(--lq-radius-pill);
		white-space: nowrap;
		flex-shrink: 0;
	}

	.lq-kb-status--indexed {
		background: var(--lq-accent-soft);
		color: var(--lq-accent);
		border: 1px solid var(--lq-accent-border);
	}

	.lq-kb-status--indexing {
		background: var(--lq-warn-soft);
		color: var(--lq-warn);
		border: 1px solid var(--lq-warn-border);
	}

	.lq-kb-status--failed {
		background: var(--lq-error-soft);
		color: var(--lq-error);
		border: 1px solid var(--lq-error-border);
	}

	.lq-kb-status--empty {
		background: var(--lq-inset);
		color: var(--lq-text-tertiary);
		border: 1px solid var(--lq-border);
	}

	.lq-btn-primary {
		background: var(--lq-accent);
		color: white;
		border: 0;
		border-radius: var(--lq-radius-pill);
		padding: 8px 16px;
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
		text-decoration: none;
		display: inline-flex;
		align-items: center;
	}

	.lq-btn-primary:hover:not(:disabled) {
		opacity: 0.85;
	}

	.lq-btn-primary:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}

	.lq-btn-secondary {
		background: transparent;
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-pill);
		padding: 6px 12px;
		font-size: 13px;
		cursor: pointer;
		text-decoration: none;
		display: inline-flex;
		align-items: center;
	}

	.lq-btn-secondary:hover:not(:disabled) {
		background: var(--lq-inset);
	}

	.lq-btn-secondary:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}
</style>
