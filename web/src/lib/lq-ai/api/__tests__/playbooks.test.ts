/**
 * Unit tests for the playbooks API client (M3-A4).
 *
 * Mocks ``globalThis.fetch`` so the calls don't escape the test runner.
 * Mirrors the saved-prompts-api / teams-api test shape: regressions in the
 * shared ``apiRequest`` helper (auth header attachment, URL encoding,
 * error translation) surface here too.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import {
	listPlaybooks,
	getPlaybook,
	executePlaybook,
	getPlaybookExecution,
	createPlaybook,
	updatePlaybook,
	deletePlaybook,
	startEasyPlaybookGeneration,
	getEasyPlaybookGeneration
} from '../playbooks';

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

	// ---------------------------------------------------------------
	// M3-A6 — Playbook CRUD + Easy Playbook wizard
	// ---------------------------------------------------------------

	it('createPlaybook POSTs /api/v1/playbooks with the body', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(201, {
				id: 'p-new',
				name: 'NDA — Custom',
				contract_type: 'NDA',
				description: '',
				version: '1.0.0',
				created_by: 'u1',
				created_at: '2026-05-20T00:00:00Z',
				updated_at: '2026-05-20T00:00:00Z',
				positions: []
			})
		);
		const playbook = await createPlaybook({
			name: 'NDA — Custom',
			contract_type: 'NDA',
			positions: [
				{
					issue: 'Definition of Confidential Information',
					standard_language: 'std',
					severity_if_missing: 'high'
				}
			]
		});
		expect(playbook.id).toBe('p-new');
		const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(String(url)).toMatch(/\/playbooks$/);
		expect(init.method).toBe('POST');
		const body = JSON.parse(String(init.body));
		expect(body.name).toBe('NDA — Custom');
		expect(body.contract_type).toBe('NDA');
		expect(body.positions).toHaveLength(1);
	});

	it('updatePlaybook PATCHes /api/v1/playbooks/{id} with the body', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, {
				id: 'p1',
				name: 'NDA — Renamed',
				contract_type: 'NDA',
				description: '',
				version: '1.0.1',
				created_by: 'u1',
				created_at: '2026-05-20T00:00:00Z',
				updated_at: '2026-05-20T00:01:00Z',
				positions: []
			})
		);
		const playbook = await updatePlaybook('p1', { name: 'NDA — Renamed', version: '1.0.1' });
		expect(playbook.name).toBe('NDA — Renamed');
		const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(String(url)).toContain('/playbooks/p1');
		expect(init.method).toBe('PATCH');
		const body = JSON.parse(String(init.body));
		expect(body).toEqual({ name: 'NDA — Renamed', version: '1.0.1' });
	});

	it('deletePlaybook calls DELETE /api/v1/playbooks/{id} and returns void on 204', async () => {
		fetchMock.mockResolvedValueOnce({
			ok: true,
			status: 204,
			headers: { get: () => null },
			json: async () => undefined
		});
		await deletePlaybook('p1');
		const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(String(url)).toContain('/playbooks/p1');
		expect(init.method).toBe('DELETE');
	});

	it('startEasyPlaybookGeneration POSTs /api/v1/playbooks/easy with document_ids + contract_type', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(202, {
				id: 'g1',
				user_id: 'u1',
				contract_type: 'NDA',
				status: 'pending',
				document_ids: ['d1', 'd2', 'd3'],
				draft_playbook: null,
				error_message: null,
				created_at: '2026-05-20T00:00:00Z'
			})
		);
		const gen = await startEasyPlaybookGeneration({
			document_ids: ['d1', 'd2', 'd3'],
			contract_type: 'NDA',
			name: 'My NDA Playbook'
		});
		expect(gen.status).toBe('pending');
		expect(gen.document_ids).toHaveLength(3);
		const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(String(url)).toContain('/playbooks/easy');
		expect(init.method).toBe('POST');
		const body = JSON.parse(String(init.body));
		expect(body).toEqual({
			document_ids: ['d1', 'd2', 'd3'],
			contract_type: 'NDA',
			name: 'My NDA Playbook'
		});
	});

	it('getEasyPlaybookGeneration GETs /api/v1/playbooks/easy/{id}', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, {
				id: 'g1',
				user_id: 'u1',
				contract_type: 'NDA',
				status: 'completed',
				document_ids: ['d1'],
				draft_playbook: {
					name: 'My NDA Playbook',
					contract_type: 'NDA',
					positions: []
				},
				error_message: null,
				created_at: '2026-05-20T00:00:00Z'
			})
		);
		const gen = await getEasyPlaybookGeneration('g1');
		expect(gen.status).toBe('completed');
		expect(gen.draft_playbook?.name).toBe('My NDA Playbook');
		expect(String(fetchMock.mock.calls[0][0])).toContain('/playbooks/easy/g1');
	});

	it('startEasyPlaybookGeneration url-encodes nothing weird (sanity)', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(202, {
				id: 'g1',
				user_id: 'u1',
				contract_type: 'NDA',
				status: 'pending',
				document_ids: [],
				draft_playbook: null,
				error_message: null,
				created_at: '2026-05-20T00:00:00Z'
			})
		);
		await startEasyPlaybookGeneration({ document_ids: ['d1'], contract_type: 'NDA' });
		const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(String(url)).toMatch(/\/playbooks\/easy$/);
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
