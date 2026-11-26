/**
 * The LQ.AI shell's theme (ADR 0045 §2).
 *
 * LQ.AI has its own theme, separate from Open WebUI's. On `/lq-ai` routes two
 * places apply it, and they must agree: the inline script in `src/app.html`
 * (before Svelte hydrates, so the first paint is right) and the root layout
 * (after client-side navigation). `__tests__/theme.test.ts` runs that inline
 * script against this module so the two cannot drift.
 *
 * Applying a theme sets four things on the document:
 * - `data-lq-theme` on `<html>`, which selects the `--lq-*` token values;
 * - the matching `light` or `dark` class, for carried Open WebUI components
 *   that render inside the shell (toasts, the root modals);
 * - `color-scheme`, so native controls and scrollbars follow;
 * - the browser theme colour.
 *
 * The browser's copy of the choice lives in `localStorage['lq-ai.theme']`.
 *
 * Dark is not offered yet. ADR 0045 §2: "Dark and Match system cannot be chosen
 * until every LQ.AI surface and modal is token-driven and the accessibility
 * check passes in both themes. Until then, Appearance offers Light only and
 * the default resolves to light." So here `system`, a missing value and any
 * unknown value all resolve to light, whatever the device prefers. Only an
 * explicit stored `dark` renders dark; no screen writes that value yet, and
 * the accessibility check's dark variants set it themselves.
 */
import { isLQAIPath } from './paths';

export type LQAITheme = 'light' | 'dark';
export type LQAIThemeChoice = 'light' | 'dark' | 'system';

export const LQAI_THEME_STORAGE_KEY = 'lq-ai.theme';

/** The browser theme colour: the page in light, the sidebar in dark (ADR 0045 §2). */
export const LQAI_THEME_COLOR: Record<LQAITheme, string> = {
	light: '#ffffff',
	dark: '#08080a'
};

/**
 * Whether `system` follows the device. Off until dark is offered (see the
 * header). The pull request that adds the choice to Appearance turns it on.
 */
export const LQAI_MATCH_SYSTEM_OFFERED: boolean = false;

/** Every root class a theme can leave behind, ours and Open WebUI's. */
const THEME_CLASSES = ['light', 'dark', 'oled-dark', 'her'];
/** Custom properties Open WebUI's OLED Dark sets inline on `<html>`. */
const OLED_SHADES = [800, 850, 900, 950];

/**
 * The Word add-in's sign-in dialog is an `/lq-ai` path that resets the layout
 * chain, so the token file is not loaded there and its colours are fixed light
 * fallbacks. It stays light until that page loads the tokens.
 */
export function isLQAIFixedLightPath(pathname: string): boolean {
	return pathname === '/lq-ai/word-addin' || pathname.startsWith('/lq-ai/word-addin/');
}

/** Reads the browser's copy of the choice. Storage can be unavailable; that is `system`. */
export function readLQAIThemeChoice(
	storage: Pick<Storage, 'getItem'> | undefined
): LQAIThemeChoice {
	try {
		const saved = storage?.getItem(LQAI_THEME_STORAGE_KEY);
		return saved === 'light' || saved === 'dark' ? saved : 'system';
	} catch {
		return 'system';
	}
}

export function resolveLQAITheme(
	choice: LQAIThemeChoice,
	prefersDark: boolean,
	pathname = '/lq-ai'
): LQAITheme {
	if (isLQAIFixedLightPath(pathname)) return 'light';
	if (choice === 'dark') return 'dark';
	if (choice === 'system' && LQAI_MATCH_SYSTEM_OFFERED && prefersDark) return 'dark';
	return 'light';
}

/** Applies a theme to the document. Clears whatever Open WebUI's theme left on `<html>`. */
export function applyLQAITheme(doc: Document, theme: LQAITheme): void {
	const root = doc.documentElement;
	root.classList.remove(...THEME_CLASSES);
	root.classList.add(theme);
	root.setAttribute('data-lq-theme', theme);
	root.style.colorScheme = theme;
	for (const shade of OLED_SHADES) root.style.removeProperty(`--color-gray-${shade}`);
	doc.querySelector('meta[name="theme-color"]')?.setAttribute('content', LQAI_THEME_COLOR[theme]);
}

/** Resolves the theme for the page the window is on, applies it and returns it. */
export function applyCurrentLQAITheme(win: Window): LQAITheme {
	let storage: Storage | undefined;
	try {
		storage = win.localStorage;
	} catch {
		storage = undefined;
	}
	const prefersDark = win.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
	const theme = resolveLQAITheme(readLQAIThemeChoice(storage), prefersDark, win.location.pathname);
	applyLQAITheme(win.document, theme);
	return theme;
}

/**
 * Hands the document back to Open WebUI's theme after client-side navigation
 * out of the shell. It gives `<html>` what `app.html` gives it on a fresh load
 * of an Open WebUI page with the same saved theme; the test compares the two.
 * `system` resolves to light there too (the carried patch from #280).
 */
export function leaveLQAITheme(doc: Document, savedUpstreamTheme: string | null | undefined): void {
	const root = doc.documentElement;
	if (!root.hasAttribute('data-lq-theme')) return;
	root.removeAttribute('data-lq-theme');
	root.style.colorScheme = '';
	root.classList.remove(...THEME_CLASSES);
	const meta = doc.querySelector('meta[name="theme-color"]');
	const saved = savedUpstreamTheme || 'system';
	if (saved === 'system' || saved === 'light') {
		root.classList.add('light');
		meta?.setAttribute('content', '#ffffff');
	} else if (saved === 'her') {
		root.classList.add('her');
		meta?.setAttribute('content', '#983724');
	} else if (saved === 'oled-dark') {
		root.style.setProperty('--color-gray-800', '#101010');
		root.style.setProperty('--color-gray-850', '#050505');
		root.style.setProperty('--color-gray-900', '#000000');
		root.style.setProperty('--color-gray-950', '#000000');
		root.classList.add('dark');
		meta?.setAttribute('content', '#000000');
	} else {
		root.classList.add('dark');
		meta?.setAttribute('content', '#171717');
	}
}

/** What the root layout needs on every navigation: our theme inside the shell, theirs outside. */
export function syncThemeToPath(win: Window): LQAITheme | null {
	if (isLQAIPath(win.location.pathname)) return applyCurrentLQAITheme(win);
	let saved: string | null = null;
	try {
		saved = win.localStorage.getItem('theme');
	} catch {
		saved = null;
	}
	leaveLQAITheme(win.document, saved);
	return null;
}
