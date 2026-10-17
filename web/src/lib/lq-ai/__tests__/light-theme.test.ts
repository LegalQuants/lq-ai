import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { describe, expect, it } from 'vitest';
import { applyLQAILightTheme, isLQAIPath } from '../light-theme';

const html = readFileSync(new URL('../../../app.html', import.meta.url), 'utf8');
const bootstrap = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]
	.map((match) => match[1])
	.find((script) => script.includes('const metaThemeColorTag'))!;

function fixture(pathname = '/lq-ai/chats', savedTheme = 'system', prefersDark = true) {
	const classes = new Set<string>();
	const properties = new Map<string, string>();
	const meta = new Map<string, string>();
	const listeners: Array<(event: { matches: boolean }) => void> = [];
	const root = {
		classList: {
			add: (...values: string[]) => values.forEach((value) => classes.add(value)),
			remove: (...values: string[]) => values.forEach((value) => classes.delete(value)),
			contains: (value: string) => classes.has(value)
		},
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
	const storage = { theme: savedTheme };
	const context = {
		document: doc,
		localStorage: storage,
		window: {
			location: { pathname },
			matchMedia: () => ({
				matches: prefersDark,
				addListener: (listener: (event: { matches: boolean }) => void) => listeners.push(listener)
			})
		}
	};
	return { classes, properties, meta, root, doc, storage, listeners, context };
}

describe('LQ.AI light-only theme', () => {
	it.each(['/lq-ai', '/lq-ai/login', '/lq-ai/chats'])('recognizes shell route %s', (path) => {
		expect(isLQAIPath(path)).toBe(true);
	});

	it.each(['/', '/auth', '/lq-ai-other'])('does not capture unrelated route %s', (path) => {
		expect(isLQAIPath(path)).toBe(false);
	});

	it('clears inherited dark/OLED styling when entering the shell', () => {
		const f = fixture();
		f.root.classList.add('dark', 'oled-dark', 'her', 'unrelated');
		f.properties.set('--color-gray-900', '#000000');
		applyLQAILightTheme(f.doc as unknown as Document);
		expect([...f.classes]).toEqual(['unrelated', 'light']);
		expect(f.properties.has('--color-gray-900')).toBe(false);
		expect(f.root.style.colorScheme).toBe('light');
		expect(f.meta.get('content')).toBe('#ffffff');
	});

	it.each(['system', 'dark', 'oled-dark', 'her', 'light'])(
		'boots light before hydration with saved %s and a dark OS',
		(savedTheme) => {
			const f = fixture('/lq-ai/login', savedTheme);
			runInNewContext(bootstrap, f.context);
			expect([...f.classes]).toEqual(['light']);
			expect(f.root.style.colorScheme).toBe('light');
			expect(f.meta.get('content')).toBe('#ffffff');
			expect(f.storage.theme).toBe(savedTheme);
		}
	);

	it('stays light when the OS changes to dark', () => {
		const f = fixture('/lq-ai/chats', 'system', false);
		runInNewContext(bootstrap, f.context);
		f.listeners.forEach((listener) => listener({ matches: true }));
		expect([...f.classes]).toEqual(['light']);
		expect(f.meta.get('content')).toBe('#ffffff');
	});

	it('ignores OS dark mode after client navigation into LQ.AI', () => {
		const f = fixture('/auth', 'system', false);
		runInNewContext(bootstrap, f.context);
		f.context.window.location.pathname = '/lq-ai/chats';
		f.listeners.forEach((listener) => listener({ matches: true }));
		expect([...f.classes]).toEqual(['light']);
	});

	it('does not read legacy storage to boot the LQ.AI login', () => {
		const f = fixture('/lq-ai/login');
		Object.defineProperty(f.context, 'localStorage', {
			get: () => {
				throw new Error('Storage unavailable');
			}
		});
		runInNewContext(bootstrap, f.context);
		expect([...f.classes]).toEqual(['light']);
	});

	it('preserves upstream theme selection outside the shell', () => {
		const f = fixture('/auth', 'dark');
		runInNewContext(bootstrap, f.context);
		expect(f.classes.has('dark')).toBe(true);
	});
});
