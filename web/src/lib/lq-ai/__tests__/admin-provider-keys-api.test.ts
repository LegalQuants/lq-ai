/**
 * Unit tests for the admin provider-keys (BYOK) API client.
 *
 * Mocks `fetch` so the calls don't escape the test runner. Mirrors the
 * gateway-proxied contract: list → {provider_keys: [...]}, set → POST {provider,
 * api_key}, revoke → DELETE (204). 400/404/409 surface as LQAIApiError.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
	listProviderKeys,
	setProviderKey,
	revokeProviderKey,
	type ProviderKeyListResponse,
	type ProviderKeyStatus
} from '../api/admin';
import { clearSession, setSession } from '../auth/store';
import { LQAIApiError } from '../api/client';

const realFetch = global.fetch;

function jsonResponse(status: number, body: unknown): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});
}

function emptyResponse(status: number): Response {
	return new Response(null, { status });
}

const SAMPLE_LIST: ProviderKeyListResponse = {
	provider_keys: [
		{
			provider: 'anthropic-prod',
			type: 'anthropic',
			configured: true,
			last4: 'cdef',
			source: 'runtime'
		},
		{ provider: 'openai-prod', type: 'openai', configured: false, last4: null, source: null }
	]
};

const SAMPLE_STATUS: ProviderKeyStatus = {
	provider: 'anthropic-prod',
	type: 'anthropic',
	configured: true,
	last4: 'wxyz',
	source: 'runtime'
};

describe('admin provider-keys API', () => {
	beforeEach(() => {
		clearSession();
		setSession({ access_token: 'tok', expires_in: 900 });
		vi.restoreAllMocks();
	});

	afterEach(() => {
		global.fetch = realFetch;
	});

	it('listProviderKeys parses the {provider_keys} shape', async () => {
		global.fetch = vi.fn(async () => jsonResponse(200, SAMPLE_LIST)) as unknown as typeof fetch;
		const out = await listProviderKeys();
		expect(out.provider_keys.map((r) => r.provider)).toEqual(['anthropic-prod', 'openai-prod']);
		expect(out.provider_keys[0].source).toBe('runtime');
		expect(out.provider_keys[1].last4).toBeNull();
	});

	it('setProviderKey POSTs {provider, api_key}', async () => {
		const fetchSpy = vi.fn(async () => jsonResponse(200, SAMPLE_STATUS));
		global.fetch = fetchSpy as unknown as typeof fetch;
		await setProviderKey('anthropic-prod', 'sk-ant-secret');
		const [url, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toContain('/admin/provider-keys');
		expect(init.method).toBe('POST');
		const parsed = JSON.parse(init.body as string);
		expect(parsed).toEqual({ provider: 'anthropic-prod', api_key: 'sk-ant-secret' });
	});

	it('setProviderKey surfaces 400 (master key unset) as LQAIApiError', async () => {
		global.fetch = vi.fn(async () =>
			jsonResponse(400, {
				detail: { code: 'failed_precondition', message: 'requires LQ_AI_GATEWAY_MASTER_KEY' }
			})
		) as unknown as typeof fetch;
		await expect(setProviderKey('anthropic-prod', 'sk-ant-x')).rejects.toBeInstanceOf(LQAIApiError);
	});

	it('setProviderKey surfaces 404 (unknown provider) as LQAIApiError', async () => {
		global.fetch = vi.fn(async () =>
			jsonResponse(404, { detail: { code: 'not_found', message: 'no provider' } })
		) as unknown as typeof fetch;
		await expect(setProviderKey('ghost', 'sk-x')).rejects.toBeInstanceOf(LQAIApiError);
	});

	it('revokeProviderKey issues a DELETE and tolerates 204', async () => {
		const fetchSpy = vi.fn(async () => emptyResponse(204));
		global.fetch = fetchSpy as unknown as typeof fetch;
		await revokeProviderKey('anthropic-prod');
		const init = (fetchSpy.mock.calls[0] as unknown as [string, RequestInit])[1];
		expect(init.method).toBe('DELETE');
	});

	it('revokeProviderKey surfaces 409 (env-sourced key) as LQAIApiError', async () => {
		global.fetch = vi.fn(async () =>
			jsonResponse(409, { detail: { code: 'conflict', message: 'env key' } })
		) as unknown as typeof fetch;
		await expect(revokeProviderKey('anthropic-prod')).rejects.toBeInstanceOf(LQAIApiError);
	});

	it('encodes the provider name for URL safety on revoke', async () => {
		const fetchSpy = vi.fn(async () => emptyResponse(204));
		global.fetch = fetchSpy as unknown as typeof fetch;
		await revokeProviderKey('weird/name');
		const url = (fetchSpy.mock.calls[0] as unknown as [string, RequestInit])[0];
		expect(url).toContain('weird%2Fname');
	});

	it('listProviderKeys attaches Authorization header', async () => {
		const fetchSpy = vi.fn(async () => jsonResponse(200, SAMPLE_LIST));
		global.fetch = fetchSpy as unknown as typeof fetch;
		await listProviderKeys();
		const init = (fetchSpy.mock.calls[0] as unknown as [string, RequestInit])[1];
		const headers = init.headers as Record<string, string>;
		expect(headers.Authorization).toBe('Bearer tok');
	});
});
