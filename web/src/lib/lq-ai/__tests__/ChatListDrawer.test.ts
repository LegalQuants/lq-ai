/**
 * The chat page's list on narrow screens (houfu, 11 Nov): a sheet behind a
 * labelled toggle below the shell's 1280 px breakpoint, closed at first, closed
 * by Escape, the backdrop or a choice; unchanged on wide screens and on a
 * matter page. The suite has no DOM, so the markup is rendered with
 * `svelte/server`, Escape is tested through its helper and the breakpoint and
 * the wiring are read from the source.
 */
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it, vi } from 'vitest';
import { render } from 'svelte/server';

import ChatListDrawer from '../components/ChatListDrawer.svelte';
import { drawerKeydown, firstVisibleFocusable } from '../chatListDrawer';
import { NARROW_QUERY } from '../rightSidebar';

const here = dirname(fileURLToPath(import.meta.url));
const drawerSource = readFileSync(resolve(here, '../components/ChatListDrawer.svelte'), 'utf8');
const panelSource = readFileSync(resolve(here, '../components/ChatPanel.svelte'), 'utf8');
const tag = (body: string, attr: string) =>
	body.match(new RegExp(`<[a-z]+\\b[^>]*${attr}[^>]*>`))?.[0] ?? '';

describe('ChatListDrawer markup', () => {
	it('renders a labelled toggle that controls the sheet, closed at first', () => {
		const body = render(ChatListDrawer, { props: {} }).body;
		const toggle = tag(body, 'data-testid="lq-chat-list-toggle"');
		expect(toggle).toContain('aria-expanded="false"');
		expect(toggle).toContain('aria-controls="lq-chat-list-sheet"');
		expect(toggle).toContain('type="button"');
		expect(body).toContain('<span>Chats</span>');
		const sheet = tag(body, 'data-testid="lq-chat-list-sheet"');
		expect(sheet).toContain('id="lq-chat-list-sheet"');
		expect(sheet).not.toMatch(/class="[^"]*\bopen\b/);
		expect(body).not.toContain('drawer-backdrop');
		expect(tag(body, 'class="chat-list-drawer')).toMatch(/\benabled\b/);
	});

	it('shows the sheet and its backdrop when open', () => {
		const body = render(ChatListDrawer, { props: { open: true } }).body;
		expect(tag(body, 'data-testid="lq-chat-list-toggle"')).toContain('aria-expanded="true"');
		expect(tag(body, 'data-testid="lq-chat-list-sheet"')).toMatch(/class="[^"]*\bopen\b/);
		expect(body).toContain('drawer-backdrop');
	});

	it('is inert when disabled (a matter page): no enabled class for the narrow rules', () => {
		const body = render(ChatListDrawer, { props: { enabled: false } }).body;
		expect(tag(body, 'class="chat-list-drawer')).not.toMatch(/\benabled\b/);
	});

	it('uses the shell’s one narrow breakpoint and changes nothing on wide screens', () => {
		expect(NARROW_QUERY).toBe('(max-width: 1279px)');
		expect(drawerSource).toContain('@media (max-width: 1279px)');
		const wide = drawerSource.slice(
			drawerSource.indexOf('<style>'),
			drawerSource.indexOf('@media')
		);
		expect(wide).toMatch(/\.chat-list-drawer,\s*\.drawer-sheet \{\s*display: contents;/);
		expect(wide).toMatch(/\.drawer-toggle,\s*\.drawer-backdrop \{\s*display: none;/);
		// Every narrow rule is scoped to an enabled drawer.
		const narrow = drawerSource.slice(
			drawerSource.indexOf('@media'),
			drawerSource.indexOf('</style>')
		);
		for (const sel of narrow.match(/^\t\t[^\n{]+\{/gm) ?? [])
			expect(sel, sel).toMatch(/\.enabled|:focus-visible/);
	});
});

describe('Escape closes the open sheet', () => {
	const event = (key: string) => ({ key, preventDefault: vi.fn(), stopPropagation: vi.fn() });

	it('closes it and stops the key there', () => {
		const close = vi.fn();
		const e = event('Escape');
		expect(drawerKeydown(e, true, close)).toBe(true);
		expect(close).toHaveBeenCalledOnce();
		expect(e.stopPropagation).toHaveBeenCalled();
		expect(e.preventDefault).toHaveBeenCalled();
	});

	it('ignores other keys and a closed sheet', () => {
		const close = vi.fn();
		expect(drawerKeydown(event('Enter'), true, close)).toBe(false);
		expect(drawerKeydown(event('Escape'), false, close)).toBe(false);
		expect(close).not.toHaveBeenCalled();
	});

	it('returns focus to the toggle when it closes', () => {
		expect(drawerSource).toMatch(/open = false;\s*await tick\(\);\s*toggleEl\?\.focus\(\);/);
	});
});

describe('ChatPanel wiring', () => {
	it('wraps its chat list in the drawer outside a matter only', () => {
		expect(panelSource).toContain(
			'<ChatListDrawer bind:this={chatListDrawer} enabled={!projectIdFilter}>'
		);
		const start = panelSource.indexOf('<ChatListDrawer');
		const end = panelSource.indexOf('</ChatListDrawer>');
		const inside = panelSource.slice(start, end);
		expect(inside).toContain(
			'<CompactPanel id="matter-chats" title="Chats" enabled={!!projectIdFilter}>'
		);
		expect(inside).toContain('<ChatSidebar');
	});

	it('closes the sheet when a chat is chosen or a new one started', () => {
		const inside = panelSource.slice(
			panelSource.indexOf('<ChatSidebar'),
			panelSource.indexOf('</CompactPanel>')
		);
		expect(inside).toMatch(
			/onSelectChat=\{\(chat\) => \{\s*void chatListDrawer\?\.close\(\);\s*return selectChat\(chat\);/
		);
		expect(inside).toMatch(
			/onNewChat=\{\(\) => \{\s*void chatListDrawer\?\.close\(\);\s*return createNewChat\(\);/
		);
	});

	it('lays the chat page out in one column on narrow screens, as a matter page is', () => {
		expect(panelSource).toContain('class:compact-chats={!projectIdFilter}');
		const narrow = panelSource.slice(panelSource.indexOf('@media (max-width: 1279px)'));
		expect(narrow).toMatch(/\.compact-matter,\s*\.compact-chats \{\s*flex-direction: column;/);
		expect(narrow).toMatch(/\.compact-chats \.lq-composer-wrap \{\s*flex: 1 0 100%;/);
	});
});

describe('focus when the sheet opens', () => {
	const el = (name: string, rects: number, disabled = false) =>
		({ name, disabled, getClientRects: () => ({ length: rects }) }) as unknown as HTMLElement;
	const root = (els: HTMLElement[]) => ({ querySelectorAll: () => els }) as unknown as ParentNode;

	it('skips hidden and disabled controls and takes the first one a person can see', () => {
		const first = el('new chat', 1);
		expect(firstVisibleFocusable(root([el('matter toggle', 0), el('off', 1, true), first]))).toBe(
			first
		);
	});

	it('finds nothing in an empty or missing sheet', () => {
		expect(firstVisibleFocusable(root([el('hidden', 0)]))).toBeNull();
		expect(firstVisibleFocusable(null)).toBeNull();
	});

	it('moves focus there on open, and Escape on the toggle closes it too', () => {
		expect(drawerSource).toContain('firstVisibleFocusable(sheetEl)?.focus();');
		const toggle = drawerSource.slice(
			drawerSource.indexOf('<button'),
			drawerSource.indexOf('</button>')
		);
		expect(toggle).toContain(
			'on:keydown={(event) => drawerKeydown(event, open, () => void close())}'
		);
	});
});
