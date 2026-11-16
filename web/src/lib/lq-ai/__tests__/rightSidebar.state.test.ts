/**
 * The right sidebar's state, as pure helpers (interface-redesign P1.4, behind
 * the developer switch): per-page remembered open state with storage absent,
 * throwing or corrupt; open, closed and absent; the narrow-screen sheet; the
 * owner rule for published content; Escape and focus return.
 *
 * vitest runs in node with no DOM here, so keyboard and focus are tested
 * through the helpers the component calls, with fake events and documents.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';

import {
	RIGHT_SIDEBAR_ID,
	RIGHT_SIDEBAR_STORAGE_KEY,
	clearShellContext,
	focusRightSidebar,
	focusRightSidebarOpener,
	handleRightSidebarKeydown,
	initialRightSidebarOpen,
	pageHeaderContent,
	publishShellContext,
	readRightSidebarOpen,
	revealRightSidebar,
	rightSidebarContent,
	rightSidebarMode,
	rightSidebarOpen,
	setRightSidebarOpen,
	syncRightSidebarForPage,
	writeRightSidebarOpen
} from '../rightSidebar';

class MemoryStorage {
	map = new Map<string, string>();
	getItem(k: string): string | null {
		return this.map.get(k) ?? null;
	}
	setItem(k: string, v: string): void {
		this.map.set(k, v);
	}
}

const throwingStorage = {
	getItem(): string | null {
		throw new DOMException('getItem blocked', 'SecurityError');
	},
	setItem(): void {
		throw new DOMException('quota', 'QuotaExceededError');
	}
};

afterEach(() => {
	publishShellContext(Symbol('reset'), null, null);
	rightSidebarOpen.set(true);
});

describe('remembered open state, per page', () => {
	it('defaults to open for a page never closed', () => {
		const s = new MemoryStorage();
		expect(readRightSidebarOpen('/lq-ai/chats', () => s)).toBe(true);
	});

	it('remembers closed for one page without touching another', () => {
		const s = new MemoryStorage();
		writeRightSidebarOpen('/lq-ai/chats', false, () => s);
		expect(readRightSidebarOpen('/lq-ai/chats', () => s)).toBe(false);
		expect(readRightSidebarOpen('/lq-ai/matters/m1', () => s)).toBe(true);
		writeRightSidebarOpen('/lq-ai/matters/m1', false, () => s);
		writeRightSidebarOpen('/lq-ai/chats', true, () => s);
		expect(readRightSidebarOpen('/lq-ai/chats', () => s)).toBe(true);
		expect(readRightSidebarOpen('/lq-ai/matters/m1', () => s)).toBe(false);
		expect(JSON.parse(s.getItem(RIGHT_SIDEBAR_STORAGE_KEY)!)).toEqual({
			'/lq-ai/chats': true,
			'/lq-ai/matters/m1': false
		});
		expect(RIGHT_SIDEBAR_STORAGE_KEY).toBe('lq-ai.right-sidebar');
	});

	it('falls back to open with no storage (server-side rendering)', () => {
		expect(readRightSidebarOpen('/lq-ai/chats', () => undefined)).toBe(true);
		// Default accessor under node: no window.
		expect(readRightSidebarOpen('/lq-ai/chats')).toBe(true);
		expect(() => writeRightSidebarOpen('/lq-ai/chats', false)).not.toThrow();
	});

	it('falls back to open when reaching or reading storage throws, and ignores a failed write', () => {
		expect(readRightSidebarOpen('/p', () => throwingStorage)).toBe(true);
		expect(
			readRightSidebarOpen('/p', () => {
				throw new DOMException('blocked', 'SecurityError');
			})
		).toBe(true);
		expect(() => writeRightSidebarOpen('/p', false, () => throwingStorage)).not.toThrow();
		expect(() =>
			writeRightSidebarOpen('/p', false, () => {
				throw new DOMException('blocked', 'SecurityError');
			})
		).not.toThrow();
	});

	it('ignores a corrupt stored value', () => {
		for (const raw of ['not json', '[false]', 'false', 'null', '"x"']) {
			const s = new MemoryStorage();
			s.setItem(RIGHT_SIDEBAR_STORAGE_KEY, raw);
			expect(readRightSidebarOpen('/p', () => s)).toBe(true);
			writeRightSidebarOpen('/p', false, () => s);
			expect(readRightSidebarOpen('/p', () => s)).toBe(false);
		}
	});
});

describe('open, closed, absent and the sheet', () => {
	it('is absent with nothing to show, whatever the open state', () => {
		for (const open of [true, false])
			for (const narrow of [true, false])
				expect(rightSidebarMode({ hasContent: false, open, narrow })).toBe('absent');
	});

	it('is closed when closed, a column when open, a sheet when open on a narrow screen', () => {
		expect(rightSidebarMode({ hasContent: true, open: false, narrow: false })).toBe('closed');
		expect(rightSidebarMode({ hasContent: true, open: false, narrow: true })).toBe('closed');
		expect(rightSidebarMode({ hasContent: true, open: true, narrow: false })).toBe('open');
		expect(rightSidebarMode({ hasContent: true, open: true, narrow: true })).toBe('sheet');
	});

	it('starts a narrow screen closed and a wide one as remembered', () => {
		expect(initialRightSidebarOpen(true, false)).toBe(true);
		expect(initialRightSidebarOpen(false, false)).toBe(false);
		expect(initialRightSidebarOpen(true, true)).toBe(false);
		expect(initialRightSidebarOpen(false, true)).toBe(false);
	});

	it('loads each page’s state into the store and remembers changes, except on a narrow screen', () => {
		const s = new MemoryStorage();
		syncRightSidebarForPage('/a', false, () => s);
		expect(get(rightSidebarOpen)).toBe(true);
		setRightSidebarOpen('/a', false, false, () => s);
		expect(get(rightSidebarOpen)).toBe(false);
		syncRightSidebarForPage('/b', false, () => s);
		expect(get(rightSidebarOpen)).toBe(true);
		syncRightSidebarForPage('/a', false, () => s);
		expect(get(rightSidebarOpen)).toBe(false);
		// The sheet: opening and closing it does not change what the wide page remembers.
		syncRightSidebarForPage('/b', true, () => s);
		expect(get(rightSidebarOpen)).toBe(false);
		setRightSidebarOpen('/b', true, true, () => s);
		setRightSidebarOpen('/b', false, true, () => s);
		expect(readRightSidebarOpen('/b', () => s)).toBe(true);
	});

	it('reveals without remembering', () => {
		rightSidebarOpen.set(false);
		revealRightSidebar();
		expect(get(rightSidebarOpen)).toBe(true);
	});
});

describe('published content', () => {
	const Dummy = () => undefined;

	it('shows what the page published and clears it when that page goes', () => {
		const owner = Symbol('page');
		publishShellContext(
			owner,
			{ title: 'T' },
			{ label: 'Chat details', component: Dummy, props: {} }
		);
		expect(get(pageHeaderContent)).toEqual({ title: 'T' });
		expect(get(rightSidebarContent)?.label).toBe('Chat details');
		clearShellContext(owner);
		expect(get(pageHeaderContent)).toBeNull();
		expect(get(rightSidebarContent)).toBeNull();
	});

	it('does not let a page that is going away clear the next page’s content', () => {
		const old = Symbol('old');
		const next = Symbol('next');
		publishShellContext(old, { title: 'Old' }, null);
		publishShellContext(next, { title: 'New' }, { label: 'X', component: Dummy, props: {} });
		clearShellContext(old);
		expect(get(pageHeaderContent)).toEqual({ title: 'New' });
		expect(get(rightSidebarContent)?.label).toBe('X');
	});
});

describe('keyboard and focus', () => {
	function keyEvent(key: string, defaultPrevented = false) {
		const e = { key, defaultPrevented, prevented: false, preventDefault() {} };
		e.preventDefault = () => {
			e.prevented = true;
		};
		return e;
	}

	it('closes on Escape and nothing else', () => {
		let closed = 0;
		const close = () => closed++;
		const esc = keyEvent('Escape');
		expect(handleRightSidebarKeydown(esc, close)).toBe(true);
		expect(esc.prevented).toBe(true);
		expect(closed).toBe(1);
		for (const key of ['Enter', ' ', 'Tab', 'Esc', 'x'])
			expect(handleRightSidebarKeydown(keyEvent(key), close)).toBe(false);
		// Something inside already used Escape (an open popover): leave it.
		expect(handleRightSidebarKeydown(keyEvent('Escape', true), close)).toBe(false);
		expect(closed).toBe(1);
	});

	function fakeDoc(found: Record<string, { focused: number; focus(): void }>) {
		const queries: string[] = [];
		return {
			queries,
			doc: {
				querySelector: (sel: string) => {
					queries.push(sel);
					return found[sel] ?? null;
				}
			} as unknown as Pick<Document, 'querySelector'>
		};
	}
	function el() {
		const e = { focused: 0, focus() {} };
		e.focus = () => {
			e.focused++;
		};
		return e;
	}

	it('returns focus to the control that points at the sidebar', () => {
		const opener = el();
		const { doc, queries } = fakeDoc({ [`[aria-controls="${RIGHT_SIDEBAR_ID}"]`]: opener });
		expect(focusRightSidebarOpener(doc)).toBe(true);
		expect(opener.focused).toBe(1);
		expect(queries).toEqual(['[aria-controls="lq-right-sidebar"]']);
	});

	it('moves focus to the close button when opened', () => {
		const close = el();
		const { doc } = fakeDoc({ [`#${RIGHT_SIDEBAR_ID} [data-right-sidebar-close]`]: close });
		expect(focusRightSidebar(doc)).toBe(true);
		expect(close.focused).toBe(1);
	});

	it('does nothing without a document or a target', () => {
		expect(focusRightSidebarOpener(undefined)).toBe(false);
		expect(focusRightSidebar(undefined)).toBe(false);
		expect(focusRightSidebarOpener(fakeDoc({}).doc)).toBe(false);
	});
});
