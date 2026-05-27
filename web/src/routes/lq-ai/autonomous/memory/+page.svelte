<script lang="ts">
	/**
	 * /lq-ai/autonomous/memory — M4-C2 Memory review surface.
	 *
	 * "System-proposes, user-owns" (PRD §3.10 / ADR 0013 D4): LQVern proposes
	 * memory entries; the user keeps (optionally editing), dismisses, or deletes.
	 *
	 * State tabs:
	 *   Proposed (default) — actionable: Keep, Edit & keep, Dismiss
	 *   Kept               — actionable: Edit (keep is idempotent + updates content), Delete
	 *   Dismissed          — actionable: Delete
	 *
	 * Edit-on-keep reveals an inline <textarea> prefilled with entry.content;
	 * on submit → keepMemory(id, editedText). Keep is idempotent server-side so
	 * it also serves as the "edit kept entry" action.
	 *
	 * Mirrors the sessions list page (+page.svelte, Task 10) and intake-bridges
	 * for structure: onMount(load), load() sets list/loading/listError, action
	 * funcs confirm/act/reload, actionError/actionSuccess banners, LQAIApiError.
	 */
	import { onMount } from 'svelte';

	import { autonomousApi } from '$lib/lq-ai/api';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import type { AutonomousMemoryRead, MemoryState } from '$lib/lq-ai/api/autonomous';
	import { emptyStateMessage, formatMemoryDate, MEMORY_TABS } from './page-helpers';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let entries: AutonomousMemoryRead[] = [];
	let loading = false;
	let listError: string | null = null;
	let actionError: string | null = null;
	let actionSuccess: string | null = null;

	/** Currently selected state tab. */
	let activeState: MemoryState = 'proposed';

	/**
	 * Map of entry id → pending action label (e.g. 'keeping', 'dismissing', 'deleting').
	 * Drives per-row disabled state + button label.
	 */
	let pendingIds: Map<string, string> = new Map();

	/**
	 * Map of entry id → edited content string.
	 * Only populated when the inline edit textarea is open for an entry.
	 */
	let editingIds: Map<string, string> = new Map();

	// ---------------------------------------------------------------------------
	// Load
	// ---------------------------------------------------------------------------

	onMount(load);

	async function load(): Promise<void> {
		loading = true;
		listError = null;
		try {
			const resp = await autonomousApi.listMemory(activeState);
			entries = resp.entries;
		} catch (err) {
			if (err instanceof LQAIApiError && err.status === 403) {
				listError = 'You need to enable autonomous mode to view memory.';
			} else {
				listError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			loading = false;
		}
	}

	async function switchTab(state: MemoryState): Promise<void> {
		activeState = state;
		// Reset edit state when switching tabs — no stale edit targets survive.
		editingIds = new Map();
		await load();
	}

	// ---------------------------------------------------------------------------
	// Actions: Proposed tab
	// ---------------------------------------------------------------------------

	async function keepEntry(entry: AutonomousMemoryRead): Promise<void> {
		pendingIds = new Map(pendingIds).set(entry.id, 'keeping');
		actionError = null;
		actionSuccess = null;
		try {
			await autonomousApi.keepMemory(entry.id);
			actionSuccess = `Kept memory entry.`;
			await load();
		} catch (err) {
			if (err instanceof LQAIApiError) {
				actionError = `Keep failed (${err.status}): ${err.message}`;
			} else {
				actionError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			const next = new Map(pendingIds);
			next.delete(entry.id);
			pendingIds = next;
		}
	}

	async function keepEntryWithEdit(entry: AutonomousMemoryRead): Promise<void> {
		const editedContent = editingIds.get(entry.id);
		if (editedContent === undefined) return;
		pendingIds = new Map(pendingIds).set(entry.id, 'keeping');
		actionError = null;
		actionSuccess = null;
		try {
			await autonomousApi.keepMemory(entry.id, editedContent.trim() || entry.content);
			// Close inline editor on success.
			const nextEdit = new Map(editingIds);
			nextEdit.delete(entry.id);
			editingIds = nextEdit;
			actionSuccess = `Kept memory entry (content updated).`;
			await load();
		} catch (err) {
			if (err instanceof LQAIApiError) {
				actionError = `Keep failed (${err.status}): ${err.message}`;
			} else {
				actionError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			const next = new Map(pendingIds);
			next.delete(entry.id);
			pendingIds = next;
		}
	}

	async function dismissEntry(entry: AutonomousMemoryRead): Promise<void> {
		pendingIds = new Map(pendingIds).set(entry.id, 'dismissing');
		actionError = null;
		actionSuccess = null;
		try {
			await autonomousApi.dismissMemory(entry.id);
			actionSuccess = `Dismissed memory entry.`;
			await load();
		} catch (err) {
			if (err instanceof LQAIApiError) {
				actionError = `Dismiss failed (${err.status}): ${err.message}`;
			} else {
				actionError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			const next = new Map(pendingIds);
			next.delete(entry.id);
			pendingIds = next;
		}
	}

	// ---------------------------------------------------------------------------
	// Actions: Kept + Dismissed tabs
	// ---------------------------------------------------------------------------

	async function deleteEntry(entry: AutonomousMemoryRead): Promise<void> {
		const confirmed = confirm(
			`Delete this memory entry? This is a permanent soft-delete — the entry ` +
				`will no longer appear in any view.`
		);
		if (!confirmed) return;
		pendingIds = new Map(pendingIds).set(entry.id, 'deleting');
		actionError = null;
		actionSuccess = null;
		try {
			await autonomousApi.deleteMemory(entry.id);
			actionSuccess = `Memory entry deleted.`;
			await load();
		} catch (err) {
			if (err instanceof LQAIApiError) {
				actionError = `Delete failed (${err.status}): ${err.message}`;
			} else {
				actionError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			const next = new Map(pendingIds);
			next.delete(entry.id);
			pendingIds = next;
		}
	}

	// ---------------------------------------------------------------------------
	// Inline edit textarea helpers (Kept tab "Edit" + Proposed "Edit & keep")
	// ---------------------------------------------------------------------------

	function openEdit(entry: AutonomousMemoryRead): void {
		editingIds = new Map(editingIds).set(entry.id, entry.content);
	}

	function cancelEdit(entry: AutonomousMemoryRead): void {
		const next = new Map(editingIds);
		next.delete(entry.id);
		editingIds = next;
	}

	// Reactive: is this entry currently in edit mode?
	function isEditing(id: string): boolean {
		return editingIds.has(id);
	}

	// Reactive: pending label for this entry (or null if not pending).
	function pendingLabel(id: string): string | undefined {
		return pendingIds.get(id);
	}
</script>

<div class="memory-page">
	<header class="page-header">
		<h1 class="lq-text-page-h">Memory</h1>
		<p class="page-intro">
			LQVern proposes memory entries as it works. Review them here: keep what's accurate,
			edit before keeping, or dismiss what doesn't apply. You own what persists.
		</p>
	</header>

	<!-- ================================================================ -->
	<!-- State-tab bar                                                     -->
	<!-- ================================================================ -->

	<div role="tablist" aria-label="Memory state tabs" class="memory-tabs">
		{#each MEMORY_TABS as tab (tab.state)}
			<button
				role="tab"
				type="button"
				aria-selected={activeState === tab.state}
				class="memory-tab"
				class:memory-tab--active={activeState === tab.state}
				on:click={() => switchTab(tab.state)}
			>
				{tab.label}
			</button>
		{/each}
	</div>

	<!-- ================================================================ -->
	<!-- Banners                                                           -->
	<!-- ================================================================ -->

	{#if listError}
		<div class="error-banner" role="alert">{listError}</div>
	{/if}
	{#if actionError}
		<div class="error-banner" role="alert">{actionError}</div>
	{/if}
	{#if actionSuccess}
		<div class="success-banner" role="status">{actionSuccess}</div>
	{/if}

	<!-- ================================================================ -->
	<!-- Loading + empty states                                           -->
	<!-- ================================================================ -->

	{#if loading && entries.length === 0}
		<p class="loading">Loading memory entries…</p>
	{/if}

	{#if !loading && entries.length === 0 && !listError}
		<p class="empty-state">{emptyStateMessage(activeState)}</p>
	{/if}

	<!-- ================================================================ -->
	<!-- Entry list                                                        -->
	<!-- ================================================================ -->

	{#if entries.length > 0}
		<ul class="entry-list" aria-label="Memory entries">
			{#each entries as entry (entry.id)}
				{@const pending = pendingLabel(entry.id)}
				{@const editing = isEditing(entry.id)}
				<li class="entry-card">
					<div class="entry-meta">
						<span class="entry-category">{entry.category}</span>
						<span class="entry-date">{formatMemoryDate(entry.created_at)}</span>
					</div>

					<!-- Content area: normal view or inline edit textarea -->
					{#if editing}
						<textarea
							class="edit-textarea"
							rows="4"
							aria-label="Edit memory content"
							value={editingIds.get(entry.id) ?? entry.content}
							on:input={(e) => {
								editingIds = new Map(editingIds).set(
									entry.id,
									(e.currentTarget as HTMLTextAreaElement).value
								);
							}}
						></textarea>
					{:else}
						<p class="entry-content">{entry.content}</p>
					{/if}

					<!-- Per-state action row -->
					<div class="entry-actions">
						{#if activeState === 'proposed'}
							<!-- Keep straight through -->
							{#if !editing}
								<button
									type="button"
									class="action-button primary"
									on:click={() => keepEntry(entry)}
									disabled={!!pending}
								>
									{pending === 'keeping' ? 'Keeping…' : 'Keep'}
								</button>

								<!-- Open inline editor for edit-on-keep -->
								<button
									type="button"
									class="action-button"
									on:click={() => openEdit(entry)}
									disabled={!!pending}
								>
									Edit &amp; keep
								</button>

								<!-- Dismiss -->
								<button
									type="button"
									class="action-button danger"
									on:click={() => dismissEntry(entry)}
									disabled={!!pending}
								>
									{pending === 'dismissing' ? 'Dismissing…' : 'Dismiss'}
								</button>
							{:else}
								<!-- Edit-on-keep submit + cancel -->
								<button
									type="button"
									class="action-button primary"
									on:click={() => keepEntryWithEdit(entry)}
									disabled={!!pending}
								>
									{pending === 'keeping' ? 'Keeping…' : 'Keep with edits'}
								</button>
								<button
									type="button"
									class="action-button"
									on:click={() => cancelEdit(entry)}
									disabled={!!pending}
								>
									Cancel
								</button>
							{/if}
						{:else if activeState === 'kept'}
							<!-- Edit (keep is idempotent + updates content) -->
							{#if !editing}
								<button
									type="button"
									class="action-button"
									on:click={() => openEdit(entry)}
									disabled={!!pending}
								>
									Edit
								</button>
								<button
									type="button"
									class="action-button danger"
									on:click={() => deleteEntry(entry)}
									disabled={!!pending}
								>
									{pending === 'deleting' ? 'Deleting…' : 'Delete'}
								</button>
							{:else}
								<!-- Save edits via keepMemory (idempotent update) -->
								<button
									type="button"
									class="action-button primary"
									on:click={() => keepEntryWithEdit(entry)}
									disabled={!!pending}
								>
									{pending === 'keeping' ? 'Saving…' : 'Save'}
								</button>
								<button
									type="button"
									class="action-button"
									on:click={() => cancelEdit(entry)}
									disabled={!!pending}
								>
									Cancel
								</button>
							{/if}
						{:else if activeState === 'dismissed'}
							<!-- Delete only -->
							<button
								type="button"
								class="action-button danger"
								on:click={() => deleteEntry(entry)}
								disabled={!!pending}
							>
								{pending === 'deleting' ? 'Deleting…' : 'Delete'}
							</button>
						{/if}
					</div>
				</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.memory-page {
		padding: var(--lq-space-5);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-5);
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

	/* ------------------------------------------------------------------ */
	/* State-tab bar — mirrors SkillDetailTabs + TopTabBar styling         */
	/* ------------------------------------------------------------------ */

	.memory-tabs {
		display: flex;
		gap: var(--lq-space-4);
		border-bottom: 1px solid var(--lq-border);
		padding: 0;
		margin-bottom: calc(-1 * var(--lq-space-5) + var(--lq-space-3));
	}

	.memory-tab {
		background: transparent;
		border: 0;
		padding: var(--lq-space-3) var(--lq-space-1);
		color: var(--lq-text-secondary);
		cursor: pointer;
		border-bottom: 2px solid transparent;
		font-size: 14px;
		font-weight: 500;
		margin-bottom: -1px;
		transition:
			color 0.12s ease,
			border-color 0.12s ease;
	}

	.memory-tab:hover {
		color: var(--lq-text);
	}

	.memory-tab--active {
		color: var(--lq-accent);
		border-bottom-color: var(--lq-accent);
	}

	.memory-tab:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
		border-radius: var(--lq-radius-sm, 3px);
	}

	/* ------------------------------------------------------------------ */
	/* Banners                                                             */
	/* ------------------------------------------------------------------ */

	.error-banner {
		padding: var(--lq-space-3) var(--lq-space-4);
		background: var(--lq-error-bg, #fee);
		color: var(--lq-error-text, #800);
		border-radius: 6px;
		border: 1px solid var(--lq-error-border, #fbb);
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

	.empty-state {
		color: var(--lq-text-secondary);
		font-style: italic;
		margin: 0;
	}

	/* ------------------------------------------------------------------ */
	/* Entry list                                                          */
	/* ------------------------------------------------------------------ */

	.entry-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
	}

	.entry-card {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
		padding: var(--lq-space-4);
		border: 1px solid var(--lq-border);
		border-radius: 8px;
		background: var(--lq-surface);
	}

	.entry-meta {
		display: flex;
		align-items: center;
		gap: var(--lq-space-3);
	}

	.entry-category {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 10px;
		font-size: 12px;
		font-weight: 500;
		background: var(--lq-info-bg, #e8f4fd);
		color: var(--lq-info-text, #0a5fa8);
		border: 1px solid var(--lq-info-border, #9ed3f5);
		text-transform: capitalize;
		white-space: nowrap;
	}

	.entry-date {
		color: var(--lq-text-secondary);
		font-size: 12px;
		white-space: nowrap;
	}

	.entry-content {
		margin: 0;
		font-size: 14px;
		line-height: 1.6;
		color: var(--lq-text);
		white-space: pre-wrap;
		word-break: break-word;
	}

	.edit-textarea {
		width: 100%;
		padding: var(--lq-space-2) var(--lq-space-3);
		border: 1px solid var(--lq-accent);
		border-radius: 6px;
		background: var(--lq-bg, #fff);
		font-size: 14px;
		line-height: 1.6;
		font-family: inherit;
		resize: vertical;
		box-sizing: border-box;
	}

	.edit-textarea:focus {
		outline: 2px solid var(--lq-accent);
		outline-offset: 0;
	}

	.entry-actions {
		display: flex;
		gap: var(--lq-space-2);
		flex-wrap: wrap;
		margin-top: var(--lq-space-1);
	}

	.action-button {
		padding: var(--lq-space-1) var(--lq-space-3);
		border-radius: 6px;
		font-size: 13px;
		cursor: pointer;
		border: 1px solid var(--lq-border);
		background: transparent;
		color: var(--lq-text);
		transition: background 0.1s;
	}

	.action-button:hover:not(:disabled) {
		background: var(--lq-surface-hover, rgba(0, 0, 0, 0.04));
	}

	.action-button.primary {
		background: var(--lq-accent);
		color: white;
		border-color: var(--lq-accent);
	}

	.action-button.primary:hover:not(:disabled) {
		opacity: 0.9;
		background: var(--lq-accent);
	}

	.action-button.danger {
		color: var(--lq-error-text, #b00);
		border-color: var(--lq-error-border, #fbb);
	}

	.action-button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
