/**
 * Pure helpers for the global-chrome notification bell (DE-324).
 *
 * Extracted from `NotificationBell.svelte` so vitest can exercise the
 * gating / badge / mark-read state transitions without the Svelte runtime.
 * Mirrors the lib pattern of `cron.ts` / `receipt-timeline.ts` in this
 * directory. No side-effects; all functions are referentially transparent.
 */

import type { AutonomousNotificationRead } from '$lib/lq-ai/api/autonomous';

/**
 * Whether the bell renders at all. The bell is autonomous-layer chrome:
 * users who have not opted in (preferences.autonomous_enabled === false)
 * see NO chrome change — zero DOM emitted.
 */
export function shouldShowBell(autonomousEnabled: boolean): boolean {
	return autonomousEnabled;
}

/**
 * Badge label for an unread count.
 *
 *   0 (or negative) → null (no badge rendered)
 *   1..99           → String(count)
 *   >99             → '99+'  (cap mirrors the autonomous rail badge)
 */
export function badgeText(unreadCount: number): string | null {
	if (unreadCount <= 0) return null;
	return unreadCount > 99 ? '99+' : String(unreadCount);
}

/** Bell dropdown state: the visible unread items + the true unread total. */
export interface BellState {
	/** Unread items shown in the dropdown (a page of the newest unread). */
	items: AutonomousNotificationRead[];
	/** Total unread count server-side — may exceed items.length. */
	unreadCount: number;
}

/**
 * State transition after a single notification is marked read: the item
 * leaves the dropdown list and the badge decrements (floored at 0 — the
 * server count may have drifted since the last fetch).
 */
export function afterMarkRead(state: BellState, id: string): BellState {
	if (!state.items.some((n) => n.id === id)) return state;
	return {
		items: state.items.filter((n) => n.id !== id),
		unreadCount: Math.max(0, state.unreadCount - 1)
	};
}

/**
 * State transition after mark-all-read: `succeededIds` are removed from the
 * dropdown and subtracted from the badge. With a partial failure the
 * remaining items / count stay visible so the user can retry.
 */
export function afterMarkAllRead(state: BellState, succeededIds: string[]): BellState {
	const succeeded = new Set(succeededIds);
	const removed = state.items.filter((n) => succeeded.has(n.id)).length;
	return {
		items: state.items.filter((n) => !succeeded.has(n.id)),
		unreadCount: Math.max(0, state.unreadCount - removed)
	};
}

/**
 * Truncate a notification body for the dropdown snippet. Whole-string cap
 * (not word-aware — dropdown rows are single-line ellipsised anyway; this
 * just bounds the DOM text length).
 */
export function snippet(body: string, maxChars = 140): string {
	if (body.length <= maxChars) return body;
	return `${body.slice(0, maxChars - 1).trimEnd()}…`;
}
