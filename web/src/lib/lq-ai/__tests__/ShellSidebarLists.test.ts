/**
 * The left sidebar's P1.3b parts rendered to HTML in node (`svelte/server`):
 * recent matters and chats, the notification bell in its two places, and the
 * collapsed strip. SSR runs every `$:` statement and no `onMount`.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { render } from 'svelte/server';

import ShellSidebar from '../components/ShellSidebar.svelte';
import NotificationBell from '../components/NotificationBell.svelte';
import NotificationsPanel from '../components/NotificationsPanel.svelte';
import RightSidebar from '../components/RightSidebar.svelte';
import { createSidebarLists } from '../sidebarLists';
import { createNotificationBell } from '../autonomous/notification-bell-controller';
import { leftSidebarNarrow, leftSidebarOpen } from '../leftSidebar';
import { clearRightSidebarOverlay, showRightSidebarOverlay } from '../rightSidebar';
import { activeChatStore, chatsStore } from '../stores';
import type { Chat, Project } from '../types';
import type { User } from '../tabs';

const member: User = {
	id: 'u1',
	email: 'm@x',
	is_admin: false,
	must_change_password: false,
	role: 'member'
};

const project = (id: string, name: string, updated: string): Project => ({
	id,
	name,
	slug: id,
	owner_id: 'u1',
	privileged: false,
	created_at: '2026-11-01T00:00:00Z',
	updated_at: updated
});
const chat = (
	id: string,
	title: string,
	projectId: string | null,
	updated: string,
	owner = 'u1'
): Chat => ({
	id,
	title,
	owner_id: owner,
	project_id: projectId,
	created_at: '2026-11-01T00:00:00Z',
	updated_at: updated
});

const noFetch = {
	listProjects: async () => {
		throw new Error('SSR tests must not fetch');
	},
	listChats: async () => {
		throw new Error('SSR tests must not fetch');
	}
};

function seeded() {
	const lists = createSidebarLists(noFetch);
	lists.seed({
		projects: [
			project('m1', 'Kestrel MSA renewal', '2026-11-05T00:00:00Z'),
			project('m2', 'Larkspur', '2026-11-02T00:00:00Z')
		],
		chats: [
			chat('c1', 'Liability cap', 'm1', '2026-11-06T00:00:00Z'),
			chat('c2', 'Redline notes', 'm1', '2026-11-04T00:00:00Z'),
			chat('o1', 'DPA summary', null, '2026-11-03T00:00:00Z')
		],
		loadedAt: 1
	});
	return lists;
}

async function bellWith(count: number) {
	const bell = createNotificationBell({
		listNotifications: async () => ({
			notifications: [
				{
					id: 'n1',
					user_id: 'u1',
					session_id: 's',
					channel: 'in_app',
					title: 'MSA review finished',
					body: 'Three findings.',
					payload: null,
					read_at: null,
					created_at: '2026-11-08T09:05:00Z',
					updated_at: '2026-11-08T09:05:00Z'
				}
			],
			total_count: count,
			limit: 10,
			offset: 0
		}),
		readNotification: async () => {
			throw new Error('not in SSR');
		}
	} as unknown as Parameters<typeof createNotificationBell>[0]);
	await bell.refresh();
	return bell;
}

function html(props: Record<string, unknown> = {}): string {
	return render(ShellSidebar, {
		props: { user: member, pathname: '/lq-ai', lists: seeded(), ...props }
	}).body;
}

const tag = (body: string, attr: string) => {
	const m = body.match(new RegExp(`<(?:a|button|li|div)\\b[^>]*${attr}[^>]*>`));
	expect(m, attr).not.toBeNull();
	return m![0];
};

afterEach(() => {
	leftSidebarOpen.set(true);
	leftSidebarNarrow.set(false);
	chatsStore.set([]);
	activeChatStore.set(null);
	clearRightSidebarOverlay();
});

describe('recent matters and chats', () => {
	it('lists matters with their chats, then other chats, above the "All" rows', () => {
		const body = html();
		const order = [...body.matchAll(/data-(sidebar-matter|sidebar-chat|nav-id)="([^"]+)"/g)]
			.map((m) => m[2])
			.filter(
				(id) =>
					![
						'new',
						'home',
						'tabular',
						'customise',
						'skills',
						'knowledge',
						'playbooks',
						'saved-prompts',
						'learn',
						'trust',
						'account'
					].includes(id)
			);
		expect(order).toEqual(['m1', 'c1', 'c2', 'm2', 'all-matters', 'o1', 'all-chats']);
		expect(tag(body, 'data-sidebar-matter="m1"')).toContain('href="/lq-ai/matters/m1"');
		expect(tag(body, 'data-sidebar-chat="c1"')).toContain('href="/lq-ai/chats?id=c1"');
		expect(body).toContain('Kestrel MSA renewal');
		expect(body).toContain('DPA summary');
		expect(body).not.toContain('Loading matters');
	});

	it('marks the matter on its page, its open chat within it, and not "All matters"', () => {
		activeChatStore.set(chat('c2', 'Redline notes', 'm1', '2026-11-04T00:00:00Z'));
		const body = html({ pathname: '/lq-ai/matters/m1' });
		expect(tag(body, 'data-sidebar-matter="m1"')).toContain('aria-current="page"');
		expect(tag(body, 'data-sidebar-chat="c2"')).toContain('aria-current="true"');
		expect(tag(body, 'data-nav-id="all-matters"')).not.toContain('aria-current');
		expect(body.match(/aria-current="page"/g)).toHaveLength(1);
	});

	it('marks the open chat on the chats page instead of "All chats"', () => {
		const body = html({ pathname: '/lq-ai/chats', urlChatId: 'o1' });
		expect(tag(body, 'data-sidebar-chat="o1"')).toContain('aria-current="page"');
		expect(tag(body, 'data-nav-id="all-chats"')).not.toContain('aria-current');
		expect(body.match(/aria-current="page"/g)).toHaveLength(1);
	});

	it('keeps "All chats" current for a chat the list does not show', () => {
		const body = html({ pathname: '/lq-ai/chats', urlChatId: 'elsewhere' });
		expect(tag(body, 'data-nav-id="all-chats"')).toContain('aria-current="page"');
	});

	it('shows a new or renamed chat from the open chat page, but never another person’s', () => {
		chatsStore.set([
			chat('o1', 'Renamed DPA', null, '2026-11-03T00:00:00Z'),
			chat('mine', 'Brand new', null, '2026-11-09T00:00:00Z'),
			chat('theirs', 'Someone else', null, '2026-11-09T00:00:00Z', 'u2')
		]);
		const body = html();
		expect(body).toContain('Renamed DPA');
		expect(body).not.toContain('DPA summary');
		expect(body).toContain('data-sidebar-chat="mine"');
		expect(body).not.toContain('data-sidebar-chat="theirs"');
	});

	it('never shows lists loaded for another person', () => {
		const lists = seeded();
		lists.seed({
			user: 'someone-else',
			projects: [project('m9', 'Their matter', '2026-11-05T00:00:00Z')],
			chats: [chat('t1', 'Their chat', null, '2026-11-05T00:00:00Z', 'someone-else')]
		});
		const body = html({ lists });
		expect(body).not.toContain('Their matter');
		expect(body).not.toContain('Their chat');
		lists.seed({ user: 'u1', projects: [project('m1', 'My matter', '2026-11-05T00:00:00Z')] });
		expect(html({ lists })).toContain('My matter');
	});

	it('shows loading before the first load and an error with Retry when it fails, keeping the rows', () => {
		const loading = render(ShellSidebar, {
			props: { user: member, pathname: '/lq-ai', lists: createSidebarLists(noFetch) }
		}).body;
		expect(loading).toContain('Loading matters…');
		expect(loading).toContain('Loading chats…');
		expect(loading).toContain('data-nav-id="all-matters"');

		const failed = seeded();
		failed.seed({
			status: 'error',
			projects: [project('m1', 'Kept matter', '2026-11-05T00:00:00Z')]
		});
		const body = html({ lists: failed });
		expect(body).toContain('data-testid="lq-shell-lists-error"');
		expect(body).toContain('>Retry</button>');
		expect(body).toContain('Kept matter');
		expect(body).toContain('data-nav-id="all-chats"');
	});
});

describe('the notification bell in its two places', () => {
	it('is absent when Automations is off', async () => {
		const body = html({ automations: false, notifications: await bellWith(3) });
		expect(body).not.toContain('lq-shell-bell');
		expect(body).not.toContain('lq-shell-notifications-row');
		expect(body).not.toContain('lq-ai-notification-bell');
	});

	it('shows the icon beside the sidebar toggle and a row under Customise, with the unread count', async () => {
		const body = html({ automations: true, notifications: await bellWith(2) });
		const icon = tag(body, 'data-testid="lq-shell-bell"');
		const row = tag(body, 'data-testid="lq-shell-notifications-row"');
		for (const t of [icon, row]) {
			expect(t).toContain('aria-label="Notifications, 2 unread"');
			expect(t).toContain('aria-expanded="false"');
		}
		// The icon sits in the head, before the toggle; the row right after Customise's group.
		expect(body.indexOf('lq-shell-bell"')).toBeLessThan(body.indexOf('lq-shell-sidebar-toggle'));
		expect(body.indexOf('lq-shell-sidebar-toggle')).toBeLessThan(body.indexOf('<nav'));
		expect(body.indexOf('data-nav-id="saved-prompts"')).toBeLessThan(
			body.indexOf('lq-shell-notifications-row')
		);
		expect(body.indexOf('lq-shell-notifications-row')).toBeLessThan(
			body.indexOf('data-section="matters"')
		);
		expect(body.match(/class="lq-sidebar-count[^"]*"[^>]*>\s*2\s*</g)).toHaveLength(2);
		// The old bell's ids stay with the old bell.
		expect(body).not.toContain('lq-ai-notification-bell');
	});

	it('caps the count at 99+ and has no count at zero', async () => {
		const many = html({ automations: true, notifications: await bellWith(102) });
		expect(tag(many, 'data-testid="lq-shell-bell"')).toContain(
			'aria-label="Notifications, 99+ (102 unread)"'
		);
		expect(many).toContain('99+');
		const none = html({ automations: true, notifications: await bellWith(0) });
		expect(tag(none, 'data-testid="lq-shell-bell"')).toContain('aria-label="Notifications"');
		expect(none).not.toContain('lq-sidebar-count');
	});

	it('reports both controls expanded while the list is shown in the right sidebar', async () => {
		showRightSidebarOverlay({ label: 'Notifications', component: null, props: {} });
		const body = html({ automations: true, notifications: await bellWith(1) });
		expect(tag(body, 'data-testid="lq-shell-bell"')).toContain('aria-expanded="true"');
		expect(tag(body, 'data-testid="lq-shell-notifications-row"')).toContain('aria-expanded="true"');
	});
});

describe('collapse', () => {
	it('is open on a wide screen with a named toggle in the head', () => {
		const body = html();
		expect(tag(body, 'data-testid="lq-shell-sidebar"')).toContain('data-mode="open"');
		const toggle = tag(body, 'data-testid="lq-shell-sidebar-toggle"');
		expect(toggle).toContain('aria-label="Collapse sidebar"');
		expect(toggle).toContain('aria-expanded="true"');
		expect(toggle).toContain('aria-controls="lq-left-sidebar"');
		expect(body).toContain('id="lq-left-sidebar"');
		expect(body).not.toContain('lq-shell-sidebar-strip');
	});

	it('collapses to a strip with the toggle (and the bell when Automations is on)', async () => {
		leftSidebarOpen.set(false);
		const body = html({ automations: true, notifications: await bellWith(4) });
		expect(tag(body, 'data-testid="lq-shell-sidebar"')).toContain('data-mode="collapsed"');
		const open = tag(body, 'data-testid="lq-shell-sidebar-open"');
		expect(open).toContain('aria-label="Open sidebar"');
		expect(open).toContain('aria-expanded="false"');
		expect(open).toContain('aria-controls="lq-left-sidebar"');
		expect(tag(body, 'data-testid="lq-shell-bell-strip"')).toContain(
			'aria-label="Notifications, 4 unread"'
		);
		expect(body).not.toContain('<nav');
		expect(body).not.toContain('id="lq-left-sidebar"');
	});

	it('opens over the page on a narrow screen, with a backdrop and a close toggle', () => {
		leftSidebarNarrow.set(true);
		leftSidebarOpen.set(true);
		const body = html();
		expect(tag(body, 'data-testid="lq-shell-sidebar"')).toContain('data-mode="overlay"');
		expect(body).toContain('lq-shell-sidebar-strip');
		expect(body).toContain('lq-shell-sidebar-backdrop');
		expect(tag(body, 'id="lq-left-sidebar"')).toContain('lq-sidebar-overlay');
		expect(tag(body, 'data-testid="lq-shell-sidebar-toggle"')).toContain(
			'aria-label="Close sidebar"'
		);
		expect(tag(body, 'data-testid="lq-shell-sidebar-open"')).toContain('aria-expanded="true"');
	});
});

describe('today’s top-bar bell (switch off) is unchanged', () => {
	it('still renders its own trigger and test ids', () => {
		const body = render(NotificationBell).body;
		expect(body).toContain('data-testid="lq-ai-notification-bell"');
		expect(body).toContain('data-testid="lq-ai-notification-bell-trigger"');
		expect(body).toContain('aria-label="Notifications"');
		expect(body).not.toContain('lq-shell-');
	});
});

describe('the notification list in the right sidebar', () => {
	it('shows the unread items, Mark shown read and the link to Automations', async () => {
		const bell = await bellWith(2);
		showRightSidebarOverlay({
			label: 'Notifications',
			component: NotificationsPanel,
			props: { bell }
		});
		const body = render(RightSidebar, { props: { pathname: '/lq-ai/chats' } }).body;
		expect(body).toMatch(/<aside[^>]*aria-label="Notifications"/);
		expect(body).toContain('data-testid="lq-shell-notifications-panel"');
		expect(body.match(/data-testid="lq-shell-notifications-item"/g)).toHaveLength(1);
		expect(body).toContain('MSA review finished');
		expect(body).toContain('2 unread, from your Automations runs');
		expect(body).toContain('data-testid="lq-shell-notifications-mark-all"');
		expect(body).toContain('aria-label="Mark read: MSA review finished"');
		expect(tag(body, 'data-testid="lq-shell-notifications-view-all"')).toContain(
			'href="/lq-ai/autonomous/notifications"'
		);
	});

	it('says so when there is nothing unread', async () => {
		const bell = createNotificationBell({
			listNotifications: async () => ({ notifications: [], total_count: 0, limit: 10, offset: 0 }),
			readNotification: async () => {
				throw new Error('no');
			}
		} as unknown as Parameters<typeof createNotificationBell>[0]);
		await bell.refresh();
		const body = render(NotificationsPanel, { props: { bell } }).body;
		expect(body).toContain('No unread notifications.');
		expect(body).not.toContain('lq-shell-notifications-mark-all');
	});
});
