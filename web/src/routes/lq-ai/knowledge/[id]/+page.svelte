<script context="module" lang="ts">
	/**
	 * Pure helpers for the Knowledge detail page — exported for vitest
	 * coverage of the per-doc status-pill mapping (matches the list
	 * page's helper-export pattern).
	 */
	import type { KnowledgeBaseFile } from '$lib/lq-ai/types';

	/**
	 * Effective per-row status combining the file-level `ingestion_status`
	 * (parse pipeline) with the M3-0.3 / DE-276 document-level
	 * `ingest_status` (embed pipeline). A file at `ingestion_status=ready`
	 * whose document is `embed_failed` or `partial` surfaces with the
	 * more-severe document-level state.
	 */
	export type DocStatus =
		| 'ready'
		| 'processing'
		| 'pending'
		| 'failed'
		| 'embed_failed'
		| 'partial';

	export function docStatusLabel(s: DocStatus): string {
		switch (s) {
			case 'ready':
				return '✓ ready';
			case 'processing':
				return '⏳ processing';
			case 'pending':
				return '⏳ pending';
			case 'failed':
				return '⚠ failed';
			case 'embed_failed':
				return '⚠ embed failed';
			case 'partial':
				return '⚠ partial embed';
		}
	}

	/** Resolve the effective per-row status for the doc-list pill. */
	export function effectiveStatus(file: KnowledgeBaseFile): DocStatus {
		if (file.ingestion_status !== 'ready') return file.ingestion_status as DocStatus;
		if (file.ingest_status === 'embed_failed' || file.ingest_status === 'partial') {
			return file.ingest_status;
		}
		return 'ready';
	}

	/** Failure-reason string for the effective status, or null when there's no failure. */
	export function effectiveFailureReason(file: KnowledgeBaseFile): string | null {
		const s = effectiveStatus(file);
		if (s === 'failed') return file.ingestion_error ?? null;
		if (s === 'embed_failed' || s === 'partial') return file.ingest_failure_reason ?? null;
		return null;
	}

	/** Human-readable file size; binary units (1 KiB = 1024 bytes). */
	export function formatBytes(n: number): string {
		if (!Number.isFinite(n) || n < 0) return '—';
		if (n < 1024) return `${n} B`;
		const units = ['KB', 'MB', 'GB', 'TB'];
		let v = n / 1024;
		let i = 0;
		while (v >= 1024 && i < units.length - 1) {
			v /= 1024;
			i += 1;
		}
		return `${v.toFixed(v >= 10 ? 0 : 1)} ${units[i]}`;
	}

	/** Stable sort: ready first, then in-flight, failure states last; tie-break on filename. */
	export function sortFiles(files: KnowledgeBaseFile[]): KnowledgeBaseFile[] {
		const rank: Record<string, number> = {
			ready: 0,
			processing: 1,
			pending: 2,
			partial: 3,
			embed_failed: 4,
			failed: 5
		};
		return [...files].sort((a, b) => {
			const d = (rank[effectiveStatus(a)] ?? 9) - (rank[effectiveStatus(b)] ?? 9);
			return d !== 0 ? d : a.filename.localeCompare(b.filename);
		});
	}
</script>

<script lang="ts">
	/**
	 * /lq-ai/knowledge/[id] — Knowledge detail page (Wave C of the M1
	 * frontend redesign per docs/superpowers/specs/2026-05-10-m1-frontend-design.md).
	 *
	 * Surfaces:
	 *  - KB header (name, description, counts, archived state)
	 *  - Doc list (filename, ingestion status, size, attached_at) with
	 *    per-row Detach
	 *  - Upload affordance: single-file pick → POST /files →
	 *    POST /knowledge-bases/{id}/files (only when ingestion_status===ready)
	 *  - Archive / unarchive + Delete (archive cycle via PATCH archived,
	 *    Delete via DELETE; KB delete is a soft-delete archive on the backend).
	 *
	 * Pattern-matches /lq-ai/skills/[id]/+page.svelte for the header.
	 */
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	import {
		getKnowledgeBase,
		listKnowledgeBaseFiles,
		attachFileToKB,
		detachFileFromKB
	} from '$lib/lq-ai/api/knowledgeBases';
	import { uploadFile, getFile } from '$lib/lq-ai/api/files';
	import { apiRequest, LQAIApiError } from '$lib/lq-ai/api/client';
	import type { KnowledgeBase as KB, KnowledgeBaseFile as KBFile } from '$lib/lq-ai/types';

	let kb: KB | null = null;
	let files: KBFile[] = [];
	let loadError: string | null = null;
	let actionError: string | null = null;
	let loading = false;

	let uploading = false;
	let uploadStatus: string | null = null;
	let fileInput: HTMLInputElement | null = null;

	let archiving = false;
	let deleting = false;

	$: kbId = $page.params.id;
	$: sortedFiles = sortFiles(files);

	async function load(): Promise<void> {
		if (!kbId) return;
		loading = true;
		loadError = null;
		try {
			const [kbRow, fileRows] = await Promise.all([
				getKnowledgeBase(kbId),
				listKnowledgeBaseFiles(kbId)
			]);
			kb = kbRow;
			files = fileRows;
		} catch (e) {
			console.error('lq-ai/knowledge/[id]: load failed', e);
			loadError =
				e instanceof LQAIApiError
					? e.message
					: e instanceof Error
						? e.message
						: 'Failed to load knowledge base.';
		} finally {
			loading = false;
		}
	}

	function shortDateTime(iso: string): string {
		try {
			return new Date(iso).toLocaleString();
		} catch {
			return iso;
		}
	}

	/**
	 * Wait briefly for the C5 ingest pipeline to flip the file from
	 * `pending` / `processing` to `ready` so the attach POST doesn't
	 * 422. Polls every 1s up to ~30s; gives up gracefully on timeout
	 * (the file row remains uploaded but unattached — operator can
	 * retry by uploading again or attach via the matter rail later).
	 * Best-effort UX shim; the backend's authoritative ingest path is
	 * unchanged.
	 */
	async function waitForReady(fileId: string, maxAttempts = 30): Promise<boolean> {
		for (let i = 0; i < maxAttempts; i += 1) {
			try {
				const fresh = await getFile(fileId);
				if (fresh.ingestion_status === 'ready') return true;
				if (fresh.ingestion_status === 'failed') return false;
			} catch {
				return false;
			}
			await new Promise((r) => setTimeout(r, 1000));
		}
		return false;
	}

	async function handleFileSelected(e: Event): Promise<void> {
		const inputEl = e.target as HTMLInputElement;
		const picked = inputEl.files?.[0];
		if (!picked || !kb) return;

		uploading = true;
		uploadStatus = `Uploading ${picked.name}…`;
		actionError = null;
		try {
			const meta = await uploadFile(picked);
			uploadStatus = `Indexing ${picked.name}…`;
			const ready = await waitForReady(meta.id);
			if (!ready) {
				actionError =
					`Upload finished but ingestion didn't complete in time. Refresh in a moment to retry the attach.`;
				uploadStatus = null;
				return;
			}
			uploadStatus = `Attaching ${picked.name}…`;
			await attachFileToKB(kb.id, meta.id);
			uploadStatus = null;
			await load();
		} catch (err) {
			console.error('lq-ai/knowledge/[id]: upload+attach failed', err);
			actionError =
				err instanceof LQAIApiError
					? err.message
					: err instanceof Error
						? err.message
						: 'Upload failed.';
			uploadStatus = null;
		} finally {
			uploading = false;
			if (inputEl) inputEl.value = '';
		}
	}

	async function handleDetach(file: KBFile): Promise<void> {
		if (!kb) return;
		const confirmed = window.confirm(
			`Detach "${file.filename}" from this knowledge base? The file itself stays in your account; only the KB attachment is removed.`
		);
		if (!confirmed) return;
		actionError = null;
		try {
			await detachFileFromKB(kb.id, file.id);
			files = files.filter((f) => f.id !== file.id);
			// Refresh the KB row so file_count / chunk_count stay accurate.
			try {
				kb = await getKnowledgeBase(kb.id);
			} catch {
				/* counts will recover on next full load */
			}
		} catch (e) {
			actionError = e instanceof Error ? e.message : 'Failed to detach file.';
		}
	}

	async function handleArchiveToggle(): Promise<void> {
		if (!kb) return;
		const wantArchived = !kb.archived_at;
		const confirmed = window.confirm(
			wantArchived
				? `Archive "${kb.name}"? Archived KBs stop appearing in attach pickers but remain queryable from any matter still using them.`
				: `Unarchive "${kb.name}"? It'll show up in the attach picker again.`
		);
		if (!confirmed) return;
		archiving = true;
		actionError = null;
		try {
			const updated = await apiRequest<KB>(
				`/knowledge-bases/${encodeURIComponent(kb.id)}`,
				{ method: 'PATCH', body: { archived: wantArchived } }
			);
			kb = updated;
		} catch (e) {
			actionError = e instanceof Error ? e.message : 'Failed to update archive state.';
		} finally {
			archiving = false;
		}
	}

	async function handleDelete(): Promise<void> {
		if (!kb) return;
		const confirmed = window.confirm(
			`Delete "${kb.name}"? This soft-deletes the KB (it's removed from listings but recoverable by an operator). Files attached to the KB are not deleted.`
		);
		if (!confirmed) return;
		deleting = true;
		actionError = null;
		try {
			await apiRequest<void>(`/knowledge-bases/${encodeURIComponent(kb.id)}`, {
				method: 'DELETE'
			});
			void goto('/lq-ai/knowledge');
		} catch (e) {
			actionError = e instanceof Error ? e.message : 'Failed to delete KB.';
			deleting = false;
		}
	}

	onMount(load);
</script>

<main class="lq-kb-detail" data-testid="lq-ai-knowledge-detail-page">
	{#if loadError}
		<p class="lq-error" role="alert">Couldn't load knowledge base: {loadError}</p>
		<p>
			<a href="/lq-ai/knowledge" class="lq-link">← Back to knowledge bases</a>
		</p>
	{:else if loading && !kb}
		<p class="lq-text-body" style="color: var(--lq-text-secondary);">Loading knowledge base…</p>
	{:else if kb}
		<header class="lq-kb-header">
			<div>
				<p class="lq-text-caption">
					<a href="/lq-ai/knowledge" class="lq-link">← Knowledge bases</a>
				</p>
				<h1 class="lq-text-page-h">
					{kb.name}
					{#if kb.archived_at}
						<span class="lq-archived-pill" data-testid="lq-ai-knowledge-archived-pill">
							Archived
						</span>
					{/if}
				</h1>
				{#if kb.description}
					<p class="lq-kb-desc">{kb.description}</p>
				{/if}
				<p class="lq-kb-meta">
					{kb.file_count} {kb.file_count === 1 ? 'doc' : 'docs'}
					·
					{kb.chunk_count} {kb.chunk_count === 1 ? 'chunk' : 'chunks'}
					·
					hybrid alpha {kb.hybrid_alpha.toFixed(2)}
				</p>
			</div>
			<div class="lq-kb-actions">
				<button
					type="button"
					class="lq-btn-secondary"
					on:click={handleArchiveToggle}
					disabled={archiving || deleting}
					data-testid="lq-ai-knowledge-archive-btn"
				>
					{archiving ? '…' : kb.archived_at ? 'Unarchive' : 'Archive'}
				</button>
				<button
					type="button"
					class="lq-btn-danger"
					on:click={handleDelete}
					disabled={deleting || archiving}
					data-testid="lq-ai-knowledge-delete-btn"
				>
					{deleting ? '…' : 'Delete'}
				</button>
			</div>
		</header>

		{#if actionError}
			<p class="lq-error" role="alert">{actionError}</p>
		{/if}

		<section class="lq-kb-section" aria-label="Upload document">
			<div class="lq-upload-card">
				<div>
					<h2 class="lq-text-section-h">Upload a document</h2>
					<p class="lq-text-caption" style="color: var(--lq-text-tertiary); margin: 4px 0 0 0;">
						PDF only for v0.1.0. After upload finishes the document is
						parsed + chunked + indexed before being attached to this KB.
					</p>
				</div>
				<div class="lq-upload-actions">
					<button
						type="button"
						class="lq-btn-primary"
						on:click={() => fileInput?.click()}
						disabled={uploading}
						data-testid="lq-ai-knowledge-upload-btn"
					>
						{uploading ? (uploadStatus ?? 'Uploading…') : 'Upload & attach'}
					</button>
					<input
						type="file"
						accept="application/pdf,.pdf"
						bind:this={fileInput}
						on:change={handleFileSelected}
						class="lq-file-input"
					/>
				</div>
			</div>
		</section>

		<section class="lq-kb-section" aria-label="Documents in this knowledge base">
			<div class="lq-section-head">
				<h2 class="lq-text-section-h">Documents</h2>
			</div>

			{#if files.length === 0}
				<div class="lq-empty-state">
					<p class="lq-text-body" style="color: var(--lq-text-secondary);">
						No documents yet. Upload one to seed this knowledge base.
					</p>
				</div>
			{:else}
				<div class="lq-table-wrap">
					<table class="lq-doc-table">
						<thead>
							<tr>
								<th class="lq-text-label">Filename</th>
								<th class="lq-text-label">Status</th>
								<th class="lq-text-label">Size</th>
								<th class="lq-text-label">Pages</th>
								<th class="lq-text-label">Attached</th>
								<th class="lq-text-label" style="text-align: right;">Actions</th>
							</tr>
						</thead>
						<tbody>
							{#each sortedFiles as file (file.id)}
								<tr
									data-testid="lq-ai-knowledge-doc-row"
									data-doc-status={effectiveStatus(file)}
								>
									<td class="lq-doc-filename">{file.filename}</td>
									<td>
										<span class="lq-doc-status lq-doc-status--{effectiveStatus(file)}">
											{docStatusLabel(effectiveStatus(file))}
										</span>
										{#if effectiveFailureReason(file)}
											<div class="lq-doc-error" data-testid="lq-ai-doc-failure-reason">
												{effectiveFailureReason(file)}
											</div>
										{/if}
									</td>
									<td class="lq-tabular">{formatBytes(file.size_bytes)}</td>
									<td class="lq-tabular">{file.page_count ?? '—'}</td>
									<td class="lq-text-caption" style="color: var(--lq-text-tertiary);">
										{shortDateTime(file.attached_at)}
									</td>
									<td style="text-align: right;">
										<button
											type="button"
											class="lq-btn-detach"
											on:click={() => handleDetach(file)}
											aria-label={`Detach ${file.filename}`}
											data-testid="lq-ai-knowledge-doc-detach-btn"
										>Detach</button>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</section>
	{/if}
</main>

<style>
	.lq-kb-detail {
		padding: var(--lq-space-6);
		max-width: 1100px;
		margin: 0 auto;
	}

	.lq-kb-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--lq-space-4);
		padding-bottom: var(--lq-space-4);
		border-bottom: 1px solid var(--lq-border);
		margin-bottom: var(--lq-space-5);
	}

	.lq-archived-pill {
		display: inline-flex;
		align-items: center;
		font-size: 12px;
		font-weight: 500;
		padding: 2px 10px;
		margin-left: var(--lq-space-2);
		border-radius: var(--lq-radius-pill);
		background: var(--lq-inset);
		color: var(--lq-text-tertiary);
		border: 1px solid var(--lq-border);
		vertical-align: middle;
	}

	.lq-kb-desc {
		margin: var(--lq-space-2) 0 0 0;
		color: var(--lq-text-secondary);
		max-width: 70ch;
		font-size: 14px;
	}

	.lq-kb-meta {
		margin: var(--lq-space-2) 0 0 0;
		color: var(--lq-text-tertiary);
		font-size: 13px;
	}

	.lq-kb-actions {
		display: flex;
		gap: var(--lq-space-2);
		flex-shrink: 0;
	}

	.lq-kb-section {
		margin-bottom: var(--lq-space-6);
	}

	.lq-section-head {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		margin-bottom: var(--lq-space-3);
	}

	.lq-upload-card {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: var(--lq-space-4);
		padding: var(--lq-space-4);
		border: 1px dashed var(--lq-border);
		border-radius: var(--lq-radius-lg);
		background: var(--lq-inset);
	}

	.lq-upload-actions {
		display: flex;
		align-items: center;
		gap: var(--lq-space-2);
	}

	.lq-file-input {
		display: none;
	}

	.lq-empty-state {
		border-radius: var(--lq-radius-lg);
		border: 1px dashed var(--lq-border);
		padding: var(--lq-space-6);
		text-align: center;
	}

	.lq-table-wrap {
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-lg);
		overflow: hidden;
	}

	.lq-doc-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
	}

	.lq-doc-table thead {
		background: var(--lq-inset);
	}

	.lq-doc-table th,
	.lq-doc-table td {
		padding: var(--lq-space-2) var(--lq-space-3);
		text-align: left;
		vertical-align: top;
	}

	.lq-doc-table tbody tr {
		border-top: 1px solid var(--lq-border);
	}

	.lq-doc-table tbody tr:hover {
		background: var(--lq-inset);
	}

	.lq-doc-filename {
		font-weight: 500;
		color: var(--lq-text);
		word-break: break-word;
	}

	.lq-tabular {
		font-variant-numeric: tabular-nums;
		color: var(--lq-text-secondary);
	}

	.lq-doc-status {
		display: inline-block;
		font-size: 11px;
		padding: 2px 8px;
		border-radius: var(--lq-radius-pill);
		white-space: nowrap;
	}

	.lq-doc-status--ready {
		background: var(--lq-accent-soft);
		color: var(--lq-accent);
		border: 1px solid var(--lq-accent-border);
	}

	.lq-doc-status--processing,
	.lq-doc-status--pending {
		background: var(--lq-warn-soft);
		color: var(--lq-warn);
		border: 1px solid var(--lq-warn-border);
	}

	.lq-doc-status--failed,
	.lq-doc-status--embed_failed {
		background: var(--lq-error-soft);
		color: var(--lq-error);
		border: 1px solid var(--lq-error-border);
	}

	/* M3-0.3: partial-embed sits between healthy and full failure — the
	   document is still partially usable for FTS, just not fully embedded. */
	.lq-doc-status--partial {
		background: var(--lq-warn-soft);
		color: var(--lq-warn);
		border: 1px solid var(--lq-warn-border);
	}

	.lq-doc-error {
		margin-top: 4px;
		font-size: 11px;
		color: var(--lq-error);
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

	.lq-link {
		color: var(--lq-accent);
		text-decoration: none;
	}
	.lq-link:hover { text-decoration: underline; }

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

	.lq-btn-primary:hover:not(:disabled) {
		filter: brightness(0.95);
	}

	.lq-btn-primary:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}

	.lq-btn-secondary {
		background: transparent;
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: 6px 12px;
		font-size: 13px;
		cursor: pointer;
	}

	.lq-btn-secondary:hover:not(:disabled) {
		background: var(--lq-inset);
	}

	.lq-btn-secondary:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.lq-btn-danger {
		background: transparent;
		color: var(--lq-error);
		border: 1px solid var(--lq-error-border);
		border-radius: var(--lq-radius);
		padding: 6px 12px;
		font-size: 13px;
		cursor: pointer;
	}
	.lq-btn-danger:hover:not(:disabled) {
		background: var(--lq-error-soft);
	}
	.lq-btn-danger:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.lq-btn-detach {
		background: transparent;
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: 4px 10px;
		font-size: 12px;
		cursor: pointer;
	}
	.lq-btn-detach:hover {
		background: var(--lq-inset);
		color: var(--lq-error);
		border-color: var(--lq-error-border);
	}
</style>
