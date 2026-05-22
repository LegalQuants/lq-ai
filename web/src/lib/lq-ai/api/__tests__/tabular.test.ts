/**
 * Unit tests for the tabular API client (M3-C3).
 *
 * Mocks ``globalThis.fetch`` so the calls don't escape the test runner.
 * Mirrors the playbooks-api test shape: regressions in the shared
 * ``apiRequest`` helper (auth header attachment, URL encoding, error
 * translation) surface here too.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import {
	previewTabularCost,
	executeTabular,
	listTabularExecutions,
	getTabularExecution,
	deleteTabularExecution,
	cancelTabularExecution
} from '../tabular';

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

describe('tabular API client', () => {
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

	it('previewTabularCost POSTs /api/v1/tabular/preview-cost with the body', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, {
				cells_count: 20,
				estimated_tokens: 12000,
				estimated_cost_usd: '0.0500',
				per_tier_breakdown: { tier_2: 16, tier_4: 4 }
			})
		);
		const preview = await previewTabularCost({
			document_ids: ['d1', 'd2', 'd3', 'd4', 'd5'],
			skill_name: 'contract-snapshot'
		});
		expect(preview.cells_count).toBe(20);
		expect(preview.estimated_cost_usd).toBe('0.0500');
		const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(String(url)).toContain('/tabular/preview-cost');
		expect(init.method).toBe('POST');
		const body = JSON.parse(String(init.body));
		expect(body.document_ids).toHaveLength(5);
		expect(body.skill_name).toBe('contract-snapshot');
	});

	it('previewTabularCost supports ad-hoc columns instead of skill_name', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, {
				cells_count: 4,
				estimated_tokens: 2400,
				estimated_cost_usd: '0.0100',
				per_tier_breakdown: { tier_2: 4 }
			})
		);
		await previewTabularCost({
			document_ids: ['d1'],
			columns: [
				{ name: 'Term', query: 'What is the term of this NDA?' },
				{
					name: 'Survival',
					query: 'How long does the obligation survive?',
					minimum_inference_tier: 4
				}
			]
		});
		const body = JSON.parse(String(fetchMock.mock.calls[0][1].body));
		expect(body.columns).toHaveLength(2);
		expect(body.columns[1].minimum_inference_tier).toBe(4);
		expect(body.skill_name).toBeUndefined();
	});

	it('executeTabular POSTs /api/v1/tabular/execute and returns 202 + execution row', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(202, {
				id: 'tex-1',
				user_id: 'u1',
				parent_execution_id: null,
				skill_name: 'contract-snapshot',
				status: 'pending',
				document_ids: ['d1', 'd2', 'd3', 'd4', 'd5'],
				columns: [{ name: 'Term', query: 'What is the term?' }],
				results: null,
				cost_estimate_usd: '0.0500',
				cost_actual_usd: null,
				error_text: null,
				created_at: '2026-05-22T15:00:00Z',
				started_at: null,
				completed_at: null
			})
		);
		const exec = await executeTabular({
			document_ids: ['d1', 'd2', 'd3', 'd4', 'd5'],
			skill_name: 'contract-snapshot',
			confirmed_cost_usd: '0.0500'
		});
		expect(exec.id).toBe('tex-1');
		expect(exec.status).toBe('pending');
		const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(String(url)).toContain('/tabular/execute');
		expect(init.method).toBe('POST');
		const body = JSON.parse(String(init.body));
		expect(body.confirmed_cost_usd).toBe('0.0500');
	});

	it('listTabularExecutions GETs /api/v1/tabular/executions', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, [
				{
					id: 'tex-1',
					user_id: 'u1',
					parent_execution_id: null,
					skill_name: 'contract-snapshot',
					status: 'completed',
					document_count: 5,
					column_count: 4,
					cost_estimate_usd: '0.0500',
					cost_actual_usd: '0.0480',
					created_at: '2026-05-22T15:00:00Z',
					completed_at: '2026-05-22T15:02:00Z'
				}
			])
		);
		const rows = await listTabularExecutions();
		expect(rows).toHaveLength(1);
		expect(rows[0].document_count).toBe(5);
		expect(rows[0].column_count).toBe(4);
		const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit | undefined];
		expect(String(url)).toMatch(/\/tabular\/executions$/);
		expect(init?.method ?? 'GET').toBe('GET');
	});

	it('getTabularExecution GETs /api/v1/tabular/executions/{id}', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, {
				id: 'tex-1',
				user_id: 'u1',
				parent_execution_id: null,
				skill_name: 'contract-snapshot',
				status: 'completed',
				document_ids: ['d1', 'd2'],
				columns: [{ name: 'Term', query: 'What is the term?' }],
				results: {
					rows: [
						{
							document_id: 'd1',
							document_name: 'NDA Acme.pdf',
							cells: {
								Term: {
									value: '3 years',
									citations: [],
									confidence: 'high',
									tier_used: 2,
									cost_usd: '0.0050',
									error: null
								}
							}
						}
					]
				},
				cost_estimate_usd: '0.0500',
				cost_actual_usd: '0.0480',
				error_text: null,
				created_at: '2026-05-22T15:00:00Z',
				started_at: '2026-05-22T15:00:05Z',
				completed_at: '2026-05-22T15:02:00Z'
			})
		);
		const exec = await getTabularExecution('tex-1');
		expect(exec.status).toBe('completed');
		expect(exec.results?.rows).toHaveLength(1);
		expect(exec.results?.rows[0].cells.Term.value).toBe('3 years');
		expect(String(fetchMock.mock.calls[0][0])).toContain('/tabular/executions/tex-1');
	});

	it('deleteTabularExecution calls DELETE /api/v1/tabular/executions/{id} and returns void on 204', async () => {
		fetchMock.mockResolvedValueOnce({
			ok: true,
			status: 204,
			headers: { get: () => null },
			json: async () => undefined
		});
		await deleteTabularExecution('tex-1');
		const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(String(url)).toContain('/tabular/executions/tex-1');
		expect(init.method).toBe('DELETE');
	});

	it('cancelTabularExecution POSTs /api/v1/tabular/executions/{id}/cancel and returns updated execution', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, {
				id: 'tex-1',
				user_id: 'u1',
				parent_execution_id: null,
				skill_name: 'contract-snapshot',
				status: 'cancelled',
				document_ids: ['d1'],
				columns: [{ name: 'Term', query: 'What is the term?' }],
				results: null,
				cost_estimate_usd: '0.0500',
				cost_actual_usd: null,
				error_text: null,
				created_at: '2026-05-22T15:00:00Z',
				started_at: '2026-05-22T15:00:05Z',
				completed_at: '2026-05-22T15:00:30Z'
			})
		);
		const exec = await cancelTabularExecution('tex-1');
		expect(exec.status).toBe('cancelled');
		const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(String(url)).toContain('/tabular/executions/tex-1/cancel');
		expect(init.method).toBe('POST');
	});

	it('getTabularExecution url-encodes IDs that contain reserved characters', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, {
				id: 'weird/id',
				user_id: null,
				parent_execution_id: null,
				skill_name: null,
				status: 'failed',
				document_ids: [],
				columns: [],
				results: null,
				cost_estimate_usd: null,
				cost_actual_usd: null,
				error_text: 'whatever',
				created_at: '2026-05-22T15:00:00Z',
				started_at: null,
				completed_at: null
			})
		);
		await getTabularExecution('weird/id');
		const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
		// '/' inside the id segment must be percent-encoded to '%2F'.
		expect(String(url)).toContain('/tabular/executions/weird%2Fid');
	});
});
