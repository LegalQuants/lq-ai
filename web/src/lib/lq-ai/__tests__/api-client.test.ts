/**
 * Unit tests for the LQ.AI API client's auth-attachment + refresh-on-401
 * behaviour. We mock global `fetch` and assert the wire calls.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
	apiRequest,
	apiStreamRequest,
	LQ_AI_API_BASE_URL,
	LQAIApiError,
	PasswordChangeRequiredError,
	refreshSession,
	UnauthorizedError
} from '../api/client';
import { clearSession, setSession, getAccessToken, getRefreshToken } from '../auth/store';

const realFetch = global.fetch;

function mockResponse(
	status: number,
	body: unknown,
	{ contentType = 'application/json' }: { contentType?: string } = {}
): Response {
	const headers = new Headers({ 'content-type': contentType });
	const stringBody =
		contentType.includes('json') && body !== undefined ? JSON.stringify(body) : (body as string);
	return new Response(stringBody, { status, headers });
}

function bearerOf(init?: RequestInit): string {
	return (init?.headers as Record<string, string> | undefined)?.Authorization ?? '';
}

/**
 * A backend that rotates refresh tokens the way /auth/refresh does: each
 * refresh token works once and is refused after that. Access tokens it
 * issued are accepted; any other token gets a 401.
 */
function rotatingBackend(liveRefreshToken: string) {
	let live: string | null = liveRefreshToken;
	let issued = 0;
	const accepted = new Set<string>();
	const paths: string[] = [];
	const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
		const path = String(url).replace(LQ_AI_API_BASE_URL, '');
		paths.push(path);
		if (path === '/auth/refresh') {
			const { refresh_token } = JSON.parse(String(init?.body)) as { refresh_token: string };
			if (refresh_token !== live) {
				return mockResponse(401, { detail: 'Invalid refresh token' });
			}
			issued += 1;
			live = `r${issued}`;
			accepted.add(`a${issued}`);
			return mockResponse(200, {
				access_token: `a${issued}`,
				refresh_token: live,
				token_type: 'Bearer',
				expires_in: 900
			});
		}
		return accepted.has(bearerOf(init).replace('Bearer ', ''))
			? mockResponse(200, { path })
			: mockResponse(401, { detail: { code: 'unauthorized', message: 'expired' } });
	});
	return {
		fetchImpl,
		refreshes: () => paths.filter((p) => p === '/auth/refresh').length,
		revokeAll: () => {
			live = null;
		}
	};
}

describe('apiRequest', () => {
	beforeEach(() => {
		clearSession();
		vi.restoreAllMocks();
	});

	afterEach(() => {
		global.fetch = realFetch;
	});

	it('attaches the Authorization header when a token is set', async () => {
		setSession({ access_token: 'tok', expires_in: 900 });
		const fetchSpy = vi.fn(async () => mockResponse(200, { ok: true }));
		global.fetch = fetchSpy as unknown as typeof fetch;

		await apiRequest('/users/me');
		expect(fetchSpy).toHaveBeenCalledTimes(1);
		const call = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
		const init = call[1];
		const headers = init.headers as Record<string, string>;
		expect(headers.Authorization).toBe('Bearer tok');
	});

	it('throws UnauthorizedError on 401 with no refresh token', async () => {
		setSession({ access_token: 'tok', expires_in: 900 });
		const fetchSpy = vi.fn(async () =>
			mockResponse(401, { detail: { code: 'unauthorized', message: 'no' } })
		);
		global.fetch = fetchSpy as unknown as typeof fetch;

		await expect(apiRequest('/users/me')).rejects.toBeInstanceOf(UnauthorizedError);
		// Session was cleared because refresh failed (no refresh token).
		expect(getAccessToken()).toBeNull();
	});

	it('refreshes once on 401 then retries the original request', async () => {
		setSession({ access_token: 'tok', refresh_token: 'rtok', expires_in: 900 });
		const responses: Response[] = [
			// initial 401 from /users/me
			mockResponse(401, { detail: { code: 'unauthorized', message: 'expired' } }),
			// refresh succeeds
			mockResponse(200, {
				access_token: 'newtok',
				refresh_token: 'newrtok',
				token_type: 'Bearer',
				expires_in: 900
			}),
			// retry of /users/me succeeds
			mockResponse(200, { id: 'u', email: 'a@b' })
		];
		const fetchSpy = vi.fn(async () => responses.shift() as Response);
		global.fetch = fetchSpy as unknown as typeof fetch;

		const out = await apiRequest<{ id: string }>('/users/me');
		expect(out.id).toBe('u');
		expect(fetchSpy).toHaveBeenCalledTimes(3);
		expect(getAccessToken()).toBe('newtok');
	});

	it('throws PasswordChangeRequiredError on 403 with that code', async () => {
		setSession({ access_token: 'tok', expires_in: 900 });
		const fetchSpy = vi.fn(async () =>
			mockResponse(403, {
				detail: { code: 'password_change_required', message: 'rotate' }
			})
		);
		global.fetch = fetchSpy as unknown as typeof fetch;

		await expect(apiRequest('/projects')).rejects.toBeInstanceOf(PasswordChangeRequiredError);
	});

	it('returns undefined on 204 No Content', async () => {
		setSession({ access_token: 'tok', expires_in: 900 });
		const fetchSpy = vi.fn(async () => new Response(null, { status: 204 }));
		global.fetch = fetchSpy as unknown as typeof fetch;

		const out = await apiRequest('/auth/logout', { method: 'POST' });
		expect(out).toBeUndefined();
	});

	it('serialises JSON bodies and sets Content-Type', async () => {
		setSession({ access_token: 'tok', expires_in: 900 });
		const fetchSpy = vi.fn(async () => mockResponse(200, { id: 'p' }));
		global.fetch = fetchSpy as unknown as typeof fetch;

		await apiRequest('/projects', { method: 'POST', body: { name: 'P' } });
		const call = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
		const init = call[1];
		expect(init.body).toBe(JSON.stringify({ name: 'P' }));
		const headers = init.headers as Record<string, string>;
		expect(headers['Content-Type']).toBe('application/json');
	});

	it('translates 4xx with a typed code into LQAIApiError carrying the code', async () => {
		setSession({ access_token: 'tok', expires_in: 900 });
		const fetchSpy = vi.fn(async () =>
			mockResponse(400, { detail: { code: 'skill_input_missing', message: 'missing' } })
		);
		global.fetch = fetchSpy as unknown as typeof fetch;

		try {
			await apiRequest('/chats/abc/messages', { method: 'POST', body: {} });
			throw new Error('expected throw');
		} catch (e) {
			expect(e).toBeInstanceOf(LQAIApiError);
			expect((e as LQAIApiError).code).toBe('skill_input_missing');
			expect((e as LQAIApiError).status).toBe(400);
		}
	});

	it('surfaces the string detail message from { "detail": "string" } FastAPI shape (DE-261)', async () => {
		// This is the plain HTTPException shape FastAPI produces when `detail` is a
		// plain string (e.g. `raise HTTPException(status_code=422, detail="slug taken")`).
		// Previously errorFor returned "Unknown error" because it assumed detail was always
		// an object with .code / .message properties.
		setSession({ access_token: 'tok', expires_in: 900 });
		const fetchSpy = vi.fn(async () =>
			mockResponse(422, { detail: "slug 'my-skill' is already used by another of your skills" })
		);
		global.fetch = fetchSpy as unknown as typeof fetch;

		try {
			await apiRequest('/user-skills', { method: 'POST', body: {} });
			throw new Error('expected throw');
		} catch (e) {
			expect(e).toBeInstanceOf(LQAIApiError);
			expect((e as LQAIApiError).status).toBe(422);
			expect((e as LQAIApiError).message).toContain("slug 'my-skill' is already used");
		}
	});

	it('surfaces the msg field from Pydantic ValidationError array detail shape', async () => {
		// FastAPI 422 from Pydantic field validation: detail is an array of { msg, type, loc }.
		setSession({ access_token: 'tok', expires_in: 900 });
		const fetchSpy = vi.fn(async () =>
			mockResponse(422, {
				detail: [{ msg: 'value is not a valid uuid', type: 'uuid_parsing', loc: ['body', 'id'] }]
			})
		);
		global.fetch = fetchSpy as unknown as typeof fetch;

		try {
			await apiRequest('/projects', { method: 'POST', body: {} });
			throw new Error('expected throw');
		} catch (e) {
			expect(e).toBeInstanceOf(LQAIApiError);
			expect((e as LQAIApiError).status).toBe(422);
			expect((e as LQAIApiError).message).toBe('value is not a valid uuid');
		}
	});
});

describe('shared refresh', () => {
	beforeEach(() => {
		clearSession();
		vi.restoreAllMocks();
	});

	afterEach(() => {
		global.fetch = realFetch;
		vi.unstubAllGlobals();
	});

	it('spends the refresh token once when requests hit 401 together', async () => {
		// After an upgrade that invalidates every access token, a page's first
		// requests all 401 at once. A second refresh with the same token is
		// refused, and that refusal used to clear the session the first one stored.
		setSession({ access_token: 'old', refresh_token: 'r0', expires_in: 900 });
		const backend = rotatingBackend('r0');
		global.fetch = backend.fetchImpl as unknown as typeof fetch;

		const results = await Promise.all([
			apiRequest<{ path: string }>('/users/me'),
			apiRequest<{ path: string }>('/users/me/preferences'),
			apiRequest<{ path: string }>('/projects')
		]);

		expect(results.map((r) => r.path)).toEqual(['/users/me', '/users/me/preferences', '/projects']);
		expect(backend.refreshes()).toBe(1);
		expect(getAccessToken()).toBe('a1');
		expect(getRefreshToken()).toBe('r1');
	});

	it('shares the refresh with a streaming request', async () => {
		setSession({ access_token: 'old', refresh_token: 'r0', expires_in: 900 });
		const backend = rotatingBackend('r0');
		global.fetch = backend.fetchImpl as unknown as typeof fetch;

		const [json, stream] = await Promise.all([
			apiRequest<{ path: string }>('/users/me'),
			apiStreamRequest('/chats/c/messages', { method: 'POST', body: {} })
		]);

		expect(json.path).toBe('/users/me');
		expect(stream.status).toBe(200);
		expect(backend.refreshes()).toBe(1);
	});

	it('retries without refreshing when a refresh landed while the request was out', async () => {
		setSession({ access_token: 'old', refresh_token: 'r0', expires_in: 900 });
		const backend = rotatingBackend('r0');
		let release: () => void = () => undefined;
		const held = new Promise<void>((resolve) => {
			release = resolve;
		});
		global.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
			if (String(url).endsWith('/slow') && bearerOf(init) === 'Bearer old') {
				await held;
			}
			return backend.fetchImpl(url, init);
		}) as typeof fetch;

		const slow = apiRequest<{ path: string }>('/slow');
		await apiRequest('/users/me');
		release();

		expect((await slow).path).toBe('/slow');
		expect(backend.refreshes()).toBe(1);
		expect(getRefreshToken()).toBe('r1');
	});

	it('shares the refresh the activity tracker starts', async () => {
		setSession({ access_token: 'old', refresh_token: 'r0', expires_in: 900 });
		const backend = rotatingBackend('r0');
		global.fetch = backend.fetchImpl as unknown as typeof fetch;

		const [renewed, me] = await Promise.all([
			refreshSession(),
			apiRequest<{ path: string }>('/users/me')
		]);

		expect(renewed).toBe(true);
		expect(me.path).toBe('/users/me');
		expect(backend.refreshes()).toBe(1);
	});

	it('signs out once when the refresh token is refused', async () => {
		setSession({ access_token: 'old', refresh_token: 'r0', expires_in: 900 });
		const backend = rotatingBackend('r0');
		backend.revokeAll();
		global.fetch = backend.fetchImpl as unknown as typeof fetch;

		const outcomes = await Promise.allSettled([apiRequest('/users/me'), apiRequest('/projects')]);

		for (const outcome of outcomes) {
			expect(outcome.status).toBe('rejected');
			expect((outcome as PromiseRejectedResult).reason).toBeInstanceOf(UnauthorizedError);
		}
		expect(backend.refreshes()).toBe(1);
		expect(getAccessToken()).toBeNull();
	});

	it('keeps the session and reports the failure when the activity refresh gets a 503', async () => {
		// /auth/refresh refuses a token only with a 401. A 503 says nothing
		// about the session, so a click during an outage must not sign out.
		setSession({ access_token: 'tok', refresh_token: 'r0', expires_in: 900 });
		global.fetch = (async () =>
			mockResponse(503, { detail: 'upstream unavailable' })) as unknown as typeof fetch;

		await expect(refreshSession()).rejects.toMatchObject({ status: 503 });

		expect(getAccessToken()).toBe('tok');
		expect(getRefreshToken()).toBe('r0');
	});

	it('surfaces a 429 from the refresh after a 401 and keeps the session', async () => {
		setSession({ access_token: 'old', refresh_token: 'r0', expires_in: 900 });
		global.fetch = (async (url: string | URL | Request) =>
			String(url).endsWith('/auth/refresh')
				? mockResponse(429, { detail: 'slow down' })
				: mockResponse(401, {
						detail: { code: 'unauthorized', message: 'expired' }
					})) as unknown as typeof fetch;

		await expect(apiRequest('/projects')).rejects.toMatchObject({ status: 429 });

		expect(getAccessToken()).toBe('old');
		expect(getRefreshToken()).toBe('r0');
	});

	it('queues the refresh behind other tabs with the Web Locks API when the browser has it', async () => {
		setSession({ access_token: 'old', refresh_token: 'r0', expires_in: 900 });
		const backend = rotatingBackend('r0');
		global.fetch = backend.fetchImpl as unknown as typeof fetch;
		const request = vi.fn((_name: string, callback: () => Promise<boolean>) => callback());
		vi.stubGlobal('navigator', { locks: { request } });

		await apiRequest('/users/me');

		expect(request).toHaveBeenCalledOnce();
		expect(request.mock.calls[0][0]).toBe('lq_ai_refresh');
		expect(backend.refreshes()).toBe(1);
	});
});
