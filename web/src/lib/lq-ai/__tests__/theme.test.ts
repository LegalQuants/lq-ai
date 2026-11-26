import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { describe, expect, it } from 'vitest';
import {
	LQAI_MATCH_SYSTEM_OFFERED,
	LQAI_THEME_COLOR,
	LQAI_THEME_STORAGE_KEY,
	applyCurrentLQAITheme,
	applyLQAITheme,
	isLQAIFixedLightPath,
	leaveLQAITheme,
	readLQAIThemeChoice,
	resolveLQAITheme,
	syncThemeToPath
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
		})
	};
	const context = { document: doc, localStorage: storage, window: win };
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
	it('renders dark only for an explicit dark choice while dark is not offered', () => {
		expect(LQAI_MATCH_SYSTEM_OFFERED).toBe(false);
		for (const prefersDark of [true, false]) {
			expect(resolveLQAITheme('dark', prefersDark)).toBe('dark');
			expect(resolveLQAITheme('light', prefersDark)).toBe('light');
			// ADR 0045 §2: until dark is offered, the default resolves to light.
			expect(resolveLQAITheme('system', prefersDark)).toBe('light');
		}
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

	it("keeps the Word add-in's sign-in dialog light, whatever is stored", () => {
		expect(isLQAIFixedLightPath('/lq-ai/word-addin/oauth-start')).toBe(true);
		expect(isLQAIFixedLightPath('/lq-ai/word-addins')).toBe(false);
		expect(isLQAIFixedLightPath('/lq-ai/chats')).toBe(false);
		expect(resolveLQAITheme('dark', true, '/lq-ai/word-addin/oauth-start')).toBe('light');
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

	it('survives storage that throws', () => {
		const f = fixture('/lq-ai/login', { lq: 'dark' });
		Object.defineProperty(f.win, 'localStorage', {
			get: () => {
				throw new Error('Storage unavailable');
			}
		});
		expect(applyCurrentLQAITheme(asWindow(f))).toBe('light');
		expect(f.state()).toEqual(LIGHT);
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
			// Only an explicit dark renders dark, and never on the fixed-light page.
			expect(booted.state()).toEqual(lq === 'dark' && !isLQAIFixedLightPath(path) ? DARK : LIGHT);
			// The shell never writes Open WebUI's saved theme.
			expect(booted.values.get('theme')).toBe(upstream);
		}
	);

	it('boots light when storage is unavailable', () => {
		const f = fixture('/lq-ai/login', { lq: 'dark' });
		Object.defineProperty(f.context, 'localStorage', {
			get: () => {
				throw new Error('Storage unavailable');
			}
		});
		runInNewContext(bootstrap, f.context);
		expect(f.state()).toEqual(LIGHT);
	});

	it.each(['light', 'dark'])('keeps %s when the device changes its colour scheme', (lq) => {
		const f = fixture('/lq-ai/chats', { lq, upstream: 'system' }, false);
		runInNewContext(bootstrap, f.context);
		expect(f.listeners).toHaveLength(1);
		f.listeners.forEach((listener) => listener({ matches: true }));
		expect(f.state()).toEqual(lq === 'dark' ? DARK : LIGHT);
	});

	it('applies the LQ.AI theme when the device changes after client navigation into the shell', () => {
		const f = fixture('/auth', { upstream: 'system', lq: 'dark' }, false);
		runInNewContext(bootstrap, f.context);
		expect(f.attributes.has('data-lq-theme')).toBe(false);
		f.win.location.pathname = '/lq-ai/chats';
		f.listeners.forEach((listener) => listener({ matches: true }));
		expect(f.state()).toEqual(DARK);
	});
});

describe("Open WebUI's theme outside the shell", () => {
	it('keeps the upstream system theme light under a dark OS (the #280 carried patch)', () => {
		const f = fixture('/auth', { upstream: 'system' }, true);
		runInNewContext(bootstrap, f.context);
		expect([...f.classes]).toEqual(['light']);
		expect(f.meta.get('content')).toBe('#ffffff');
		expect(f.attributes.has('data-lq-theme')).toBe(false);
		f.listeners.forEach((listener) => listener({ matches: true }));
		expect([...f.classes]).toEqual(['light']);
	});

	it("ignores LQ.AI's choice on an Open WebUI page", () => {
		const f = fixture('/auth', { upstream: 'light', lq: 'dark' });
		runInNewContext(bootstrap, f.context);
		expect([...f.classes]).toEqual(['light']);
		expect(f.attributes.has('data-lq-theme')).toBe(false);
	});

	it.each(['system', 'light', 'dark', 'oled-dark', 'her'])(
		'gets the document back as a fresh load would leave it (saved %s)',
		(upstream) => {
			// A fresh load of an Open WebUI page with this saved theme.
			const fresh = fixture('/auth', { upstream });
			runInNewContext(bootstrap, fresh.context);
			// The same page reached by client navigation out of a dark LQ.AI shell.
			const left = fixture('/lq-ai/chats', { upstream, lq: 'dark' });
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
		leaveLQAITheme(asDocument(f), 'light');
		expect([...f.classes]).toEqual(['dark']);
	});
});
