/**
 * Unit tests for the playbooks API client (M3-A4).
 *
 * Mocks ``globalThis.fetch`` so the calls don't escape the test runner.
 * Mirrors the saved-prompts-api / teams-api test shape: regressions in the
 * shared ``apiRequest`` helper (auth header attachment, URL encoding,
 * error translation) surface here too.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { listPlaybooks, getPlaybook, executePlaybook, getPlaybookExecution } from '../playbooks';

/**
 * Minimal ``Response``-shaped object usable as a vitest mock return value.
 * The real ``apiRequest`` reads ``res.headers.get('content-type')`` to
 * decide between ``res.json()`` and ``res.text()``, so the headers shim
 * is required even on a fake response object.
 */
function jsonResponseLike(status: number, body: unknown) {
	return {
		ok: status >= 200 && status < 300,
		status,
		headers: {
			get: (name: string) => (name.toLowerCase() === 'content-type' ? 'application/json' : null)
		},
		json: async () => body
	};
}

describe('playbooks API client', () => {
	const fetchMock = vi.fn();
	let originalFetch: typeof globalThis.fetch;

	beforeEach(() => {
		originalFetch = globalThis.fetch;
		globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
		fetchMock.mockReset();
	});

	afterEach(() => {
		globalThis.fetch = originalFetch;
	});

	it('listPlaybooks calls GET /api/v1/playbooks and returns the array', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, [
				{
					id: 'p1',
					name: 'NDA — Mutual',
					contract_type: 'NDA',
					description: '',
					version: '1.0.0',
					created_by: null,
					created_at: '2026-05-18T00:00:00Z',
					updated_at: '2026-05-18T00:00:00Z',
					positions: []
				}
			])
		);
		const playbooks = await listPlaybooks();
		expect(playbooks).toHaveLength(1);
		expect(playbooks[0].name).toBe('NDA — Mutual');
		const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit | undefined];
		expect(String(url)).toContain('/playbooks');
		expect(init?.method ?? 'GET').toBe('GET');
	});

	it('getPlaybook calls GET /api/v1/playbooks/{id}', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, {
				id: 'p1',
				name: 'NDA — Mutual',
				contract_type: 'NDA',
				description: '',
				version: '1.0.0',
				created_by: null,
				created_at: '2026-05-18T00:00:00Z',
				updated_at: '2026-05-18T00:00:00Z',
				positions: []
			})
		);
		const playbook = await getPlaybook('p1');
		expect(playbook.name).toBe('NDA — Mutual');
		expect(String(fetchMock.mock.calls[0][0])).toContain('/playbooks/p1');
	});

	it('executePlaybook posts the body and returns the PlaybookExecution', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(202, {
				id: 'e1',
				playbook_id: 'p1',
				target_document_id: 'd1',
				user_id: 'u1',
				project_id: null,
				status: 'pending',
				results: null,
				error: null,
				created_at: '2026-05-18T00:00:00Z',
				completed_at: null
			})
		);
		const exec = await executePlaybook('p1', { target_document_id: 'd1' });
		expect(exec.status).toBe('pending');
		const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(String(url)).toContain('/playbooks/p1/execute');
		expect(init.method).toBe('POST');
		const body = JSON.parse(String(init.body));
		expect(body).toEqual({ target_document_id: 'd1' });
	});

	it('getPlaybookExecution calls GET /api/v1/playbook-executions/{id}', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, {
				id: 'e1',
				playbook_id: 'p1',
				target_document_id: 'd1',
				user_id: 'u1',
				project_id: null,
				status: 'completed',
				results: {
					schema_version: 'm3-a2-v1',
					positions: [],
					summary: {
						matches_standard: 0,
						matches_fallback: 0,
						deviates: 0,
						missing: 0
					}
				},
				error: null,
				created_at: '2026-05-18T00:00:00Z',
				completed_at: '2026-05-18T00:01:00Z'
			})
		);
		const exec = await getPlaybookExecution('e1');
		expect(exec.status).toBe('completed');
		expect(exec.results?.summary).toBeDefined();
		expect(String(fetchMock.mock.calls[0][0])).toContain('/playbook-executions/e1');
	});
});
