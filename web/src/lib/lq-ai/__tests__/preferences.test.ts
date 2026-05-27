/**
 * Unit tests for the preferences store (readCache / writeCache / defaultPreferences).
 *
 * Covers localStorage round-trips, missing-key sentinel, schema-migration fill,
 * and regression-guard on defaultPreferences matching backend server defaults.
 *
 * localStorage is not available in the vitest node runner, so tests use a
 * simple in-memory mock consistent with how existing auth-store tests operate.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { preferences, defaultPreferences, readCache, writeCache } from '../stores/preferences';

const STORAGE_KEY = 'lq-ai:preferences-cache';

let mockStorage: Record<string, string> = {};

const localStorageMock = {
	getItem: (key: string) => mockStorage[key] ?? null,
	setItem: (key: string, val: string) => {
		mockStorage[key] = val;
	},
	removeItem: (key: string) => {
		delete mockStorage[key];
	},
	clear: () => {
		mockStorage = {};
	}
};

beforeEach(() => {
	mockStorage = {};
	vi.stubGlobal('localStorage', localStorageMock);
	preferences.set({ ...defaultPreferences });
});

afterEach(() => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe('preferences store', () => {
	it('starts at defaults', () => {
		const p = get(preferences);
		expect(p.featured_tools).toBe('prominent');
		expect(p.workspace_layout).toBe('three_pane');
		expect(p.trust_pills).toBe('labels');
		expect(p.provenance_pills).toBe('always');
		expect(p.reasoning_visibility).toBe('disclosure');
	});

	it('writeCache → readCache round-trips all fields', () => {
		writeCache({ ...defaultPreferences, trust_pills: 'dots' });
		const c = readCache();
		expect(c?.trust_pills).toBe('dots');
		expect(c?.featured_tools).toBe('prominent');
		expect(c?.workspace_layout).toBe('three_pane');
	});

	it('readCache returns null on missing key', () => {
		expect(readCache()).toBeNull();
	});

	it('readCache merges missing keys with defaults (schema-migration fill)', () => {
		localStorageMock.setItem(STORAGE_KEY, JSON.stringify({ trust_pills: 'dots' }));
		const c = readCache();
		expect(c?.trust_pills).toBe('dots');
		expect(c?.featured_tools).toBe('prominent');
		expect(c?.workspace_layout).toBe('three_pane');
		expect(c?.provenance_pills).toBe('always');
		expect(c?.reasoning_visibility).toBe('disclosure');
	});

	it('defaultPreferences matches backend server defaults (regression guard)', () => {
		expect(defaultPreferences.reasoning_visibility).toBe('disclosure');
		expect(defaultPreferences.featured_tools).toBe('prominent');
		expect(defaultPreferences.workspace_layout).toBe('three_pane');
		expect(defaultPreferences.trust_pills).toBe('labels');
		expect(defaultPreferences.provenance_pills).toBe('always');
		expect(defaultPreferences.autonomous_enabled).toBe(false);
	});
});
