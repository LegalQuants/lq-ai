/**
 * Open and collapsed state of the left sidebar in the redesigned LQ.AI shell
 * (interface-redesign work plan, Annex B P1.3b), behind the developer switch
 * in `./shell`.
 *
 * Wide screens: the sidebar is a column, open or collapsed to a thin strip
 * that keeps its toggle (and the notification bell when Automations is on).
 * The choice is remembered in `localStorage['lq-ai.left-sidebar']`, every
 * access guarded as in `./shell` and `./rightSidebar`: server-side rendering,
 * blocked site data or an unknown value fall back to open, and a failed write
 * is ignored.
 *
 * Narrow screens (the same breakpoint as the right sidebar's sheet,
 * `NARROW_QUERY`): only the strip takes room; opening the sidebar lays it
 * over the page. It starts closed there and the choice is not remembered.
 */
import { writable } from 'svelte/store';

export { NARROW_QUERY } from './rightSidebar';

export const LEFT_SIDEBAR_STORAGE_KEY = 'lq-ai.left-sidebar';
/** The sidebar panel's id; both toggles point at it. */
export const LEFT_SIDEBAR_ID = 'lq-left-sidebar';

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>;
type GetStorage = () => StorageLike | undefined;

const defaultStorage: GetStorage = () =>
	typeof window === 'undefined' ? undefined : window.localStorage;

/** Whether the sidebar is open (a column on wide screens, over the page on narrow ones). */
export const leftSidebarOpen = writable(true);
/** Whether the viewport is narrow. */
export const leftSidebarNarrow = writable(false);

/** The remembered choice on wide screens: open unless the person collapsed it. */
export function readLeftSidebarOpen(getStorage: GetStorage = defaultStorage): boolean {
	try {
		return getStorage()?.getItem(LEFT_SIDEBAR_STORAGE_KEY) !== 'collapsed';
	} catch {
		return true;
	}
}

/** Remember the choice. A failed write is ignored. */
export function writeLeftSidebarOpen(open: boolean, getStorage: GetStorage = defaultStorage): void {
	try {
		getStorage()?.setItem(LEFT_SIDEBAR_STORAGE_KEY, open ? 'open' : 'collapsed');
	} catch {
		// Storage blocked or full: the choice is simply not remembered.
	}
}

/** Narrow screens start closed; wide ones as remembered. */
export function initialLeftSidebarOpen(remembered: boolean, narrow: boolean): boolean {
	return remembered && !narrow;
}

export type LeftSidebarMode = 'open' | 'collapsed' | 'overlay';

/**
 * How the sidebar renders: a column when open on a wide screen, a strip when
 * closed (any width), the strip plus the panel over the page when open on a
 * narrow screen.
 */
export function leftSidebarMode(state: { open: boolean; narrow: boolean }): LeftSidebarMode {
	if (!state.open) return 'collapsed';
	return state.narrow ? 'overlay' : 'open';
}

/**
 * Whether the layout renders the ADR 0001 attribution footer below the page.
 * With the redesigned chrome off it always does (today's footer). With it on,
 * the sidebar panel carries the footer in its foot whenever the panel is
 * rendered (open on a wide screen, or over the page on a narrow one); when the
 * sidebar is collapsed to its strip, at any width, the footer goes below the
 * page instead. The two are complements, so exactly one attribution shows.
 */
export function attributionBelowPage(state: {
	sidebarChrome: boolean;
	open: boolean;
	narrow: boolean;
}): boolean {
	if (!state.sidebarChrome) return true;
	return leftSidebarMode(state) === 'collapsed';
}

/** Load the state for the current width (on mount and when the width crosses the breakpoint). */
export function syncLeftSidebar(narrow: boolean, getStorage: GetStorage = defaultStorage): void {
	leftSidebarNarrow.set(narrow);
	leftSidebarOpen.set(initialLeftSidebarOpen(readLeftSidebarOpen(getStorage), narrow));
}

/** Open or close it; remembered only on a wide screen. */
export function setLeftSidebarOpen(
	open: boolean,
	narrow: boolean,
	getStorage: GetStorage = defaultStorage
): void {
	leftSidebarOpen.set(open);
	if (!narrow) writeLeftSidebarOpen(open, getStorage);
}

/**
 * Whether focus leaving the overlay should close it: only on a narrow screen,
 * and only when focus went somewhere else on the page (not nowhere, which a
 * click on the backdrop or on plain text also causes; the backdrop closes it).
 */
export function shouldCloseOnFocusOut(
	mode: LeftSidebarMode,
	panel: Pick<Node, 'contains'> | null,
	next: Node | null
): boolean {
	return mode === 'overlay' && !!panel && !!next && !panel.contains(next);
}

type FocusDoc = Pick<Document, 'querySelector'> | undefined;
const defaultDoc = (): FocusDoc => (typeof document === 'undefined' ? undefined : document);

/** Focus the strip's toggle (after the sidebar closes). */
export function focusLeftSidebarOpener(doc: FocusDoc = defaultDoc()): boolean {
	const opener = doc?.querySelector<HTMLElement>('[data-left-sidebar-opener]');
	if (!opener) return false;
	opener.focus();
	return true;
}

/** Focus the toggle inside the panel (after the sidebar opens). */
export function focusLeftSidebar(doc: FocusDoc = defaultDoc()): boolean {
	const close = doc?.querySelector<HTMLElement>(`#${LEFT_SIDEBAR_ID} [data-left-sidebar-close]`);
	if (!close) return false;
	close.focus();
	return true;
}
