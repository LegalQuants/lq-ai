import { describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { createNotificationBell, type BellApi } from '../notification-bell-controller';
import type {
	AutonomousNotificationRead,
	AutonomousNotificationListResponse
} from '../../api/autonomous';

function deferred<T>() {
	let resolve!: (value: T) => void;
	let reject!: (error: Error) => void;
	const promise = new Promise<T>((yes, no) => {
		resolve = yes;
		reject = no;
	});
	return { promise, resolve, reject };
}
function note(id: string): AutonomousNotificationRead {
	return {
		id,
		user_id: 'user',
		session_id: 'session',
		channel: 'in_app',
		title: id,
		body: id,
		payload: null,
		read_at: null,
		created_at: '2026-07-01T00:00:00Z',
		updated_at: '2026-07-01T00:00:00Z'
	};
}
function page(ids: string[], total = ids.length): AutonomousNotificationListResponse {
	return { notifications: ids.map(note), total_count: total, limit: 10, offset: 0 };
}
function client() {
	return {
		listNotifications: vi.fn<
			Parameters<BellApi['listNotifications']>,
			ReturnType<BellApi['listNotifications']>
		>(),
		readNotification: vi.fn<
			Parameters<BellApi['readNotification']>,
			ReturnType<BellApi['readNotification']>
		>()
	};
}

describe('notification bell requests and actions', () => {
	it('distinguishes pending, failed, retried and confirmed-empty loads', async () => {
		const api = client();
		api.listNotifications
			.mockRejectedValueOnce(new Error('offline'))
			.mockResolvedValueOnce(page([]));
		const bell = createNotificationBell(api);
		expect(get(bell).status).toBe('loading');
		await bell.refresh();
		expect(get(bell).status).toBe('error');
		await bell.refresh();
		expect(get(bell).status).toBe('ready');
		expect(get(bell).items).toEqual([]);
		expect(api.listNotifications).toHaveBeenLastCalledWith(true, 10);
	});

	it('ignores an older success after a newer navigation response', async () => {
		const api = client();
		const old = deferred<AutonomousNotificationListResponse>();
		const fresh = deferred<AutonomousNotificationListResponse>();
		api.listNotifications.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
		const bell = createNotificationBell(api);
		const first = bell.refresh();
		const second = bell.refresh();
		fresh.resolve(page(['new'], 25));
		await second;
		old.resolve(page(['old'], 99));
		await first;
		expect(get(bell).items.map((n) => n.id)).toEqual(['new']);
		expect(get(bell).unreadCount).toBe(25);
	});

	it('ignores an older error after a newer successful response', async () => {
		const api = client();
		const old = deferred<AutonomousNotificationListResponse>();
		api.listNotifications.mockReturnValueOnce(old.promise).mockResolvedValueOnce(page(['new']));
		const bell = createNotificationBell(api);
		const first = bell.refresh();
		await bell.refresh();
		old.reject(new Error('old failure'));
		await first;
		expect(get(bell).status).toBe('ready');
	});

	it('does not restore an item when a pre-read GET resolves after the POST', async () => {
		const api = client();
		const old = deferred<AutonomousNotificationListResponse>();
		const fresh = deferred<AutonomousNotificationListResponse>();
		api.listNotifications
			.mockResolvedValueOnce(page(['a', 'b']))
			.mockReturnValueOnce(old.promise)
			.mockReturnValueOnce(fresh.promise);
		api.readNotification.mockResolvedValue(note('a'));
		const bell = createNotificationBell(api);
		await bell.refresh();
		const staleLoad = bell.refresh();
		const read = bell.markRead('a');
		await vi.waitFor(() => expect(api.listNotifications).toHaveBeenCalledTimes(3));
		old.resolve(page(['a', 'b']));
		await staleLoad;
		expect(get(bell).items.map((n) => n.id)).toEqual(['b']);
		fresh.resolve(page(['b']));
		await read;
		expect(get(bell).unreadCount).toBe(1);
	});

	it('refills the ten-item page after a successful individual read', async () => {
		const ids = Array.from({ length: 11 }, (_, i) => `n${i}`);
		const api = client();
		api.listNotifications
			.mockResolvedValueOnce(page(ids.slice(0, 10), 11))
			.mockResolvedValueOnce(page(ids.slice(1), 10));
		api.readNotification.mockResolvedValue(note('n0'));
		const bell = createNotificationBell(api);
		await bell.refresh();
		await bell.markRead('n0');
		expect(get(bell).items.map((n) => n.id)).toEqual(ids.slice(1));
		expect(get(bell).unreadCount).toBe(10);
		expect(get(bell).status).toBe('ready');
	});

	it('keeps failed reads visible with an actionable error', async () => {
		const api = client();
		api.listNotifications.mockResolvedValue(page(['a']));
		api.readNotification.mockRejectedValue(new Error('offline'));
		const bell = createNotificationBell(api);
		await bell.refresh();
		await bell.markRead('a');
		expect(get(bell).items.map((n) => n.id)).toEqual(['a']);
		expect(get(bell).unreadCount).toBe(1);
		expect(get(bell).actionError).toContain('try again');
		expect(get(bell).pendingIds.size).toBe(0);
	});

	it('marks only the shown page and preserves failed/off-page items', async () => {
		const api = client();
		const ids = Array.from({ length: 12 }, (_, i) => `n${i}`);
		api.listNotifications
			.mockResolvedValueOnce(page(ids.slice(0, 10), 12))
			.mockResolvedValueOnce(page(['n1', 'n10', 'n11'], 3));
		api.readNotification.mockImplementation((id) =>
			id === 'n1' ? Promise.reject(new Error('offline')) : Promise.resolve(note(id))
		);
		const bell = createNotificationBell(api);
		await bell.refresh();
		await bell.markShownRead();
		expect(api.readNotification).toHaveBeenCalledTimes(10);
		expect(api.readNotification).not.toHaveBeenCalledWith('n10');
		expect(get(bell).items.map((n) => n.id)).toEqual(['n1', 'n10', 'n11']);
		expect(get(bell).unreadCount).toBe(3);
		expect(get(bell).actionError).toContain('1 notification');
		expect(get(bell).markingAll).toBe(false);
	});

	it('coalesces duplicate reads and prevents bulk overlap with a pending row', async () => {
		const api = client();
		const post = deferred<AutonomousNotificationRead>();
		api.listNotifications.mockResolvedValue(page(['a']));
		api.readNotification.mockReturnValue(post.promise);
		const bell = createNotificationBell(api);
		await bell.refresh();
		const read = bell.markRead('a');
		await bell.markRead('a');
		await bell.markShownRead();
		expect(api.readNotification).toHaveBeenCalledTimes(1);
		post.resolve(note('a'));
		await read;
	});

	it('ignores loads after the bell is destroyed during a session change', async () => {
		const api = client();
		const load = deferred<AutonomousNotificationListResponse>();
		api.listNotifications.mockReturnValue(load.promise);
		const bell = createNotificationBell(api);
		const loading = bell.refresh();
		bell.destroy();
		load.resolve(page(['previous-user']));
		await loading;
		expect(get(bell).items).toEqual([]);
		await bell.refresh();
		expect(api.listNotifications).toHaveBeenCalledTimes(1);
	});

	it('does not refresh after a pending mutation completes on a destroyed bell', async () => {
		const api = client();
		const post = deferred<AutonomousNotificationRead>();
		api.listNotifications.mockResolvedValue(page(['a']));
		api.readNotification.mockReturnValue(post.promise);
		const bell = createNotificationBell(api);
		await bell.refresh();
		const read = bell.markRead('a');
		bell.destroy();
		post.resolve(note('a'));
		await read;
		expect(api.listNotifications).toHaveBeenCalledTimes(1);
	});
});
