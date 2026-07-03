<script context="module" lang="ts">
	/**
	 * MentionPopover — typeahead listbox for @-referencing matter
	 * documents (referenced-files Phase 2). Clone of SlashPopover with the fetch
	 * replaced by client-side filtering over the caller-loaded
	 * referenceable list: the whole matter file set is already in memory
	 * (files/referenceable.ts), so there is no per-keystroke request and
	 * no request-token race guard.
	 *
	 * Only READY files are offered — the mention flow is keyboard-driven
	 * and never renders a disabled row; non-ready files surface as
	 * "Preparing…" rows in FilePickerDropdown instead.
	 */
	import { filterReferenceable, type ReferencedFile } from '../files/referenceable';
	import { nextIndex } from './SlashPopover.svelte';

	export type MentionPopoverState = {
		results: ReferencedFile[];
		activeIndex: number;
		loading: boolean;
		error: string | null;
		query: string;
	};

	export type MentionStateKind =
		| 'loading'
		| 'error'
		| 'empty-with-query'
		| 'empty-no-query'
		| 'results';

	export type MentionKeyAction =
		| { kind: 'select'; result: ReferencedFile }
		| { kind: 'dismiss' }
		| { kind: 'move'; nextIndex: number }
		| { kind: 'noop' };

	export function mentionResults(files: ReferencedFile[], query: string): ReferencedFile[] {
		return filterReferenceable(files, query).filter((f) => f.ready);
	}

	export function mentionStateKind(state: MentionPopoverState): MentionStateKind {
		if (state.loading) return 'loading';
		if (state.error) return 'error';
		if (state.results.length === 0) {
			return state.query ? 'empty-with-query' : 'empty-no-query';
		}
		return 'results';
	}

	export function decideMentionKeyAction(
		key: string,
		state: MentionPopoverState
	): MentionKeyAction {
		if (key === 'Escape') return { kind: 'dismiss' };
		const len = state.results.length;
		if (len === 0) return { kind: 'noop' };
		if (key === 'Enter') {
			const result = state.results[state.activeIndex];
			if (!result) return { kind: 'noop' };
			return { kind: 'select', result };
		}
		if (key === 'ArrowDown') {
			return { kind: 'move', nextIndex: nextIndex(state.activeIndex, len, 1) };
		}
		if (key === 'ArrowUp') {
			return { kind: 'move', nextIndex: nextIndex(state.activeIndex, len, -1) };
		}
		return { kind: 'noop' };
	}
</script>

<script lang="ts">
	export let query: string;
	export let files: ReferencedFile[];
	export let loading: boolean = false;
	export let error: string | null = null;
	export let onSelect: (file: ReferencedFile) => void;
	export let onDismiss: () => void;
	export let onRetry: () => void;

	let activeIndex = 0;
	let lastQuery: string | undefined;

	$: results = mentionResults(files, query);
	// Reset the active row on ANY query change (matching SlashPopover's
	// semantics): after an edit, position N of the new result set is an
	// unrelated file, so a stale highlight must never survive the edit.
	$: if (query !== lastQuery) {
		lastQuery = query;
		activeIndex = 0;
	}
	// Clamp if the file list itself shrinks (e.g. a reload) with no query change.
	$: if (activeIndex >= results.length) activeIndex = 0;
	$: kind = mentionStateKind({ results, activeIndex, loading, error, query });

	function onWindowKey(e: KeyboardEvent) {
		const action = decideMentionKeyAction(e.key, { results, activeIndex, loading, error, query });
		switch (action.kind) {
			case 'select':
				e.preventDefault();
				e.stopPropagation();
				onSelect(action.result);
				return;
			case 'dismiss':
				e.preventDefault();
				e.stopPropagation();
				onDismiss();
				return;
			case 'move':
				e.preventDefault();
				e.stopPropagation();
				activeIndex = action.nextIndex;
				return;
			case 'noop':
				return;
		}
	}

	function onRowMouseDown(e: MouseEvent, file: ReferencedFile) {
		e.preventDefault();
		onSelect(file);
	}
</script>

<svelte:window on:keydown={onWindowKey} />

<!-- tabindex="-1" required by a11y rule when aria-activedescendant is set; composer retains focus and keyboard events are caught by window handler above, so this listbox is never tab-focused. -->
<div
	class="lq-mention-popover"
	role="listbox"
	tabindex="-1"
	aria-label="Document suggestions"
	data-testid="lq-ai-mention-popover"
	aria-activedescendant={kind === 'results' ? `lq-mention-row-${activeIndex}` : undefined}
>
	{#if kind === 'loading'}
		<div class="lq-mention-popover__status" role="presentation">Loading documents…</div>
	{:else if kind === 'error'}
		<div class="lq-mention-popover__status lq-mention-popover__status--error" role="presentation">
			Couldn't load documents ·
			<button type="button" class="lq-mention-popover__retry" on:click={onRetry}>retry</button>
		</div>
	{:else if kind === 'empty-with-query'}
		<div class="lq-mention-popover__status" role="presentation">
			No matching documents · Esc to dismiss
		</div>
	{:else if kind === 'empty-no-query'}
		<div class="lq-mention-popover__status" role="presentation">
			No documents ready to reference in this matter
		</div>
	{:else}
		{#each results as r, i}
			<button
				type="button"
				role="option"
				id={`lq-mention-row-${i}`}
				class="lq-mention-popover__row"
				class:active={i === activeIndex}
				aria-selected={i === activeIndex}
				data-testid="lq-ai-mention-row"
				on:mousedown={(e) => onRowMouseDown(e, r)}
				on:mouseenter={() => (activeIndex = i)}
			>
				<span class="lq-mention-popover__icon" aria-hidden="true">📄</span>
				<span class="lq-mention-popover__body">
					<span class="lq-mention-popover__title">{r.filename}</span>
				</span>
			</button>
		{/each}
	{/if}
</div>

<style>
	.lq-mention-popover {
		display: flex;
		flex-direction: column;
		min-width: 280px;
		max-width: clamp(280px, 90vw, 420px);
		max-height: 320px;
		overflow-y: auto;
		background: var(--lq-surface, var(--lq-canvas, #ffffff));
		border: 1px solid var(--lq-border, #e5e7eb);
		border-radius: var(--lq-radius, 6px);
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
		padding: var(--lq-space-1, 4px);
		font-family: var(--lq-font-sans);
		font-size: 13px;
		color: var(--lq-text, #1a1a1a);
	}

	.lq-mention-popover__status {
		padding: var(--lq-space-2, 8px) var(--lq-space-3, 12px);
		color: var(--lq-text-tertiary, #9ca3af);
		font-size: 12px;
	}

	.lq-mention-popover__status--error {
		color: var(--lq-error, #b54848);
	}

	.lq-mention-popover__retry {
		background: none;
		border: 0;
		padding: 0;
		margin: 0;
		color: inherit;
		font: inherit;
		text-decoration: underline;
		cursor: pointer;
	}

	.lq-mention-popover__retry:focus-visible {
		outline: 2px solid var(--lq-accent, #1f7a6b);
		outline-offset: 2px;
	}

	.lq-mention-popover__row {
		display: flex;
		align-items: flex-start;
		gap: var(--lq-space-2, 8px);
		width: 100%;
		text-align: left;
		background: none;
		border: 0;
		padding: var(--lq-space-2, 8px) var(--lq-space-3, 12px);
		border-radius: var(--lq-radius-sm, 4px);
		color: inherit;
		font: inherit;
		cursor: pointer;
	}

	.lq-mention-popover__row.active {
		background: var(--lq-accent-soft, #e8f4ec);
	}

	.lq-mention-popover__row:focus-visible {
		outline: 2px solid var(--lq-accent, #1f7a6b);
		outline-offset: -2px;
	}

	.lq-mention-popover__icon {
		font-size: 14px;
		line-height: 1.3;
		padding-top: 1px;
		flex: 0 0 auto;
	}

	.lq-mention-popover__body {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.lq-mention-popover__title {
		font-weight: 500;
		color: var(--lq-text, #1a1a1a);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
</style>
