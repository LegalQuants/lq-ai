import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { clearSession, setSession } from '../auth/store';
import { getPreferences, patchPreferences } from '../api/preferences';
import {
	autonomousChromeEnabled,
	defaultPreferences,
	initPreferences,
	preferences,
	preferencesReadyFor,
	setPreference
} from '../stores/preferences';
import type { Preferences, User } from '../types';

vi.mock('../api/preferences', () => ({ getPreferences: vi.fn(), patchPreferences: vi.fn() }));
function deferred<T>() {
	let resolve!: (value: T) => void;
	let reject!: (error: Error) => void;
	const promise = new Promise<T>((yes, no) => {
		resolve = yes;
		reject = no;
	});
	return { promise, resolve, reject };
}
const enabled = { ...defaultPreferences, autonomous_enabled: true };
function signIn(id = 'a') {
	const user: User = {
		id,
		email: `${id}@example.test`,
		is_admin: false,
		mfa_enabled: false,
		must_change_password: false,
		created_at: '2026-01-01T00:00:00Z'
	};
	setSession({ access_token: `token-${id}`, expires_in: 900, user });
}
beforeEach(() => {
	clearSession();
	vi.resetAllMocks();
	vi.stubGlobal('localStorage', { getItem: () => JSON.stringify(enabled), setItem: vi.fn() });
	signIn();
});
afterEach(() => {
	clearSession();
	vi.unstubAllGlobals();
});

describe('server-confirmed autonomous chrome', () => {
	it('keeps cached enabled chrome hidden while the server opt-out is pending', async () => {
		const response = deferred<Preferences>();
		vi.mocked(getPreferences).mockReturnValue(response.promise);
		const loading = initPreferences();
		expect(get(preferences).autonomous_enabled).toBe(true);
		expect(get(autonomousChromeEnabled)).toBe(false);
		response.resolve({ ...defaultPreferences });
		await loading;
		expect(get(autonomousChromeEnabled)).toBe(false);
		expect(get(preferencesReadyFor)).toBe('a');
	});
	it('does not authorize the cached enabled flag when the GET fails', async () => {
		vi.mocked(getPreferences).mockRejectedValue(new Error('offline'));
		await initPreferences();
		expect(get(preferencesReadyFor)).toBeNull();
		expect(get(autonomousChromeEnabled)).toBe(false);
	});
	it('coalesces shell and dashboard initialization into one server read', async () => {
		const response = deferred<Preferences>();
		vi.mocked(getPreferences).mockReturnValue(response.promise);
		const shell = initPreferences();
		const dashboard = initPreferences();
		expect(shell).toBe(dashboard);
		response.resolve(enabled);
		await shell;
		expect(getPreferences).toHaveBeenCalledTimes(1);
		expect(get(autonomousChromeEnabled)).toBe(true);
	});
	it('hides chrome immediately on logout', async () => {
		vi.mocked(getPreferences).mockResolvedValue(enabled);
		await initPreferences();
		expect(get(autonomousChromeEnabled)).toBe(true);
		clearSession();
		expect(get(autonomousChromeEnabled)).toBe(false);
		expect(get(preferencesReadyFor)).toBeNull();
	});
	it('discards an earlier user response after a different user signs in', async () => {
		const old = deferred<Preferences>();
		vi.mocked(getPreferences)
			.mockReturnValueOnce(old.promise)
			.mockResolvedValueOnce({ ...defaultPreferences });
		const first = initPreferences();
		await Promise.resolve();
		signIn('b');
		await initPreferences();
		old.resolve(enabled);
		await first;
		expect(get(preferencesReadyFor)).toBe('b');
		expect(get(preferences).autonomous_enabled).toBe(false);
		expect(get(autonomousChromeEnabled)).toBe(false);
	});
	it('discards a previous session response even when the same user signs in again', async () => {
		const old = deferred<Preferences>();
		vi.mocked(getPreferences)
			.mockReturnValueOnce(old.promise)
			.mockResolvedValueOnce({ ...defaultPreferences });
		const first = initPreferences();
		await Promise.resolve();
		clearSession();
		signIn('a');
		await initPreferences();
		old.resolve(enabled);
		await first;
		expect(get(preferences).autonomous_enabled).toBe(false);
		expect(get(autonomousChromeEnabled)).toBe(false);
	});
	it('requires server confirmation for an optimistic enable and stays hidden on failure', async () => {
		vi.mocked(getPreferences).mockResolvedValue({ ...defaultPreferences });
		await initPreferences();
		const response = deferred<Preferences>();
		vi.mocked(patchPreferences).mockReturnValue(response.promise);
		const saving = setPreference('autonomous_enabled', true);
		expect(get(autonomousChromeEnabled)).toBe(false);
		response.reject(new Error('offline'));
		await saving;
		expect(get(autonomousChromeEnabled)).toBe(false);
	});
	it('discards an old GET after a newer opt-out PATCH', async () => {
		const old = deferred<Preferences>();
		vi.mocked(getPreferences).mockReturnValue(old.promise);
		const loading = initPreferences();
		await Promise.resolve();
		vi.mocked(patchPreferences).mockResolvedValue({ ...defaultPreferences });
		await setPreference('autonomous_enabled', false);
		old.resolve(enabled);
		await loading;
		expect(get(preferences).autonomous_enabled).toBe(false);
		expect(get(autonomousChromeEnabled)).toBe(false);
	});
	it('accepts verified preferences even if localStorage is unavailable', async () => {
		vi.stubGlobal('localStorage', {
			getItem: () => {
				throw new Error('denied');
			},
			setItem: () => {
				throw new Error('quota');
			}
		});
		vi.mocked(getPreferences).mockResolvedValue(enabled);
		await initPreferences();
		expect(get(autonomousChromeEnabled)).toBe(true);
	});
});
