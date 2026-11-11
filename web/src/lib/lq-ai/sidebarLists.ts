/**
 * Recent matters with their chats, then other chats, for the left sidebar of
 * the redesigned LQ.AI shell (interface-redesign work plan, Annex B P1.3b;
 * C10).
 *
 * Data comes from the existing list endpoints, two requests per refresh:
 * `GET /projects` (active matters; the per-user sandbox is excluded by the
 * server) and one page of `GET /chats` (the caller's own chats, newest
 * first). Chats are grouped by `project_id` here. The server orders both by
 * creation, so recency is re-sorted on `updated_at`.
 *
 * Refreshes happen on mount, after navigation (at most once per
 * `MIN_REFRESH_MS`, no polling) and on Retry. Chats the open chat page
 * already knows (the shell's `chatsStore`, updated on create, rename and
 * archive) are merged in, so a new or renamed chat shows without a request.
 */
import { get, writable } from 'svelte/store';

import type { Chat, PaginatedChats, Project } from './types';

/** How much the sidebar lists. "All matters" and "All chats" lead to the rest. */
export const SIDEBAR_CAPS = { matters: 5, chatsPerMatter: 3, otherChats: 5 } as const;
/** One page of the caller's chats; enough to fill the caps in practice. */
export const SIDEBAR_CHAT_PAGE = 50;
/** Navigation refreshes at most this often. */
export const MIN_REFRESH_MS = 30_000;

export type SidebarCaps = { matters: number; chatsPerMatter: number; otherChats: number };

export interface SidebarMatter {
	project: Project;
	chats: Chat[];
}

export interface SidebarLists {
	matters: SidebarMatter[];
	otherChats: Chat[];
}

const byRecent = (a: { updated_at: string }, b: { updated_at: string }) =>
	b.updated_at.localeCompare(a.updated_at);

/** Fetched chats with the live ones laid over them (the live copy wins). */
export function mergeChats(fetched: readonly Chat[], live: readonly Chat[]): Chat[] {
	const byId = new Map<string, Chat>();
	for (const chat of fetched) byId.set(chat.id, chat);
	for (const chat of live) byId.set(chat.id, chat);
	return [...byId.values()];
}

/**
 * Group and cap. Matters are ordered by their latest activity (the matter's
 * own `updated_at` or its newest chat's, whichever is later); each lists its
 * newest chats. Other chats are those outside any matter. Archived chats and
 * archived or sandbox matters are left out, and a chat whose matter is not in
 * the list (a sandbox, an archived matter) is not shown as an "other" chat.
 */
export function shapeSidebarLists(
	projects: readonly Project[],
	chats: readonly Chat[],
	caps: SidebarCaps = SIDEBAR_CAPS
): SidebarLists {
	const live = chats.filter((c) => !c.archived_at);
	const byProject = new Map<string, Chat[]>();
	const other: Chat[] = [];
	for (const chat of live) {
		if (!chat.project_id) other.push(chat);
		else {
			const list = byProject.get(chat.project_id) ?? [];
			list.push(chat);
			byProject.set(chat.project_id, list);
		}
	}
	const activity = (p: Project) => {
		const newest = (byProject.get(p.id) ?? []).reduce(
			(max, c) => (c.updated_at > max ? c.updated_at : max),
			''
		);
		return newest > p.updated_at ? newest : p.updated_at;
	};
	const matters = projects
		.filter((p) => !p.archived_at && !p.is_sandbox)
		.map((p) => ({ project: p, at: activity(p) }))
		.sort((a, b) => b.at.localeCompare(a.at))
		.slice(0, caps.matters)
		.map(({ project }) => ({
			project,
			chats: [...(byProject.get(project.id) ?? [])].sort(byRecent).slice(0, caps.chatsPerMatter)
		}));
	return { matters, otherChats: other.sort(byRecent).slice(0, caps.otherChats) };
}

/** The matter and chat the current page shows, for `aria-current`. */
export function currentSidebarRows(
	pathname: string,
	urlChatId: string | null,
	activeChatId: string | null
): { matterId: string | null; chatId: string | null } {
	const matter = /^\/lq-ai\/matters\/([^/]+)\/?$/.exec(pathname);
	if (matter) return { matterId: decodeURIComponent(matter[1]), chatId: activeChatId };
	if (pathname === '/lq-ai/chats' || pathname === '/lq-ai/chats/')
		return { matterId: null, chatId: activeChatId ?? urlChatId };
	return { matterId: null, chatId: null };
}

/** Whether a listed row is current, so "All matters" / "All chats" should not also claim it. */
export function listClaimsCurrent(
	lists: SidebarLists,
	current: { matterId: string | null; chatId: string | null }
): { matters: boolean; chats: boolean } {
	const matterChats = lists.matters.flatMap((m) => m.chats);
	return {
		matters: lists.matters.some((m) => m.project.id === current.matterId),
		chats:
			current.chatId !== null &&
			[...matterChats, ...lists.otherChats].some((c) => c.id === current.chatId)
	};
}

export interface SidebarListsApi {
	listProjects: () => Promise<Project[]>;
	listChats: (opts: { limit: number }) => Promise<PaginatedChats>;
}

export interface SidebarListsState {
	status: 'idle' | 'loading' | 'ready' | 'error';
	projects: Project[];
	chats: Chat[];
	/** When the last successful load finished (ms), for the navigation throttle. */
	loadedAt: number | null;
	/** Whose lists these are (the signed-in person's id); undefined before anyone. */
	user?: string | null;
}

const EMPTY: SidebarListsState = { status: 'idle', projects: [], chats: [], loadedAt: null };

/**
 * The lists' async state. A failed refresh keeps what was last loaded (the
 * sidebar stays usable) and reports `error`; responses that arrive after a
 * newer request, or after a reset, are dropped.
 */
export function createSidebarLists(api: SidebarListsApi, now: () => number = Date.now) {
	const store = writable<SidebarListsState>({ ...EMPTY });
	let generation = 0;

	async function refresh(opts: { force?: boolean } = {}): Promise<void> {
		const current = get(store);
		if (current.status === 'loading' && !opts.force) return;
		if (
			!opts.force &&
			current.status === 'ready' &&
			current.loadedAt !== null &&
			now() - current.loadedAt < MIN_REFRESH_MS
		)
			return;
		const request = ++generation;
		store.update((s) => ({ ...s, status: 'loading' }));
		try {
			const [projects, page] = await Promise.all([
				api.listProjects(),
				api.listChats({ limit: SIDEBAR_CHAT_PAGE })
			]);
			if (request !== generation) return;
			store.update((s) => ({
				...s,
				status: 'ready',
				projects,
				chats: page.items,
				loadedAt: now()
			}));
		} catch {
			if (request === generation) store.update((s) => ({ ...s, status: 'error' }));
		}
	}

	return {
		subscribe: store.subscribe,
		refresh,
		/** Forget everything (another person signed in); in-flight responses are dropped. */
		reset(): void {
			++generation;
			store.set({ ...EMPTY });
		},
		/**
		 * The signed-in person. A different person empties the lists at once (the
		 * shared instance outlives the sidebar across sign-out and sign-in), drops
		 * any response still in flight, and loads theirs.
		 */
		forUser(user: string | null): void {
			if (get(store).user === user) return;
			++generation;
			store.set({ ...EMPTY, user });
			if (user) void refresh({ force: true });
		},
		/** Set the state directly (server-side render tests). */
		seed(state: Partial<SidebarListsState>): void {
			++generation;
			store.set({ ...EMPTY, status: 'ready', ...state });
		}
	};
}

export type SidebarListsController = ReturnType<typeof createSidebarLists>;
