/**
 * Which controls a run offers in which state: approve and reject while a plan awaits a
 * decision, halt for as long as the run holds the owner's allowance, close for a run
 * whose outcome is uncertain.
 */
import { describe, expect, it } from 'vitest';

import type { OrchestrationChatRun } from '../../api/orchestration';
import { availableActions, type RunActions } from '../actions';
import { ACTIVE_STATUSES, POLLING_STATUSES, TERMINAL_STATUSES } from '../status';
import { allRuns, legacyRun, run, withRun } from './fixtures';

const NONE: RunActions = { approve: false, reject: false, halt: false, close: false };
const HALT: RunActions = { ...NONE, halt: true };

/** A recorded run with a plan that is waiting for a decision, shown in another status. */
const awaiting = run('awaiting-approval');
const inStatus = (status: string): OrchestrationChatRun => withRun(awaiting, { status });

describe('availableActions by status', () => {
	const expected: [string, RunActions][] = [
		['planning', HALT],
		['awaiting_approval', { approve: true, reject: true, halt: true, close: false }],
		['queued', HALT],
		['running', HALT],
		['waiting_children', HALT],
		['uncertain', { approve: false, reject: false, halt: true, close: true }],
		['completed', NONE],
		['failed', NONE],
		['rejected', NONE],
		['halted', NONE],
		['expired', NONE],
		['closed', NONE],
		['something_new', NONE],
		['', NONE]
	];

	it.each(expected)('%s', (status, actions) => {
		expect(availableActions(inStatus(status))).toEqual(actions);
	});

	it('offers nothing once the run has ended, whatever the plan on it says', () => {
		for (const status of TERMINAL_STATUSES) {
			expect(availableActions(inStatus(status)), status).toEqual(NONE);
		}
	});

	it('offers halt for as long as the run holds the owner’s allowance, and then not at all', () => {
		for (const status of ACTIVE_STATUSES)
			expect(availableActions(inStatus(status)).halt, status).toBe(true);
		for (const status of [...TERMINAL_STATUSES, 'something_new']) {
			expect(availableActions(inStatus(status)).halt, status).toBe(false);
		}
	});

	it('offers halt for every run that is being followed', () => {
		for (const status of POLLING_STATUSES)
			expect(availableActions(inStatus(status)).halt, status).toBe(true);
	});

	it('offers close for an uncertain run and for no other', () => {
		for (const status of [...ACTIVE_STATUSES, ...TERMINAL_STATUSES, 'something_new']) {
			expect(availableActions(inStatus(status)).close, status).toBe(status === 'uncertain');
		}
	});
});

describe('approve and reject', () => {
	it('are offered together, only while there is a plan that has not been approved and the run awaits it', () => {
		expect(availableActions(awaiting)).toMatchObject({ approve: true, reject: true });
	});

	it('are not offered when there is no plan to decide on', () => {
		const noPlan = withRun(awaiting, { tree: null });
		expect(availableActions(noPlan)).toEqual(HALT);
	});

	it('are not offered once the plan is approved, even if the run still reads as awaiting', () => {
		const approved = structuredClone(awaiting);
		approved.tree!.approved = true;
		expect(availableActions(approved)).toEqual(HALT);
	});

	it('are not offered on a plan whose approval is not recorded as false', () => {
		for (const approved of [undefined, null]) {
			const odd = structuredClone(awaiting);
			(odd.tree as { approved?: boolean | null }).approved = approved;
			expect(availableActions(odd), String(approved)).toEqual(HALT);
		}
	});

	it('are never offered without each other, or without halt', () => {
		for (const { label, run: value } of allRuns()) {
			const actions = availableActions(value);
			expect(actions.approve, label).toBe(actions.reject);
			if (actions.approve) expect(actions.halt, label).toBe(true);
			if (actions.close) expect(actions.halt, label).toBe(true);
		}
	});
});

describe('on every recorded run', () => {
	const A = { approve: true, reject: true, halt: true, close: false };
	const C = { approve: false, reject: false, halt: true, close: true };
	const recorded: [string, RunActions][] = [
		['planning', HALT],
		['awaiting-approval', A],
		['queued', HALT],
		['children-admitted', HALT],
		['one-child-done', HALT],
		['completed', NONE],
		['rejected', NONE],
		['halted', NONE],
		['failed-plan', NONE],
		['unfunded-plan', NONE],
		['uncertain-planning', C],
		['uncertain-child', C],
		['closed-planning', NONE],
		['closed-child', NONE],
		['refusals-and-partial', NONE],
		['documents.planning', HALT],
		['documents.awaiting-approval', A],
		['documents.completed', NONE]
	];

	it.each(recorded)('run.%s', (name, actions) => {
		expect(availableActions(run(name))).toEqual(actions);
	});

	it.each([
		['model-run', NONE],
		['rejected-run', NONE],
		// Recorded as uncertain although the owner had asked to halt it: still stuck, still closable.
		['stalled-model-run', C],
		['timeout-run', C],
		['fenced-plan-run', NONE],
		['truncated-plan-run', NONE]
	] as const)('previous release: %s', (name, actions) => {
		expect(availableActions(legacyRun(name))).toEqual(actions);
	});
});

describe('a run read with less than usual', () => {
	it('works from the status and the plan alone', () => {
		expect(availableActions({ status: 'uncertain', stop_reason: null })).toEqual({
			approve: false,
			reject: false,
			halt: true,
			close: true
		});
		expect(
			availableActions({ status: 'awaiting_approval', stop_reason: null, tree: null })
		).toEqual(HALT);
	});
});
