/**
 * Preferences store — server-synced via /users/me/preferences with
 * localStorage as an offline cache so the chrome doesn't flash defaults
 * on every page load.
 */
import { derived, writable } from 'svelte/store';
import { auth } from '../auth/store';
import { shouldShowBell } from '../autonomous/notification-bell';
import type { Preferences, PreferencesUpdate } from '../types';
import { getPreferences, patchPreferences } from '../api/preferences';

const STORAGE_KEY = 'lq-ai:preferences-cache';

export const defaultPreferences: Preferences = {
	reasoning_visibility: 'disclosure',
	featured_tools: 'prominent',
	workspace_layout: 'three_pane',
	trust_pills: 'labels',
	provenance_pills: 'always',
	autonomous_enabled: false
};

export const preferences = writable<Preferences>({ ...defaultPreferences });

export function readCache(): Preferences | null {
	if (typeof localStorage === 'undefined') return null;
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (!raw) return null;
		return { ...defaultPreferences, ...(JSON.parse(raw) as Partial<Preferences>) };
	} catch {
		return null;
	}
}

export function writeCache(p: Preferences): void {
	try {
		if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
	} catch {
		// Cache availability must not prevent a successful server sync.
	}
}

/** The user whose preferences have been confirmed by a successful server response. */
export const preferencesReadyFor = writable<string | null>(null);

/** Cached display preferences never authorize autonomous chrome. */
export const autonomousChromeEnabled = derived(
	[preferences, preferencesReadyFor, auth],
	([$preferences, owner, session]) =>
		Boolean(
			session.access_token &&
			owner &&
			owner === session.user?.id &&
			shouldShowBell($preferences.autonomous_enabled)
		)
);

let currentUserId: string | null = null;
let generation = 0;
let pending: { generation: number; promise: Promise<void> } | null = null;

auth.subscribe((session) => {
	const nextUserId = session.access_token ? (session.user?.id ?? null) : null;
	if (nextUserId === currentUserId) return;
	currentUserId = nextUserId;
	generation++;
	pending = null;
	preferencesReadyFor.set(null);
	preferences.set({ ...defaultPreferences });
});

export function initPreferences(): Promise<void> {
	const userId = currentUserId;
	if (!userId) return Promise.resolve();
	if (pending?.generation === generation) return pending.promise;

	const request = ++generation;
	preferencesReadyFor.set(null);
	const cached = readCache();
	if (cached) preferences.set(cached);
	// Defer so pending is assigned before the request can settle, even with a throwing client.
	const promise = Promise.resolve().then(async () => {
		if (request !== generation || userId !== currentUserId) return;
		try {
			const fresh = await getPreferences();
			if (request !== generation || userId !== currentUserId) return;
			preferences.set(fresh);
			writeCache(fresh);
			preferencesReadyFor.set(userId);
		} catch {
			// Cached appearance remains available; autonomous chrome stays unconfirmed.
		} finally {
			if (pending?.generation === request) pending = null;
		}
	});
	pending = { generation: request, promise };
	return promise;
}

export async function setPreference<K extends keyof Preferences>(
	key: K,
	value: Preferences[K]
): Promise<void> {
	const userId = currentUserId;
	const request = ++generation;
	pending = null;
	// An optimistic enable is not a server-confirmed opt-in.
	if (key === 'autonomous_enabled') preferencesReadyFor.set(null);
	preferences.update((p) => {
		const next = { ...p, [key]: value };
		writeCache(next);
		return next;
	});
	try {
		const fresh = await patchPreferences({ [key]: value } as PreferencesUpdate);
		if (!userId || request !== generation || userId !== currentUserId) return;
		preferences.set(fresh);
		writeCache(fresh);
		preferencesReadyFor.set(userId);
	} catch {
		// Keep existing optimistic appearance behavior; a failed opt-in never enables chrome.
	}
}
