import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { describe, expect, it } from 'vitest';
import {
	LQAI_THEME_CHOICES,
	LQAI_THEME_COLOR,
	LQAI_THEME_EVENT,
	LQAI_THEME_LABEL,
	LQAI_THEME_STORAGE_KEY,
	applyCurrentLQAITheme,
	applyLQAITheme,
	isLQAIFixedLightPath,
	isLQAIThemeChoice,
	leaveLQAITheme,
	nextLQAIThemeChoice,
	readLQAIThemeChoice,
	resolveLQAITheme,
	setLQAIThemeChoice,
	syncThemeToPath,
	writeLQAIThemeChoice
} from '../theme';

const html = readFileSync(new URL('../../../app.html', import.meta.url), 'utf8');
/** The inline script in app.html that applies a theme before Svelte hydrates. */
const bootstrap = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]
	.map((match) => match[1])
	.find((script) => script.includes('const metaThemeColorTag'))!;

interface Stored {
	/** Open WebUI's saved theme (`localStorage.theme`). */
	upstream?: string;
	/** LQ.AI's saved choice (`localStorage['lq-ai.theme']`). */
	lq?: string;
}

/** A document, storage and window small enough to run the inline script and the module on. */
function fixture(pathname = '/lq-ai/chats', stored: Stored = {}, prefersDark = true) {
	const classes = new Set<string>();
	const attributes = new Map<string, string>();
	const properties = new Map<string, string>();
	const meta = new Map<string, string>();
	const listeners: Array<(event: { matches: boolean }) => void> = [];
	const events: Array<{ type: string; detail: unknown }> = [];
	const root = {
		classList: {
			add: (...values: string[]) => values.forEach((value) => classes.add(value)),
			remove: (...values: string[]) => values.forEach((value) => classes.delete(value)),
			contains: (value: string) => classes.has(value)
		},
		setAttribute: (key: string, value: string) => attributes.set(key, value),
		removeAttribute: (key: string) => attributes.delete(key),
		hasAttribute: (key: string) => attributes.has(key),
		style: {
			colorScheme: '',
			setProperty: (key: string, value: string) => properties.set(key, value),
			removeProperty: (key: string) => properties.delete(key)
		}
	};
	const doc = {
		documentElement: root,
		querySelector: () => ({ setAttribute: (key: string, value: string) => meta.set(key, value) }),
		createElement: () => ({ setAttribute: () => {} }),
		head: { appendChild: () => {} },
		addEventListener: () => {}
	};
	const values = new Map<string, string>();
	if (stored.upstream !== undefined) values.set('theme', stored.upstream);
	if (stored.lq !== undefined) values.set(LQAI_THEME_STORAGE_KEY, stored.lq);
	const storage = {
		getItem: (key: string) => values.get(key) ?? null,
		setItem: (key: string, value: string) => void values.set(key, value),
		get theme() {
			return values.get('theme');
		},
		set theme(value: string | undefined) {
			if (value === undefined) values.delete('theme');
			else values.set('theme', value);
		}
	};
	const win = {
		location: { pathname },
		document: doc,
		localStorage: storage,
		matchMedia: () => ({
			matches: prefersDark,
			addListener: (listener: (event: { matches: boolean }) => void) => listeners.push(listener)
		}),
		dispatchEvent: (event: { type: string; detail?: unknown }) => {
			events.push({ type: event.type, detail: event.detail });
			return true;
		}
	};
	/** The inline script runs in its own realm, so it gets an event class of its own. */
	class FixtureEvent {
		detail: unknown;
		constructor(
			public type: string,
			init?: { detail?: unknown }
		) {
			this.detail = init?.detail;
		}
	}
	const context = { document: doc, localStorage: storage, window: win, CustomEvent: FixtureEvent };
	const state = () => ({
		classes: [...classes].sort(),
		lqTheme: attributes.get('data-lq-theme'),
		colorScheme: root.style.colorScheme,
		themeColor: meta.get('content'),
		oled: [...properties.keys()].sort()
	});
	return {
		classes,
		attributes,
		properties,
		meta,
		root,
		doc,
		win,
		values,
		listeners,
		events,
		context,
		state
	};
}

const asDocument = (f: ReturnType<typeof fixture>) => f.doc as unknown as Document;
const asWindow = (f: ReturnType<typeof fixture>) => f.win as unknown as Window;

const LIGHT = {
	classes: ['light'],
	lqTheme: 'light',
	colorScheme: 'light',
	themeColor: '#ffffff',
	oled: []
};
const DARK = {
	classes: ['dark'],
	lqTheme: 'dark',
	colorScheme: 'dark',
	themeColor: '#08080a',
	oled: []
};

describe('LQ.AI theme: resolving the choice', () => {
	it('offers Light, Dark and Match system, in that order', () => {
		expect(LQAI_THEME_CHOICES).toEqual(['light', 'dark', 'system']);
		expect(LQAI_THEME_LABEL).toEqual({ light: 'Light', dark: 'Dark', system: 'Match system' });
		expect(nextLQAIThemeChoice('light')).toBe('dark');
		expect(nextLQAIThemeChoice('dark')).toBe('system');
		expect(nextLQAIThemeChoice('system')).toBe('light');
		expect(['light', 'dark', 'system'].every(isLQAIThemeChoice)).toBe(true);
		expect([undefined, null, '', 'oled-dark', 'Dark', 1].some(isLQAIThemeChoice)).toBe(false);
	});

	it('follows the device for Match system and nothing else', () => {
		for (const prefersDark of [true, false]) {
			expect(resolveLQAITheme('dark', prefersDark)).toBe('dark');
			expect(resolveLQAITheme('light', prefersDark)).toBe('light');
		}
		// ADR 0045 §2: Match system follows the device's prefers-color-scheme.
		expect(resolveLQAITheme('system', true)).toBe('dark');
		expect(resolveLQAITheme('system', false)).toBe('light');
	});

	it('reads the browser copy and treats anything else as system', () => {
		const stored = (value?: string) => ({
			getItem: (key: string) => (key === LQAI_THEME_STORAGE_KEY ? (value ?? null) : 'dark')
		});
		expect(readLQAIThemeChoice(stored('dark'))).toBe('dark');
		expect(readLQAIThemeChoice(stored('light'))).toBe('light');
		expect(readLQAIThemeChoice(stored('system'))).toBe('system');
		expect(readLQAIThemeChoice(stored())).toBe('system');
		// Open WebUI's values are not ours.
		expect(readLQAIThemeChoice(stored('oled-dark'))).toBe('system');
		expect(readLQAIThemeChoice(undefined)).toBe('system');
		expect(
			readLQAIThemeChoice({
				getItem: () => {
					throw new Error('Storage unavailable');
				}
			})
		).toBe('system');
	});

	it('writes the browser copy, and survives storage that refuses', () => {
		const f = fixture();
		for (const choice of LQAI_THEME_CHOICES) {
			writeLQAIThemeChoice(f.win.localStorage, choice);
			expect(f.values.get(LQAI_THEME_STORAGE_KEY)).toBe(choice);
			expect(readLQAIThemeChoice(f.win.localStorage)).toBe(choice);
		}
		expect(() =>
			writeLQAIThemeChoice(
				{
					setItem: () => {
						throw new Error('Quota exceeded');
					}
				},
				'dark'
			)
		).not.toThrow();
		expect(() => writeLQAIThemeChoice(undefined, 'dark')).not.toThrow();
	});

	it("keeps the Word add-in's sign-in dialog light, whatever is stored", () => {
		expect(isLQAIFixedLightPath('/lq-ai/word-addin/oauth-start')).toBe(true);
		expect(isLQAIFixedLightPath('/lq-ai/word-addins')).toBe(false);
		expect(isLQAIFixedLightPath('/lq-ai/chats')).toBe(false);
		expect(resolveLQAITheme('dark', true, '/lq-ai/word-addin/oauth-start')).toBe('light');
		expect(resolveLQAITheme('system', true, '/lq-ai/word-addin/oauth-start')).toBe('light');
		const f = fixture('/lq-ai/word-addin/oauth-start', { lq: 'dark' });
		expect(applyCurrentLQAITheme(asWindow(f))).toBe('light');
		expect(f.state()).toEqual(LIGHT);
	});
});

describe('LQ.AI theme: applying it', () => {
	it('sets the attribute, the class, color-scheme and the browser theme colour', () => {
		expect(LQAI_THEME_COLOR).toEqual({ light: '#ffffff', dark: '#08080a' });
		const f = fixture();
		applyLQAITheme(asDocument(f), 'dark');
		expect(f.state()).toEqual(DARK);
		applyLQAITheme(asDocument(f), 'light');
		expect(f.state()).toEqual(LIGHT);
	});

	it("clears what Open WebUI's theme left on the root", () => {
		const f = fixture();
		f.root.classList.add('dark', 'oled-dark', 'her', 'unrelated');
		f.properties.set('--color-gray-900', '#000000');
		applyLQAITheme(asDocument(f), 'light');
		expect(f.state()).toEqual({ ...LIGHT, classes: ['light', 'unrelated'] });
	});

	it('follows the device when storage throws', () => {
		for (const prefersDark of [true, false]) {
			const f = fixture('/lq-ai/login', { lq: 'dark' }, prefersDark);
			Object.defineProperty(f.win, 'localStorage', {
				get: () => {
					throw new Error('Storage unavailable');
				}
			});
			expect(applyCurrentLQAITheme(asWindow(f))).toBe(prefersDark ? 'dark' : 'light');
			expect(f.state()).toEqual(prefersDark ? DARK : LIGHT);
		}
	});

	it('announces the theme it applied, so the toasts can follow', () => {
		const f = fixture('/lq-ai/chats', { lq: 'dark' });
		applyCurrentLQAITheme(asWindow(f));
		expect(f.events).toEqual([{ type: LQAI_THEME_EVENT, detail: 'dark' }]);
	});

	it('saves a choice to the browser, applies it and announces it', () => {
		const f = fixture('/lq-ai/chats', { lq: 'light', upstream: 'dark' }, true);
		expect(setLQAIThemeChoice(asWindow(f), 'dark')).toBe('dark');
		expect(f.values.get(LQAI_THEME_STORAGE_KEY)).toBe('dark');
		expect(f.state()).toEqual(DARK);
		expect(setLQAIThemeChoice(asWindow(f), 'system')).toBe('dark');
		expect(f.values.get(LQAI_THEME_STORAGE_KEY)).toBe('system');
		expect(setLQAIThemeChoice(asWindow(f), 'light')).toBe('light');
		expect(f.state()).toEqual(LIGHT);
		expect(f.events.map((event) => event.detail)).toEqual(['dark', 'dark', 'light']);
		// Open WebUI's saved theme is never ours to write.
		expect(f.values.get('theme')).toBe('dark');
	});

	it('saves a choice made outside the shell without touching that page', () => {
		const f = fixture('/auth', { upstream: 'light' });
		f.root.classList.add('light');
		expect(setLQAIThemeChoice(asWindow(f), 'dark')).toBeNull();
		expect(f.values.get(LQAI_THEME_STORAGE_KEY)).toBe('dark');
		expect([...f.classes]).toEqual(['light']);
		expect(f.attributes.has('data-lq-theme')).toBe(false);
		expect(f.events).toEqual([]);
	});
});

describe('LQ.AI theme: the inline script in app.html agrees with the module', () => {
	const paths = ['/lq-ai', '/lq-ai/login', '/lq-ai/chats', '/lq-ai/word-addin/oauth-start'];
	const lqValues = [undefined, 'light', 'dark', 'system', 'oled-dark'];
	const upstreamValues = ['system', 'dark', 'oled-dark', 'her', 'light'];
	const cases = paths.flatMap((path) =>
		lqValues.flatMap((lq) =>
			upstreamValues.flatMap((upstream) =>
				[true, false].map((prefersDark) => ({ path, lq, upstream, prefersDark }))
			)
		)
	);

	it.each(cases)(
		'boots $path the same way (lq-ai.theme=$lq, theme=$upstream, dark OS=$prefersDark)',
		({ path, lq, upstream, prefersDark }) => {
			const booted = fixture(path, { lq, upstream }, prefersDark);
			runInNewContext(bootstrap, booted.context);
			const applied = fixture(path, { lq, upstream }, prefersDark);
			applyCurrentLQAITheme(asWindow(applied));
			expect(booted.state()).toEqual(applied.state());
			expect(booted.events).toEqual(applied.events);
			// Light and Dark are fixed; anything else follows the device. One page is always light.
			const dark =
				!isLQAIFixedLightPath(path) && (lq === 'dark' || (lq !== 'light' && prefersDark));
			expect(booted.state()).toEqual(dark ? DARK : LIGHT);
			// The shell never writes Open WebUI's saved theme.
			expect(booted.values.get('theme')).toBe(upstream);
		}
	);

	it('follows the device when storage is unavailable', () => {
		for (const prefersDark of [true, false]) {
			const f = fixture('/lq-ai/login', { lq: 'dark' }, prefersDark);
			Object.defineProperty(f.context, 'localStorage', {
				get: () => {
					throw new Error('Storage unavailable');
				}
			});
			runInNewContext(bootstrap, f.context);
			expect(f.state()).toEqual(prefersDark ? DARK : LIGHT);
		}
	});

	it.each(['light', 'dark'])('keeps %s when the device changes its colour scheme', (lq) => {
		const f = fixture('/lq-ai/chats', { lq, upstream: 'system' }, false);
		runInNewContext(bootstrap, f.context);
		expect(f.listeners).toHaveLength(1);
		f.listeners.forEach((listener) => listener({ matches: true }));
		expect(f.state()).toEqual(lq === 'dark' ? DARK : LIGHT);
	});

	it.each([undefined, 'system'])(
		'follows the device when it changes and the choice is Match system (stored %s)',
		(lq) => {
			const f = fixture('/lq-ai/chats', { lq, upstream: 'light' }, false);
			runInNewContext(bootstrap, f.context);
			expect(f.state()).toEqual(LIGHT);
			f.listeners.forEach((listener) => listener({ matches: true }));
			expect(f.state()).toEqual(DARK);
			f.listeners.forEach((listener) => listener({ matches: false }));
			expect(f.state()).toEqual(LIGHT);
			expect(f.events.map((event) => event.detail)).toEqual(['light', 'dark', 'light']);
			// Open WebUI's saved theme played no part.
			expect(f.values.get('theme')).toBe('light');
		}
	);

	it('applies the LQ.AI theme when the device changes after client navigation into the shell', () => {
		const f = fixture('/auth', { upstream: 'system', lq: 'dark' }, false);
		runInNewContext(bootstrap, f.context);
		expect(f.attributes.has('data-lq-theme')).toBe(false);
		f.win.location.pathname = '/lq-ai/chats';
		f.listeners.forEach((listener) => listener({ matches: true }));
		expect(f.state()).toEqual(DARK);
	});

	it("never takes Open WebUI's class inside the shell when the device changes", () => {
		// Open WebUI's own listener handles its `system`; it must not run on an LQ.AI page.
		const f = fixture('/lq-ai/chats', { lq: 'light', upstream: 'system' }, false);
		runInNewContext(bootstrap, f.context);
		f.listeners.forEach((listener) => listener({ matches: true }));
		expect(f.state()).toEqual(LIGHT);
	});
});

describe("Open WebUI's theme outside the shell", () => {
	// ADR 0045 §2 reverts #280's stopgap: `/` renders as upstream does, in each of its themes.
	it.each([true, false])(
		'follows the device for the upstream system theme (dark OS=%s)',
		(dark) => {
			const f = fixture('/auth', { upstream: 'system' }, dark);
			runInNewContext(bootstrap, f.context);
			expect([...f.classes]).toEqual([dark ? 'dark' : 'light']);
			expect(f.meta.get('content')).toBe(dark ? '#171717' : '#ffffff');
			expect(f.attributes.has('data-lq-theme')).toBe(false);
			expect(f.root.style.colorScheme).toBe('');
			expect(f.events).toEqual([]);
			f.listeners.forEach((listener) => listener({ matches: !dark }));
			expect([...f.classes]).toEqual([dark ? 'light' : 'dark']);
			expect(f.meta.get('content')).toBe(dark ? '#ffffff' : '#171717');
		}
	);

	it.each(['light', 'dark', 'oled-dark', 'her'])(
		'keeps the upstream %s theme when the device changes',
		(upstream) => {
			const f = fixture('/auth', { upstream }, false);
			runInNewContext(bootstrap, f.context);
			const before = f.state();
			f.listeners.forEach((listener) => listener({ matches: true }));
			expect(f.state()).toEqual(before);
		}
	);

	it('gives a first visit the upstream system theme', () => {
		const f = fixture('/auth', {}, true);
		runInNewContext(bootstrap, f.context);
		expect(f.values.get('theme')).toBe('system');
		expect([...f.classes]).toEqual(['dark']);
	});

	it("ignores LQ.AI's choice on an Open WebUI page", () => {
		const f = fixture('/auth', { upstream: 'light', lq: 'dark' });
		runInNewContext(bootstrap, f.context);
		expect([...f.classes]).toEqual(['light']);
		expect(f.attributes.has('data-lq-theme')).toBe(false);
	});

	const leaving = ['system', 'light', 'dark', 'oled-dark', 'her'].flatMap((upstream) =>
		[true, false].map((prefersDark) => ({ upstream, prefersDark }))
	);
	it.each(leaving)(
		'gets the document back as a fresh load would leave it (saved $upstream, dark OS=$prefersDark)',
		({ upstream, prefersDark }) => {
			// A fresh load of an Open WebUI page with this saved theme.
			const fresh = fixture('/auth', { upstream }, prefersDark);
			runInNewContext(bootstrap, fresh.context);
			// The same page reached by client navigation out of a dark LQ.AI shell.
			const left = fixture('/lq-ai/chats', { upstream, lq: 'dark' }, prefersDark);
			expect(syncThemeToPath(asWindow(left))).toBe('dark');
			left.win.location.pathname = '/auth';
			expect(syncThemeToPath(asWindow(left))).toBeNull();
			expect(left.state()).toEqual({ ...fresh.state(), colorScheme: '' });
			expect(left.attributes.has('data-lq-theme')).toBe(false);
		}
	);

	it('leaves a document it never themed alone', () => {
		const f = fixture('/auth', { upstream: 'dark' });
		f.root.classList.add('dark');
		leaveLQAITheme(asDocument(f), 'light', true);
		expect([...f.classes]).toEqual(['dark']);
	});
});
