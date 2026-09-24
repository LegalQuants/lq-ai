import { describe, expect, it, vi } from 'vitest';
vi.mock('../client', () => ({ apiRequest: vi.fn() }));
import { apiRequest } from '../client';
import { orchestrationApi, shouldPollTree } from '../orchestration';
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
		for (const state of ['queued', 'running', 'waiting_children'])
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
