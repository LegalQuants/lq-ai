/**
 * Preferences store — server-synced via /users/me/preferences with
 * localStorage as an offline cache so the chrome doesn't flash defaults
 * on every page load.
 */
import { writable } from 'svelte/store';
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
	const raw = localStorage.getItem(STORAGE_KEY);
	if (!raw) return null;
	try {
		return { ...defaultPreferences, ...(JSON.parse(raw) as Partial<Preferences>) };
	} catch {
		return null;
	}
}

export function writeCache(p: Preferences): void {
	if (typeof localStorage !== 'undefined') {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
	}
}

export async function initPreferences(): Promise<void> {
	const cached = readCache();
	if (cached) preferences.set(cached);
	try {
		const fresh = await getPreferences();
		preferences.set(fresh);
		writeCache(fresh);
	} catch {
		// offline / unauthorized — keep cached or default
	}
}

export async function setPreference<K extends keyof Preferences>(
	key: K,
	value: Preferences[K]
): Promise<void> {
	preferences.update((p) => {
		const next = { ...p, [key]: value };
		writeCache(next);
		return next;
	});
	try {
		const fresh = await patchPreferences({ [key]: value } as PreferencesUpdate);
		preferences.set(fresh);
		writeCache(fresh);
	} catch {
		// server-side rollback on failure deferred to Wave F — keep optimistic state
	}
}
