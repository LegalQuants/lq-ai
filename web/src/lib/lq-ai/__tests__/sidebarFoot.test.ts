/**
 * The left sidebar's caps and pinned foot (houfu, 11 Nov): at most 5 matters
 * with 3 chats each and 8 other chats are listed, inside a scrolling area; the
 * foot (Learn, Trust & Privacy, Admin, Account settings) and the attribution sit
 * outside it, so they stay on screen however long the lists are. Rendered in
 * node (`svelte/server`); the scrolling itself is checked in the browser.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { render } from 'svelte/server';

import ShellSidebar from '../components/ShellSidebar.svelte';
import { createSidebarLists } from '../sidebarLists';
import type { Chat, Project } from '../types';
import type { User } from '../tabs';

const admin: User = {
	id: 'u1',
	email: 'a@x',
	is_admin: true,
	must_change_password: false,
	role: 'admin'
};
const at = (n: number) =>
	`2026-11-${String(10 + (n % 18)).padStart(2, '0')}T${String(n % 24).padStart(2, '0')}:00:00Z`;
const project = (i: number): Project => ({
	id: `m${i}`,
	name: `Matter ${i}`,
	slug: `m${i}`,
	owner_id: 'u1',
	privileged: false,
	created_at: '2026-11-01T00:00:00Z',
	updated_at: at(i)
});
const chat = (id: string, projectId: string | null, n: number): Chat => ({
	id,
	title: `Chat ${id}`,
	owner_id: 'u1',
	project_id: projectId,
	created_at: '2026-11-01T00:00:00Z',
	updated_at: at(n)
});

function body(): string {
	const lists = createSidebarLists({
		listProjects: async () => {
			throw new Error('no fetch');
		},
		listChats: async () => {
			throw new Error('no fetch');
		}
	});
	lists.seed({
		projects: Array.from({ length: 9 }, (_, i) => project(i)),
		chats: [
			...Array.from({ length: 9 }, (_, i) =>
				Array.from({ length: 5 }, (_, j) => chat(`m${i}c${j}`, `m${i}`, i * 5 + j))
			).flat(),
			...Array.from({ length: 12 }, (_, i) => chat(`o${i}`, null, i))
		],
		loadedAt: 1
	});
	return render(ShellSidebar, { props: { user: admin, pathname: '/lq-ai', lists } }).body.replace(
		/<!--[[\]!]?\d*-->/g,
		''
	);
}

/** Whether the element starting at `start` (a `<div`) has closed before `index`. */
function divClosedBefore(html: string, start: number, index: number): boolean {
	let depth = 0;
	const re = /<div\b|<\/div>/g;
	re.lastIndex = start;
	for (let m = re.exec(html); m && m.index < index; m = re.exec(html)) {
		depth += m[0] === '</div>' ? -1 : 1;
		if (depth === 0) return true;
	}
	return false;
}

describe('the sidebar caps and the pinned foot', () => {
	it('lists at most 5 matters, 3 chats under each and 8 other chats', () => {
		const html = body();
		expect(html.match(/data-sidebar-matter="/g)).toHaveLength(5);
		const chats = [...html.matchAll(/data-sidebar-chat="([^"]+)"/g)].map((m) => m[1]);
		expect(chats.filter((id) => id.startsWith('o'))).toHaveLength(8);
		for (const m of new Set(chats.filter((id) => id.startsWith('m')).map((id) => id.split('c')[0])))
			expect(chats.filter((id) => id.startsWith(`${m}c`)).length).toBeLessThanOrEqual(3);
		expect(chats.filter((id) => id.startsWith('m'))).toHaveLength(15);
		// The rest is behind the existing "All" rows.
		expect(html).toContain('data-nav-id="all-matters"');
		expect(html).toContain('data-nav-id="all-chats"');
	});

	it('puts the lists in the scrolling area and the foot and attribution outside it', () => {
		const html = body();
		const scroll = html.indexOf('<div class="lq-sidebar-scroll');
		expect(scroll).toBeGreaterThan(-1);
		const lastChat = html.lastIndexOf('data-sidebar-chat="');
		const foot = html.indexOf('data-section="foot"');
		const attribution = html.indexOf('data-testid="lq-ai-dual-branding-footer"');
		expect(divClosedBefore(html, scroll, lastChat)).toBe(false);
		expect(divClosedBefore(html, scroll, foot)).toBe(true);
		expect(foot).toBeLessThan(attribution);
		for (const id of ['learn', 'trust', 'admin', 'account'])
			expect(html.indexOf(`data-nav-id="${id}"`)).toBeGreaterThan(foot);
	});

	it('scrolls the lists, not the nav, and keeps the foot from shrinking', () => {
		const here = dirname(fileURLToPath(import.meta.url));
		const css = readFileSync(resolve(here, '../components/ShellSidebar.svelte'), 'utf8');
		const rule = (sel: string) =>
			css.match(new RegExp(`\\n\\t${sel.replace('.', '\\.')} \\{([^}]*)\\}`))?.[1] ?? '';
		expect(rule('.lq-sidebar-scroll')).toMatch(/overflow-y: auto/);
		expect(rule('.lq-sidebar-scroll')).toMatch(/min-height: 0/);
		expect(rule('.lq-sidebar-nav')).not.toMatch(/overflow/);
		expect(rule('.lq-sidebar-foot')).toMatch(/flex-shrink: 0/);
		expect(rule('.lq-sidebar-attribution')).toMatch(/flex-shrink: 0/);
	});
});
