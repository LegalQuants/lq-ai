/**
 * The left sidebar's recent matters and chats (interface-redesign P1.3b):
 * grouping, ordering and caps, the current row, and the async state.
 */
import { describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import {
	MIN_REFRESH_MS,
	SIDEBAR_CAPS,
	SIDEBAR_CHAT_PAGE,
	createSidebarLists,
	currentSidebarRows,
	listClaimsCurrent,
	mergeChats,
	shapeSidebarLists
} from '../sidebarLists';
import type { Chat, Project } from '../types';

const day = (n: number) => `2026-11-${String(n).padStart(2, '0')}T09:00:00Z`;

const project = (id: string, updated: number, over: Partial<Project> = {}): Project => ({
	id,
	name: `Matter ${id}`,
	slug: id,
	owner_id: 'u1',
	privileged: false,
	created_at: day(1),
	updated_at: day(updated),
	...over
});

const chat = (
	id: string,
	updated: number,
	projectId: string | null = null,
	over: Partial<Chat> = {}
): Chat => ({
	id,
	title: `Chat ${id}`,
	owner_id: 'u1',
	project_id: projectId,
	created_at: day(1),
	updated_at: day(updated),
	...over
});

describe('mergeChats', () => {
	it('lays the live copy over the fetched one and adds chats the fetch did not have', () => {
		const merged = mergeChats(
			[chat('a', 2), chat('b', 3)],
			[chat('a', 2, null, { title: 'Renamed' }), chat('new', 9)]
		);
		expect(merged.map((c) => [c.id, c.title])).toEqual([
			['a', 'Renamed'],
			['b', 'Chat b'],
			['new', 'Chat new']
		]);
	});
});

describe('shapeSidebarLists', () => {
	it('puts each chat under its matter and the rest under other chats, newest first', () => {
		const lists = shapeSidebarLists(
			[project('m1', 5), project('m2', 4)],
			[chat('c1', 2, 'm1'), chat('c2', 3, 'm2'), chat('c3', 4, 'm1'), chat('o1', 6), chat('o2', 8)]
		);
		expect(lists.matters.map((m) => [m.project.id, m.chats.map((c) => c.id)])).toEqual([
			['m1', ['c3', 'c1']],
			['m2', ['c2']]
		]);
		expect(lists.otherChats.map((c) => c.id)).toEqual(['o2', 'o1']);
	});

	it('orders matters by their latest activity, the matter itself or its newest chat', () => {
		const lists = shapeSidebarLists(
			[project('old-but-busy', 1), project('recent', 5), project('quiet', 3)],
			[chat('c', 9, 'old-but-busy')]
		);
		expect(lists.matters.map((m) => m.project.id)).toEqual(['old-but-busy', 'recent', 'quiet']);
	});

	it('caps matters, chats per matter and other chats', () => {
		const projects = Array.from({ length: 8 }, (_, i) => project(`m${i}`, 10 + i));
		const chats = [
			...Array.from({ length: 6 }, (_, i) => chat(`in${i}`, 1 + i, 'm7')),
			...Array.from({ length: 9 }, (_, i) => chat(`o${i}`, 1 + i))
		];
		const lists = shapeSidebarLists(projects, chats);
		expect(lists.matters).toHaveLength(SIDEBAR_CAPS.matters);
		expect(lists.matters[0].chats.map((c) => c.id)).toEqual(['in5', 'in4', 'in3']);
		expect(lists.otherChats.map((c) => c.id)).toEqual([
			'o8',
			'o7',
			'o6',
			'o5',
			'o4',
			'o3',
			'o2',
			'o1'
		]);
		expect(SIDEBAR_CAPS).toEqual({ matters: 5, chatsPerMatter: 3, otherChats: 8 });
		expect(
			shapeSidebarLists(projects, chats, { matters: 2, chatsPerMatter: 1, otherChats: 1 })
		).toMatchObject({
			matters: [
				{ project: { id: 'm7' }, chats: [{ id: 'in5' }] },
				{ project: { id: 'm6' }, chats: [] }
			],
			otherChats: [{ id: 'o8' }]
		});
	});

	it('leaves out archived chats, archived and sandbox matters, and chats of unlisted matters', () => {
		const lists = shapeSidebarLists(
			[
				project('live', 2),
				project('gone', 9, { archived_at: day(9) }),
				project('sandbox', 9, { is_sandbox: true })
			],
			[
				chat('archived', 9, null, { archived_at: day(9) }),
				chat('in-sandbox', 9, 'sandbox'),
				chat('in-unknown', 9, 'not-listed'),
				chat('kept', 1)
			]
		);
		expect(lists.matters.map((m) => m.project.id)).toEqual(['live']);
		expect(lists.otherChats.map((c) => c.id)).toEqual(['kept']);
	});
});

describe('the current row', () => {
	it('is the matter on a matter page, with the open chat current within it', () => {
		expect(currentSidebarRows('/lq-ai/matters/m%201', 'ignored', 'c1')).toEqual({
			matterId: 'm 1',
			chatId: 'c1'
		});
	});

	it('is the open chat on the chats page, else the chat in the address', () => {
		expect(currentSidebarRows('/lq-ai/chats', 'url', 'open')).toEqual({
			matterId: null,
			chatId: 'open'
		});
		expect(currentSidebarRows('/lq-ai/chats', 'url', null)).toEqual({
			matterId: null,
			chatId: 'url'
		});
	});

	it('is nothing elsewhere, even with a chat still open in the store', () => {
		for (const path of ['/lq-ai', '/lq-ai/matters', '/lq-ai/matters/m1/files', '/lq-ai/skills'])
			expect(currentSidebarRows(path, 'url', 'open')).toEqual({ matterId: null, chatId: null });
	});

	it('says when a listed row is current, so the "All" row does not claim it too', () => {
		const lists = shapeSidebarLists([project('m1', 2)], [chat('in', 2, 'm1'), chat('o', 2)]);
		expect(listClaimsCurrent(lists, { matterId: 'm1', chatId: 'in' })).toEqual({
			matters: true,
			chats: true
		});
		expect(listClaimsCurrent(lists, { matterId: null, chatId: 'o' })).toEqual({
			matters: false,
			chats: true
		});
		expect(listClaimsCurrent(lists, { matterId: 'm9', chatId: 'zz' })).toEqual({
			matters: false,
			chats: false
		});
		expect(listClaimsCurrent(lists, { matterId: null, chatId: null })).toEqual({
			matters: false,
			chats: false
		});
	});
});

function fakeApi() {
	return {
		listProjects: vi.fn(async () => [project('m1', 2)]),
		listChats: vi.fn(async () => ({ items: [chat('c1', 2)], next_cursor: null }))
	};
}

describe('createSidebarLists', () => {
	it('loads matters and one page of chats in two requests', async () => {
		const api = fakeApi();
		const lists = createSidebarLists(api, () => 1000);
		expect(get(lists).status).toBe('idle');
		await lists.refresh();
		expect(api.listProjects).toHaveBeenCalledTimes(1);
		expect(api.listChats).toHaveBeenCalledWith({ limit: SIDEBAR_CHAT_PAGE });
		expect(get(lists)).toMatchObject({ status: 'ready', loadedAt: 1000 });
		expect(get(lists).chats.map((c) => c.id)).toEqual(['c1']);
	});

	it('refreshes on navigation at most once per interval; Retry and sign-in force it', async () => {
		const api = fakeApi();
		let now = 0;
		const lists = createSidebarLists(api, () => now);
		await lists.refresh();
		now = MIN_REFRESH_MS - 1;
		await lists.refresh();
		expect(api.listProjects).toHaveBeenCalledTimes(1);
		await lists.refresh({ force: true });
		expect(api.listProjects).toHaveBeenCalledTimes(2);
		now += MIN_REFRESH_MS;
		await lists.refresh();
		expect(api.listProjects).toHaveBeenCalledTimes(3);
	});

	it('keeps the last lists when a refresh fails, and reports the error', async () => {
		const api = fakeApi();
		const lists = createSidebarLists(api, () => 0);
		await lists.refresh();
		api.listChats.mockRejectedValueOnce(new Error('down'));
		await lists.refresh({ force: true });
		expect(get(lists).status).toBe('error');
		expect(get(lists).projects.map((p) => p.id)).toEqual(['m1']);
		expect(get(lists).chats.map((c) => c.id)).toEqual(['c1']);
		await lists.refresh();
		expect(get(lists).status).toBe('ready');
	});

	it('drops a response that arrives after a reset (another person signed in)', async () => {
		let release!: () => void;
		const api = fakeApi();
		api.listProjects.mockImplementationOnce(
			() => new Promise((resolve) => (release = () => resolve([project('old-user', 2)])))
		);
		const lists = createSidebarLists(api, () => 0);
		const pending = lists.refresh();
		lists.reset();
		release();
		await pending;
		expect(get(lists)).toMatchObject({ status: 'idle', projects: [], chats: [] });
	});

	it('empties the lists at once for a different person and loads theirs', async () => {
		const api = fakeApi();
		const lists = createSidebarLists(api, () => 0);
		lists.forUser('u1');
		await Promise.resolve();
		await Promise.resolve();
		await vi.waitFor(() => expect(get(lists).status).toBe('ready'));
		expect(get(lists)).toMatchObject({ user: 'u1', projects: [{ id: 'm1' }] });
		lists.forUser('u1');
		expect(api.listProjects).toHaveBeenCalledTimes(1);
		let release!: () => void;
		api.listProjects.mockImplementationOnce(
			() => new Promise((resolve) => (release = () => resolve([project('stale', 2)])))
		);
		lists.forUser('u2');
		expect(get(lists)).toMatchObject({ user: 'u2', projects: [], chats: [] });
		lists.forUser(null);
		release();
		await Promise.resolve();
		await Promise.resolve();
		expect(get(lists)).toMatchObject({ user: null, status: 'idle', projects: [], chats: [] });
		expect(api.listProjects).toHaveBeenCalledTimes(2);
	});

	it('does not start a second request while one is in flight', async () => {
		const api = fakeApi();
		const lists = createSidebarLists(api, () => 0);
		const first = lists.refresh();
		await lists.refresh();
		await first;
		expect(api.listProjects).toHaveBeenCalledTimes(1);
	});
});
