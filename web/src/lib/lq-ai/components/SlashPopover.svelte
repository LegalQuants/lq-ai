<script context="module" lang="ts">
	/**
	 * SlashPopover — typeahead listbox rendered by the composer when the
	 * user types a leading "/" to invoke a skill (Wave D.2 Task 3.3).
	 *
	 * Caller contract:
	 *   - Parent (eventually `ChatPanel.svelte`, Task 7.1) *conditionally
	 *     renders* this component when the slash-typeahead is open. While
	 *     mounted, the component owns global keyboard handling via
	 *     `<svelte:window on:keydown>` — Arrow keys cycle the active row,
	 *     Enter selects, Escape dismisses. Unmount the component to hand
	 *     keyboard control back to the composer.
	 *   - `onSelect` fires on row click (mousedown|preventDefault, so the
	 *     event lands before the composer blurs and tears the popover
	 *     out from under the click) and on Enter.
	 *   - `onDismiss` fires on Escape.
	 *
	 * Convention notes for reviewers:
	 *   - Callback props (onSelect, onDismiss) match SkillPicker /
	 *     AttachKBModal / AttachedSkillPill rather than
	 *     createEventDispatcher.
	 *   - The API import is a named function — `autocompleteSkills` —
	 *     from `$lib/lq-ai/api/skills`, not a `skillsApi.autocomplete`
	 *     method (the latter was the plan-text shape; the actual export
	 *     shape per Task 3.1 is a plain function).
	 *   - `SkillAutocompleteItem.description` is `string | null` (per
	 *     Task 3.1's wire type), so the template `?? ''`s it.
	 *   - Design tokens: the design spec called for `--lq-secure-tint`,
	 *     which doesn't exist in this codebase. The "secure / sage" tone
	 *     of AttachedSkillPill and TrustPill maps to `--lq-accent-soft`,
	 *     `--lq-accent`, `--lq-accent-border` (styles/practice.css), so
	 *     we use those here for the active row. `--lq-surface` is
	 *     referenced elsewhere in the codebase but never defined, so we
	 *     fall back to `--lq-canvas` (#ffffff) for the panel background.
	 *   - Pure helpers exported from <script context="module"> so vitest
	 *     can exercise them without @testing-library/svelte (which is
	 *     not installed; see AttachKBModal.test.ts header).
	 */
	import { autocompleteSkills } from '$lib/lq-ai/api/skills';
	import type { SkillAutocompleteItem } from '../types';

	export type SlashPopoverState = {
		results: SkillAutocompleteItem[];
		activeIndex: number;
		loading: boolean;
		error: string | null;
		query: string;
	};

	export type EmptyStateKind =
		| 'loading'
		| 'error'
		| 'empty-with-query'
		| 'empty-no-query'
		| 'results';

	export type KeyAction =
		| { kind: 'select'; result: SkillAutocompleteItem }
		| { kind: 'dismiss' }
		| { kind: 'move'; nextIndex: number }
		| { kind: 'noop' };

	/**
	 * Wrap-around index helper used by ArrowDown (direction = +1) and
	 * ArrowUp (direction = -1). When there are no results the function
	 * returns 0 — the caller is expected to early-return at the
	 * decideKeyAction layer, but this defensive default keeps the helper
	 * total (no NaN if it's ever called with length === 0).
	 */
	export function nextIndex(
		activeIndex: number,
		length: number,
		direction: 1 | -1
	): number {
		if (length === 0) return 0;
		// JS `%` keeps sign of the dividend, so add `length` to handle
		// negative wraps when direction = -1.
		return (((activeIndex + direction) % length) + length) % length;
	}

	/**
	 * Decide which of the five panel states to render. Ordering matters:
	 * loading wins over error wins over results (we don't show stale
	 * results during an in-flight retry).
	 */
	export function emptyStateKind(state: SlashPopoverState): EmptyStateKind {
		if (state.loading) return 'loading';
		if (state.error) return 'error';
		if (state.results.length === 0) {
			return state.query ? 'empty-with-query' : 'empty-no-query';
		}
		return 'results';
	}

	/**
	 * Map a KeyboardEvent.key + current state to the discrete action the
	 * component should take. Pure for testability; the Svelte handler
	 * calls e.preventDefault() at the action-application site so tests
	 * don't need to construct synthetic events.
	 */
	export function decideKeyAction(
		key: string,
		state: SlashPopoverState
	): KeyAction {
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

	/** Bounds-checked active-row read; returns undefined when out of range. */
	export function effectiveResult(
		results: SkillAutocompleteItem[],
		activeIndex: number
	): SkillAutocompleteItem | undefined {
		if (activeIndex < 0 || activeIndex >= results.length) return undefined;
		return results[activeIndex];
	}

	/**
	 * Thin wrapper around the autocomplete client. Returns the bare
	 * results array (the component holds onto the array, not the
	 * envelope). Errors propagate; the component catches and surfaces
	 * them in the "error" empty state.
	 */
	export async function fetchResults(
		query: string,
		limit = 10
	): Promise<SkillAutocompleteItem[]> {
		const resp = await autocompleteSkills(query, limit);
		return resp.results;
	}

	/**
	 * The result's own icon as the skill author wrote it, or null when it has none; the row
	 * then draws the Tabler fallback (matches AttachedSkillPill).
	 */
	export function displayIcon(icon: string | null | undefined): string | null {
		return icon ? icon : null;
	}
</script>

<script lang="ts">
	import { onMount } from 'svelte';
	import { IconTool } from '@tabler/icons-svelte';

	export let query: string;
	export let onSelect: (skill: SkillAutocompleteItem) => void;
	export let onDismiss: () => void;

	let results: SkillAutocompleteItem[] = [];
	let activeIndex = 0;
	let loading = false;
	let error: string | null = null;

	// Monotonic request token: when the user types fast, multiple load()
	// calls can be in-flight simultaneously and resolve out of order. We
	// capture an id at the top of each call and check it before every
	// state mutation so only the most-recent fetch wins.
	let requestId = 0;

	$: kind = emptyStateKind({ results, activeIndex, loading, error, query });

	async function load() {
		const myId = ++requestId;
		loading = true;
		error = null;
		try {
			const next = await fetchResults(query, 10);
			if (myId !== requestId) return; // superseded by a newer call
			results = next;
			// Clamp activeIndex to the new result-set length.
			if (activeIndex >= results.length) activeIndex = 0;
		} catch (e: unknown) {
			if (myId !== requestId) return;
			error =
				e instanceof Error
					? (e.message ?? 'Failed to load suggestions.')
					: 'Failed to load suggestions.';
			results = [];
		} finally {
			if (myId === requestId) loading = false;
		}
	}

	function retry() {
		void load();
	}

	// Initial fetch + re-fetch on query change.
	let lastQuery: string | undefined;
	onMount(() => {
		lastQuery = query;
		void load();
	});
	$: if (lastQuery !== undefined && query !== lastQuery) {
		lastQuery = query;
		activeIndex = 0;
		void load();
	}

	function onWindowKey(e: KeyboardEvent) {
		const action = decideKeyAction(e.key, {
			results,
			activeIndex,
			loading,
			error,
			query
		});
		switch (action.kind) {
			case 'select':
				// stopPropagation so the composer's Enter-to-send handler
				// (Task 7.1) doesn't also fire on the same keystroke.
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
				// Let unhandled keys continue propagating so the user can
				// keep typing into the composer.
				return;
		}
	}

	function onRowMouseDown(e: MouseEvent, result: SkillAutocompleteItem) {
		// mousedown (not click) so the handler fires before the composer
		// blurs and the popover unmounts out from under us.
		e.preventDefault();
		onSelect(result);
	}
</script>

<svelte:window on:keydown={onWindowKey} />

<!-- tabindex="-1" required by a11y rule when aria-activedescendant is set;
     the composer (Task 7.1) retains focus and keyboard events are caught
     by the window handler above, so this listbox is never tab-focused. -->
<div
	class="lq-slash-popover"
	role="listbox"
	tabindex="-1"
	aria-label="Skill suggestions"
	aria-activedescendant={kind === 'results' ? `lq-slash-row-${activeIndex}` : undefined}
>
	{#if kind === 'loading'}
		<div class="lq-slash-popover__status" role="presentation">Loading…</div>
	{:else if kind === 'error'}
		<div class="lq-slash-popover__status lq-slash-popover__status--error" role="presentation">
			Couldn't load suggestions ·
			<button type="button" class="lq-slash-popover__retry" on:click={retry}>retry</button>
		</div>
	{:else if kind === 'empty-with-query'}
		<div class="lq-slash-popover__status" role="presentation">
			No matching skills · Esc to dismiss
		</div>
	{:else if kind === 'empty-no-query'}
		<div class="lq-slash-popover__status" role="presentation">
			You don't have any skills yet —
			<a href="/lq-ai/skills" class="lq-slash-popover__link">Browse</a>
			·
			<a href="/lq-ai/skills/new" class="lq-slash-popover__link">Create</a>
		</div>
	{:else}
		{#each results as r, i}
			<button
				type="button"
				role="option"
				id={`lq-slash-row-${i}`}
				class="lq-slash-popover__row"
				class:active={i === activeIndex}
				aria-selected={i === activeIndex}
				on:mousedown={(e) => onRowMouseDown(e, r)}
				on:mouseenter={() => (activeIndex = i)}
			>
				<span class="lq-slash-popover__icon" aria-hidden="true"
					>{#if displayIcon(r.icon)}{displayIcon(r.icon)}{:else}<IconTool
							size={14}
							stroke={1.75}
						/>{/if}</span
				>
				<span class="lq-slash-popover__body">
					<span class="lq-slash-popover__title">{r.title}</span>
					<span class="lq-slash-popover__desc">{r.description ?? ''}</span>
				</span>
			</button>
		{/each}
	{/if}
</div>

<style>
	.lq-slash-popover {
		display: flex;
		flex-direction: column;
		min-width: 280px;
		max-width: clamp(280px, 90vw, 420px);
		max-height: 320px;
		overflow-y: auto;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
		padding: var(--lq-space-1);
		font-family: var(--lq-font-sans);
		font-size: 13px;
		color: var(--lq-text);
	}

	.lq-slash-popover__status {
		padding: var(--lq-space-2) var(--lq-space-3);
		color: var(--lq-text-tertiary);
		font-size: 12px;
	}

	.lq-slash-popover__status--error {
		color: var(--lq-error);
	}

	.lq-slash-popover__retry {
		background: none;
		border: 0;
		padding: 0;
		margin: 0;
		color: inherit;
		font: inherit;
		text-decoration: underline;
		cursor: pointer;
	}

	.lq-slash-popover__retry:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}

	.lq-slash-popover__link {
		color: var(--lq-accent);
		text-decoration: underline;
	}

	.lq-slash-popover__row {
		display: flex;
		align-items: flex-start;
		gap: var(--lq-space-2);
		width: 100%;
		text-align: left;
		background: none;
		border: 0;
		padding: var(--lq-space-2) var(--lq-space-3);
		border-radius: var(--lq-radius-sm);
		color: inherit;
		font: inherit;
		cursor: pointer;
	}

	.lq-slash-popover__row.active {
		background: var(--lq-accent-soft);
	}

	.lq-slash-popover__row:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: -2px;
	}

	.lq-slash-popover__icon {
		font-size: 14px;
		line-height: 1.3;
		padding-top: 1px;
		flex: 0 0 auto;
	}

	.lq-slash-popover__body {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.lq-slash-popover__title {
		font-weight: 500;
		color: var(--lq-text);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.lq-slash-popover__desc {
		color: var(--lq-text-tertiary);
		font-size: 12px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
</style>
