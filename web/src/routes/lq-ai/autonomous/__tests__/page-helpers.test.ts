/**
 * Pure-helper tests for the M4-C2 autonomous sessions list page.
 *
 * Mirrors the pattern from:
 *   web/src/routes/lq-ai/playbook-executions/[id]/__tests__/page-helpers.test.ts
 *   web/src/routes/lq-ai/admin/intake-bridges/__tests__/page-helpers.test.ts
 */
import { describe, expect, it } from 'vitest';

import { formatCost, formatCreatedAt, isHaltable, statusPillClass } from '../page-helpers';
import type { SessionStatus } from '$lib/lq-ai/api/autonomous';

// ---------------------------------------------------------------------------
// statusPillClass
// ---------------------------------------------------------------------------

describe('statusPillClass', () => {
	it('maps each real SessionStatus to a unique lq pill class', () => {
		expect(statusPillClass('running')).toBe('lq-status--running');
		expect(statusPillClass('completed')).toBe('lq-status--completed');
		expect(statusPillClass('halted')).toBe('lq-status--halted');
		expect(statusPillClass('failed')).toBe('lq-status--failed');
	});

	it('returns distinct classes for all four statuses', () => {
		const statuses: SessionStatus[] = ['running', 'completed', 'halted', 'failed'];
		const classes = statuses.map(statusPillClass);
		const unique = new Set(classes);
		expect(unique.size).toBe(4);
	});
});

// ---------------------------------------------------------------------------
// formatCost
// ---------------------------------------------------------------------------

describe('formatCost', () => {
	it('formats total + cap from STRING inputs to "$0.10 / $0.50"', () => {
		expect(formatCost('0.10', '0.50')).toBe('$0.10 / $0.50');
	});

	it('formats total only (null cap) from string input to "$0.10"', () => {
		expect(formatCost('0.10', null)).toBe('$0.10');
	});

	it('formats total only (undefined cap) from string input', () => {
		expect(formatCost('0.10', undefined)).toBe('$0.10');
	});

	it('accepts number inputs as well (API may not always coerce)', () => {
		expect(formatCost(0.1, null)).toBe('$0.10');
		expect(formatCost(0.1, 0.5)).toBe('$0.10 / $0.50');
	});

	it('coerces string "0.1" the same as number 0.1', () => {
		expect(formatCost('0.1', null)).toBe('$0.10');
	});

	it('handles zero cost', () => {
		expect(formatCost('0.00', null)).toBe('$0.00');
		expect(formatCost('0', '1.00')).toBe('$0.00 / $1.00');
	});

	it('omits cap section when cap is empty string', () => {
		expect(formatCost('0.10', '')).toBe('$0.10');
	});
});

// ---------------------------------------------------------------------------
// isHaltable
// ---------------------------------------------------------------------------

describe('isHaltable', () => {
	it('returns true only for running status', () => {
		expect(isHaltable('running')).toBe(true);
	});

	it('returns false for completed', () => {
		expect(isHaltable('completed')).toBe(false);
	});

	it('returns false for halted', () => {
		expect(isHaltable('halted')).toBe(false);
	});

	it('returns false for failed', () => {
		expect(isHaltable('failed')).toBe(false);
	});

	it('there is no paused SessionStatus — all non-running statuses are non-haltable', () => {
		const nonRunning: SessionStatus[] = ['completed', 'halted', 'failed'];
		expect(nonRunning.every((s) => !isHaltable(s))).toBe(true);
	});
});

// ---------------------------------------------------------------------------
// formatCreatedAt
// ---------------------------------------------------------------------------

describe('formatCreatedAt', () => {
	const now = new Date('2026-05-26T12:00:00Z');

	it('returns "just now" for sessions under an hour old', () => {
		expect(formatCreatedAt('2026-05-26T11:45:00Z', now)).toBe('just now');
	});

	it('returns "N hours ago" for sessions within today', () => {
		expect(formatCreatedAt('2026-05-26T08:00:00Z', now)).toBe('4 hours ago');
	});

	it('returns "1 hour ago" with singular for exactly one hour', () => {
		expect(formatCreatedAt('2026-05-26T11:00:00Z', now)).toBe('1 hour ago');
	});

	it('returns "N days ago" for sessions within two weeks', () => {
		expect(formatCreatedAt('2026-05-23T12:00:00Z', now)).toBe('3 days ago');
	});

	it('returns "1 day ago" with singular for exactly one day', () => {
		expect(formatCreatedAt('2026-05-25T12:00:00Z', now)).toBe('1 day ago');
	});

	it('returns ISO date for sessions older than two weeks', () => {
		expect(formatCreatedAt('2026-01-01T00:00:00Z', now)).toBe('2026-01-01');
	});

	it('returns the input verbatim when not parseable', () => {
		expect(formatCreatedAt('not-a-date', now)).toBe('not-a-date');
	});
});
