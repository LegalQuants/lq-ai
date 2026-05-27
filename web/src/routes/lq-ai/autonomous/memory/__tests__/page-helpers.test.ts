/**
 * Pure-helper tests for the M4-C2 memory review page.
 *
 * Mirrors the pattern from:
 *   web/src/routes/lq-ai/autonomous/__tests__/page-helpers.test.ts
 */
import { describe, expect, it } from 'vitest';

import { emptyStateMessage, formatMemoryDate, MEMORY_TABS } from '../page-helpers';
import type { MemoryState } from '$lib/lq-ai/api/autonomous';

// ---------------------------------------------------------------------------
// MEMORY_TABS
// ---------------------------------------------------------------------------

describe('MEMORY_TABS', () => {
	it('contains exactly three tabs in proposed → kept → dismissed order', () => {
		expect(MEMORY_TABS.map((t) => t.state)).toEqual(['proposed', 'kept', 'dismissed']);
	});

	it('labels match expected display strings', () => {
		expect(MEMORY_TABS.map((t) => t.label)).toEqual(['Proposed', 'Kept', 'Dismissed']);
	});
});

// ---------------------------------------------------------------------------
// emptyStateMessage
// ---------------------------------------------------------------------------

describe('emptyStateMessage', () => {
	it('returns distinct messages for each state', () => {
		const states: MemoryState[] = ['proposed', 'kept', 'dismissed'];
		const messages = states.map(emptyStateMessage);
		const unique = new Set(messages);
		expect(unique.size).toBe(3);
	});

	it('proposed message mentions "proposed"', () => {
		expect(emptyStateMessage('proposed').toLowerCase()).toContain('proposed');
	});

	it('kept message mentions "kept"', () => {
		expect(emptyStateMessage('kept').toLowerCase()).toContain('kept');
	});

	it('dismissed message mentions "dismissed"', () => {
		expect(emptyStateMessage('dismissed').toLowerCase()).toContain('dismissed');
	});
});

// ---------------------------------------------------------------------------
// formatMemoryDate
// ---------------------------------------------------------------------------

describe('formatMemoryDate', () => {
	const now = new Date('2026-05-26T12:00:00Z');

	it('returns "just now" for entries under an hour old', () => {
		expect(formatMemoryDate('2026-05-26T11:45:00Z', now)).toBe('just now');
	});

	it('returns "N hours ago" for entries within today', () => {
		expect(formatMemoryDate('2026-05-26T08:00:00Z', now)).toBe('4 hours ago');
	});

	it('returns "1 hour ago" with singular for exactly one hour', () => {
		expect(formatMemoryDate('2026-05-26T11:00:00Z', now)).toBe('1 hour ago');
	});

	it('returns "N days ago" for entries within two weeks', () => {
		expect(formatMemoryDate('2026-05-23T12:00:00Z', now)).toBe('3 days ago');
	});

	it('returns "1 day ago" with singular for exactly one day', () => {
		expect(formatMemoryDate('2026-05-25T12:00:00Z', now)).toBe('1 day ago');
	});

	it('returns ISO date for entries older than two weeks', () => {
		expect(formatMemoryDate('2026-01-01T00:00:00Z', now)).toBe('2026-01-01');
	});

	it('returns the input verbatim when not parseable', () => {
		expect(formatMemoryDate('not-a-date', now)).toBe('not-a-date');
	});
});
