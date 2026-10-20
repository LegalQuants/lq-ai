import { describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { ProjectContextProposalRead as Proposal } from '$lib/lq-ai/api/autonomous';
import { createProposalInbox } from '../proposal-inbox';

function deferred<T>() {
	let resolve!: (value: T) => void;
	let reject!: (error: unknown) => void;
	const promise = new Promise<T>((yes, no) => {
		resolve = yes;
		reject = no;
	});
	return { promise, resolve, reject };
}

function proposal(id: string, project_id = 'A'): Proposal {
	return {
		id,
		project_id,
		user_id: 'user',
		precedent_id: 'precedent',
		suggested_md: id,
		state: 'proposed',
		accepted_at: null,
		rejected_at: null,
		created_at: '2026-07-01T00:00:00Z',
		updated_at: '2026-07-01T00:00:00Z'
	};
}

function setup(rows = [proposal('a')]) {
	let server = [...rows];
	const deps = {
		getOptIn: vi.fn(async () => true),
		list: vi.fn(async (id: string, limit: number, offset: number) => {
			const scoped = server.filter((row) => row.project_id === id);
			return {
				proposals: scoped.slice(offset, offset + limit),
				total_count: scoped.length,
				limit,
				offset
			};
		}),
		accept: vi.fn(async (id: string) => {
			server = server.filter((row) => row.id !== id);
		}),
		reject: vi.fn(async (id: string) => {
			server = server.filter((row) => row.id !== id);
		}),
		onAccepted: vi.fn<[string, () => boolean], Promise<void>>(async () => {})
	};
	const inbox = createProposalInbox(deps);
	return { deps, inbox };
}

describe('Matter proposal inbox request lifecycle', () => {
	it('clears A immediately on navigation and ignores its delayed list after B loads', async () => {
		const { inbox, deps } = setup([proposal('b', 'B')]);
		const old = deferred<Awaited<ReturnType<typeof deps.list>>>();
		deps.list.mockImplementationOnce(() => old.promise);
		const loadingA = inbox.setMatter('A');
		await vi.waitFor(() => expect(deps.list).toHaveBeenCalled());
		await inbox.setMatter('B');
		expect(get(inbox).proposals.map((p) => p.id)).toEqual(['b']);
		old.resolve({ proposals: [proposal('a')], total_count: 1, limit: 50, offset: 0 });
		await loadingA;
		expect(get(inbox).proposals.map((p) => p.id)).toEqual(['b']);
		expect(get(inbox).totalCount).toBe(1);
	});

	it('resets loaded rows, messages and pending actions before the next preference read resolves', async () => {
		const { inbox, deps } = setup();
		await inbox.setMatter('A');
		const action = deferred<void>();
		deps.accept.mockImplementationOnce(() => action.promise);
		const accepting = inbox.accept('a');
		expect(get(inbox).pending.a).toBe('accepting');
		const pref = deferred<boolean>();
		deps.getOptIn.mockImplementationOnce(() => pref.promise);
		const loadingB = inbox.setMatter('B');
		expect(get(inbox)).toMatchObject({
			enabled: false,
			proposals: [],
			totalCount: 0,
			pending: {},
			success: null
		});
		action.resolve();
		await accepting;
		expect(deps.onAccepted).not.toHaveBeenCalled();
		pref.resolve(true);
		await loadingB;
		expect(get(inbox).success).toBeNull();
	});

	it('invalidates pending refresh callbacks even after navigating A to B and back to A', async () => {
		const { inbox, deps } = setup([proposal('a'), proposal('b', 'B')]);
		await inbox.setMatter('A');
		const refresh = deferred<void>();
		let stillCurrent!: () => boolean;
		deps.onAccepted.mockImplementationOnce(async (_id, active) => {
			stillCurrent = active;
			await refresh.promise;
		});
		const accepting = inbox.accept('a');
		await vi.waitFor(() => expect(deps.onAccepted).toHaveBeenCalled());
		await inbox.setMatter('B');
		await inbox.setMatter('A');
		expect(stillCurrent()).toBe(false);
		refresh.resolve();
		await accepting;
		expect(get(inbox).success).toBeNull();
	});

	it('ignores an old preference read and never lists the old Matter', async () => {
		const { inbox, deps } = setup([proposal('b', 'B')]);
		const pref = deferred<boolean>();
		deps.getOptIn.mockImplementationOnce(() => pref.promise);
		const loadingA = inbox.setMatter('A');
		await inbox.setMatter('B');
		pref.resolve(true);
		await loadingA;
		expect(deps.list.mock.calls.map((call) => call[0])).toEqual(['B']);
	});

	it('fails closed when the preference read rejects, without treating cached opt-in as evidence', async () => {
		const { inbox, deps } = setup();
		deps.getOptIn.mockRejectedValueOnce(new Error('preferences unavailable; cache was true'));
		await inbox.setMatter('A');
		expect(get(inbox)).toMatchObject({ enabled: false, proposals: [], totalCount: 0 });
		expect(deps.list).not.toHaveBeenCalled();
		await inbox.accept('a');
		expect(deps.accept).not.toHaveBeenCalled();
	});

	it('never lists proposals for a fresh opted-out user', async () => {
		const { inbox, deps } = setup();
		deps.getOptIn.mockResolvedValueOnce(false);
		await inbox.setMatter('A');
		expect(get(inbox).enabled).toBe(false);
		expect(deps.list).not.toHaveBeenCalled();
	});

	it('ignores a late list result after destroy', async () => {
		const { inbox, deps } = setup();
		const response = deferred<Awaited<ReturnType<typeof deps.list>>>();
		deps.list.mockImplementationOnce(() => response.promise);
		const loading = inbox.setMatter('A');
		await vi.waitFor(() => expect(deps.list).toHaveBeenCalled());
		inbox.destroy();
		response.resolve({ proposals: [proposal('a')], total_count: 1, limit: 50, offset: 0 });
		await loading;
		expect(get(inbox)).toMatchObject({ enabled: false, proposals: [] });
	});
});

describe('Proposal pagination and mutation integration', () => {
	const fiftyOne = () => Array.from({ length: 51 }, (_, i) => proposal(`p${i}`));

	it('reports the real 51-row total and loads the remaining row at offset 50', async () => {
		const { inbox, deps } = setup(fiftyOne());
		await inbox.setMatter('A');
		expect(get(inbox).proposals).toHaveLength(50);
		expect(get(inbox).totalCount).toBe(51);
		await inbox.loadMore();
		expect(deps.list).toHaveBeenLastCalledWith('A', 50, 50);
		expect(get(inbox).proposals).toHaveLength(51);
		expect(get(inbox).proposals.at(-1)?.id).toBe('p50');
		await inbox.loadMore();
		expect(deps.list).toHaveBeenCalledTimes(2);
	});

	it.each(['accept', 'reject'] as const)(
		'refills offset zero after %s so the 51st row remains reachable',
		async (action) => {
			const { inbox, deps } = setup(fiftyOne());
			await inbox.setMatter('A');
			await inbox[action]('p0');
			expect(deps.list).toHaveBeenLastCalledWith('A', 50, 0);
			expect(get(inbox).totalCount).toBe(50);
			expect(get(inbox).proposals).toHaveLength(50);
			expect(get(inbox).proposals.some((row) => row.id === 'p0')).toBe(false);
			expect(get(inbox).proposals.at(-1)?.id).toBe('p50');
			expect(deps.onAccepted).toHaveBeenCalledTimes(action === 'accept' ? 1 : 0);
		}
	);

	it('guards repeated actions synchronously', async () => {
		const { inbox, deps } = setup();
		await inbox.setMatter('A');
		const response = deferred<void>();
		deps.accept.mockImplementationOnce(() => response.promise);
		const accepting = inbox.accept('a');
		await inbox.accept('a');
		await inbox.reject('a');
		expect(deps.accept).toHaveBeenCalledTimes(1);
		expect(deps.reject).not.toHaveBeenCalled();
		response.resolve();
		await accepting;
		expect(get(inbox).pending).toEqual({});
	});

	it('keeps the pending row actionable after a failed mutation', async () => {
		const { inbox, deps } = setup();
		await inbox.setMatter('A');
		deps.accept.mockRejectedValueOnce(new Error('503'));
		await inbox.accept('a');
		expect(get(inbox).proposals.map((row) => row.id)).toEqual(['a']);
		expect(get(inbox).pending).toEqual({});
		expect(get(inbox).error).toContain('Accept failed');
	});

	it('does not report a committed accept as failed when refreshing the Matter fails', async () => {
		const { inbox, deps } = setup();
		await inbox.setMatter('A');
		deps.onAccepted.mockRejectedValueOnce(new Error('refresh unavailable'));
		await inbox.accept('a');
		expect(get(inbox).success).toBe('Added to matter context.');
		expect(get(inbox).error).toContain('Context was added');
		expect(get(inbox).proposals).toEqual([]);
	});

	it('discards an older load-more response after resolving a row', async () => {
		const { inbox, deps } = setup(fiftyOne());
		await inbox.setMatter('A');
		const oldPage = deferred<Awaited<ReturnType<typeof deps.list>>>();
		deps.list.mockImplementationOnce(() => oldPage.promise);
		const more = inbox.loadMore();
		await inbox.accept('p0');
		oldPage.resolve({ proposals: [proposal('p50')], total_count: 51, limit: 50, offset: 50 });
		await more;
		expect(get(inbox).totalCount).toBe(50);
		expect(get(inbox).proposals).toHaveLength(50);
		expect(get(inbox).proposals.some((row) => row.id === 'p0')).toBe(false);
	});
});
