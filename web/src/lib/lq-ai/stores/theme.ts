/**
 * The theme choice, for the screens that show or change it (ADR 0045 §2).
 *
 * `themeChoice` is what Appearance and the sidebar read: Light, Dark or Match
 * system. It starts from the browser's copy, which is also what painted the
 * page. Two things change it:
 *
 * - a person choosing (`applyThemeChoice`): the browser's copy and the page
 *   change at once; `chooseTheme` in `stores/preferences.ts` then saves the
 *   choice to the account;
 * - the account's value arriving (`adoptAccountTheme`): it wins over the
 *   browser's copy, so a choice made on another device follows the person.
 *
 * Only a server response may call `adoptAccountTheme`, and only a response
 * that carries one of the three values is adopted. Defaults and the cached
 * preferences never are: the cache is not keyed by person, and a default is
 * not a choice. A response without the field (an API from before the
 * preference existed) leaves the browser's copy standing. Signing out changes
 * nothing here, so the sign-in page keeps the theme the browser last showed.
 */
import { writable } from 'svelte/store';
import {
	isLQAIThemeChoice,
	readLQAIThemeChoice,
	setLQAIThemeChoice,
	type LQAIThemeChoice
} from '../theme';

function browserStorage(): Storage | undefined {
	try {
		return typeof window === 'undefined' ? undefined : window.localStorage;
	} catch {
		return undefined;
	}
}

export const themeChoice = writable<LQAIThemeChoice>(readLQAIThemeChoice(browserStorage()));

/** A person chose a theme: this browser shows it now and remembers it. */
export function applyThemeChoice(choice: LQAIThemeChoice): void {
	themeChoice.set(choice);
	if (typeof window !== 'undefined') setLQAIThemeChoice(window, choice);
}

/** The account's saved choice, as a server response carried it. It wins over the browser's copy. */
export function adoptAccountTheme(value: unknown): void {
	if (!isLQAIThemeChoice(value)) return;
	themeChoice.set(value);
	if (typeof window === 'undefined') return;
	if (readLQAIThemeChoice(browserStorage()) !== value) setLQAIThemeChoice(window, value);
}
