/**
 * The LQ.AI shell's theme (ADR 0045 §2).
 *
 * LQ.AI has its own theme, separate from Open WebUI's. People choose Light,
 * Dark or Match system; Match system is the default and follows the device.
 *
 * On `/lq-ai` routes two places apply the theme, and they must agree: the
 * inline script in `src/app.html` (before Svelte hydrates, so the first paint
 * is right, and again when the device changes its colour scheme) and the root
 * layout (after client-side navigation). `__tests__/theme.test.ts` runs that
 * inline script against this module so the two cannot drift.
 *
 * Applying a theme sets four things on the document:
 * - `data-lq-theme` on `<html>`, which selects the `--lq-*` token values;
 * - the matching `light` or `dark` class, for carried Open WebUI components
 *   that render inside the shell (toasts, the root modals);
 * - `color-scheme`, so native controls and scrollbars follow;
 * - the browser theme colour.
 * It also announces the theme on the window (`LQAI_THEME_EVENT`), which is how
 * the root layout keeps the toasts in step without a navigation.
 *
 * Where the choice lives: the account holds it (`appearance_theme` on
 * `/api/v1/users/me/preferences`), and the browser keeps a copy in
 * `localStorage['lq-ai.theme']` so the page paints in the right theme before
 * sign-in has loaded. The account's value wins once it arrives; that part is in
 * `stores/theme.ts`. This module knows only the browser copy and the document.
 */
import { isLQAIPath } from './paths';

export type LQAITheme = 'light' | 'dark';
export type LQAIThemeChoice = 'light' | 'dark' | 'system';

// Shared with the pre-hydration device listener in app.html. This page can keep
// its choice even when browser storage refuses writes or another tab changes it.
declare global {
	interface Window {
		lqThemeChoice?: LQAIThemeChoice;
	}
}

/** The choices, in the order Appearance shows them and the sidebar steps through them. */
export const LQAI_THEME_CHOICES: readonly LQAIThemeChoice[] = ['light', 'dark', 'system'];

export const LQAI_THEME_LABEL: Record<LQAIThemeChoice, string> = {
	light: 'Light',
	dark: 'Dark',
	system: 'Match system'
};

export const LQAI_THEME_STORAGE_KEY = 'lq-ai.theme';

/** Fired on the window, with the applied theme as `detail`, whenever a theme is applied. */
export const LQAI_THEME_EVENT = 'lq-ai:theme';

/** The browser theme colour: the page in light, the sidebar in dark (ADR 0045 §2). */
export const LQAI_THEME_COLOR: Record<LQAITheme, string> = {
	light: '#ffffff',
	dark: '#08080a'
};

/** Every root class a theme can leave behind, ours and Open WebUI's. */
const THEME_CLASSES = ['light', 'dark', 'oled-dark', 'her'];
/** Custom properties Open WebUI's OLED Dark sets inline on `<html>`. */
const OLED_SHADES = [800, 850, 900, 950];

export function isLQAIThemeChoice(value: unknown): value is LQAIThemeChoice {
	return value === 'light' || value === 'dark' || value === 'system';
}

/** The choice after this one, for a control that steps through all three. */
export function nextLQAIThemeChoice(choice: LQAIThemeChoice): LQAIThemeChoice {
	const index = LQAI_THEME_CHOICES.indexOf(choice);
	return LQAI_THEME_CHOICES[(index + 1) % LQAI_THEME_CHOICES.length];
}

/** Reads the browser's copy of the choice. A missing or foreign value, or no storage, is `system`. */
export function readLQAIThemeChoice(
	storage: Pick<Storage, 'getItem'> | undefined
): LQAIThemeChoice {
	try {
		const saved = storage?.getItem(LQAI_THEME_STORAGE_KEY);
		return isLQAIThemeChoice(saved) ? saved : 'system';
	} catch {
		return 'system';
	}
}

/** Writes the browser's copy of the choice. Storage that refuses is ignored: the page still themes. */
export function writeLQAIThemeChoice(
	storage: Pick<Storage, 'setItem'> | undefined,
	choice: LQAIThemeChoice
): void {
	try {
		storage?.setItem(LQAI_THEME_STORAGE_KEY, choice);
	} catch {
		// The choice then lasts for this page only.
	}
}

export function resolveLQAITheme(choice: LQAIThemeChoice, prefersDark: boolean): LQAITheme {
	if (choice === 'light' || choice === 'dark') return choice;
	return prefersDark ? 'dark' : 'light';
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

function storageOf(win: Window): Storage | undefined {
	try {
		return win.localStorage;
	} catch {
		return undefined;
	}
}

function prefersDark(win: Window): boolean {
	return win.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
}

export function currentLQAIThemeChoice(win: Window): LQAIThemeChoice {
	return (win.lqThemeChoice ??= readLQAIThemeChoice(storageOf(win)));
}

/** Resolves the theme for the page the window is on, applies it, announces it and returns it. */
export function applyCurrentLQAITheme(win: Window): LQAITheme {
	const theme = resolveLQAITheme(currentLQAIThemeChoice(win), prefersDark(win));
	applyLQAITheme(win.document, theme);
	try {
		win.dispatchEvent(new CustomEvent(LQAI_THEME_EVENT, { detail: theme }));
	} catch {
		// Nothing can be listening where events are unavailable.
	}
	return theme;
}

/**
 * Saves a choice to the browser and, inside the shell, applies it. Returns the
 * theme now showing, or null on a page that is not LQ.AI's (its theme is Open
 * WebUI's, and stays as it is).
 */
export function setLQAIThemeChoice(win: Window, choice: LQAIThemeChoice): LQAITheme | null {
	win.lqThemeChoice = choice;
	writeLQAIThemeChoice(storageOf(win), choice);
	return isLQAIPath(win.location.pathname) ? applyCurrentLQAITheme(win) : null;
}

/**
 * Hands the document back to Open WebUI's theme after client-side navigation
 * out of the shell. It gives `<html>` what `app.html` gives it on a fresh load
 * of an Open WebUI page with the same saved theme; the test compares the two.
 * Open WebUI's `system` follows the device, as upstream has it.
 */
export function leaveLQAITheme(
	doc: Document,
	savedUpstreamTheme: string | null | undefined,
	devicePrefersDark: boolean
): void {
	const root = doc.documentElement;
	if (!root.hasAttribute('data-lq-theme')) return;
	root.removeAttribute('data-lq-theme');
	root.style.colorScheme = '';
	root.classList.remove(...THEME_CLASSES);
	const meta = doc.querySelector('meta[name="theme-color"]');
	const saved = savedUpstreamTheme || 'system';
	if (saved === 'light' || (saved === 'system' && !devicePrefersDark)) {
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
	leaveLQAITheme(win.document, saved, prefersDark(win));
	return null;
}
