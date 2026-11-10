/**
 * Session-activity tracker.
 *
 * Tracks user idle time, posts /auth/refresh (debounced to once per minute)
 * on activity, shows a warning at 25 minutes idle, and fires the onLogout
 * callback at 30 minutes idle.
 *
 * PRD §5.1 defaults; backend enforces the same window via migration 0018.
 */
import { writable } from 'svelte/store';

import { refreshSession } from '../api';
import { getRefreshToken } from '../auth/store';

export const IDLE_WARN_AT_MS = 25 * 60 * 1000; // 25 minutes
export const IDLE_LOGOUT_AT_MS = 30 * 60 * 1000; // 30 minutes
export const REFRESH_DEBOUNCE_MS = 60 * 1000; // refresh at most once per minute
export const CHECK_INTERVAL_MS = 30 * 1000; // check twice per minute

export interface SessionActivityState {
	lastActivityMs: number;
	showWarning: boolean;
}

export const sessionActivity = writable<SessionActivityState>({
	lastActivityMs: Date.now(),
	showWarning: false
});

let watchInterval: ReturnType<typeof setInterval> | null = null;
let lastRefreshMs = 0;

export function noteActivity(): void {
	const now = Date.now();
	sessionActivity.update(() => ({ lastActivityMs: now, showWarning: false }));
	if (now - lastRefreshMs > REFRESH_DEBOUNCE_MS) {
		lastRefreshMs = now;
		if (getRefreshToken()) {
			// Shares the client's refresh, so it never spends the refresh token
			// a 401 retry is already spending.
			refreshSession().catch(() => {
				// Silent — a network or server error leaves the session as it is,
				// and the next API call or activity refresh tries again.
			});
		}
	}
}

export function startTracker(onLogout: () => void): void {
	if (watchInterval) return;
	watchInterval = setInterval(() => {
		sessionActivity.update((s) => {
			const idleMs = Date.now() - s.lastActivityMs;
			if (idleMs >= IDLE_LOGOUT_AT_MS) {
				onLogout();
				return { ...s, showWarning: false };
			}
			return { ...s, showWarning: idleMs >= IDLE_WARN_AT_MS };
		});
	}, CHECK_INTERVAL_MS);
}

export function stopTracker(): void {
	if (watchInterval) {
		clearInterval(watchInterval);
		watchInterval = null;
	}
}

/** Reset internal state between tests. Not intended for production use. */
export function _resetTracker(): void {
	stopTracker();
	lastRefreshMs = 0;
	sessionActivity.set({ lastActivityMs: Date.now(), showWarning: false });
}
