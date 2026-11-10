<script context="module" lang="ts">
	/**
	 * Pure helpers exported for unit tests. The DOM rendering below composes
	 * these — keeping the logic out of the Svelte template lets us validate it
	 * without @testing-library/svelte (the project doesn't depend on it; see
	 * CLAUDE.md "Don't add libraries without justification").
	 */
	import type { KnowledgeBase } from '$lib/lq-ai/types';

	export type SortKey = 'recent' | 'alphabetical' | 'most_attached' | 'indexing_status';

	/**
	 * Status-display roll-up. Backend's KnowledgeBase row carries an optional
	 * `ingestion_status` (M1 best-effort); when absent we fall back to
	 * file-count: a KB with zero files is `pending`, otherwise treat as
	 * `ready`. Keeps the badge truthful when the backend hasn't surfaced the
	 * field yet — a KB with files indexed is queryable even if the rollup
	 * is missing from the row.
	 */
	export function kbDisplayStatus(kb: KnowledgeBase): 'ready' | 'indexing' | 'failed' | 'pending' {
		if (kb.ingestion_status === 'ready') return 'ready';
		if (kb.ingestion_status === 'failed') return 'failed';
		if (kb.ingestion_status === 'processing' || kb.ingestion_status === 'pending') {
			return 'indexing';
		}
		return (kb.file_count ?? 0) > 0 ? 'ready' : 'pending';
	}

	/** Case-insensitive substring match on KB.name. Empty query → all KBs. */
	export function filterKBs(kbs: KnowledgeBase[], query: string): KnowledgeBase[] {
		const q = query.trim().toLowerCase();
		if (!q) return kbs;
		return kbs.filter((kb) => kb.name.toLowerCase().includes(q));
	}

	/**
	 * Sort KBs by the chosen key. Stable: ties fall back to alphabetical.
	 * `most_attached` uses `chunk_count` as the proxy for "how richly this KB
	 * has been used" since the backend doesn't track attach-count separately;
	 * `chunk_count` correlates directly with file volume and is a reasonable
	 * roll-up for the M1 surface (refine to true attach-count in v1.1+ when
	 * `project_knowledge_bases` aggregate is exposed).
	 */
	export function sortKBs(kbs: KnowledgeBase[], key: SortKey): KnowledgeBase[] {
		const copy = kbs.slice();
		const byName = (a: KnowledgeBase, b: KnowledgeBase) => a.name.localeCompare(b.name);

		switch (key) {
			case 'alphabetical':
				return copy.sort(byName);
			case 'most_attached':
				return copy.sort((a, b) => {
					const d = (b.chunk_count ?? 0) - (a.chunk_count ?? 0);
					return d !== 0 ? d : byName(a, b);
				});
			case 'indexing_status': {
				// ready first, indexing second, pending third, failed last
				const rank: Record<string, number> = {
					ready: 0,
					indexing: 1,
					pending: 2,
					failed: 3
				};
				return copy.sort((a, b) => {
					const d = rank[kbDisplayStatus(a)] - rank[kbDisplayStatus(b)];
					return d !== 0 ? d : byName(a, b);
				});
			}
			case 'recent':
			default:
				return copy.sort((a, b) => {
					const d = b.updated_at.localeCompare(a.updated_at);
					return d !== 0 ? d : byName(a, b);
				});
		}
	}

	/**
	 * Split a list of KBs into ones already attached to the matter and the
	 * rest, preserving order within each group. Drives the "currently
	 * attached" badge + Detach link on cards in the grid.
	 */
	export function splitAttached(
		kbs: KnowledgeBase[],
		attachedKbIds: string[]
	): { attached: KnowledgeBase[]; available: KnowledgeBase[] } {
		const attachedSet = new Set(attachedKbIds);
		const attached: KnowledgeBase[] = [];
		const available: KnowledgeBase[] = [];
		for (const kb of kbs) {
			if (attachedSet.has(kb.id)) attached.push(kb);
			else available.push(kb);
		}
		return { attached, available };
	}

	/** Display copy for the CTA — keeps grammatical agreement on count. */
	export function attachCtaLabel(selectedCount: number): string {
		if (selectedCount === 0) return 'Attach knowledge bases';
		if (selectedCount === 1) return 'Attach 1 selected';
		return `Attach ${selectedCount} selected`;
	}

	/** localStorage key for dismissing the first-time JIT banner. */
	export const JIT_BANNER_DISMISSED_KEY = 'lq_ai_jit_kb_attach_seen';
</script>

<script lang="ts">
	import { onMount } from 'svelte';
	import { listKnowledgeBases, createKnowledgeBase } from '$lib/lq-ai/api/knowledgeBases';
	import { attachKnowledgeBase, detachKnowledgeBase } from '$lib/lq-ai/api/projectKnowledgeBases';
	import { uploadFile } from '$lib/lq-ai/api/files';
	import InfoTip from './InfoTip.svelte';
	// `KnowledgeBase` is imported in the module script above; Svelte merges
	// the two script blocks at compile time, so re-importing here would
	// duplicate-identifier under svelte-check.

	export let open: boolean;
	export let projectId: string;
	export let attachedKbIds: string[];
	export let onClose: () => void;
	export let onAttach: (newlyAttachedKbIds: string[]) => void;
	export let onDetach: (kbId: string) => void;

	// ---- State ----------------------------------------------------------
	let kbs: KnowledgeBase[] = [];
	let loading = false;
	let loadError: string | null = null;
	let search = '';
	let sortKey: SortKey = 'recent';
	let selected = new Set<string>();
	let attaching = false;
	let attachError: string | null = null;
	let uploading = false;
	let uploadError: string | null = null;
	let bannerDismissed = false;
	let fileInput: HTMLInputElement | null = null;

	$: filtered = sortKBs(filterKBs(kbs, search), sortKey);
	$: ({ attached, available } = splitAttached(filtered, attachedKbIds));
	$: ctaLabel = attachCtaLabel(selected.size);

	// ---- Lifecycle ------------------------------------------------------
	async function loadKBs() {
		loading = true;
		loadError = null;
		try {
			kbs = await listKnowledgeBases();
		} catch (e: unknown) {
			loadError =
				e instanceof Error
					? (e.message ?? 'Failed to load knowledge bases.')
					: 'Failed to load knowledge bases.';
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		if (typeof window !== 'undefined') {
			try {
				bannerDismissed = window.localStorage.getItem(JIT_BANNER_DISMISSED_KEY) === '1';
			} catch {
				bannerDismissed = false;
			}
		}
	});

	// Reload + reset selection each time the modal opens.
	$: if (open) {
		selected = new Set<string>();
		attachError = null;
		void loadKBs();
	}

	// ---- Handlers -------------------------------------------------------
	function toggleSelected(id: string) {
		const next = new Set(selected);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		selected = next;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') onClose();
	}

	async function handleAttach() {
		if (selected.size === 0 || attaching) return;
		attaching = true;
		attachError = null;
		const ids = Array.from(selected);
		try {
			for (const kbId of ids) {
				await attachKnowledgeBase(projectId, kbId);
			}
			onAttach(ids);
			selected = new Set<string>();
		} catch (e: unknown) {
			attachError =
				e instanceof Error
					? (e.message ?? 'Failed to attach one or more knowledge bases.')
					: 'Failed to attach one or more knowledge bases.';
		} finally {
			attaching = false;
		}
	}

	async function handleDetach(kbId: string) {
		try {
			await detachKnowledgeBase(projectId, kbId);
			onDetach(kbId);
		} catch (e: unknown) {
			attachError =
				e instanceof Error
					? (e.message ?? 'Failed to detach knowledge base.')
					: 'Failed to detach knowledge base.';
		}
	}

	/**
	 * Minimum-viable inline uploader: create one KB named after the first
	 * file, upload all selected files to the matter, then attach each
	 * ready-status file to the new KB. The full upload-and-ingest poll loop
	 * is deferred to v1.1+ — the matter-rail "Knowledge" tab is where users
	 * will manage in-flight ingestion. This entry point's job is to get the
	 * KB created so the operator can finish the attach in one motion.
	 */
	async function handleFilesSelected(e: Event) {
		const inputEl = e.target as HTMLInputElement;
		const files = inputEl.files;
		if (!files || files.length === 0) return;

		uploading = true;
		uploadError = null;
		try {
			const firstName = files[0].name.replace(/\.[^.]+$/, '') || 'New KB';
			const newKB = await createKnowledgeBase({
				name: firstName,
				project_id: projectId
			});
			// Upload each file to the matter; KB-attach is best-effort and only
			// succeeds once ingestion_status='ready' (per OpenAPI 422 contract).
			// Surfacing failures inline keeps the operator in control without
			// blocking the modal.
			for (let i = 0; i < files.length; i++) {
				await uploadFile(files[i], { project_id: projectId });
			}
			kbs = [newKB, ...kbs];
			// Auto-select the just-created KB so the operator can hit "Attach"
			// immediately for the common single-file flow.
			const next = new Set(selected);
			next.add(newKB.id);
			selected = next;
		} catch (err: unknown) {
			uploadError =
				err instanceof Error
					? (err.message ?? 'Upload failed. Try again.')
					: 'Upload failed. Try again.';
		} finally {
			uploading = false;
			if (inputEl) inputEl.value = '';
		}
	}

	function dismissBanner() {
		bannerDismissed = true;
		if (typeof window !== 'undefined') {
			try {
				window.localStorage.setItem(JIT_BANNER_DISMISSED_KEY, '1');
			} catch {
				// localStorage unavailable (private mode / SSR) — best-effort dismiss
			}
		}
	}
</script>

{#if open}
	<div
		class="akm-backdrop"
		role="dialog"
		aria-modal="true"
		aria-labelledby="akm-title"
		tabindex="-1"
		on:click={onClose}
		on:keydown={handleKeydown}
	>
		<!-- svelte-ignore a11y-no-static-element-interactions -->
		<div class="akm-panel" on:click|stopPropagation on:keydown|stopPropagation>
			<header class="akm-header">
				<h2 id="akm-title" class="akm-title">
					Attach knowledge bases
					<InfoTip
						content="Knowledge bases are document collections you attach to a chat or matter. The AI can search and cite from them when answering. Documents are processed once at upload, then available across all your chats. You can attach multiple knowledge bases to a single matter."
					/>
				</h2>
				<button type="button" class="akm-close" aria-label="Close" on:click={onClose}>×</button>
			</header>

			<div class="akm-toolbar">
				<input type="text" class="akm-search" placeholder="Search by name…" bind:value={search} />
				<label class="akm-sort-label">
					<span class="akm-sr">Sort</span>
					<select class="akm-sort" bind:value={sortKey} aria-label="Sort">
						<option value="recent">Recently used</option>
						<option value="alphabetical">Alphabetical</option>
						<option value="most_attached">Most attached</option>
						<option value="indexing_status">Indexing status</option>
					</select>
				</label>
			</div>

			{#if !bannerDismissed}
				<div class="akm-banner" role="note">
					<span>
						Knowledge bases give your matter relevant context — they're searched alongside your
						prompt. You can attach more than one.
					</span>
					<button
						type="button"
						class="akm-banner-dismiss"
						on:click={dismissBanner}
						aria-label="Dismiss tip">×</button
					>
				</div>
			{/if}

			<div class="akm-body">
				{#if loading}
					<p class="akm-empty">Loading knowledge bases…</p>
				{:else if loadError}
					<p class="akm-error" role="alert">{loadError}</p>
				{:else if kbs.length === 0}
					<p class="akm-empty">No knowledge bases yet — upload a file below to create one.</p>
				{:else if filtered.length === 0}
					<p class="akm-empty">No KBs match "{search}".</p>
				{:else}
					<div class="akm-grid" role="list">
						{#each attached as kb (kb.id)}
							<article class="akm-card akm-card--attached" role="listitem">
								<h3 class="akm-card-name">{kb.name}</h3>
								<p class="akm-card-meta">
									{kb.file_count}
									{kb.file_count === 1 ? 'doc' : 'docs'}
									<span class="akm-status akm-status--{kbDisplayStatus(kb)}">
										{kbDisplayStatus(kb)}
									</span>
								</p>
								<div class="akm-card-foot">
									<span class="akm-badge-attached">currently attached</span>
									<button type="button" class="akm-link" on:click={() => handleDetach(kb.id)}
										>Detach</button
									>
								</div>
							</article>
						{/each}
						{#each available as kb (kb.id)}
							<label class="akm-card" role="listitem">
								<h3 class="akm-card-name">{kb.name}</h3>
								<p class="akm-card-meta">
									{kb.file_count}
									{kb.file_count === 1 ? 'doc' : 'docs'}
									<span class="akm-status akm-status--{kbDisplayStatus(kb)}">
										{kbDisplayStatus(kb)}
									</span>
								</p>
								<div class="akm-card-foot">
									<input
										type="checkbox"
										aria-label={`Select ${kb.name}`}
										checked={selected.has(kb.id)}
										on:change={() => toggleSelected(kb.id)}
									/>
								</div>
							</label>
						{/each}
					</div>
				{/if}

				<div class="akm-uploader">
					<div class="akm-uploader-divider">or upload a new KB</div>
					<button
						type="button"
						class="akm-uploader-btn"
						disabled={uploading}
						on:click={() => fileInput?.click()}
					>
						{uploading ? 'Uploading…' : 'Upload files…'}
					</button>
					<input
						type="file"
						bind:this={fileInput}
						multiple
						class="akm-file-input"
						on:change={handleFilesSelected}
					/>
					{#if uploadError}
						<p class="akm-error" role="alert">{uploadError}</p>
					{/if}
				</div>
			</div>

			{#if attachError}
				<p class="akm-error akm-error--footer" role="alert">{attachError}</p>
			{/if}

			<footer class="akm-actions">
				<button type="button" class="akm-btn-secondary" on:click={onClose} disabled={attaching}
					>Cancel</button
				>
				<button
					type="button"
					class="akm-btn-primary"
					on:click={handleAttach}
					disabled={selected.size === 0 || attaching}
				>
					{attaching ? 'Attaching…' : ctaLabel}
				</button>
			</footer>
		</div>
	</div>
{/if}

<style>
	.akm-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.35);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
	}

	.akm-panel {
		background: var(--lq-canvas);
		border-radius: var(--lq-radius-lg);
		padding: var(--lq-space-6);
		max-width: 800px;
		width: calc(100% - 32px);
		box-shadow: 0 24px 64px rgba(0, 0, 0, 0.18);
		max-height: calc(100vh - 64px);
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-4);
	}

	.akm-header {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		border-bottom: 1px solid var(--lq-border);
		padding-bottom: var(--lq-space-3);
	}

	.akm-title {
		margin: 0;
		font-size: 18px;
		font-weight: 600;
		color: var(--lq-text-primary);
	}

	.akm-close {
		background: transparent;
		border: 0;
		font-size: 20px;
		line-height: 1;
		color: var(--lq-text-secondary);
		cursor: pointer;
		padding: var(--lq-space-1) var(--lq-space-2);
	}

	.akm-toolbar {
		display: flex;
		gap: var(--lq-space-3);
		align-items: center;
	}

	.akm-search {
		flex: 1;
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-3);
		font-size: 14px;
		color: var(--lq-text-primary);
	}

	.akm-search:focus {
		outline: none;
		border-color: var(--lq-accent);
		box-shadow: 0 0 0 2px var(--lq-accent-soft);
	}

	.akm-sort-label {
		display: inline-flex;
		align-items: center;
	}

	.akm-sort {
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-3);
		font-size: 14px;
		color: var(--lq-text-primary);
	}

	.akm-sr {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}

	.akm-banner {
		background: var(--lq-accent-soft);
		border: 1px solid var(--lq-accent-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-3);
		color: var(--lq-text-primary);
		font-size: 13px;
		display: flex;
		gap: var(--lq-space-3);
		align-items: flex-start;
	}

	.akm-banner-dismiss {
		background: transparent;
		border: 0;
		font-size: 16px;
		line-height: 1;
		color: var(--lq-text-secondary);
		cursor: pointer;
		flex-shrink: 0;
	}

	.akm-body {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-4);
	}

	.akm-empty {
		color: var(--lq-text-tertiary);
		font-size: 14px;
		text-align: center;
		margin: var(--lq-space-4) 0;
	}

	.akm-error {
		color: var(--lq-danger);
		font-size: 13px;
		margin: 0;
	}

	.akm-error--footer {
		border: 1px solid var(--lq-danger-border);
		background: var(--lq-danger-soft);
		padding: var(--lq-space-2) var(--lq-space-3);
		border-radius: var(--lq-radius);
	}

	.akm-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
		gap: var(--lq-space-3);
	}

	.akm-card {
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-3);
		background: var(--lq-canvas);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
		cursor: pointer;
		transition:
			border-color 0.15s ease,
			background 0.15s ease;
	}

	.akm-card:hover {
		border-color: var(--lq-accent);
		background: var(--lq-inset);
	}

	.akm-card--attached {
		background: var(--lq-inset-secure);
		cursor: default;
	}

	.akm-card--attached:hover {
		border-color: var(--lq-border);
		background: var(--lq-inset-secure);
	}

	.akm-card-name {
		margin: 0;
		font-size: 14px;
		font-weight: 600;
		color: var(--lq-text-primary);
	}

	.akm-card-meta {
		margin: 0;
		font-size: 12px;
		color: var(--lq-text-secondary);
		display: flex;
		gap: var(--lq-space-2);
		align-items: center;
	}

	.akm-status {
		font-size: 11px;
		padding: 2px 8px;
		border-radius: var(--lq-radius-pill);
		text-transform: capitalize;
	}

	.akm-status--ready {
		background: var(--lq-accent-soft);
		color: var(--lq-accent);
	}

	.akm-status--indexing {
		background: var(--lq-warning-soft);
		color: var(--lq-warning);
	}

	.akm-status--pending {
		background: var(--lq-inset);
		color: var(--lq-text-tertiary);
	}

	.akm-status--failed {
		background: var(--lq-danger-soft);
		color: var(--lq-danger);
	}

	.akm-card-foot {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-top: auto;
	}

	.akm-badge-attached {
		font-size: 11px;
		color: var(--lq-accent);
		font-weight: 500;
	}

	.akm-link {
		background: transparent;
		border: 0;
		color: var(--lq-text-secondary);
		font-size: 12px;
		cursor: pointer;
		text-decoration: underline;
		padding: 0;
	}

	.akm-link:hover {
		color: var(--lq-text-primary);
	}

	.akm-uploader {
		border-top: 1px dashed var(--lq-border);
		padding-top: var(--lq-space-4);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.akm-uploader-divider {
		font-size: 12px;
		color: var(--lq-text-tertiary);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		text-align: center;
	}

	.akm-uploader-btn {
		align-self: flex-start;
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-pill);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-size: 14px;
		color: var(--lq-text-primary);
		cursor: pointer;
	}

	.akm-uploader-btn:hover:not(:disabled) {
		background: var(--lq-accent-soft);
		border-color: var(--lq-accent);
	}

	.akm-uploader-btn:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.akm-file-input {
		display: none;
	}

	.akm-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--lq-space-3);
		padding-top: var(--lq-space-3);
		border-top: 1px solid var(--lq-border);
	}

	.akm-btn-primary {
		background: var(--lq-accent);
		color: white;
		border: 0;
		border-radius: var(--lq-radius-pill);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-weight: 500;
		font-size: 14px;
		cursor: pointer;
	}

	.akm-btn-primary:hover:not(:disabled) {
		opacity: 0.85;
	}

	.akm-btn-primary:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}

	.akm-btn-secondary {
		background: transparent;
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-pill);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-weight: 500;
		font-size: 14px;
		cursor: pointer;
	}

	.akm-btn-secondary:hover:not(:disabled) {
		background: var(--lq-inset);
	}

	.akm-btn-secondary:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}
</style>
