/**
 * The right sidebar, the page header and the chat's details rendered to HTML
 * in node (`svelte/server`), plus ChatPanel's test-id checklist
 * (interface-redesign P1.4, behind the developer switch).
 *
 * SSR runs every `$:` statement and no `onMount`, so the narrow-screen
 * detection is not exercised here (see rightSidebar.test.ts for the helpers).
 */
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'svelte/server';

vi.mock('../api/receipts', () => ({
	listChatReceipts: vi.fn(async () => []),
	exportChatReceiptsJsonl: vi.fn(async () => ({ jsonl: '', filename: 'x.jsonl' }))
}));

import RightSidebar from '../components/RightSidebar.svelte';
import PageHeader from '../components/PageHeader.svelte';
import ChatDetailsPanel from '../components/ChatDetailsPanel.svelte';
import ReceiptsDrawer from '../components/ReceiptsDrawer.svelte';
import {
	RIGHT_SIDEBAR_STORAGE_KEY,
	publishShellContext,
	rightSidebarNarrow,
	rightSidebarOpen,
	type RightSidebarContent
} from '../rightSidebar';
import type { FileMeta } from '../types';

const owner = Symbol('test');

const file = (id: string, name: string): FileMeta =>
	({ id, filename: name, ingestion_status: 'ready' }) as unknown as FileMeta;

function chatDetails(over: Record<string, unknown> = {}): RightSidebarContent {
	return {
		label: 'Chat details',
		component: ChatDetailsPanel,
		props: {
			chatId: 'c1',
			chatFiles: [file('f1', 'msa.txt')],
			projectFiles: [],
			attachLimitReached: true,
			receiptsOpen: true,
			...over
		}
	};
}

/** Storage seen by the components' default accessors during SSR. */
function stubStorage(map: Record<string, boolean> | null): void {
	const store = new Map<string, string>();
	if (map) store.set(RIGHT_SIDEBAR_STORAGE_KEY, JSON.stringify(map));
	vi.stubGlobal('window', {
		localStorage: {
			getItem: (k: string) => store.get(k) ?? null,
			setItem: (k: string, v: string) => void store.set(k, v)
		}
	});
}

beforeEach(() => {
	vi.useFakeTimers();
});
afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
	publishShellContext(Symbol('reset'), null, null);
	rightSidebarOpen.set(true);
	rightSidebarNarrow.set(false);
});

/** The `<aside …>…</aside>` of the sidebar, or null. */
function aside(body: string): string | null {
	const m = body.match(/<aside\b[^>]*id="lq-right-sidebar"[\s\S]*<\/aside>/);
	return m ? m[0] : null;
}

describe('RightSidebar', () => {
	it('renders nothing when the page published nothing (the middle widens)', () => {
		const body = render(RightSidebar, { props: { pathname: '/lq-ai/chats' } }).body;
		expect(body).not.toContain('<aside');
		expect(body).not.toContain('lq-right-sidebar');
	});

	it('is a labelled complementary landmark with a named close button around the page’s content', () => {
		publishShellContext(owner, { title: 'Liability cap' }, chatDetails());
		const html = aside(render(RightSidebar, { props: { pathname: '/lq-ai/chats' } }).body);
		expect(html).not.toBeNull();
		expect(html).toMatch(/^<aside\b[^>]*aria-label="Chat details"/);
		expect(html).toContain('data-mode="open"');
		expect(html).toMatch(/<h2 class="lq-right-sidebar-title[^"]*">Chat details<\/h2>/);
		expect(html).toMatch(
			/<button[^>]*type="button"[^>]*aria-label="Close chat details"[^>]*data-right-sidebar-close/
		);
		expect(html).toContain('data-testid="lq-chat-details"');
	});

	it('is absent on a page where the person closed it, and open on another page', () => {
		publishShellContext(owner, { title: 'T' }, chatDetails());
		stubStorage({ '/lq-ai/chats': false });
		expect(aside(render(RightSidebar, { props: { pathname: '/lq-ai/chats' } }).body)).toBeNull();
		expect(
			aside(render(RightSidebar, { props: { pathname: '/lq-ai/matters/m1' } }).body)
		).not.toBeNull();
	});

	it('stays open when storage is unreadable', () => {
		publishShellContext(owner, { title: 'T' }, chatDetails());
		vi.stubGlobal('window', {
			get localStorage(): Storage {
				throw new DOMException('blocked', 'SecurityError');
			}
		});
		expect(
			aside(render(RightSidebar, { props: { pathname: '/lq-ai/chats' } }).body)
		).not.toBeNull();
	});
});

describe('PageHeader', () => {
	it('renders nothing without a published title', () => {
		expect(render(PageHeader, { props: { pathname: '/lq-ai' } }).body).not.toContain('<header');
	});

	it('renders the title, and no toggle when there is no sidebar content', () => {
		publishShellContext(owner, { title: 'Liability cap in the Halden MSA' }, null);
		const body = render(PageHeader, { props: { pathname: '/lq-ai/chats' } }).body;
		expect(body).toMatch(/<header class="lq-page-header[^"]*" data-testid="lq-page-header">/);
		expect(body).toMatch(
			/<h1 class="lq-page-header-title[^"]*">Liability cap in the Halden MSA<\/h1>/
		);
		expect(body).not.toContain('aria-controls');
	});

	it('carries a toggle that points at the sidebar and says whether it is open', () => {
		publishShellContext(owner, { title: 'T' }, chatDetails());
		let body = render(PageHeader, { props: { pathname: '/p' } }).body;
		let toggle = body.match(/<button[^>]*data-testid="lq-page-header-sidebar-toggle"[^>]*>/)?.[0];
		expect(toggle).toContain('aria-controls="lq-right-sidebar"');
		expect(toggle).toContain('aria-expanded="true"');
		expect(toggle).toContain('aria-label="Hide chat details"');
		rightSidebarOpen.set(false);
		body = render(PageHeader, { props: { pathname: '/p' } }).body;
		toggle = body.match(/<button[^>]*data-testid="lq-page-header-sidebar-toggle"[^>]*>/)?.[0];
		expect(toggle).toContain('aria-expanded="false"');
		expect(toggle).toContain('aria-label="Show chat details"');
	});
});

describe('ChatDetailsPanel inside the sidebar (the moved panels keep every control)', () => {
	const MOVED_TEST_IDS = [
		'lq-ai-attached-files-panel',
		'lq-ai-upload-btn',
		'lq-ai-attach-limit-notice',
		'lq-ai-file-input',
		'lq-ai-detach-f1',
		'export-jsonl',
		'empty-state'
	];

	it('puts the attached files and the receipts, with all their test ids, inside the aside', () => {
		publishShellContext(owner, { title: 'T' }, chatDetails());
		const html = aside(render(RightSidebar, { props: { pathname: '/lq-ai/chats' } }).body)!;
		for (const id of MOVED_TEST_IDS) expect(html, id).toContain(`data-testid="${id}"`);
		expect(html).toContain('id="matter-files-toggle"');
		expect(html).toContain('aria-label="Close receipts drawer"');
		// The receipts become a section of the sidebar, not a second complementary landmark.
		expect(html.match(/<aside\b/g)).toHaveLength(1);
		expect(html).toMatch(
			/<section[^>]*class="receipts-drawer[^"]*embedded[^"]*"[^>]*aria-label="Receipts drawer"/
		);
	});

	it('shows the receipts only while the receipts toggle has them open', () => {
		publishShellContext(owner, { title: 'T' }, chatDetails({ receiptsOpen: false }));
		const html = aside(render(RightSidebar, { props: { pathname: '/lq-ai/chats' } }).body)!;
		expect(html).toContain('data-testid="lq-ai-attached-files-panel"');
		expect(html).not.toContain('export-jsonl');
	});

	it('keeps ReceiptsDrawer its own landmark outside the sidebar (switch off)', () => {
		const body = render(ReceiptsDrawer, { props: { open: true, chatId: 'c1' } }).body;
		expect(body).toMatch(
			/<aside[^>]*class="receipts-drawer[^"]*"[^>]*aria-label="Receipts drawer"/
		);
		expect(body).not.toContain('embedded');
	});
});

describe('ChatPanel test-id checklist', () => {
	const here = dirname(fileURLToPath(import.meta.url));
	const source = readFileSync(resolve(here, '../components/ChatPanel.svelte'), 'utf8');
	const markup = source.slice(source.lastIndexOf('</script>'));

	/** The 18 ids ChatPanel carried before the right sidebar (receipts/s1-7/testids-before.txt). */
	const CHAT_PANEL_TEST_IDS = [
		'lq-ai-abort-btn',
		'lq-ai-attach-kb-btn',
		'lq-ai-attachment-warning',
		'lq-ai-chat-header',
		'lq-ai-chat-shell',
		'lq-ai-composer',
		'lq-ai-composer-input',
		'lq-ai-enhance-btn',
		'lq-ai-harness-block',
		'lq-ai-harness-recheck',
		'lq-ai-harness-strip',
		'lq-ai-receipts-toggle',
		'lq-ai-run-profiles-error',
		'lq-ai-run-propose-hint',
		'lq-ai-send-btn',
		'lq-ai-send-error',
		'lq-ai-slash-popover-anchor',
		'lq-ai-sticky-toggle'
	];

	/** The one block the switch hides: the panels beside the chat. */
	const switchBlock = (() => {
		const start = markup.indexOf('{#if !sidebarShell}');
		expect(start, 'switch block').toBeGreaterThan(-1);
		let depth = 0;
		const re = /\{#if\b|\{\/if\}/g;
		re.lastIndex = start;
		for (let m = re.exec(markup); m; m = re.exec(markup)) {
			depth += m[0] === '{/if}' ? -1 : 1;
			if (depth === 0) return markup.slice(start, m.index + m[0].length);
		}
		throw new Error('unclosed switch block');
	})();

	it('still carries each of its 18 test ids exactly once', () => {
		const found = [...markup.matchAll(/data-testid="([^"]+)"/g)].map((m) => m[1]).sort();
		expect(found).toEqual([...CHAT_PANEL_TEST_IDS].sort());
	});

	it('hides none of them with the switch on: the switch only moves the side panels', () => {
		for (const id of CHAT_PANEL_TEST_IDS) expect(switchBlock).not.toContain(id);
		expect(switchBlock).toContain('<AttachedFilesPanel');
		expect(switchBlock).toContain('<ReceiptsDrawer');
		expect((markup.match(/\{#if !sidebarShell\}/g) ?? []).length).toBe(1);
	});

	it('gives the sidebar the same panel props it renders with the switch off', () => {
		for (const prop of [
			'chatFiles',
			'projectFiles',
			'uploading',
			'attachLimitReached',
			'onUpload: uploadAttached',
			'onDetach: detachFile',
			'newHarness: harnessChosen',
			'receiptsOpen: receiptsDrawerOpen',
			'compact: !!projectIdFilter'
		])
			expect(source, prop).toContain(prop);
	});
});
