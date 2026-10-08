/**
 * Plain-language status over every recorded run: the six from the previous release
 * (no profile, no step notes, no tools) and the ones recorded for this release.
 */
import { describe, expect, it } from 'vitest';

import {
	ACTIVE_STATUSES,
	POLLING_STATUSES,
	TERMINAL_STATUSES,
	UNCERTAIN_EXPLANATION,
	isActiveStatus,
	isTerminalStatus,
	runDetail,
	runHeadline,
	shouldAnnounceSettled,
	shouldPollStatus,
	stopReasonText,
	taskCounts
} from '../status';
import { allRuns, legacyRun, run, withRun, withTasks } from './fixtures';

const UNCERTAIN = 'Uncertain: a provider call has no confirmed outcome';

describe('runHeadline on recorded runs', () => {
	const expected: [string, string][] = [
		['planning', 'Proposing a plan…'],
		['awaiting-approval', 'Waiting for your approval'],
		['queued', 'Plan approved. Waiting for the tasks to start'],
		['children-admitted', '2 tasks waiting to start'],
		['one-child-done', '1 task waiting to start'],
		['completed', 'Answer delivered'],
		['rejected', 'You rejected the plan'],
		['halted', 'Halted'],
		['failed-plan', 'The model could not produce a usable plan'],
		['unfunded-plan', 'The plan needs more tasks than the budget can fund'],
		['uncertain-planning', UNCERTAIN],
		['uncertain-child', UNCERTAIN],
		['closed-planning', 'Closed'],
		['closed-child', 'Closed'],
		['refusals-and-partial', 'Answer delivered'],
		['documents.planning', 'Proposing a plan…'],
		['documents.awaiting-approval', 'Waiting for your approval'],
		['documents.completed', 'Answer delivered']
	];
	it.each(expected)('run.%s', (name, headline) => {
		expect(runHeadline(run(name))).toBe(headline);
	});

	it.each([
		['model-run', 'Answer delivered'],
		['rejected-run', 'You rejected the plan'],
		['stalled-model-run', UNCERTAIN],
		['timeout-run', UNCERTAIN],
		['fenced-plan-run', 'The model could not produce a usable plan'],
		['truncated-plan-run', 'The model could not produce a usable plan']
	] as const)('previous release: %s', (name, headline) => {
		expect(runHeadline(legacyRun(name))).toBe(headline);
	});
});

describe('runHeadline while tasks are in flight', () => {
	const admitted = run('children-admitted');

	it('counts the tasks that are running', () => {
		expect(runHeadline(withTasks(admitted, ['running', 'running'], 'waiting_children'))).toBe(
			'2 tasks running'
		);
		expect(runHeadline(withTasks(admitted, ['running', 'queued'], 'waiting_children'))).toBe(
			'1 task running'
		);
	});

	it('says the answers are being combined once every task has finished', () => {
		expect(runHeadline(withTasks(admitted, ['completed', 'completed'], 'running'))).toBe(
			'Combining the answers'
		);
		// A task that failed has still finished.
		expect(runHeadline(withTasks(admitted, ['completed', 'failed'], 'running'))).toBe(
			'Combining the answers'
		);
	});

	it('says the tasks are starting before any is admitted', () => {
		expect(runHeadline(withTasks(admitted, [], 'running'))).toBe('2 tasks waiting to start');
		const empty = withRun(admitted, { tree: null, status: 'running' });
		expect(runHeadline(empty)).toBe('Starting the tasks');
	});
});

describe('runHeadline on endings the recordings do not cover', () => {
	const base = run('completed');
	it('names a budget overrun, a deadline and an unusable combined answer', () => {
		expect(runHeadline(withRun(base, { status: 'halted', stop_reason: 'observed_budget_overrun' }))).toBe(
			'Halted: a call cost more than its allowance'
		);
		expect(runHeadline(withRun(base, { status: 'expired', stop_reason: 'root_deadline' }))).toBe(
			'The run reached its time limit'
		);
		expect(runHeadline(withRun(base, { status: 'failed', stop_reason: 'invalid_synthesis' }))).toBe(
			'The combined answer could not be produced'
		);
	});

	it('does not throw on a status it has never seen', () => {
		expect(runHeadline(withRun(base, { status: 'paused_for_review' }))).toBe('Paused for review');
		expect(runHeadline(withRun(base, { status: '' }))).toBe('Unknown status');
	});

	it('says something for a failure with no stop reason', () => {
		expect(runHeadline(withRun(base, { status: 'failed', stop_reason: null }))).toBe('The run failed');
	});
});

describe('runDetail', () => {
	it('explains an uncertain run in plain words, including what closing does', () => {
		for (const name of ['uncertain-planning', 'uncertain-child'] as const) {
			const detail = runDetail(run(name));
			expect(detail).toBe(UNCERTAIN_EXPLANATION);
			expect(detail).toMatch(/will not\s+retry/);
			expect(detail).toMatch(/charges that unresolved\s+reservation/);
			expect(detail).toMatch(/frees you to start another run/);
		}
	});

	it('says a closed run was charged and retried nothing', () => {
		expect(runDetail(run('closed-child'))).toMatch(/charged and nothing was retried/);
	});

	it('says how many tasks have finished while the run is moving', () => {
		expect(runDetail(run('one-child-done'))).toBe('1 of 2 tasks finished.');
		expect(runDetail(run('children-admitted'))).toBe('0 of 2 tasks finished.');
	});

	it('says an answer covers only part of the request when coverage is partial', () => {
		expect(runDetail(run('refusals-and-partial'))).toMatch(/only part of the request/);
		expect(runDetail(run('completed'))).toBeNull();
	});

	it('explains the two ways a plan can fail', () => {
		expect(runDetail(run('failed-plan'))).toMatch(/could not be turned into a valid plan/);
		expect(runDetail(run('unfunded-plan'))).toMatch(/more tasks than the total cap can fund/);
	});

	it('works on every recorded shape and always returns text or null', () => {
		for (const { label, run: value } of allRuns()) {
			const detail = runDetail(value);
			expect(detail === null || (typeof detail === 'string' && detail.length > 0), label).toBe(true);
			expect(runHeadline(value).length, label).toBeGreaterThan(0);
		}
	});
});

describe('status sets', () => {
	it('"active" is exactly the states that hold the owner’s single allowance', () => {
		expect([...ACTIVE_STATUSES].sort()).toEqual(
			['awaiting_approval', 'planning', 'queued', 'running', 'uncertain', 'waiting_children'].sort()
		);
	});

	it('polls only planning, queued, running and waiting_children', () => {
		expect([...POLLING_STATUSES].sort()).toEqual(
			['planning', 'queued', 'running', 'waiting_children'].sort()
		);
		for (const status of POLLING_STATUSES) expect(shouldPollStatus(status)).toBe(true);
		for (const status of ['awaiting_approval', 'uncertain', ...TERMINAL_STATUSES]) {
			expect(shouldPollStatus(status)).toBe(false);
		}
	});

	it('every known status is active or terminal, never both', () => {
		for (const status of [...ACTIVE_STATUSES, ...TERMINAL_STATUSES]) {
			expect(isActiveStatus(status) !== isTerminalStatus(status), status).toBe(true);
		}
		expect(isActiveStatus('something_new')).toBe(false);
		expect(isTerminalStatus('something_new')).toBe(false);
		expect(shouldPollStatus('something_new')).toBe(false);
	});
});

describe('shouldAnnounceSettled', () => {
	it('fires once when a run moves from active to finished', () => {
		expect(shouldAnnounceSettled({ previous: 'running', current: 'completed', messageHasContent: false })).toBe(true);
		expect(shouldAnnounceSettled({ previous: 'planning', current: 'failed', messageHasContent: false })).toBe(true);
		expect(shouldAnnounceSettled({ previous: 'uncertain', current: 'closed', messageHasContent: false })).toBe(true);
		expect(shouldAnnounceSettled({ previous: 'completed', current: 'completed', messageHasContent: true })).toBe(false);
	});

	it('stays quiet while the run is still active', () => {
		expect(shouldAnnounceSettled({ previous: 'running', current: 'waiting_children', messageHasContent: false })).toBe(false);
		expect(shouldAnnounceSettled({ previous: null, current: 'uncertain', messageHasContent: false })).toBe(false);
	});

	it('on a first look, only a completed run whose message is still empty needs the row read again', () => {
		expect(shouldAnnounceSettled({ previous: null, current: 'completed', messageHasContent: false })).toBe(true);
		expect(shouldAnnounceSettled({ previous: null, current: 'completed', messageHasContent: true })).toBe(false);
		expect(shouldAnnounceSettled({ previous: null, current: 'halted', messageHasContent: false })).toBe(false);
	});
});

describe('stopReasonText', () => {
	it('says every reason the backend emits as a sentence', () => {
		for (const reason of [
			'owner_halt',
			'owner_closed',
			'invalid_proposal',
			'unfunded_plan',
			'invalid_synthesis',
			'unresolved_effect',
			'unresolved_reservation',
			'root_deadline',
			'observed_budget_overrun'
		]) {
			const text = stopReasonText(reason);
			expect(text, reason).toMatch(/^[A-Z].*\.$/);
			expect(text, reason).not.toContain('_');
		}
	});

	it('humanises a reason it does not know and returns null for none', () => {
		expect(stopReasonText('provider_went_away')).toBe('Provider went away.');
		expect(stopReasonText(null)).toBeNull();
		expect(stopReasonText('')).toBeNull();
	});

	it('does not mistake an object property for a known reason', () => {
		expect(stopReasonText('constructor')).toBe('Constructor.');
		expect(stopReasonText('__proto__')).toBe('Proto.');
		expect(stopReasonText('toString')).toBe('ToString.');
	});
});

describe('taskCounts', () => {
	it('counts tasks by what they are doing', () => {
		expect(taskCounts(run('one-child-done').tree)).toEqual({
			total: 2,
			finished: 1,
			running: 0,
			waiting: 1,
			stopped: 0,
			failed: 0
		});
		expect(taskCounts(run('refusals-and-partial').tree)).toMatchObject({
			total: 2,
			finished: 2,
			failed: 1
		});
		expect(taskCounts(run('halted').tree)).toMatchObject({ finished: 1, stopped: 1 });
	});

	it('is safe with no plan', () => {
		expect(taskCounts(null)).toMatchObject({ total: 0, finished: 0 });
		expect(taskCounts(undefined)).toMatchObject({ total: 0 });
		expect(taskCounts(run('failed-plan').tree)).toMatchObject({ total: 0 });
	});
});

describe('runDetail for a halted run', () => {
	const REST = 'No combined answer was produced. Task answers and files finished before the halt remain below.';

	it('says the owner halted it, when they did', () => {
		const halted = run('halted');
		expect(halted.stop_reason).toBe('owner_halt');
		expect(runDetail(halted)).toBe(`You halted the run. ${REST}`);
	});

	it('does not say the owner did it when something else stopped it', () => {
		for (const stop_reason of ['observed_budget_overrun', 'root_deadline', 'unresolved_effect', 'something_new', '', null]) {
			expect(runDetail(withRun(run('halted'), { stop_reason })), String(stop_reason)).toBe(REST);
		}
	});

	it('begins with the same sentence the stop reason is worded with, and leaves the headline alone', () => {
		const halted = run('halted');
		expect(runDetail(halted)!.startsWith(`${stopReasonText('owner_halt')} `)).toBe(true);
		expect(runHeadline(halted)).toBe('Halted');
		expect(runHeadline(withRun(halted, { stop_reason: 'observed_budget_overrun' }))).toBe(
			'Halted: a call cost more than its allowance'
		);
	});

	it('is not what an uncertain run says, even one recorded with the owner’s halt as its stop reason', () => {
		for (const name of ['stalled-model-run', 'timeout-run'] as const) {
			const stalled = legacyRun(name);
			expect(stalled.stop_reason).toBe('owner_halt');
			expect(runDetail(stalled)).toBe(UNCERTAIN_EXPLANATION);
		}
	});
});
