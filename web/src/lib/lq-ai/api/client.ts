/**
 * Base HTTP client for the LQ.AI backend.
 *
 * - Attaches `Authorization: Bearer <access_token>` to every request once a
 *   session is established.
 * - On 401, attempts a single refresh-and-retry; on a second 401 the session
 *   is cleared and the caller is expected to redirect to login. Requests that
 *   hit 401 together share one refresh (see `refreshSession`).
 * - On 403 with `code=password_change_required`, throws `PasswordChangeRequiredError`
 *   so the layout's gate can intercept and route to the change-password screen.
 * - All errors surface as typed exception subclasses; the response body's
 *   `detail.code` is preserved on the exception for downstream branching.
 */
import {
	adoptStoredSession,
	auth,
	clearSession,
	getAccessToken,
	getRefreshToken,
	setSession,
	tokenIsStale
} from '../auth/store';
import type { TokenResponse, ErrorBody } from '../types';
import { get } from 'svelte/store';

// Direct feature-detection so this module is portable to the vitest node
// runner without SvelteKit alias setup.
const browser =
	typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';

/**
 * Base URL for backend API calls.
 *
 * Production deployments front web + api at the same origin via a
 * reverse proxy and leave PUBLIC_LQ_AI_API_BASE_URL unset, so all calls
 * go to ``/api/v1`` on the same origin (no CORS needed).
 *
 * Local Compose dev needs an absolute URL because web (:3000) and api
 * (:8000) live at different origins. The operator's .env sets
 * PUBLIC_LQ_AI_API_BASE_URL=http://localhost:8000/api/v1; Vite bakes
 * it into the build via the PUBLIC_LQ_AI_API_BASE_URL build arg passed
 * through docker-compose.yml.
 */
// SvelteKit's dynamic-public env import. Unlike $env/static/public, the
// dynamic variant does not require the variable to be declared at build time,
// so CI svelte-check passes even when no .env is present. At runtime Vite
// (and the web Dockerfile build arg) still injects the value correctly.
//
// Production: PUBLIC_LQ_AI_API_BASE_URL is unset → defaults to /api/v1
// (same-origin behind a reverse proxy). Local Compose dev: set via
// .env to http://localhost:8000/api/v1.
import { env } from '$env/dynamic/public';

export const LQ_AI_API_BASE_URL: string = env.PUBLIC_LQ_AI_API_BASE_URL || '/api/v1';

export class LQAIApiError extends Error {
	readonly status: number;
	readonly code: string;
	readonly details: Record<string, unknown> | undefined;

	constructor(status: number, code: string, message: string, details?: Record<string, unknown>) {
		super(message);
		this.name = 'LQAIApiError';
		this.status = status;
		this.code = code;
		this.details = details;
	}
}

export class UnauthorizedError extends LQAIApiError {
	constructor(message = 'Not authenticated', details?: Record<string, unknown>) {
		super(401, 'unauthorized', message, details);
		this.name = 'UnauthorizedError';
	}
}

export class PasswordChangeRequiredError extends LQAIApiError {
	constructor(message = 'Password change required', details?: Record<string, unknown>) {
		super(403, 'password_change_required', message, details);
		this.name = 'PasswordChangeRequiredError';
	}
}

interface RequestOptions {
	method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
	body?: unknown;
	headers?: Record<string, string>;
	/** Skip auth header attachment (used by /auth/login + /auth/refresh). */
	skipAuth?: boolean;
	/** Skip the on-401 refresh-and-retry (used by /auth/refresh itself). */
	skipRefresh?: boolean;
	/** Override the `Accept` header (e.g., for SSE). */
	accept?: string;
	/** When true, expect a streaming response and return the raw `Response`. */
	stream?: boolean;
	/** Multipart form body; replaces `body`. */
	formData?: FormData;
	signal?: AbortSignal;
}

/**
 * Internal: perform a single HTTP request with auth header attachment and
 * structured error translation. Caller handles refresh / retry.
 */
async function rawRequest(path: string, options: RequestOptions): Promise<Response> {
	const headers: Record<string, string> = { ...(options.headers ?? {}) };

	if (options.formData) {
		// Browsers set the multipart Content-Type with boundary themselves.
	} else if (options.body !== undefined) {
		headers['Content-Type'] = headers['Content-Type'] ?? 'application/json';
	}

	if (options.accept) {
		headers['Accept'] = options.accept;
	}

	if (!options.skipAuth) {
		const token = getAccessToken();
		if (token) {
			headers['Authorization'] = `Bearer ${token}`;
		}
	}

	const init: RequestInit = {
		method: options.method ?? 'GET',
		headers,
		signal: options.signal
	};

	if (options.formData) {
		init.body = options.formData;
	} else if (options.body !== undefined) {
		init.body = JSON.stringify(options.body);
	}

	return fetch(`${LQ_AI_API_BASE_URL}${path}`, init);
}

/**
 * POST /auth/refresh with the refresh token in the store. Resolves `true` when
 * a new session is stored and `false` when the server refuses the token, which
 * it does only with a 401. Any other failure throws and leaves the session as
 * it is: a 502, 503 or 429 says nothing about whether the session is good.
 */
async function postRefresh(): Promise<boolean> {
	const refresh_token = getRefreshToken();
	if (!refresh_token) {
		return false;
	}
	const res = await rawRequest('/auth/refresh', {
		method: 'POST',
		body: { refresh_token },
		skipAuth: true,
		skipRefresh: true
	});
	if (res.status === 401) {
		return false;
	}
	if (!res.ok) {
		throw errorFor(res.status, await parseErrorBody(res));
	}
	const data = (await res.json()) as TokenResponse;
	setSession({
		access_token: data.access_token,
		refresh_token: data.refresh_token,
		expires_in: data.expires_in
	});
	return true;
}

async function refreshOnce(): Promise<boolean> {
	// Another tab may already have spent the refresh token this tab holds.
	// Its newer session replaces this one. If that session's access token has
	// expired too, the refresh below spends its refresh token instead.
	if (adoptStoredSession() && !tokenIsStale()) {
		return true;
	}
	if (await postRefresh()) {
		return true;
	}
	// Refused. Without Web Locks another tab can spend the same token first;
	// its session is then the one to keep, not a reason to sign out.
	if (adoptStoredSession() && (!tokenIsStale() || (await postRefresh()))) {
		return true;
	}
	clearSession();
	return false;
}

/**
 * The refresh in flight, if any. Refresh tokens rotate (PRD §5.1): the server
 * revokes a refresh token once it is spent and refuses it after that, so two
 * refreshes with the same token always leave one refused. A refused refresh
 * clears the session, so every caller waits on this one instead.
 */
let refreshInFlight: Promise<boolean> | null = null;

/**
 * Renew the access token, sharing one refresh among every caller in this tab
 * and, where the browser has the Web Locks API, queueing behind a refresh in
 * another tab. Clears the session when the refresh token is refused and
 * resolves `true` when a renewed session is in the store. Any other failure
 * rejects and leaves the session as it is.
 */
export function refreshSession(): Promise<boolean> {
	if (!refreshInFlight) {
		const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined;
		// The DOM typings return a promise of the callback's promise; the
		// browser settles it once, and `then` tells TypeScript so.
		const run = locks
			? locks.request('lq_ai_refresh', refreshOnce).then((renewed) => renewed)
			: refreshOnce();
		refreshInFlight = run.finally(() => {
			refreshInFlight = null;
		});
	}
	return refreshInFlight;
}

/**
 * After a 401, put a newer access token in the store: one a refresh stored
 * while this request was in flight, or else a shared refresh's. A different
 * token that is already stale is one taken from another tab and still being
 * renewed, so the request waits for that renewal instead of retrying with it.
 */
async function renewAfter401(sentToken: string | null): Promise<boolean> {
	const current = getAccessToken();
	if (current && current !== sentToken && !tokenIsStale()) {
		return true;
	}
	return refreshSession();
}

async function parseErrorBody(res: Response): Promise<ErrorBody | null> {
	try {
		return (await res.json()) as ErrorBody;
	} catch {
		return null;
	}
}

/**
 * Extract a human-readable error message + code from the three FastAPI
 * detail shapes:
 *
 *   1. String:   `{ "detail": "some message" }` — the common plain-text shape.
 *   2. Object:   `{ "detail": { "code": "...", "message": "...", "details": {} } }`
 *                — LQ.AI structured error shape.
 *   3. Array:    `{ "detail": [{ "msg": "...", "type": "...", "loc": [...] }] }`
 *                — Pydantic ValidationError shape (FastAPI 422 responses).
 *
 * Falls back to a generic "Request failed with status N" message when none of
 * the above shapes match.
 */
function errorFor(status: number, body: ErrorBody | null): LQAIApiError {
	const detail = body?.detail;

	let code = `http_${status}`;
	let message = `Request failed with status ${status}`;
	let details: Record<string, unknown> | undefined;

	if (detail !== null && detail !== undefined) {
		if (typeof detail === 'string') {
			// Shape 1: { "detail": "some message" }
			message = detail;
		} else if (Array.isArray(detail)) {
			// Shape 3: Pydantic ValidationError — [{ "msg": "...", ... }, ...]
			const first = detail[0];
			if (first && typeof first === 'object' && 'msg' in first) {
				message = String((first as { msg: unknown }).msg);
			}
		} else if (typeof detail === 'object') {
			// Shape 2: LQ.AI structured error — { "code": "...", "message": "...", ... }
			const d = detail as Record<string, unknown>;
			if (typeof d.code === 'string') code = d.code;
			if (typeof d.message === 'string') message = d.message;
			if (d.details && typeof d.details === 'object' && !Array.isArray(d.details)) {
				details = d.details as Record<string, unknown>;
			}
		}
	}

	if (status === 401) {
		return new UnauthorizedError(message, details);
	}
	if (status === 403 && code === 'password_change_required') {
		return new PasswordChangeRequiredError(message, details);
	}
	return new LQAIApiError(status, code, message, details);
}

/**
 * JSON request: serialize body, parse JSON response, throw typed errors on
 * non-2xx. Refresh-and-retry once on 401.
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
	const sentToken = getAccessToken();
	let res = await rawRequest(path, options);

	if (res.status === 401 && !options.skipRefresh && !options.skipAuth) {
		if (await renewAfter401(sentToken)) {
			res = await rawRequest(path, options);
		}
	}

	if (!res.ok) {
		const body = await parseErrorBody(res);
		const err = errorFor(res.status, body);
		if (err.status === 401) {
			clearSession();
		}
		throw err;
	}

	if (res.status === 204) {
		// No content
		return undefined as T;
	}

	const contentType = res.headers.get('content-type') ?? '';
	if (contentType.includes('application/json')) {
		return (await res.json()) as T;
	}
	return (await res.text()) as unknown as T;
}

/**
 * Streaming variant: returns the raw `Response` (after auth + refresh-on-401)
 * so the caller can iterate `res.body`. Throws on non-OK before any bytes
 * are returned.
 */
export async function apiStreamRequest(
	path: string,
	options: RequestOptions = {}
): Promise<Response> {
	const sentToken = getAccessToken();
	let res = await rawRequest(path, { ...options, accept: 'text/event-stream' });

	if (res.status === 401 && !options.skipRefresh && !options.skipAuth) {
		if (await renewAfter401(sentToken)) {
			res = await rawRequest(path, { ...options, accept: 'text/event-stream' });
		}
	}

	if (!res.ok) {
		const body = await parseErrorBody(res);
		const err = errorFor(res.status, body);
		if (err.status === 401) {
			clearSession();
		}
		throw err;
	}

	return res;
}

/**
 * Subscribe to the auth store: when the user signs out, this hook fires.
 * Used by the layout to redirect to /lq-ai/login on revocation.
 */
export function onSignOut(handler: () => void): () => void {
	if (!browser) {
		return () => undefined;
	}
	const unsub = auth.subscribe((state) => {
		if (!state.access_token) {
			handler();
		}
	});
	// Drop the initial fire if we already had no token.
	const initial = get(auth);
	if (initial.access_token) {
		// no-op — first real change will fire correctly
	}
	return unsub;
}
