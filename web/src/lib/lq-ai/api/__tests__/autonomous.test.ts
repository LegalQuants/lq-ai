/**
 * Unit tests for the autonomous API client (M4-C2).
 *
 * Mocks ``globalThis.fetch`` so calls don't escape the test runner.
 * Mirrors the playbooks-api / tabular-api test shape: regressions in the
 * shared ``apiRequest`` helper (auth header attachment, URL construction,
 * error translation) surface here too.
 *
 * Focus: URL construction + request-body serialization. Full schema
 * round-trip coverage lives in the API integration tests.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import {
	listSessions,
	getSession,
	haltSession,
	listMemory,
	keepMemory,
	dismissMemory,
	deleteMemory,
	listPrecedents,
	dismissPrecedent,
	promotePrecedent,
	listProposals,
	acceptProposal,
	rejectProposal,
	runNow,
	listSchedules,
	createSchedule,
	updateSchedule,
	deleteSchedule,
	listWatches,
	createWatch,
	updateWatch,
	deleteWatch,
	listNotifications,
	readNotification
} from '../autonomous';

/** Minimal Response-shaped stub. apiRequest reads content-type to decide json/text. */
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

/** Extracts the URL string and init from the first fetchMock call. */
function firstCall(fetchMock: ReturnType<typeof vi.fn>): [string, RequestInit] {
	return fetchMock.mock.calls[0] as [string, RequestInit];
}

describe('autonomous API client', () => {
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

	// -----------------------------------------------------------------------
	// Sessions
	// -----------------------------------------------------------------------

	it('listSessions calls GET /autonomous/sessions with limit + offset', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { sessions: [], total_count: 0, limit: 50, offset: 0 })
		);
		const res = await listSessions(50, 0);
		expect(res.sessions).toHaveLength(0);
		expect(res.total_count).toBe(0);
		const [url, init] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/sessions');
		expect(String(url)).toContain('limit=50');
		expect(String(url)).toContain('offset=0');
		expect(init?.method ?? 'GET').toBe('GET');
	});

	it('listSessions uses custom limit + offset', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { sessions: [], total_count: 100, limit: 20, offset: 40 })
		);
		await listSessions(20, 40);
		const [url] = firstCall(fetchMock);
		expect(String(url)).toContain('limit=20');
		expect(String(url)).toContain('offset=40');
	});

	it('getSession calls GET /autonomous/sessions/{id} and returns session + receipt', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, {
				session: { id: 'sess-1', status: 'running' },
				receipt: {
					session_id: 'sess-1',
					trigger_kind: 'manual',
					status: 'running',
					halt_state: 'running',
					current_phase: 'intake',
					cost_total_usd: 0.0,
					max_cost_usd: null,
					cost_cap_reached: false,
					created_at: '2026-05-01T00:00:00Z',
					completed_at: null,
					phase_transitions: [],
					tool_calls: [],
					terminal_reason: null
				}
			})
		);
		const detail = await getSession('sess-1');
		expect(detail.session.id).toBe('sess-1');
		expect(detail.receipt.phase_transitions).toHaveLength(0);
		const [url] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/sessions/sess-1');
	});

	it('haltSession calls POST /autonomous/sessions/{id}/halt and returns AutonomousSessionRead', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, {
				id: 'sess-1',
				halt_state: 'halt_requested',
				status: 'running'
			})
		);
		const session = await haltSession('sess-1');
		expect(session.halt_state).toBe('halt_requested');
		const [url, init] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/sessions/sess-1/halt');
		expect(init.method).toBe('POST');
	});

	it('runNow POSTs /autonomous/run-now with the body and returns a manual session', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(201, {
				id: 's1',
				trigger_kind: 'manual',
				status: 'running'
			})
		);
		const result = await runNow({ skill_ref: 'nda-review', max_cost_usd: '0.50' });
		expect(result.trigger_kind).toBe('manual');
		const [url, init] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/run-now');
		expect(init.method).toBe('POST');
		const body = JSON.parse(String(init.body));
		expect(body.skill_ref).toBe('nda-review');
		expect(body.max_cost_usd).toBe('0.50');
	});

	// -----------------------------------------------------------------------
	// Memory — envelope key is `entries`, NOT `items`
	// -----------------------------------------------------------------------

	it('listMemory without state calls GET /autonomous/memory with limit+offset', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { entries: [], total_count: 0, limit: 50, offset: 0 })
		);
		const res = await listMemory();
		expect(res.entries).toHaveLength(0);
		const [url] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/memory');
		expect(String(url)).not.toContain('state=');
	});

	it('listMemory with state=proposed appends ?state=proposed', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { entries: [], total_count: 0, limit: 50, offset: 0 })
		);
		await listMemory('proposed');
		const [url] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/memory');
		expect(String(url)).toContain('state=proposed');
	});

	it('keepMemory with content sends POST /autonomous/memory/{id}/keep with body', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { id: 'mem-abc', state: 'kept', content: 'edited text' })
		);
		const mem = await keepMemory('abc', 'edited');
		expect(mem.state).toBe('kept');
		const [url, init] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/memory/abc/keep');
		expect(init.method).toBe('POST');
		const body = JSON.parse(String(init.body));
		expect(body).toEqual({ content: 'edited' });
	});

	it('keepMemory without content sends POST /autonomous/memory/{id}/keep without body', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { id: 'mem-abc', state: 'kept', content: 'original' })
		);
		await keepMemory('abc');
		const [url, init] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/memory/abc/keep');
		expect(init.method).toBe('POST');
		// body should be undefined (not sent) when no content arg provided
		expect(init.body).toBeUndefined();
	});

	it('dismissMemory sends POST /autonomous/memory/{id}/dismiss', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { id: 'mem-abc', state: 'dismissed' })
		);
		await dismissMemory('abc');
		const [url, init] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/memory/abc/dismiss');
		expect(init.method).toBe('POST');
	});

	it('deleteMemory sends DELETE /autonomous/memory/{id} and returns 200 entity', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { id: 'mem-abc', state: 'kept', deleted_at: '2026-05-01T00:00:00Z' })
		);
		const mem = await deleteMemory('abc');
		expect(mem.deleted_at).toBe('2026-05-01T00:00:00Z');
		const [url, init] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/memory/abc');
		expect(init.method).toBe('DELETE');
	});

	// -----------------------------------------------------------------------
	// Precedents — envelope key is `entries`
	// -----------------------------------------------------------------------

	it('listPrecedents without filter returns entries envelope', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { entries: [], total_count: 0, limit: 50, offset: 0 })
		);
		const res = await listPrecedents();
		expect(res.entries).toHaveLength(0);
		const [url] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/precedents');
		expect(String(url)).not.toContain('pattern_kind=');
	});

	it('listPrecedents with pattern_kind appends the filter', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { entries: [], total_count: 0, limit: 50, offset: 0 })
		);
		await listPrecedents('nda_risk');
		const [url] = firstCall(fetchMock);
		expect(String(url)).toContain('pattern_kind=nda_risk');
	});

	it('dismissPrecedent sends POST /autonomous/precedents/{id}/dismiss', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { id: 'prec-1', dismissed_at: '2026-05-01T00:00:00Z' })
		);
		await dismissPrecedent('prec-1');
		const [url, init] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/precedents/prec-1/dismiss');
		expect(init.method).toBe('POST');
	});

	it('promotePrecedent sends POST /autonomous/precedents/{id}/promote with {project_id} body', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(201, {
				id: 'prop-1',
				precedent_id: 'prec-1',
				project_id: 'proj-abc',
				state: 'proposed'
			})
		);
		const proposal = await promotePrecedent('prec-1', 'proj-abc');
		expect(proposal.state).toBe('proposed');
		const [url, init] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/precedents/prec-1/promote');
		expect(init.method).toBe('POST');
		const body = JSON.parse(String(init.body));
		expect(body).toEqual({ project_id: 'proj-abc' });
	});

	// -----------------------------------------------------------------------
	// Project-context proposals — envelope key is `proposals`
	// -----------------------------------------------------------------------

	it('listProposals without filters returns proposals envelope', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { proposals: [], total_count: 0, limit: 50, offset: 0 })
		);
		const res = await listProposals();
		expect(res.proposals).toHaveLength(0);
		const [url] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/project-context-proposals');
		expect(String(url)).not.toContain('state=');
	});

	it('listProposals with state filter appends ?state=proposed', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { proposals: [], total_count: 0, limit: 50, offset: 0 })
		);
		await listProposals('proposed');
		const [url] = firstCall(fetchMock);
		expect(String(url)).toContain('state=proposed');
	});

	it('acceptProposal sends POST /autonomous/project-context-proposals/{id}/accept', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { id: 'prop-1', state: 'accepted', accepted_at: '2026-05-01T00:00:00Z' })
		);
		const p = await acceptProposal('prop-1');
		expect(p.state).toBe('accepted');
		const [url, init] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/project-context-proposals/prop-1/accept');
		expect(init.method).toBe('POST');
	});

	it('rejectProposal sends POST /autonomous/project-context-proposals/{id}/reject', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { id: 'prop-1', state: 'rejected' })
		);
		await rejectProposal('prop-1');
		const [url, init] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/project-context-proposals/prop-1/reject');
		expect(init.method).toBe('POST');
	});

	// -----------------------------------------------------------------------
	// Schedules — envelope key is `schedules`
	// -----------------------------------------------------------------------

	it('listSchedules returns schedules envelope', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { schedules: [], total_count: 0, limit: 50, offset: 0 })
		);
		const res = await listSchedules();
		expect(res.schedules).toHaveLength(0);
		const [url] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/schedules');
	});

	it('createSchedule POSTs /autonomous/schedules with the body', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(201, {
				id: 'sched-1',
				cron_expr: '0 9 * * 1',
				enabled: true,
				name: 'Weekly NDA review'
			})
		);
		const sched = await createSchedule({ cron_expr: '0 9 * * 1', name: 'Weekly NDA review' });
		expect(sched.cron_expr).toBe('0 9 * * 1');
		const [url, init] = firstCall(fetchMock);
		expect(String(url)).toMatch(/\/autonomous\/schedules$/);
		expect(init.method).toBe('POST');
		const body = JSON.parse(String(init.body));
		expect(body.cron_expr).toBe('0 9 * * 1');
		expect(body.name).toBe('Weekly NDA review');
	});

	it('updateSchedule PATCHes /autonomous/schedules/{id} with the body', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { id: 'sched-1', enabled: false })
		);
		await updateSchedule('sched-1', { enabled: false });
		const [url, init] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/schedules/sched-1');
		expect(init.method).toBe('PATCH');
		const body = JSON.parse(String(init.body));
		expect(body).toEqual({ enabled: false });
	});

	it('deleteSchedule sends DELETE /autonomous/schedules/{id} and returns 200 entity', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { id: 'sched-1', deleted_at: '2026-05-01T00:00:00Z' })
		);
		const sched = await deleteSchedule('sched-1');
		expect(sched.deleted_at).toBe('2026-05-01T00:00:00Z');
		const [url, init] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/schedules/sched-1');
		expect(init.method).toBe('DELETE');
	});

	// -----------------------------------------------------------------------
	// Watches — envelope key is `watches`
	// -----------------------------------------------------------------------

	it('listWatches returns watches envelope', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { watches: [], total_count: 0, limit: 50, offset: 0 })
		);
		const res = await listWatches();
		expect(res.watches).toHaveLength(0);
		const [url] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/watches');
	});

	it('createWatch POSTs /autonomous/watches with the body', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(201, { id: 'watch-1', knowledge_base_id: 'kb-1', enabled: true })
		);
		const watch = await createWatch({ knowledge_base_id: 'kb-1' });
		expect(watch.knowledge_base_id).toBe('kb-1');
		const [url, init] = firstCall(fetchMock);
		expect(String(url)).toMatch(/\/autonomous\/watches$/);
		expect(init.method).toBe('POST');
		const body = JSON.parse(String(init.body));
		expect(body.knowledge_base_id).toBe('kb-1');
	});

	it('updateWatch PATCHes /autonomous/watches/{id} with body', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { id: 'watch-1', enabled: false })
		);
		await updateWatch('watch-1', { enabled: false });
		const [url, init] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/watches/watch-1');
		expect(init.method).toBe('PATCH');
	});

	it('deleteWatch sends DELETE /autonomous/watches/{id} and returns 200 entity', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { id: 'watch-1', deleted_at: '2026-05-01T00:00:00Z' })
		);
		const watch = await deleteWatch('watch-1');
		expect(watch.deleted_at).toBe('2026-05-01T00:00:00Z');
		const [url, init] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/watches/watch-1');
		expect(init.method).toBe('DELETE');
	});

	// -----------------------------------------------------------------------
	// Notifications — envelope key is `notifications`
	// -----------------------------------------------------------------------

	it('listNotifications without unreadOnly returns all notifications', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { notifications: [], total_count: 0, limit: 50, offset: 0 })
		);
		const res = await listNotifications();
		expect(res.notifications).toHaveLength(0);
		const [url] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/notifications');
		expect(String(url)).not.toContain('unread=true');
	});

	it('listNotifications with unreadOnly=true appends ?unread=true', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, { notifications: [], total_count: 0, limit: 50, offset: 0 })
		);
		await listNotifications(true);
		const [url] = firstCall(fetchMock);
		expect(String(url)).toContain('unread=true');
	});

	it('readNotification sends POST /autonomous/notifications/{id}/read', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponseLike(200, {
				id: 'notif-1',
				read_at: '2026-05-01T00:00:00Z',
				channel: 'in_app'
			})
		);
		const note = await readNotification('notif-1');
		expect(note.read_at).toBe('2026-05-01T00:00:00Z');
		const [url, init] = firstCall(fetchMock);
		expect(String(url)).toContain('/autonomous/notifications/notif-1/read');
		expect(init.method).toBe('POST');
	});
});
