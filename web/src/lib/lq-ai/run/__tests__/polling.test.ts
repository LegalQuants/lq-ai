/**
 * When to look at a run again: the delay, whether to look at all, and what counts as
 * the run having moved. The timing itself, with timers, is in `follow.test.ts`.
 */
import { describe, expect, it } from 'vitest';

import type { OrchestrationChatRun } from '../../api/orchestration';
import {
	POLL_MAX_MS,
	POLL_START_MS,
	nextPollDelay,
	pollDecision,
	runFingerprint
} from '../polling';
import { ACTIVE_STATUSES, POLLING_STATUSES, TERMINAL_STATUSES, shouldPollStatus } from '../status';
import { allRuns, run, withTasks } from './fixtures';

function edited(
	base: OrchestrationChatRun,
	change: (copy: OrchestrationChatRun) => void
): OrchestrationChatRun {
	const copy = structuredClone(base);
	change(copy);
	return copy;
}

describe('nextPollDelay', () => {
	it('starts at two seconds and never waits more than ten', () => {
		expect(POLL_START_MS).toBe(2000);
		expect(POLL_MAX_MS).toBe(10000);
		expect(nextPollDelay(0)).toBe(2000);
		expect(nextPollDelay(1000)).toBe(10000);
	});

	it('grows by a quarter for each look that found nothing new, in steps of 100 ms', () => {
		expect(Array.from({ length: 10 }, (_, unchanged) => nextPollDelay(unchanged))).toEqual([
			2000, 2500, 3100, 3900, 4900, 6100, 7600, 9500, 10000, 10000
		]);
	});

	it('only ever grows, within its bounds', () => {
		let previous = 0;
		for (let unchanged = 0; unchanged < 60; unchanged += 1) {
			const delay = nextPollDelay(unchanged);
			expect(delay).toBeGreaterThanOrEqual(previous);
			expect(delay).toBeGreaterThanOrEqual(POLL_START_MS);
			expect(delay).toBeLessThanOrEqual(POLL_MAX_MS);
			expect(delay % 100).toBe(0);
			previous = delay;
		}
	});

	it('is the start delay for a count that makes no sense, and the longest for a very large one', () => {
		for (const unchanged of [-1, -100, Number.NaN])
			expect(nextPollDelay(unchanged)).toBe(POLL_START_MS);
		expect(nextPollDelay(1.9)).toBe(nextPollDelay(1));
		expect(nextPollDelay(1e6)).toBe(POLL_MAX_MS);
	});
});

describe('pollDecision', () => {
	it('polls a run that moves on its own while the tab is visible', () => {
		for (const status of ['planning', 'queued', 'running', 'waiting_children']) {
			expect(pollDecision({ status, hidden: false }), status).toBe('poll');
		}
	});

	it('pauses, rather than stops, while the tab is hidden', () => {
		for (const status of POLLING_STATUSES) {
			expect(pollDecision({ status, hidden: true }), status).toBe('paused');
		}
	});

	it('stops for a run that is waiting on the owner, and says so even when hidden', () => {
		for (const status of ['awaiting_approval', 'uncertain']) {
			expect(pollDecision({ status, hidden: false }), status).toBe('stop');
			expect(pollDecision({ status, hidden: true }), status).toBe('stop');
		}
	});

	it('stops for every status in which the run is over, closed included', () => {
		expect([...TERMINAL_STATUSES].sort()).toEqual(
			['closed', 'completed', 'expired', 'failed', 'halted', 'rejected'].sort()
		);
		for (const status of TERMINAL_STATUSES) {
			expect(pollDecision({ status, hidden: false }), status).toBe('stop');
			expect(pollDecision({ status, hidden: true }), status).toBe('stop');
		}
	});

	it('stops for a status it has never seen rather than asking about it forever', () => {
		for (const status of ['', 'paused_for_review', 'RUNNING', 'constructor', '__proto__']) {
			expect(pollDecision({ status, hidden: false }), status).toBe('stop');
		}
	});

	it('polls exactly the statuses `shouldPollStatus` says move on their own', () => {
		for (const status of [...ACTIVE_STATUSES, ...TERMINAL_STATUSES, 'something_new']) {
			expect(pollDecision({ status, hidden: false }) === 'poll', status).toBe(
				shouldPollStatus(status)
			);
		}
	});
});

describe('runFingerprint', () => {
	it('is a non-empty string for every recorded run, old and new', () => {
		for (const { label, run: value } of allRuns()) {
			const fingerprint = runFingerprint(value);
			expect(typeof fingerprint, label).toBe('string');
			expect(fingerprint.length, label).toBeGreaterThan(0);
			expect(fingerprint, label).not.toMatch(/undefined|NaN/);
		}
	});

	it('is the same for the same read, and does not depend on the object it was read from', () => {
		for (const { label, run: value } of allRuns()) {
			expect(runFingerprint(structuredClone(value)), label).toBe(runFingerprint(value));
		}
	});

	it('is different at every recorded moment of one run, so each step forward is noticed', () => {
		// These recordings are one run caught at six moments.
		const moments = [
			'planning',
			'awaiting-approval',
			'queued',
			'children-admitted',
			'one-child-done',
			'completed'
		] as const;
		const fingerprints = moments.map((name) => runFingerprint(run(name)));
		expect(new Set(fingerprints).size).toBe(moments.length);
	});

	it('changes when the status changes', () => {
		const base = run('children-admitted');
		expect(runFingerprint(edited(base, (copy) => (copy.status = 'running')))).not.toBe(
			runFingerprint(base)
		);
	});

	it('changes when a task changes status, or a different task does', () => {
		const base = run('children-admitted');
		const first = withTasks(base, ['running', 'queued'], base.status);
		const second = withTasks(base, ['queued', 'running'], base.status);
		expect(
			new Set([runFingerprint(base), runFingerprint(first), runFingerprint(second)]).size
		).toBe(3);
	});

	it('changes when a task records a step', () => {
		const base = run('one-child-done');
		const moved = edited(base, (copy) => {
			const child = copy.tree!.children[1];
			child.effects.push(structuredClone(copy.tree!.children[0].effects[0]));
		});
		expect(runFingerprint(moved)).not.toBe(runFingerprint(base));
	});

	it('changes when the orchestrator records a step', () => {
		const base = run('completed');
		const moved = edited(base, (copy) => {
			copy.tree!.root.effects.push(structuredClone(copy.tree!.root.effects[0]));
		});
		expect(runFingerprint(moved)).not.toBe(runFingerprint(base));
		const planning = edited(base, (copy) => {
			copy.effects.push(structuredClone(copy.effects[0]));
		});
		expect(runFingerprint(planning)).not.toBe(runFingerprint(base));
	});

	it('changes when a task saves a file', () => {
		const base = run('one-child-done');
		const moved = edited(base, (copy) => {
			const child = copy.tree!.children[1];
			child.files.push(structuredClone(copy.tree!.children[0].files[0]));
		});
		expect(runFingerprint(moved)).not.toBe(runFingerprint(base));
	});

	it('changes when money is spent or reserved', () => {
		const base = run('children-admitted');
		expect(runFingerprint(edited(base, (copy) => (copy.spent_usd = '0.0100')))).not.toBe(
			runFingerprint(base)
		);
		expect(runFingerprint(edited(base, (copy) => (copy.reserved_usd = '0.9999')))).not.toBe(
			runFingerprint(base)
		);
	});

	it('changes when the plan is approved', () => {
		const base = run('awaiting-approval');
		expect(runFingerprint(edited(base, (copy) => (copy.tree!.approved = true)))).not.toBe(
			runFingerprint(base)
		);
	});

	it('reads a run that has no plan yet', () => {
		const planning = run('planning');
		expect(planning.tree).toBeNull();
		expect(runFingerprint(planning)).toContain('planning');
	});
});
