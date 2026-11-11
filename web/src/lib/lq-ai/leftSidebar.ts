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
 *
 * Matter pages (houfu's ruling, 10 Nov): a matter workspace already has three
 * columns (matter rail, chat list, right sidebar), and with the left sidebar
 * open as well the chat composer is too narrow to use (27 px at 1440 px wide).
 * So on a matter page the sidebar starts collapsed to its strip. The choice
 * there is remembered under its own key, `LEFT_SIDEBAR_MATTER_STORAGE_KEY`,
 * collapsed until the person opens it: opening it on a matter page keeps it
 * open on matter pages, and neither key changes the other, so the choice made
 * on other pages is never overwritten by the matter-page default.
 */
import { writable } from 'svelte/store';

import { currentSidebarRows } from './sidebarLists';

export { NARROW_QUERY } from './rightSidebar';

export const LEFT_SIDEBAR_STORAGE_KEY = 'lq-ai.left-sidebar';
/** The choice made on matter pages, kept apart from every other page's. */
export const LEFT_SIDEBAR_MATTER_STORAGE_KEY = 'lq-ai.left-sidebar.matter';
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

/** Which remembered choice applies: matter pages have their own. */
export type LeftSidebarPage = 'matter' | 'other';

/** A matter workspace (`/lq-ai/matters/<id>`); the list of matters is not one. */
export function leftSidebarPageFor(pathname: string): LeftSidebarPage {
	return currentSidebarRows(pathname, null, null).matterId !== null ? 'matter' : 'other';
}

/**
 * The remembered choice on wide screens. Other pages: open unless the person
 * collapsed it. Matter pages: collapsed unless the person opened it there.
 * Without readable storage each falls back to its default.
 */
export function readLeftSidebarOpen(
	getStorage: GetStorage = defaultStorage,
	page: LeftSidebarPage = 'other'
): boolean {
	try {
		if (page === 'matter') return getStorage()?.getItem(LEFT_SIDEBAR_MATTER_STORAGE_KEY) === 'open';
		return getStorage()?.getItem(LEFT_SIDEBAR_STORAGE_KEY) !== 'collapsed';
	} catch {
		return page !== 'matter';
	}
}

/** Remember the choice for the kind of page. A failed write is ignored. */
export function writeLeftSidebarOpen(
	open: boolean,
	getStorage: GetStorage = defaultStorage,
	page: LeftSidebarPage = 'other'
): void {
	try {
		getStorage()?.setItem(
			page === 'matter' ? LEFT_SIDEBAR_MATTER_STORAGE_KEY : LEFT_SIDEBAR_STORAGE_KEY,
			open ? 'open' : 'collapsed'
		);
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

/**
 * Load the state for the current width and kind of page (on mount, when the
 * width crosses the breakpoint, and when navigation moves between a matter
 * page and any other page).
 */
export function syncLeftSidebar(
	narrow: boolean,
	getStorage: GetStorage = defaultStorage,
	page: LeftSidebarPage = 'other'
): void {
	leftSidebarNarrow.set(narrow);
	leftSidebarOpen.set(initialLeftSidebarOpen(readLeftSidebarOpen(getStorage, page), narrow));
}

/** Open or close it; remembered, for the kind of page, only on a wide screen. */
export function setLeftSidebarOpen(
	open: boolean,
	narrow: boolean,
	getStorage: GetStorage = defaultStorage,
	page: LeftSidebarPage = 'other'
): void {
	leftSidebarOpen.set(open);
	if (!narrow) writeLeftSidebarOpen(open, getStorage, page);
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
