/**
 * Refresh across tabs. Tabs share one stored session, but each holds its own
 * copy in memory; once one tab refreshes, the refresh token the others hold is
 * revoked. The store only touches `localStorage` in a browser, so this file
 * stands one up before the modules load.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const storage = vi.hoisted(() => {
	const data = new Map<string, string>();
	const localStorage = {
		getItem: (key: string) => data.get(key) ?? null,
		setItem: (key: string, value: string) => {
			data.set(key, String(value));
		},
		removeItem: (key: string) => {
			data.delete(key);
		},
		clear: () => data.clear()
	};
	Object.assign(globalThis, { window: { localStorage }, localStorage });
	return localStorage;
});

import { apiRequest, LQ_AI_API_BASE_URL } from '../api/client';
import { clearSession, getAccessToken, getRefreshToken, setSession } from '../auth/store';
import type { User } from '../types';

const STORAGE_KEY = 'lq_ai_auth';
const realFetch = global.fetch;

function user(id: string): User {
	return {
		id,
		email: `${id}@lq.ai`,
		is_admin: false,
		mfa_enabled: false,
		must_change_password: false,
		created_at: '2025-01-01T00:00:00Z'
	};
}

/**
 * What another tab writes: after its own refresh, a session that expires
 * later than this tab's (`expiresInMs` past this tab's 15 minutes); when it
 * only caches the user, the older session it holds (a negative offset).
 */
function anotherTabStores(
	access_token: string,
	refresh_token: string,
	owner: User,
	expiresInMs = 60_000
): void {
	storage.setItem(
		STORAGE_KEY,
		JSON.stringify({
			access_token,
			refresh_token,
			expires_at: Date.now() + 900_000 + expiresInMs,
			user: owner
		})
	);
}

function json(status: number, body: unknown): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});
}

/** Accepts only `a1`; counts refresh calls, answering each with `onRefresh`. */
function backend(onRefresh: () => Response) {
	let refreshes = 0;
	const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
		const path = String(url).replace(LQ_AI_API_BASE_URL, '');
		if (path === '/auth/refresh') {
			refreshes += 1;
			return onRefresh();
		}
		const bearer = (init?.headers as Record<string, string> | undefined)?.Authorization;
		return bearer === 'Bearer a1'
			? json(200, { path })
			: json(401, { detail: { code: 'unauthorized', message: 'expired' } });
	});
	return { fetchImpl, refreshes: () => refreshes };
}

describe('refresh across tabs', () => {
	beforeEach(() => {
		clearSession();
		storage.clear();
	});

	afterEach(() => {
		global.fetch = realFetch;
	});

	it('takes the session another tab stored instead of spending a revoked token', async () => {
		setSession({ access_token: 'a0', refresh_token: 'r0', expires_in: 900, user: user('u') });
		anotherTabStores('a1', 'r1', user('u'));
		const server = backend(() => json(401, { detail: 'Invalid refresh token' }));
		global.fetch = server.fetchImpl as unknown as typeof fetch;

		const out = await apiRequest<{ path: string }>('/projects');

		expect(out.path).toBe('/projects');
		expect(server.refreshes()).toBe(0);
		expect(getAccessToken()).toBe('a1');
		expect(getRefreshToken()).toBe('r1');
	});

	it('keeps the session another tab stored while the refresh here was refused', async () => {
		// Without Web Locks two tabs can refresh with the same token at once.
		setSession({ access_token: 'a0', refresh_token: 'r0', expires_in: 900, user: user('u') });
		const server = backend(() => {
			anotherTabStores('a1', 'r1', user('u'));
			return json(401, { detail: 'Invalid refresh token' });
		});
		global.fetch = server.fetchImpl as unknown as typeof fetch;

		const out = await apiRequest<{ path: string }>('/projects');

		expect(out.path).toBe('/projects');
		expect(server.refreshes()).toBe(1);
		expect(getAccessToken()).toBe('a1');
	});

	it('never takes an older session a stale tab wrote back', async () => {
		setSession({ access_token: 'a0', refresh_token: 'r0', expires_in: 900, user: user('u') });
		anotherTabStores('a-stale', 'r-stale', user('u'), -600_000);
		const server = backend(() =>
			json(200, { access_token: 'a1', refresh_token: 'r1', token_type: 'Bearer', expires_in: 900 })
		);
		global.fetch = server.fetchImpl as unknown as typeof fetch;

		const out = await apiRequest<{ path: string }>('/projects');

		expect(out.path).toBe('/projects');
		expect(server.refreshes()).toBe(1);
		expect(getRefreshToken()).toBe('r1');
	});

	it('never takes a session stored for a different user', async () => {
		setSession({ access_token: 'a0', refresh_token: 'r0', expires_in: 900, user: user('u') });
		anotherTabStores('a1', 'r1', user('someone-else'));
		const server = backend(() => json(401, { detail: 'Invalid refresh token' }));
		global.fetch = server.fetchImpl as unknown as typeof fetch;

		await expect(apiRequest('/projects')).rejects.toMatchObject({ status: 401 });

		expect(server.refreshes()).toBe(1);
		expect(getAccessToken()).toBeNull();
	});
});
