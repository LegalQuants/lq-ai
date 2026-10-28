/**
 * LQ.AI auth store.
 *
 * Holds the access token, refresh token, expiry timestamp, and the current
 * user. Persists to `localStorage` under keys distinct from OpenWebUI's
 * `token` key (per ADR 0009).
 */
import { writable, get, type Writable } from 'svelte/store';

import type { User } from '../types';

// Avoid `$app/environment` so this module is portable to vitest's node
// runner without SvelteKit alias setup. Direct feature-detection on
// `localStorage` is equivalent for our purposes.
const browser =
	typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';

export interface AuthState {
	access_token: string | null;
	refresh_token: string | null;
	/** Unix-millis when the access token expires. Null when no session. */
	expires_at: number | null;
	user: User | null;
}

const STORAGE_KEY = 'lq_ai_auth';

const empty: AuthState = {
	access_token: null,
	refresh_token: null,
	expires_at: null,
	user: null
};

function loadInitial(): AuthState {
	if (!browser) {
		return empty;
	}
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (!raw) {
			return empty;
		}
		const parsed = JSON.parse(raw) as Partial<AuthState>;
		return {
			access_token: parsed.access_token ?? null,
			refresh_token: parsed.refresh_token ?? null,
			expires_at: parsed.expires_at ?? null,
			user: parsed.user ?? null
		};
	} catch {
		return empty;
	}
}

export const auth: Writable<AuthState> = writable(loadInitial());

if (browser) {
	auth.subscribe((value) => {
		try {
			if (value.access_token) {
				localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
			} else {
				localStorage.removeItem(STORAGE_KEY);
			}
		} catch {
			// localStorage may be unavailable (private mode, quota); ignore.
		}
	});
}

/**
 * Apply a successful login or refresh response to the store.
 */
export function setSession(params: {
	access_token: string;
	refresh_token?: string | null;
	expires_in: number;
	user?: User | null;
}): void {
	const now = Date.now();
	auth.update((state) => ({
		access_token: params.access_token,
		refresh_token: params.refresh_token ?? state.refresh_token,
		expires_at: now + params.expires_in * 1000,
		user: params.user ?? state.user
	}));
}

/**
 * Update only the cached user (e.g. after `/users/me` or a password change
 * that clears `must_change_password`).
 */
export function setUser(user: User | null): void {
	auth.update((state) => ({ ...state, user }));
}

/**
 * Clear the session entirely (logout, revocation, refresh failure).
 */
export function clearSession(): void {
	auth.set(empty);
}

/**
 * Take the session another tab stored, when it is a newer session for the
 * same user. Refresh tokens rotate (PRD §5.1), so once another tab refreshes,
 * the token this tab holds is revoked and refreshing with it would fail.
 * Newer means a later expiry: every refresh sets one, while a tab that only
 * caches the user (`setUser`) writes back the older session it holds.
 * Returns `true` when a session was taken.
 */
export function adoptStoredSession(): boolean {
	if (!browser) {
		return false;
	}
	const stored = loadInitial();
	const current = get(auth);
	if (
		!stored.access_token ||
		!stored.refresh_token ||
		stored.refresh_token === current.refresh_token ||
		(stored.expires_at ?? 0) <= (current.expires_at ?? 0) ||
		(stored.user?.id ?? null) !== (current.user?.id ?? null)
	) {
		return false;
	}
	auth.set(stored);
	return true;
}

export function getAccessToken(): string | null {
	return get(auth).access_token;
}

export function getRefreshToken(): string | null {
	return get(auth).refresh_token;
}

export function getCurrentUser(): User | null {
	return get(auth).user;
}

/**
 * `true` when the access token is missing or within `marginSeconds` of
 * expiry. The default 60-second margin gives the refresh call a
 * safe window before the token actually expires.
 */
export function tokenIsStale(marginSeconds = 60): boolean {
	const state = get(auth);
	if (!state.access_token || !state.expires_at) {
		return true;
	}
	return Date.now() + marginSeconds * 1000 >= state.expires_at;
}
