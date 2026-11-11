/**
 * The ADR 0001 attribution footer with the redesigned chrome (houfu's ruling,
 * 10 Nov): with the left sidebar collapsed to its strip, on a phone in
 * particular, the footer shows below the page; whenever the sidebar panel is
 * rendered, its foot carries it. Exactly one copy is on the page in every
 * state, and with the switch off nothing changes.
 *
 * The layout itself renders nothing on the server (it waits for the sign-in
 * gate), so these tests render the two pieces it places, `ShellSidebar` and
 * `ShellAttribution`, against the same collapse state.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { render } from 'svelte/server';

import DualBrandingFooter from '../components/DualBrandingFooter.svelte';
import ShellAttribution from '../components/ShellAttribution.svelte';
import ShellSidebar from '../components/ShellSidebar.svelte';
import {
	LEFT_SIDEBAR_MATTER_STORAGE_KEY,
	LEFT_SIDEBAR_STORAGE_KEY,
	attributionBelowPage,
	leftSidebarNarrow,
	leftSidebarOpen,
	leftSidebarPageFor,
	syncLeftSidebar
} from '../leftSidebar';
import { sidebarChromeOn } from '../shell';
import type { User } from '../tabs';

const FOOTER = 'data-testid="lq-ai-dual-branding-footer"';
const member: User = {
	id: 'm',
	email: 'm@x',
	is_admin: false,
	must_change_password: false,
	role: 'member'
};

function count(body: string): number {
	return body.split(FOOTER).length - 1;
}

/** Svelte's hydration markers (`<!--[-->`, `<!--]-->`, `<!---->`) are not markup. */
function stripMarkers(body: string): string {
	return body.replace(/<!--[[\]!]?\d*-->/g, '');
}

function setState(state: { open: boolean; narrow: boolean }): void {
	leftSidebarOpen.set(state.open);
	leftSidebarNarrow.set(state.narrow);
}

/** What the layout puts on the page with the switch on: the sidebar and the footer below the page. */
function shellWithSidebar(): { sidebar: string; below: string } {
	return {
		sidebar: render(ShellSidebar, { props: { user: member, pathname: '/lq-ai' } }).body,
		below: render(ShellAttribution, { props: { sidebarChrome: true } }).body
	};
}

afterEach(() => setState({ open: true, narrow: false }));

describe('sidebarChromeOn', () => {
	it('is on only with the switch on and outside the sign-in routes', () => {
		expect(sidebarChromeOn('sidebar', false)).toBe(true);
		expect(sidebarChromeOn('sidebar', true)).toBe(false);
		expect(sidebarChromeOn('tabs', false)).toBe(false);
		expect(sidebarChromeOn('tabs', true)).toBe(false);
	});
});

describe('attributionBelowPage', () => {
	const states = [
		{ open: true, narrow: false },
		{ open: false, narrow: false },
		{ open: true, narrow: true },
		{ open: false, narrow: true }
	];

	it('always shows with the switch off, in every collapse state', () => {
		for (const s of states)
			expect(
				attributionBelowPage({ sidebarChrome: sidebarChromeOn('tabs', false), ...s }),
				JSON.stringify(s)
			).toBe(true);
	});

	it('always shows on the sign-in routes with the switch on (they keep today’s chrome)', () => {
		for (const s of states)
			expect(
				attributionBelowPage({ sidebarChrome: sidebarChromeOn('sidebar', true), ...s }),
				JSON.stringify(s)
			).toBe(true);
	});

	it('shows below the page when the sidebar is collapsed on a narrow screen', () => {
		expect(attributionBelowPage({ sidebarChrome: true, open: false, narrow: true })).toBe(true);
	});

	it('shows below the page when the sidebar is collapsed on a wide screen (the panel and its foot are gone)', () => {
		expect(attributionBelowPage({ sidebarChrome: true, open: false, narrow: false })).toBe(true);
	});

	it('does not show when the sidebar panel, with the footer in its foot, is rendered', () => {
		expect(attributionBelowPage({ sidebarChrome: true, open: true, narrow: false })).toBe(false);
		expect(attributionBelowPage({ sidebarChrome: true, open: true, narrow: true })).toBe(false);
	});
});

describe('exactly one attribution on the page (server render)', () => {
	it('wide screen, sidebar open: in the sidebar foot only', () => {
		setState({ open: true, narrow: false });
		const { sidebar, below } = shellWithSidebar();
		expect(count(sidebar)).toBe(1);
		expect(count(below)).toBe(0);
	});

	it('wide screen, sidebar collapsed: below the page only', () => {
		setState({ open: false, narrow: false });
		const { sidebar, below } = shellWithSidebar();
		expect(count(sidebar)).toBe(0);
		expect(count(below)).toBe(1);
	});

	it('narrow screen, sidebar collapsed (how a phone starts): below the page only', () => {
		setState({ open: false, narrow: true });
		const { sidebar, below } = shellWithSidebar();
		expect(count(sidebar)).toBe(0);
		expect(count(below)).toBe(1);
	});

	it('narrow screen, sidebar open over the page: in the sidebar foot only', () => {
		setState({ open: true, narrow: true });
		const { sidebar, below } = shellWithSidebar();
		expect(count(sidebar)).toBe(1);
		expect(count(below)).toBe(0);
	});

	it('before the width is known (the stores’ defaults): in the sidebar foot only', () => {
		const { sidebar, below } = shellWithSidebar();
		expect(count(sidebar) + count(below)).toBe(1);
	});

	it('switch off or a sign-in route: today’s footer, in every collapse state', () => {
		for (const open of [true, false])
			for (const narrow of [true, false]) {
				setState({ open, narrow });
				const below = render(ShellAttribution, { props: { sidebarChrome: false } }).body;
				expect(count(below), JSON.stringify({ open, narrow })).toBe(1);
			}
	});
});

describe('matter pages start with the sidebar collapsed (server render)', () => {
	class MemoryStorage {
		map = new Map<string, string>();
		getItem(k: string) {
			return this.map.get(k) ?? null;
		}
		setItem(k: string, v: string) {
			this.map.set(k, v);
		}
	}
	const MATTER = '/lq-ai/matters/m1';
	const shellOn = (pathname: string) => ({
		sidebar: render(ShellSidebar, { props: { user: member, pathname } }).body,
		below: render(ShellAttribution, { props: { sidebarChrome: true } }).body
	});
	const modeOf = (body: string) =>
		/data-testid="lq-shell-sidebar"[^>]*data-mode="(\w+)"/.exec(body)?.[1];

	it('loaded on a matter page with no choice made there: the strip, and the footer below the page', () => {
		const s = new MemoryStorage();
		s.setItem(LEFT_SIDEBAR_STORAGE_KEY, 'open');
		syncLeftSidebar(false, () => s, leftSidebarPageFor(MATTER));
		const { sidebar, below } = shellOn(MATTER);
		expect(modeOf(sidebar)).toBe('collapsed');
		expect(sidebar).toContain('data-testid="lq-shell-sidebar-open"');
		expect(count(sidebar)).toBe(0);
		expect(count(below)).toBe(1);
	});

	it('loaded on a matter page after the person opened it there: the panel, footer in its foot', () => {
		const s = new MemoryStorage();
		s.setItem(LEFT_SIDEBAR_MATTER_STORAGE_KEY, 'open');
		syncLeftSidebar(false, () => s, leftSidebarPageFor(MATTER));
		const { sidebar, below } = shellOn(MATTER);
		expect(modeOf(sidebar)).toBe('open');
		expect(count(sidebar)).toBe(1);
		expect(count(below)).toBe(0);
	});

	it('loaded on another page (Knowledge) with no choice made: the panel stays open', () => {
		const s = new MemoryStorage();
		syncLeftSidebar(false, () => s, leftSidebarPageFor('/lq-ai/knowledge'));
		const { sidebar, below } = shellOn('/lq-ai/knowledge');
		expect(modeOf(sidebar)).toBe('open');
		expect(count(sidebar) + count(below)).toBe(1);
	});

	it('the server render loads nothing itself: it draws the state it is given, one attribution', () => {
		// The stores' defaults (open, wide); the matter-page rule runs only after mount.
		const { sidebar, below } = shellOn(MATTER);
		expect(modeOf(sidebar)).toBe('open');
		expect(count(sidebar) + count(below)).toBe(1);
	});
});

describe('switch off: unchanged', () => {
	it('renders exactly today’s footer markup, with the wording unchanged', () => {
		setState({ open: false, narrow: true });
		const below = stripMarkers(render(ShellAttribution, { props: { sidebarChrome: false } }).body);
		const today = stripMarkers(render(DualBrandingFooter).body);
		expect(below).toBe(today);
		expect(below).toContain('Open-Source Legal AI');
		expect(below).toContain('Web shell powered by');
		expect(below).toContain('(forked at v0.11.0; see ADR\u00a00001).');
	});
});
