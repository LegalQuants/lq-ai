/**
 * Pure helpers for the M4-C2 memory review page.
 *
 * Extracted from `+page.svelte` so vitest can exercise them without the
 * SvelteKit / Svelte runtime. No side-effects; all functions are referentially
 * transparent (or accept a `now` parameter for deterministic tests).
 */

import type { MemoryState } from '$lib/lq-ai/api/autonomous';

/** The three state-tab definitions, in display order. */
export interface MemoryTabDef {
	state: MemoryState;
	label: string;
}

export const MEMORY_TABS: MemoryTabDef[] = [
	{ state: 'proposed', label: 'Proposed' },
	{ state: 'kept', label: 'Kept' },
	{ state: 'dismissed', label: 'Dismissed' }
];

/**
 * Return the empty-state message for a given MemoryState tab.
 *
 * Used in the template so the message is deterministic and testable.
 */
export function emptyStateMessage(state: MemoryState): string {
	switch (state) {
		case 'proposed':
			return 'No proposed memory yet.';
		case 'kept':
			return 'No kept memory yet.';
		case 'dismissed':
			return 'No dismissed memory yet.';
	}
}

/**
 * Format a memory entry's created_at ISO string into a short human-readable
 * form. Pass `now` for deterministic testing.
 *
 * Mirrors formatCreatedAt from the sessions page-helpers.
 */
export function formatMemoryDate(iso: string, now: Date = new Date()): string {
	const d = new Date(iso);
	if (Number.isNaN(d.getTime())) {
		return iso;
	}
	const deltaMs = now.getTime() - d.getTime();
	const deltaHours = Math.floor(deltaMs / (60 * 60 * 1000));
	if (deltaHours < 1) return 'just now';
	if (deltaHours < 24) return `${deltaHours} hour${deltaHours === 1 ? '' : 's'} ago`;
	const deltaDays = Math.floor(deltaHours / 24);
	if (deltaDays < 14) return `${deltaDays} day${deltaDays === 1 ? '' : 's'} ago`;
	return d.toISOString().slice(0, 10);
}
