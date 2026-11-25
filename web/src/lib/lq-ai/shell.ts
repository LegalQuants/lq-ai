/**
 * Developer-only switch for the redesigned LQ.AI chrome (interface-redesign
 * work plan, fork 11).
 *
 * While the left sidebar is built in pieces, `routes/lq-ai/+layout.svelte`
 * renders it only when `localStorage['lq-ai.shell']` is exactly `'sidebar'`.
 * Anything else, including no value, an unreadable store, or server-side
 * rendering, keeps today's header and tab row. The switch is not shown in the
 * interface; the cutover (P1.3c) makes the sidebar the default and deletes
 * this file.
 */

export const SHELL_SWITCH_KEY = 'lq-ai.shell';

export type ShellVariant = 'tabs' | 'sidebar';

type StorageLike = Pick<Storage, 'getItem'>;

/**
 * Whether the redesigned chrome is on for this page: the switch is on and the
 * page is not one of the sign-in routes (sign-in and forced password change),
 * which keep today's chrome.
 */
export function sidebarChromeOn(shell: ShellVariant, authExempt: boolean): boolean {
	return shell === 'sidebar' && !authExempt;
}

/**
 * The chrome to render. `getStorage` is called inside the guard because
 * merely reading `window.localStorage` can throw (blocked site data, some
 * private windows); every failure falls back to today's chrome.
 */
export function readShellSwitch(
	getStorage: () => StorageLike | undefined = () =>
		typeof window === 'undefined' ? undefined : window.localStorage
): ShellVariant {
	try {
		return getStorage()?.getItem(SHELL_SWITCH_KEY) === 'sidebar' ? 'sidebar' : 'tabs';
	} catch {
		return 'tabs';
	}
}
