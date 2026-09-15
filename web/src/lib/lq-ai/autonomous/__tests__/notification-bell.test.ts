/**
 * Pure-helper tests for the global-chrome notification bell (DE-324).
 *
 * Mirrors the pattern from cron.test.ts / receipt-timeline.test.ts in this
 * directory: exercise the extracted helpers without the Svelte runtime.
 */
import { describe, expect, it } from 'vitest';

import {
	afterMarkAllRead,
	afterMarkRead,
	badgeText,
	shouldShowBell,
	snippet,
	type BellState
} from '../notification-bell';
import type { AutonomousNotificationRead } from '$lib/lq-ai/api/autonomous';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeNotification(
	id: string,
	overrides: Partial<AutonomousNotificationRead> = {}
): AutonomousNotificationRead {
	return {
		id,
		user_id: 'user-1',
		session_id: `session-${id}`,
		channel: 'in_app',
		title: `Notification ${id}`,
		body: `Body for ${id}`,
		payload: null,
		read_at: null,
		created_at: '2026-07-01T12:00:00Z',
		updated_at: '2026-07-01T12:00:00Z',
		...overrides
	};
}

function makeState(ids: string[], unreadCount = ids.length): BellState {
	return { items: ids.map((id) => makeNotification(id)), unreadCount };
}

// ---------------------------------------------------------------------------
// shouldShowBell — the opt-in gating decision
// ---------------------------------------------------------------------------

describe('shouldShowBell', () => {
	it('hides the bell when the user has NOT opted in to autonomous mode', () => {
		expect(shouldShowBell(false)).toBe(false);
	});

	it('shows the bell when the user HAS opted in', () => {
		expect(shouldShowBell(true)).toBe(true);
	});
});

// ---------------------------------------------------------------------------
// badgeText
// ---------------------------------------------------------------------------

describe('badgeText', () => {
	it('returns null for zero unread (no badge rendered)', () => {
		expect(badgeText(0)).toBeNull();
	});

	it('returns null for negative counts (defensive)', () => {
		expect(badgeText(-1)).toBeNull();
	});

	it('returns the count as a string for 1..99', () => {
		expect(badgeText(1)).toBe('1');
		expect(badgeText(42)).toBe('42');
		expect(badgeText(99)).toBe('99');
	});

	it('caps at "99+" above 99 (mirrors the autonomous rail badge)', () => {
		expect(badgeText(100)).toBe('99+');
		expect(badgeText(1234)).toBe('99+');
	});
});

// ---------------------------------------------------------------------------
// afterMarkRead — single-item transition
// ---------------------------------------------------------------------------

describe('afterMarkRead', () => {
	it('removes the marked item and decrements the unread count', () => {
		const next = afterMarkRead(makeState(['a', 'b', 'c']), 'b');
		expect(next.items.map((n) => n.id)).toEqual(['a', 'c']);
		expect(next.unreadCount).toBe(2);
	});

	it('is a no-op (same state) for an unknown id', () => {
		const state = makeState(['a', 'b']);
		expect(afterMarkRead(state, 'nope')).toBe(state);
	});

	it('never decrements the count below zero', () => {
		const next = afterMarkRead(makeState(['a'], 0), 'a');
		expect(next.items).toEqual([]);
		expect(next.unreadCount).toBe(0);
	});

	it('does not mutate the input state', () => {
		const state = makeState(['a', 'b']);
		afterMarkRead(state, 'a');
		expect(state.items.map((n) => n.id)).toEqual(['a', 'b']);
		expect(state.unreadCount).toBe(2);
	});
});

// ---------------------------------------------------------------------------
// afterMarkAllRead — bulk transition
// ---------------------------------------------------------------------------

describe('afterMarkAllRead', () => {
	it('removes all succeeded ids and decrements the count by that many', () => {
		const next = afterMarkAllRead(makeState(['a', 'b', 'c']), ['a', 'b', 'c']);
		expect(next.items).toEqual([]);
		expect(next.unreadCount).toBe(0);
	});

	it('keeps failed items visible on partial failure', () => {
		const next = afterMarkAllRead(makeState(['a', 'b', 'c']), ['a', 'c']);
		expect(next.items.map((n) => n.id)).toEqual(['b']);
		expect(next.unreadCount).toBe(1);
	});

	it('preserves the off-page unread remainder (count > visible items)', () => {
		// 10 visible, 25 unread total: marking the visible page leaves 15.
		const ids = Array.from({ length: 10 }, (_, i) => `n${i}`);
		const next = afterMarkAllRead(makeState(ids, 25), ids);
		expect(next.items).toEqual([]);
		expect(next.unreadCount).toBe(15);
	});

	it('ignores succeeded ids not present in the visible items', () => {
		const next = afterMarkAllRead(makeState(['a', 'b']), ['zzz']);
		expect(next.items.map((n) => n.id)).toEqual(['a', 'b']);
		expect(next.unreadCount).toBe(2);
	});

	it('never decrements the count below zero', () => {
		const next = afterMarkAllRead(makeState(['a', 'b'], 1), ['a', 'b']);
		expect(next.unreadCount).toBe(0);
	});
});

// ---------------------------------------------------------------------------
// snippet
// ---------------------------------------------------------------------------

describe('snippet', () => {
	it('returns short bodies unchanged', () => {
		expect(snippet('Review completed.')).toBe('Review completed.');
	});

	it('returns a body exactly at the cap unchanged', () => {
		const body = 'x'.repeat(140);
		expect(snippet(body)).toBe(body);
	});

	it('truncates long bodies to the cap with a trailing ellipsis', () => {
		const body = 'x'.repeat(200);
		const out = snippet(body);
		expect(out.length).toBe(140);
		expect(out.endsWith('…')).toBe(true);
	});

	it('trims trailing whitespace before the ellipsis', () => {
		const body = `${'x'.repeat(130)}         tail`;
		const out = snippet(body);
		expect(out.endsWith(' …')).toBe(false);
		expect(out.endsWith('…')).toBe(true);
	});

	it('honors a custom maxChars', () => {
		expect(snippet('hello world', 6)).toBe('hello…');
	});
});
