/**
 * The contextual right sidebar and the page header of the redesigned LQ.AI
 * shell (interface-redesign work plan, Annex B P1.4; proposed ADR 0045, C6,
 * C14, C19).
 *
 * The layout hosts both: a header over the main column only, and a right
 * column beside it. A page fills them by publishing what it has open
 * (`publishShellContext`) and clears them when it goes away. With nothing
 * published the header and the sidebar are absent, so the middle column
 * widens.
 *
 * The sidebar's open or closed state is remembered per page (pathname) in
 * one JSON map under `localStorage['lq-ai.right-sidebar']`. Every storage
 * access is guarded: server-side
 * rendering, blocked site data or a corrupt value fall back to the default
 * (open), and a failed write is ignored. On narrow screens the sidebar is a
 * sheet over the page: it starts closed and its state is not remembered.
 */
import { derived, get, writable } from 'svelte/store';

export const RIGHT_SIDEBAR_STORAGE_KEY = 'lq-ai.right-sidebar';
/** The sidebar element's id; the header's toggle points at it. */
export const RIGHT_SIDEBAR_ID = 'lq-right-sidebar';
/** Below this width the sidebar is a sheet (the same breakpoint as CompactPanel). */
export const NARROW_QUERY = '(max-width: 1279px)';

/** What the page header shows. */
export interface PageHeaderContent {
	title: string;
}

/**
 * What the right sidebar shows: a label (its accessible name and heading)
 * and one component with its props. The component is the page's own, so the
 * sidebar stays one shared shell around it.
 */
export interface RightSidebarContent {
	label: string;
	// A Svelte component; typed loosely because legacy and runes components differ.
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	component: any;
	props: Record<string, unknown>;
}

interface Owned<T> {
	owner: symbol;
	value: T;
}

interface Overlay {
	value: RightSidebarContent;
	/** The control that opened it; focus returns there when it closes. */
	opener: HTMLElement | null;
}

const headerStore = writable<Owned<PageHeaderContent> | null>(null);
const sidebarStore = writable<Owned<RightSidebarContent> | null>(null);
/**
 * Shell-level content shown over the page's own (the notification list,
 * opened from the left sidebar). While it is set the sidebar shows it, open,
 * whatever the page published or the person chose for the page; clearing it
 * brings the page's content and remembered state back untouched.
 */
const overlayStore = writable<Overlay | null>(null);

export const pageHeaderContent = {
	subscribe: (run: (v: PageHeaderContent | null) => void) =>
		headerStore.subscribe((o) => run(o?.value ?? null))
};
const shownContent = derived(
	[overlayStore, sidebarStore],
	([overlay, page]) => overlay?.value ?? page?.value ?? null
);
/** What the sidebar shows: the shell overlay when set, else the page's content. */
export const rightSidebarContent = { subscribe: shownContent.subscribe };
/** The label of the shell overlay being shown, or null when the page's content shows. */
export const rightSidebarOverlayLabel = derived(
	overlayStore,
	(overlay) => overlay?.value.label ?? null
);

/** Show shell content over the page's own; `opener` gets focus back on close. */
export function showRightSidebarOverlay(
	content: RightSidebarContent,
	opener: HTMLElement | null = null
): void {
	overlayStore.set({ value: content, opener });
}

/**
 * Clear the shell overlay, if any. Returns the element that opened it so the
 * caller can return focus there; nothing is written to storage.
 */
export function clearRightSidebarOverlay(): HTMLElement | null {
	const overlay = get(overlayStore);
	if (!overlay) return null;
	overlayStore.set(null);
	return overlay.opener;
}

/**
 * Close what the sidebar shows. A shell overlay is only dismissed (the page's
 * own state is neither changed nor remembered); otherwise the page's sidebar
 * closes and, on a wide screen, that is remembered for the page.
 */
export function closeRightSidebar(
	page: string,
	narrow: boolean,
	getStorage: GetStorage = defaultStorage
): { overlay: boolean; opener: HTMLElement | null } {
	if (get(overlayStore)) return { overlay: true, opener: clearRightSidebarOverlay() };
	setRightSidebarOpen(page, false, narrow, getStorage);
	return { overlay: false, opener: null };
}
/** Whether the sidebar is open on the current page (absent content wins). */
export const rightSidebarOpen = writable(true);
/** Whether the viewport is narrow, so the sidebar is a sheet. */
export const rightSidebarNarrow = writable(false);

/**
 * Publish the page's header and sidebar content. `owner` is the publishing
 * component's own symbol, so a page that is already going away cannot clear
 * what the next page published.
 */
export function publishShellContext(
	owner: symbol,
	header: PageHeaderContent | null,
	sidebar: RightSidebarContent | null
): void {
	headerStore.set(header ? { owner, value: header } : null);
	sidebarStore.set(sidebar ? { owner, value: sidebar } : null);
}

/** Clear what `owner` published; anything another owner published stays. */
export function clearShellContext(owner: symbol): void {
	if (get(headerStore)?.owner === owner) headerStore.set(null);
	if (get(sidebarStore)?.owner === owner) sidebarStore.set(null);
}

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>;
type GetStorage = () => StorageLike | undefined;

const defaultStorage: GetStorage = () =>
	typeof window === 'undefined' ? undefined : window.localStorage;

function readMap(getStorage: GetStorage): Record<string, boolean> {
	try {
		const raw = getStorage()?.getItem(RIGHT_SIDEBAR_STORAGE_KEY);
		if (!raw) return {};
		const parsed: unknown = JSON.parse(raw);
		if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
		return parsed as Record<string, boolean>;
	} catch {
		return {};
	}
}

/** The remembered state for a page: open unless the person closed it there. */
export function readRightSidebarOpen(
	page: string,
	getStorage: GetStorage = defaultStorage
): boolean {
	return readMap(getStorage)[page] !== false;
}

/** Remember the state for a page. A failed write is ignored. */
export function writeRightSidebarOpen(
	page: string,
	open: boolean,
	getStorage: GetStorage = defaultStorage
): void {
	try {
		const store = getStorage();
		if (!store) return;
		const map = readMap(getStorage);
		map[page] = open;
		store.setItem(RIGHT_SIDEBAR_STORAGE_KEY, JSON.stringify(map));
	} catch {
		// Storage blocked or full: the state is simply not remembered.
	}
}

/** On a narrow screen the sheet starts closed; otherwise the remembered state. */
export function initialRightSidebarOpen(remembered: boolean, narrow: boolean): boolean {
	return remembered && !narrow;
}

export type RightSidebarMode = 'absent' | 'closed' | 'open' | 'sheet';

/**
 * How the sidebar renders: absent with nothing to show, closed when the
 * person closed it (both leave the middle column the full width), a column
 * when open, a sheet over the page when open on a narrow screen.
 */
export function rightSidebarMode(state: {
	hasContent: boolean;
	open: boolean;
	narrow: boolean;
}): RightSidebarMode {
	if (!state.hasContent) return 'absent';
	if (!state.open) return 'closed';
	return state.narrow ? 'sheet' : 'open';
}

/** Load the page's state into the open store (on page change or resize). */
export function syncRightSidebarForPage(
	page: string,
	narrow: boolean,
	getStorage: GetStorage = defaultStorage
): void {
	rightSidebarOpen.set(initialRightSidebarOpen(readRightSidebarOpen(page, getStorage), narrow));
}

/** Open or close it; remembered for the page except on a narrow screen. */
export function setRightSidebarOpen(
	page: string,
	open: boolean,
	narrow: boolean,
	getStorage: GetStorage = defaultStorage
): void {
	rightSidebarOpen.set(open);
	if (!narrow) writeRightSidebarOpen(page, open, getStorage);
}

/** Open it without remembering (a control inside the page asked to show something there). */
export function revealRightSidebar(): void {
	rightSidebarOpen.set(true);
}

/** Escape closes the sidebar. Returns true when the key was handled. */
export function handleRightSidebarKeydown(
	event: Pick<KeyboardEvent, 'key' | 'defaultPrevented'> & { preventDefault(): void },
	close: () => void
): boolean {
	if (event.key !== 'Escape' || event.defaultPrevented) return false;
	event.preventDefault();
	close();
	return true;
}

type FocusDoc = Pick<Document, 'querySelector'> | undefined;
const defaultDoc = (): FocusDoc => (typeof document === 'undefined' ? undefined : document);

/** Return focus to the control that opens the sidebar (the header's toggle). */
export function focusRightSidebarOpener(doc: FocusDoc = defaultDoc()): boolean {
	const opener = doc?.querySelector<HTMLElement>(`[aria-controls="${RIGHT_SIDEBAR_ID}"]`);
	if (!opener) return false;
	opener.focus();
	return true;
}

/** Move focus into the sidebar (its close button) after it opens. */
export function focusRightSidebar(doc: FocusDoc = defaultDoc()): boolean {
	const close = doc?.querySelector<HTMLElement>(`#${RIGHT_SIDEBAR_ID} [data-right-sidebar-close]`);
	if (!close) return false;
	close.focus();
	return true;
}
