/**
 * Unit tests for the sources API client (PR6c Task 5).
 *
 * Mocks `fetch` so calls don't escape the test runner. Mirrors
 * the shape of models-api.test.ts and saved-prompts-api.test.ts.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { getMessageSources } from '../api/sources';
import type { ToolSource } from '../types';
import { clearSession, setSession } from '../auth/store';

const realFetch = global.fetch;

function jsonResponse(status: number, body: unknown): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});
}

const SAMPLE: ToolSource = {
	id: 's1',
	message_id: 'm1',
	source_kind: 'caselaw',
	label: 'Roe v. Wade',
	subtitle: null,
	url: null,
	external_ref: '42',
	provider: 'courtlistener',
	tool: 'search_case_law',
	created_at: '2026-01-01T00:00:00Z'
};

describe('getMessageSources', () => {
	beforeEach(() => {
		clearSession();
		setSession({ access_token: 'tok', expires_in: 900 });
		vi.restoreAllMocks();
	});

	afterEach(() => {
		global.fetch = realFetch;
	});

	it('GETs the sources path and returns the array', async () => {
		const fetchSpy = vi.fn(async () => jsonResponse(200, [SAMPLE]));
		global.fetch = fetchSpy as unknown as typeof fetch;
		const out = await getMessageSources('c1', 'm1');
		const url = (fetchSpy.mock.calls[0] as unknown as [string, RequestInit])[0];
		expect(url).toContain('/chats/c1/messages/m1/sources');
		expect(out).toEqual([SAMPLE]);
	});

	it('encodes chatId and messageId in the path', async () => {
		const fetchSpy = vi.fn(async () => jsonResponse(200, []));
		global.fetch = fetchSpy as unknown as typeof fetch;
		await getMessageSources('chat with space', 'msg/slash');
		const url = (fetchSpy.mock.calls[0] as unknown as [string, RequestInit])[0];
		expect(url).toContain('chat%20with%20space');
		expect(url).toContain('msg%2Fslash');
	});

	it('attaches Authorization header', async () => {
		const fetchSpy = vi.fn(async () => jsonResponse(200, []));
		global.fetch = fetchSpy as unknown as typeof fetch;
		await getMessageSources('c1', 'm1');
		const init = (fetchSpy.mock.calls[0] as unknown as [string, RequestInit])[1];
		const headers = init.headers as Record<string, string>;
		expect(headers.Authorization).toBe('Bearer tok');
	});
});
