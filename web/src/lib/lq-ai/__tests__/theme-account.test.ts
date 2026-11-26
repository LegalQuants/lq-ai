/**
 * The theme choice across the browser and the account (ADR 0045 §2): "The
 * browser keeps a copy … The account's value wins once it arrives."
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { clearSession, setSession } from '../auth/store';
import { getPreferences, patchPreferences } from '../api/preferences';
import {
	chooseTheme,
	defaultPreferences,
	initPreferences,
	preferences,
	setPreference
} from '../stores/preferences';
import { adoptAccountTheme, applyThemeChoice, themeChoice } from '../stores/theme';
import { LQAI_THEME_STORAGE_KEY } from '../theme';
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

/** A browser small enough for the theme module: storage, a document root and a device setting. */
function browser(pathname = '/lq-ai/chats', prefersDark = false) {
	const values = new Map<string, string>();
	const attributes = new Map<string, string>();
	const classes = new Set<string>();
	const storage = {
		getItem: (key: string) => values.get(key) ?? null,
		setItem: (key: string, value: string) => void values.set(key, value)
	};
	const win = {
		location: { pathname },
		localStorage: storage,
		matchMedia: () => ({ matches: prefersDark }),
		dispatchEvent: () => true,
		document: {
			documentElement: {
				classList: {
					add: (...names: string[]) => names.forEach((name) => classes.add(name)),
					remove: (...names: string[]) => names.forEach((name) => classes.delete(name))
				},
				setAttribute: (key: string, value: string) => attributes.set(key, value),
				style: { colorScheme: '', removeProperty: () => {} }
			},
			querySelector: () => null
		}
	};
	vi.stubGlobal('window', win);
	vi.stubGlobal('localStorage', storage);
	return {
		values,
		showing: () => attributes.get('data-lq-theme'),
		saved: () => values.get(LQAI_THEME_STORAGE_KEY)
	};
}

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

const account = (appearance_theme?: Preferences['appearance_theme']): Preferences => ({
	...defaultPreferences,
	...(appearance_theme ? { appearance_theme } : {})
});

beforeEach(() => {
	clearSession();
	vi.resetAllMocks();
	themeChoice.set('system');
});
afterEach(() => {
	clearSession();
	vi.unstubAllGlobals();
});

describe('a person chooses a theme', () => {
	it('shows and remembers it at once, then saves it to the account', async () => {
		const b = browser();
		signIn();
		const saving = deferred<Preferences>();
		vi.mocked(patchPreferences).mockReturnValue(saving.promise);
		const done = chooseTheme('dark');
		// Before the account answers.
		expect(get(themeChoice)).toBe('dark');
		expect(b.saved()).toBe('dark');
		expect(b.showing()).toBe('dark');
		expect(patchPreferences).toHaveBeenCalledWith({ appearance_theme: 'dark' });
		saving.resolve(account('dark'));
		await done;
		expect(get(themeChoice)).toBe('dark');
		expect(get(preferences).appearance_theme).toBe('dark');
	});

	it('keeps the choice in this browser when the save fails', async () => {
		const b = browser();
		signIn();
		vi.mocked(patchPreferences).mockRejectedValue(new Error('offline'));
		await chooseTheme('dark');
		expect(get(themeChoice)).toBe('dark');
		expect(b.saved()).toBe('dark');
		expect(b.showing()).toBe('dark');
	});

	it('keeps the choice when the API predates the preference and answers without it', async () => {
		const b = browser();
		signIn();
		vi.mocked(patchPreferences).mockResolvedValue(account());
		await chooseTheme('dark');
		expect(get(themeChoice)).toBe('dark');
		expect(b.saved()).toBe('dark');
		expect(b.showing()).toBe('dark');
	});

	it('saves to the browser only when nobody is signed in', async () => {
		const b = browser('/lq-ai/login');
		await chooseTheme('dark');
		expect(patchPreferences).not.toHaveBeenCalled();
		expect(b.saved()).toBe('dark');
		expect(b.showing()).toBe('dark');
	});

	it('lets the last of two quick choices stand, whichever answer arrives last', async () => {
		const b = browser();
		signIn();
		const first = deferred<Preferences>();
		const second = deferred<Preferences>();
		vi.mocked(patchPreferences)
			.mockReturnValueOnce(first.promise)
			.mockReturnValueOnce(second.promise);
		const one = chooseTheme('dark');
		const two = chooseTheme('light');
		second.resolve(account('light'));
		await two;
		first.resolve(account('dark'));
		await one;
		expect(get(themeChoice)).toBe('light');
		expect(b.saved()).toBe('light');
		expect(b.showing()).toBe('light');
	});

	it('follows the device for Match system', async () => {
		const b = browser('/lq-ai/chats', true);
		applyThemeChoice('system');
		expect(b.saved()).toBe('system');
		expect(b.showing()).toBe('dark');
	});
});

describe("the account's value arrives", () => {
	it('wins over a different browser copy', async () => {
		const b = browser();
		b.values.set(LQAI_THEME_STORAGE_KEY, 'light');
		signIn();
		vi.mocked(getPreferences).mockResolvedValue(account('dark'));
		await initPreferences();
		expect(get(themeChoice)).toBe('dark');
		expect(b.saved()).toBe('dark');
		expect(b.showing()).toBe('dark');
	});

	it('turns a browser pinned to Dark back to the device when the account says Match system', async () => {
		const b = browser('/lq-ai/chats', false);
		b.values.set(LQAI_THEME_STORAGE_KEY, 'dark');
		signIn();
		vi.mocked(getPreferences).mockResolvedValue(account('system'));
		await initPreferences();
		expect(get(themeChoice)).toBe('system');
		expect(b.saved()).toBe('system');
		expect(b.showing()).toBe('light');
	});

	it("leaves the browser's copy alone when the response has no theme", async () => {
		// An API from before the preference existed, and every mocked fixture.
		const b = browser();
		b.values.set(LQAI_THEME_STORAGE_KEY, 'dark');
		themeChoice.set('dark');
		signIn();
		vi.mocked(getPreferences).mockResolvedValue(account());
		await initPreferences();
		expect(get(themeChoice)).toBe('dark');
		expect(b.saved()).toBe('dark');
		expect(b.showing()).toBeUndefined();
	});

	it('ignores a value that is not one of the three', () => {
		const b = browser();
		b.values.set(LQAI_THEME_STORAGE_KEY, 'dark');
		themeChoice.set('dark');
		for (const value of ['oled-dark', '', null, undefined, 1]) adoptAccountTheme(value);
		expect(get(themeChoice)).toBe('dark');
		expect(b.saved()).toBe('dark');
	});

	it('never adopts a theme from the cached preferences', async () => {
		// The cache is not keyed by person: another account's Dark must not apply before the server answers.
		const b = browser();
		b.values.set('lq-ai:preferences-cache', JSON.stringify(account('dark')));
		b.values.set(LQAI_THEME_STORAGE_KEY, 'light');
		themeChoice.set('light');
		signIn();
		const answer = deferred<Preferences>();
		vi.mocked(getPreferences).mockReturnValue(answer.promise);
		const loading = initPreferences();
		expect(get(preferences).appearance_theme).toBe('dark');
		expect(get(themeChoice)).toBe('light');
		expect(b.saved()).toBe('light');
		answer.reject(new Error('offline'));
		await loading;
		expect(get(themeChoice)).toBe('light');
		expect(b.saved()).toBe('light');
	});

	it('adopts the theme carried by the answer to another preference', async () => {
		const b = browser();
		b.values.set(LQAI_THEME_STORAGE_KEY, 'light');
		signIn();
		vi.mocked(patchPreferences).mockResolvedValue({ ...account('dark'), trust_pills: 'dots' });
		await setPreference('trust_pills', 'dots');
		expect(get(themeChoice)).toBe('dark');
		expect(b.saved()).toBe('dark');
	});

	it('does not repaint when the account agrees with the browser', async () => {
		const b = browser();
		b.values.set(LQAI_THEME_STORAGE_KEY, 'dark');
		signIn();
		vi.mocked(getPreferences).mockResolvedValue(account('dark'));
		await initPreferences();
		expect(get(themeChoice)).toBe('dark');
		expect(b.showing()).toBeUndefined();
	});
});

describe('signing out', () => {
	it("keeps the browser's copy, so the sign-in page stays in the same theme", async () => {
		const b = browser();
		signIn();
		vi.mocked(patchPreferences).mockResolvedValue(account('dark'));
		await chooseTheme('dark');
		clearSession();
		expect(get(preferences)).toEqual(defaultPreferences);
		expect(get(themeChoice)).toBe('dark');
		expect(b.saved()).toBe('dark');
	});

	it('never treats the default preferences as an account value', () => {
		expect('appearance_theme' in defaultPreferences).toBe(false);
	});
});
