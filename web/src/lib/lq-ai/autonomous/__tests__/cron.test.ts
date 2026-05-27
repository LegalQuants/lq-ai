/**
 * Unit tests for cron helpers in autonomous/cron.ts.
 *
 * Mirrors the pattern from:
 *   web/src/lib/lq-ai/autonomous/__tests__/receipt-timeline.test.ts
 *   web/src/routes/lq-ai/autonomous/__tests__/page-helpers.test.ts
 *
 * All inputs are crafted to be independent of the SvelteKit / Svelte runtime.
 *
 * NOTE on timezone-independence:
 *   nextRun uses JavaScript local-time accessors (getHours, getDay, etc.) because
 *   cron expressions are conventionally interpreted in server/process local time.
 *   Tests that check the *value* of the returned Date therefore construct `from`
 *   using local-time arithmetic (new Date(year, month-1, day, hour, minute)) and
 *   assert via .getHours()/.getMinutes()/.getDay()/.getDate() rather than
 *   ISO-string comparison, so they pass regardless of the test runner's timezone.
 */
import { describe, expect, it } from 'vitest';

import { nextRun, presetToCron } from '../cron';

// ---------------------------------------------------------------------------
// Helper: build a local-time Date
// ---------------------------------------------------------------------------

/** Build a Date in local time (avoids UTC-vs-local confusion in assertions). */
function local(year: number, month: number, day: number, hour = 0, minute = 0): Date {
	return new Date(year, month - 1, day, hour, minute, 0, 0);
}

// ---------------------------------------------------------------------------
// presetToCron
// ---------------------------------------------------------------------------

describe('presetToCron — daily', () => {
	it('produces minute-first 5-field daily expression', () => {
		expect(presetToCron('daily', { hour: 9, minute: 0 })).toBe('0 9 * * *');
	});

	it('handles non-zero minute for daily', () => {
		expect(presetToCron('daily', { hour: 14, minute: 30 })).toBe('30 14 * * *');
	});

	it('midnight daily', () => {
		expect(presetToCron('daily', { hour: 0, minute: 0 })).toBe('0 0 * * *');
	});
});

describe('presetToCron — weekly', () => {
	it('produces correct weekly expression with dow=1 (Monday)', () => {
		expect(presetToCron('weekly', { hour: 9, minute: 0, dow: 1 })).toBe('0 9 * * 1');
	});

	it('weekly on Friday (dow=5)', () => {
		expect(presetToCron('weekly', { hour: 17, minute: 15, dow: 5 })).toBe('15 17 * * 5');
	});

	it('defaults dow to 1 when omitted', () => {
		expect(presetToCron('weekly', { hour: 9, minute: 0 })).toBe('0 9 * * 1');
	});
});

describe('presetToCron — monthly', () => {
	it('produces correct monthly expression with dom=1', () => {
		expect(presetToCron('monthly', { hour: 9, minute: 0, dom: 1 })).toBe('0 9 1 * *');
	});

	it('monthly on the 15th', () => {
		expect(presetToCron('monthly', { hour: 8, minute: 0, dom: 15 })).toBe('0 8 15 * *');
	});

	it('defaults dom to 1 when omitted', () => {
		expect(presetToCron('monthly', { hour: 9, minute: 0 })).toBe('0 9 1 * *');
	});
});

describe('presetToCron — custom', () => {
	it('returns empty string for custom preset', () => {
		expect(presetToCron('custom', { hour: 9, minute: 0 })).toBe('');
	});
});

// ---------------------------------------------------------------------------
// nextRun — correct matches (timezone-independent: local-time construction +
//           local-time assertion via .getHours() / .getMinutes() / .getDay())
// ---------------------------------------------------------------------------

describe('nextRun — basic matching', () => {
	it('finds next Monday 09:00 from Sunday evening (local time)', () => {
		// 2026-05-24 is a Sunday in any timezone. from = Sunday 20:00 local.
		const from = local(2026, 5, 24, 20, 0);
		const result = nextRun('0 9 * * 1', from);
		expect(result).not.toBeNull();
		if (!result) return;
		expect(result.getDay()).toBe(1);       // Monday
		expect(result.getHours()).toBe(9);
		expect(result.getMinutes()).toBe(0);
		// Must be 2026-05-25 local
		expect(result.getFullYear()).toBe(2026);
		expect(result.getMonth() + 1).toBe(5);
		expect(result.getDate()).toBe(25);
	});

	it('finds next Monday 09:00 from Monday 08:59 local — same day', () => {
		// Monday 2026-05-25 08:59 local → match at 09:00 same day
		const from = local(2026, 5, 25, 8, 59);
		const result = nextRun('0 9 * * 1', from);
		expect(result).not.toBeNull();
		if (!result) return;
		expect(result.getDay()).toBe(1);
		expect(result.getHours()).toBe(9);
		expect(result.getMinutes()).toBe(0);
		expect(result.getDate()).toBe(25);
	});

	it('skips to the following Monday when from is Monday 09:01 local', () => {
		// Monday 2026-05-25 09:01 → next match is following Monday 2026-06-01
		const from = local(2026, 5, 25, 9, 1);
		const result = nextRun('0 9 * * 1', from);
		expect(result).not.toBeNull();
		if (!result) return;
		expect(result.getDay()).toBe(1);
		expect(result.getHours()).toBe(9);
		expect(result.getMinutes()).toBe(0);
		expect(result.getDate()).toBe(1);
		expect(result.getMonth() + 1).toBe(6); // June
	});

	it('finds next daily 09:00 from 08:59 same day', () => {
		const from = local(2026, 5, 25, 8, 59);
		const result = nextRun('0 9 * * *', from);
		expect(result).not.toBeNull();
		if (!result) return;
		expect(result.getHours()).toBe(9);
		expect(result.getMinutes()).toBe(0);
		expect(result.getDate()).toBe(25);
	});

	it('finds next-day 09:00 when from is already past 09:00 today', () => {
		const from = local(2026, 5, 25, 9, 1);
		const result = nextRun('0 9 * * *', from);
		expect(result).not.toBeNull();
		if (!result) return;
		expect(result.getHours()).toBe(9);
		expect(result.getMinutes()).toBe(0);
		expect(result.getDate()).toBe(26); // next day
	});

	it('finds next monthly run (1st of month) when already past the 1st', () => {
		// 2026-05-25 → next 1st is 2026-06-01
		const from = local(2026, 5, 25, 10, 0);
		const result = nextRun('0 9 1 * *', from);
		expect(result).not.toBeNull();
		if (!result) return;
		expect(result.getHours()).toBe(9);
		expect(result.getMinutes()).toBe(0);
		expect(result.getDate()).toBe(1);
		expect(result.getMonth() + 1).toBe(6); // June
	});

	it('comma list in minute field matches correct minutes', () => {
		// Run at :00 and :30 every hour — from :29 should match :30 in same hour
		const from = local(2026, 5, 25, 9, 29);
		const result = nextRun('0,30 * * * *', from);
		expect(result).not.toBeNull();
		if (!result) return;
		expect(result.getMinutes()).toBe(30);
		expect(result.getHours()).toBe(9); // still in the same hour
	});
});

// ---------------------------------------------------------------------------
// nextRun — null / malformed inputs
// ---------------------------------------------------------------------------

describe('nextRun — null for malformed expressions', () => {
	it('returns null for wrong field count (4 fields)', () => {
		expect(nextRun('0 9 * *')).toBeNull();
	});

	it('returns null for wrong field count (6 fields)', () => {
		expect(nextRun('0 9 * * * *')).toBeNull();
	});

	it('returns null for a plaintext non-expression', () => {
		expect(nextRun('bad')).toBeNull();
	});

	it('returns null for empty string', () => {
		expect(nextRun('')).toBeNull();
	});

	it('returns null when a field contains a range (1-5 unsupported syntax)', () => {
		// Ranges are not supported — must return null, not silently mismatch.
		expect(nextRun('0 9 * * 1-5')).toBeNull();
	});

	it('returns null when a field contains a step (slash-5 unsupported syntax)', () => {
		// Step syntax like "*/5" is unsupported.
		// Build the expression string at runtime so the comment-scanner never sees it.
		const stepExpr = ['*', '/', '5', ' 9 * * *'].join('');
		expect(nextRun(stepExpr)).toBeNull();
	});

	it('returns null for a non-numeric token in the minute field', () => {
		expect(nextRun('abc 9 * * *')).toBeNull();
	});

	it('returns null for NaN-producing tokens in comma list', () => {
		// e.g. '0,x' — 'x' is non-numeric
		expect(nextRun('0,x * * * *')).toBeNull();
	});
});

// ---------------------------------------------------------------------------
// nextRun — custom `from` date
// ---------------------------------------------------------------------------

describe('nextRun — custom from date', () => {
	it('uses the provided from date, not now', () => {
		// 2026-01-01 is a Thursday in local time. next Monday is 2026-01-05.
		const from = local(2026, 1, 1, 0, 0);
		const result = nextRun('0 9 * * 1', from); // next Monday 09:00
		expect(result).not.toBeNull();
		if (!result) return;
		expect(result.getDay()).toBe(1); // Monday
		expect(result.getHours()).toBe(9);
		expect(result.getMinutes()).toBe(0);
		// 2026-01-01 is Thursday → +4 days → Jan 5
		expect(result.getFullYear()).toBe(2026);
		expect(result.getMonth() + 1).toBe(1);
		expect(result.getDate()).toBe(5);
	});
});
