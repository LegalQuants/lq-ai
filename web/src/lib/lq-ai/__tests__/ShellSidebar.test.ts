import { afterEach, describe, expect, it } from 'vitest';
import { render } from 'svelte/server';

import ShellSidebar from '../components/ShellSidebar.svelte';
import { defaultPreferences, preferences } from '../stores/preferences';
import type { User } from '../tabs';

const member: User = {
	id: 'm',
	email: 'm@x',
	is_admin: false,
	must_change_password: false,
	role: 'member'
};
const viewer: User = { ...member, id: 'v', role: 'viewer' };
const adminByRole: User = { ...member, id: 'a1', role: 'admin' };
const adminByFlag: User = { id: 'a2', email: 'a@x', is_admin: true, must_change_password: false };

function html(user: User | null, pathname = '/lq-ai', autonomousEnabled = false): string {
	preferences.set({ ...defaultPreferences, autonomous_enabled: autonomousEnabled });
	return render(ShellSidebar, { props: { user, pathname } }).body;
}

/** Row ids in document order, from the data-nav-id each row carries. */
function rowIds(body: string): string[] {
	return [...body.matchAll(/data-nav-id="([^"]+)"/g)].map((m) => m[1]);
}

/** The opening tag of the row with this id. */
function rowTag(body: string, id: string): string {
	const tag = body.match(new RegExp(`<(?:a|button)\\b[^>]*data-nav-id="${id}"[^>]*>`));
	expect(tag, `row ${id}`).not.toBeNull();
	return tag![0];
}

afterEach(() => preferences.set({ ...defaultPreferences }));

describe('ShellSidebar rows and order (from nav.ts)', () => {
	it('renders the full sidebar in order for an admin with Autonomous on', () => {
		expect(rowIds(html(adminByRole, '/lq-ai', true))).toEqual([
			'new',
			'home',
			'tabular',
			'labs',
			'customise',
			'skills',
			'knowledge',
			'playbooks',
			'saved-prompts',
			'all-matters',
			'all-chats',
			'learn',
			'trust',
			'admin',
			'account'
		]);
	});

	it('shows Admin for either admin signal and hides it from members and viewers', () => {
		expect(rowIds(html(adminByRole))).toContain('admin');
		expect(rowIds(html(adminByFlag))).toContain('admin');
		expect(rowIds(html(member))).not.toContain('admin');
		expect(rowIds(html(viewer))).not.toContain('admin');
		expect(rowIds(html(null))).not.toContain('admin');
	});

	it('shows Labs only when the Autonomous opt-in is on', () => {
		expect(rowIds(html(member, '/lq-ai', false))).not.toContain('labs');
		expect(rowIds(html(member, '/lq-ai', true))).toContain('labs');
		expect(rowIds(html(adminByRole, '/lq-ai', false))).not.toContain('labs');
	});

	it('links each row to the route nav.ts gives it, Labs and Admin included', () => {
		const body = html(adminByFlag, '/lq-ai', true);
		const hrefs: Record<string, string> = {
			new: '/lq-ai/chats',
			home: '/lq-ai',
			tabular: '/lq-ai/tabular',
			labs: '/lq-ai/autonomous',
			skills: '/lq-ai/skills',
			'all-matters': '/lq-ai/matters',
			'all-chats': '/lq-ai/chats',
			learn: '/lq-ai/learn',
			trust: '/lq-ai/trust',
			admin: '/lq-ai/admin/audit-log',
			account: '/lq-ai/settings/account'
		};
		for (const [id, href] of Object.entries(hrefs))
			expect(rowTag(body, id)).toContain(`href="${href}"`);
		// Customise is a group, not a page.
		expect(rowTag(body, 'customise')).toMatch(/^<button/);
		expect(rowTag(body, 'customise')).not.toContain('href=');
	});

	it('keeps the full attribution wording at the foot, outside the navigation landmark', () => {
		const body = html(member);
		expect(body).toContain('data-testid="lq-ai-dual-branding-footer"');
		expect(body).toContain('Open-Source Legal AI');
		expect(body).toContain('Web shell powered by');
		expect(body).toContain('(forked at v0.11.0; see ADR 0001)');
		expect(body.indexOf('</nav>')).toBeLessThan(body.indexOf('lq-ai-dual-branding-footer'));
	});
});

describe('ShellSidebar landmarks, current row and the Customise group', () => {
	it('is one labelled navigation landmark', () => {
		const body = html(member);
		expect(body.match(/<nav\b/g)).toHaveLength(1);
		expect(body).toMatch(/<nav[^>]*aria-label="Primary"/);
		expect(body).not.toContain('role="tab');
	});

	it.each([
		['/lq-ai', 'home'],
		['/lq-ai/tabular/abc', 'tabular'],
		['/lq-ai/matters/123', 'all-matters'],
		['/lq-ai/chats/abc', 'all-chats'],
		['/lq-ai/admin/users', 'admin'],
		['/lq-ai/settings/appearance', 'account'],
		['/lq-ai/autonomous/sessions/1', 'labs'],
		['/lq-ai/trust', 'trust']
	])('marks exactly one row current on %s', (pathname, id) => {
		const body = html(adminByRole, pathname, true);
		expect(body.match(/aria-current="page"/g)).toHaveLength(1);
		expect(rowTag(body, id)).toContain('aria-current="page"');
	});

	it('never marks New current (a new chat belongs to All chats)', () => {
		const body = html(member, '/lq-ai/chats');
		expect(rowTag(body, 'new')).not.toContain('aria-current');
		expect(rowTag(body, 'all-chats')).toContain('aria-current="page"');
	});

	it('keeps Customise collapsed when none of its rows is current', () => {
		const body = html(member, '/lq-ai');
		const group = rowTag(body, 'customise');
		expect(group).toContain('aria-expanded="false"');
		expect(group).toContain('aria-controls="lq-sidebar-group-customise"');
		expect(body).toMatch(/<ul[^>]*id="lq-sidebar-group-customise"[^>]*hidden/);
	});

	it('opens Customise and marks the child, not the group, on a Customise page', () => {
		const body = html(member, '/lq-ai/knowledge/kb-1');
		const group = rowTag(body, 'customise');
		expect(group).toContain('aria-expanded="true"');
		expect(group).not.toContain('aria-current');
		expect(body).not.toMatch(/<ul[^>]*id="lq-sidebar-group-customise"[^>]*hidden/);
		expect(rowTag(body, 'knowledge')).toContain('aria-current="page"');
		expect(body.match(/aria-current="page"/g)).toHaveLength(1);
	});
});
