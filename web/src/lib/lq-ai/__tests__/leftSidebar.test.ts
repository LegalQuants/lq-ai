/**
 * The left sidebar's collapse (interface-redesign P1.3b) and the right
 * sidebar's shell overlay that the notification bell opens. The suite has no
 * DOM, so keyboard and focus behaviour is tested through the helpers.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import {
	LEFT_SIDEBAR_ID,
	LEFT_SIDEBAR_STORAGE_KEY,
	NARROW_QUERY,
	focusLeftSidebar,
	focusLeftSidebarOpener,
	initialLeftSidebarOpen,
	leftSidebarMode,
	leftSidebarNarrow,
	leftSidebarOpen,
	readLeftSidebarOpen,
	setLeftSidebarOpen,
	shouldCloseOnFocusOut,
	syncLeftSidebar,
	writeLeftSidebarOpen
} from '../leftSidebar';
import {
	RIGHT_SIDEBAR_STORAGE_KEY,
	clearRightSidebarOverlay,
	closeRightSidebar,
	handleRightSidebarKeydown,
	publishShellContext,
	clearShellContext,
	rightSidebarContent,
	rightSidebarOpen,
	rightSidebarOverlayLabel,
	showRightSidebarOverlay,
	type RightSidebarContent
} from '../rightSidebar';

class MemoryStorage {
	map = new Map<string, string>();
	getItem(k: string) {
		return this.map.get(k) ?? null;
	}
	setItem(k: string, v: string) {
		this.map.set(k, v);
	}
}
const throwing = {
	getItem: () => {
		throw new DOMException('blocked', 'SecurityError');
	},
	setItem: () => {
		throw new DOMException('full', 'QuotaExceededError');
	}
};

afterEach(() => {
	leftSidebarOpen.set(true);
	leftSidebarNarrow.set(false);
	rightSidebarOpen.set(true);
	clearRightSidebarOverlay();
});

describe('remembered choice (wide screens)', () => {
	it('is open by default and remembers a collapse', () => {
		const s = new MemoryStorage();
		expect(readLeftSidebarOpen(() => s)).toBe(true);
		writeLeftSidebarOpen(false, () => s);
		expect(s.getItem(LEFT_SIDEBAR_STORAGE_KEY)).toBe('collapsed');
		expect(readLeftSidebarOpen(() => s)).toBe(false);
		writeLeftSidebarOpen(true, () => s);
		expect(readLeftSidebarOpen(() => s)).toBe(true);
		expect(LEFT_SIDEBAR_STORAGE_KEY).toBe('lq-ai.left-sidebar');
	});

	it('falls back to open with no storage, blocked storage or an unknown value; a failed write is ignored', () => {
		expect(readLeftSidebarOpen(() => undefined)).toBe(true);
		expect(readLeftSidebarOpen()).toBe(true); // node: no window
		expect(readLeftSidebarOpen(() => throwing)).toBe(true);
		expect(
			readLeftSidebarOpen(() => {
				throw new DOMException('blocked', 'SecurityError');
			})
		).toBe(true);
		const s = new MemoryStorage();
		s.setItem(LEFT_SIDEBAR_STORAGE_KEY, 'sideways');
		expect(readLeftSidebarOpen(() => s)).toBe(true);
		expect(() => writeLeftSidebarOpen(false, () => throwing)).not.toThrow();
		expect(() => writeLeftSidebarOpen(false)).not.toThrow();
	});
});

describe('narrow screens', () => {
	it('uses the right sidebar’s breakpoint', () => {
		expect(NARROW_QUERY).toBe('(max-width: 1279px)');
	});

	it('starts closed on a narrow screen and as remembered on a wide one', () => {
		expect(initialLeftSidebarOpen(true, false)).toBe(true);
		expect(initialLeftSidebarOpen(false, false)).toBe(false);
		expect(initialLeftSidebarOpen(true, true)).toBe(false);
	});

	it('is a column when open and wide, a strip when closed, an overlay when open and narrow', () => {
		expect(leftSidebarMode({ open: true, narrow: false })).toBe('open');
		expect(leftSidebarMode({ open: false, narrow: false })).toBe('collapsed');
		expect(leftSidebarMode({ open: false, narrow: true })).toBe('collapsed');
		expect(leftSidebarMode({ open: true, narrow: true })).toBe('overlay');
	});

	it('loads the state for the width and remembers changes only when wide', () => {
		const s = new MemoryStorage();
		syncLeftSidebar(true, () => s);
		expect(get(leftSidebarOpen)).toBe(false);
		expect(get(leftSidebarNarrow)).toBe(true);
		setLeftSidebarOpen(true, true, () => s);
		expect(get(leftSidebarOpen)).toBe(true);
		expect(s.getItem(LEFT_SIDEBAR_STORAGE_KEY)).toBeNull();
		syncLeftSidebar(false, () => s);
		expect(get(leftSidebarOpen)).toBe(true);
		setLeftSidebarOpen(false, false, () => s);
		expect(s.getItem(LEFT_SIDEBAR_STORAGE_KEY)).toBe('collapsed');
		syncLeftSidebar(false, () => s);
		expect(get(leftSidebarOpen)).toBe(false);
	});

	it('closes the overlay on Escape (the shared key helper)', () => {
		const close = vi.fn();
		const esc = { key: 'Escape', defaultPrevented: false, preventDefault: vi.fn() };
		expect(handleRightSidebarKeydown(esc, close)).toBe(true);
		expect(close).toHaveBeenCalledTimes(1);
		expect(handleRightSidebarKeydown({ ...esc, key: 'Tab' }, close)).toBe(false);
		expect(close).toHaveBeenCalledTimes(1);
	});

	it('closes the overlay when focus moves elsewhere on the page, not on a wide screen or to nowhere', () => {
		const inside = {} as Node;
		const outside = {} as Node;
		const panel = { contains: (n: Node | null) => n === inside };
		expect(shouldCloseOnFocusOut('overlay', panel, outside)).toBe(true);
		expect(shouldCloseOnFocusOut('overlay', panel, inside)).toBe(false);
		expect(shouldCloseOnFocusOut('overlay', panel, null)).toBe(false);
		expect(shouldCloseOnFocusOut('open', panel, outside)).toBe(false);
		expect(shouldCloseOnFocusOut('collapsed', panel, outside)).toBe(false);
	});

	it('moves focus into the panel on open and back to the strip’s toggle on close', () => {
		const focus = vi.fn();
		const seen: string[] = [];
		const doc = {
			querySelector: (sel: string) => {
				seen.push(sel);
				return { focus } as unknown as Element;
			}
		} as Pick<Document, 'querySelector'>;
		expect(focusLeftSidebar(doc)).toBe(true);
		expect(focusLeftSidebarOpener(doc)).toBe(true);
		expect(seen).toEqual([
			`#${LEFT_SIDEBAR_ID} [data-left-sidebar-close]`,
			'[data-left-sidebar-opener]'
		]);
		expect(focus).toHaveBeenCalledTimes(2);
		const empty = { querySelector: () => null } as Pick<Document, 'querySelector'>;
		expect(focusLeftSidebar(empty)).toBe(false);
		expect(focusLeftSidebarOpener(empty)).toBe(false);
		expect(focusLeftSidebar(undefined)).toBe(false);
	});
});

describe('the right sidebar’s shell overlay (the notification list)', () => {
	const owner = Symbol('page');
	const page: RightSidebarContent = { label: 'Chat details', component: null, props: {} };
	const notes: RightSidebarContent = { label: 'Notifications', component: null, props: {} };

	afterEach(() => clearShellContext(owner));

	it('shows over the page’s content and gives it back when cleared', () => {
		publishShellContext(owner, { title: 'A chat' }, page);
		const opener = { id: 'bell' } as unknown as HTMLElement;
		showRightSidebarOverlay(notes, opener);
		expect(get(rightSidebarContent)?.label).toBe('Notifications');
		expect(get(rightSidebarOverlayLabel)).toBe('Notifications');
		expect(clearRightSidebarOverlay()).toBe(opener);
		expect(get(rightSidebarContent)?.label).toBe('Chat details');
		expect(get(rightSidebarOverlayLabel)).toBeNull();
		expect(clearRightSidebarOverlay()).toBeNull();
	});

	it('shows with nothing published by the page', () => {
		showRightSidebarOverlay(notes);
		expect(get(rightSidebarContent)?.label).toBe('Notifications');
	});

	it('closing dismisses the overlay without changing or remembering the page’s state', () => {
		const s = new MemoryStorage();
		publishShellContext(owner, null, page);
		showRightSidebarOverlay(notes);
		const result = closeRightSidebar('/lq-ai/chats', false, () => s);
		expect(result.overlay).toBe(true);
		expect(get(rightSidebarOpen)).toBe(true);
		expect(s.getItem(RIGHT_SIDEBAR_STORAGE_KEY)).toBeNull();
		expect(get(rightSidebarContent)?.label).toBe('Chat details');
	});

	it('closing without an overlay closes the page’s sidebar and remembers it (wide)', () => {
		const s = new MemoryStorage();
		publishShellContext(owner, null, page);
		expect(closeRightSidebar('/lq-ai/chats', false, () => s)).toEqual({
			overlay: false,
			opener: null
		});
		expect(get(rightSidebarOpen)).toBe(false);
		expect(JSON.parse(s.getItem(RIGHT_SIDEBAR_STORAGE_KEY)!)).toEqual({ '/lq-ai/chats': false });
	});

	it('a page clearing its own content leaves the overlay in place', () => {
		publishShellContext(owner, null, page);
		showRightSidebarOverlay(notes);
		clearShellContext(owner);
		expect(get(rightSidebarContent)?.label).toBe('Notifications');
	});
});
