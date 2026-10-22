import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('../client', () => ({ apiRequest: vi.fn() }));
import { apiRequest } from '../client';
import { orchestrationApi, promptPath, shouldPollTree } from '../orchestration';
import type { OrchestrationTree } from '../orchestration';

describe('Orchestration consent and polling contract', () => {
	it('submits only the reviewed revision and hash', async () => {
		const tree = {
			root_id: 'root',
			plan: { revision: 3 },
			plan_hash: 'reviewed'
		} as OrchestrationTree;
		await orchestrationApi.approve(tree);
		expect(apiRequest).toHaveBeenCalledWith('/autonomous/orchestration/root/approve', {
			method: 'POST',
			body: { revision: 3, plan_hash: 'reviewed' }
		});
	});
	it('polls active work but stops at approval waits, uncertainty and terminal states', () => {
		for (const state of ['planning', 'queued', 'running', 'waiting_children'])
			expect(shouldPollTree(state)).toBe(true);
		for (const state of [
			'awaiting_approval',
			'uncertain',
			'completed',
			'failed',
			'rejected',
			'halted',
			'expired'
		])
			expect(shouldPollTree(state)).toBe(false);
	});
});

describe('the two reads that show how a run was set up', () => {
	beforeEach(() => {
		vi.mocked(apiRequest).mockReset();
		vi.mocked(apiRequest).mockResolvedValue({});
	});

	it('reads a session’s trace by the run’s root and the session, each encoded', async () => {
		const signal = new AbortController().signal;
		await orchestrationApi.trace('root-1', 'session-2', signal);
		expect(apiRequest).toHaveBeenCalledWith(
			'/autonomous/orchestration/root-1/sessions/session-2/trace',
			{ signal }
		);
		await orchestrationApi.trace('a/b', '../c?d#e');
		expect(vi.mocked(apiRequest).mock.calls[1][0]).toBe(
			'/autonomous/orchestration/a%2Fb/sessions/..%2Fc%3Fd%23e/trace'
		);
	});

	it('reads a prompt by the two parts of its name, which has a slash in it', async () => {
		await orchestrationApi.prompt('new_harness/orchestrator.v1');
		expect(apiRequest).toHaveBeenCalledWith(
			'/autonomous/orchestration/prompts/new_harness/orchestrator.v1',
			{ signal: undefined }
		);
	});

	it('encodes each part of a prompt’s name on its own, so a part cannot become two', async () => {
		expect(promptPath('family/role.v1')).toBe('family/role.v1');
		expect(promptPath('a b/c?d')).toBe('a%20b/c%3Fd');
		// The first slash divides the name. A third part is refused, not sent as a deeper path.
		expect(promptPath('a/b/c')).toBeNull();
	});

	it('does not send a name that is not exactly two plain parts', async () => {
		for (const name of [
			'',
			'orchestrator.v1',
			'/x',
			'x/',
			'/',
			'../x',
			'x/..',
			'./x',
			'x/.',
			'a\\b/c'
		]) {
			expect(promptPath(name), JSON.stringify(name)).toBeNull();
			await expect(orchestrationApi.prompt(name), JSON.stringify(name)).rejects.toThrow(
				/not the name of a prompt file/
			);
		}
		expect(apiRequest).not.toHaveBeenCalled();
	});

	it('hands back what the server sent, untouched', async () => {
		const prompt = {
			name: 'f/r.v1',
			family: 'f',
			role: 'r',
			version: 1,
			digest: 'd',
			text: '<b>x</b>'
		};
		vi.mocked(apiRequest).mockResolvedValue(prompt);
		await expect(orchestrationApi.prompt('f/r.v1')).resolves.toEqual(prompt);
	});
});
