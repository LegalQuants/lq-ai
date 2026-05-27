/**
 * Unit tests for the preferences API client.
 *
 * Mocks global.fetch so no real HTTP calls escape. Mirrors the mock
 * pattern in saved-prompts-api.test.ts.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getPreferences, patchPreferences } from '../api/preferences';
import { clearSession, setSession } from '../auth/store';
import { LQAIApiError } from '../api/client';
import type { Preferences } from '../types';

const realFetch = global.fetch;

function jsonResponse(status: number, body: unknown): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});
}

const FULL_PREFS: Preferences = {
	reasoning_visibility: 'disclosure',
	featured_tools: 'prominent',
	workspace_layout: 'three_pane',
	trust_pills: 'labels',
	provenance_pills: 'always',
	autonomous_enabled: false
};

describe('preferences API client', () => {
	beforeEach(() => {
		clearSession();
		setSession({ access_token: 'tok', expires_in: 900 });
		vi.restoreAllMocks();
	});

	afterEach(() => {
		global.fetch = realFetch;
	});

	it('getPreferences GETs /users/me/preferences and returns the parsed shape', async () => {
		global.fetch = vi.fn(async () => jsonResponse(200, FULL_PREFS)) as unknown as typeof fetch;
		const p = await getPreferences();
		expect(p.featured_tools).toBe('prominent');
		expect(p.workspace_layout).toBe('three_pane');
		expect(p.trust_pills).toBe('labels');
		expect(p.provenance_pills).toBe('always');
		expect(p.reasoning_visibility).toBe('disclosure');
		const [url] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
		expect(url).toContain('/users/me/preferences');
	});

	it('patchPreferences PATCHes with the diff body and returns parsed response', async () => {
		const patched = { ...FULL_PREFS, featured_tools: 'inline' as const };
		const spy = vi.fn(async () => jsonResponse(200, patched)) as unknown as typeof fetch;
		global.fetch = spy;
		const p = await patchPreferences({ featured_tools: 'inline' });
		expect(p.featured_tools).toBe('inline');
		const [, opts] = (spy as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
		expect(opts.method).toBe('PATCH');
		expect(JSON.parse(opts.body as string)).toEqual({ featured_tools: 'inline' });
	});

	it('patchPreferences with empty body returns current state', async () => {
		global.fetch = vi.fn(async () => jsonResponse(200, FULL_PREFS)) as unknown as typeof fetch;
		const p = await patchPreferences({});
		expect(p.featured_tools).toBe('prominent');
		const [, opts] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
			string,
			RequestInit
		];
		expect(opts.method).toBe('PATCH');
		expect(JSON.parse(opts.body as string)).toEqual({});
	});

	it('throws LQAIApiError on 401', async () => {
		global.fetch = vi.fn(async () =>
			jsonResponse(401, { detail: { code: 'unauthorized', message: 'Not authenticated' } })
		) as unknown as typeof fetch;
		await expect(getPreferences()).rejects.toBeInstanceOf(LQAIApiError);
	});
});
