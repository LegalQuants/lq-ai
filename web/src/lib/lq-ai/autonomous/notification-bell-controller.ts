/** Async state for the shell bell: current responses win, read actions refill the page. */
import { get, writable } from 'svelte/store';
import type {
	AutonomousNotificationListResponse,
	AutonomousNotificationRead
} from '../api/autonomous';
import { afterMarkAllRead, afterMarkRead, type BellState } from './notification-bell';

export interface BellApi {
	listNotifications: (
		unread: boolean,
		limit: number
	) => Promise<AutonomousNotificationListResponse>;
	readNotification: (id: string) => Promise<AutonomousNotificationRead>;
}

export interface BellSnapshot extends BellState {
	status: 'loading' | 'ready' | 'error';
	pendingIds: Set<string>;
	markingAll: boolean;
	actionError: string | null;
}

export function createNotificationBell(api: BellApi) {
	const store = writable<BellSnapshot>({
		items: [],
		unreadCount: 0,
		status: 'loading',
		pendingIds: new Set(),
		markingAll: false,
		actionError: null
	});
	let generation = 0;
	let disposed = false;

	async function refresh(): Promise<void> {
		if (disposed) return;
		const request = ++generation;
		store.update((s) => ({ ...s, status: 'loading' }));
		try {
			const result = await api.listNotifications(true, 10);
			if (disposed || request !== generation) return;
			store.update((s) => ({
				...s,
				items: result.notifications,
				unreadCount: result.total_count,
				status: 'ready'
			}));
		} catch {
			if (!disposed && request === generation) store.update((s) => ({ ...s, status: 'error' }));
		}
	}

	async function markRead(id: string): Promise<void> {
		const current = get(store);
		if (disposed || current.markingAll || current.pendingIds.has(id)) return;
		store.update((s) => ({ ...s, pendingIds: new Set(s.pendingIds).add(id), actionError: null }));
		try {
			await api.readNotification(id);
			if (disposed) return;
			++generation; // Invalidate every GET begun before this successful mutation.
			store.update((s) => ({ ...s, ...afterMarkRead(s, id) }));
			await refresh();
		} catch {
			if (!disposed)
				store.update((s) => ({
					...s,
					actionError: 'Could not mark notification as read. Please try again.'
				}));
		} finally {
			if (!disposed)
				store.update((s) => {
					const pendingIds = new Set(s.pendingIds);
					pendingIds.delete(id);
					return { ...s, pendingIds };
				});
		}
	}

	async function markShownRead(): Promise<void> {
		const current = get(store);
		if (disposed || current.markingAll || current.pendingIds.size > 0 || current.items.length === 0)
			return;
		const ids = current.items.map((n) => n.id);
		store.update((s) => ({ ...s, markingAll: true, actionError: null }));
		try {
			const results = await Promise.allSettled(ids.map((id) => api.readNotification(id)));
			if (disposed) return;
			const succeeded = ids.filter((_, i) => results[i].status === 'fulfilled');
			const failed = ids.length - succeeded.length;
			++generation;
			store.update((s) => ({
				...s,
				...afterMarkAllRead(s, succeeded),
				actionError: failed
					? `${failed} notification${failed === 1 ? '' : 's'} could not be marked read. Please try again.`
					: null
			}));
			await refresh();
		} finally {
			if (!disposed) store.update((s) => ({ ...s, markingAll: false }));
		}
	}

	return {
		subscribe: store.subscribe,
		refresh,
		markRead,
		markShownRead,
		destroy() {
			disposed = true;
			++generation;
		}
	};
}
