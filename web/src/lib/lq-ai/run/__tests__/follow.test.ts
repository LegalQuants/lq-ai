/**
 * Following one run until it stops moving, with fake timers.
 *
 * What is followed (planning, queued, running, waiting on tasks), what is not (waiting
 * on the owner, uncertain, and every ending), how the delay backs off, what a hidden tab
 * does, and what an error does: keep going through the transient ones, stop for good
 * on 401, 403 and 404.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { OrchestrationChatRun } from '../../api/orchestration';
import { RunFollower, isFatalFollowError, type FollowerOptions } from '../follow';
import { TERMINAL_STATUSES } from '../status';
import { run, withRun } from './fixtures';

/** A run that is moving on its own: its tasks are admitted and waiting to start. */
const MOVING = run('children-admitted');
/** The same run a moment later: only its spend differs, which is enough to count as a change. */
const MOVED = withRun(MOVING, { spent_usd: '0.0100' });
const MOVED_AGAIN = withRun(MOVING, { spent_usd: '0.0200' });

class HttpError extends Error {
	constructor(readonly status?: number) {
		super(`HTTP ${status}`);
	}
}

type Step = OrchestrationChatRun | Error;

function visibility(initiallyHidden = false) {
	const state = { hidden: initiallyHidden, listeners: new Set<() => void>() };
	return {
		state,
		isHidden: () => state.hidden,
		subscribeVisibility: (listener: () => void) => {
			state.listeners.add(listener);
			return () => {
				state.listeners.delete(listener);
			};
		},
		set(hidden: boolean) {
			state.hidden = hidden;
			for (const listener of [...state.listeners]) listener();
		}
	};
}

/** A follower whose fetches answer from a script, repeating the last answer for ever. */
function scripted(script: Step[], options: Partial<FollowerOptions> = {}, hidden = false) {
	const tab = visibility(hidden);
	const loads: number[] = [];
	const signals: AbortSignal[] = [];
	const runs: OrchestrationChatRun[] = [];
	const errors: { error: unknown; fatal: boolean }[] = [];
	const follower = new RunFollower({
		load: (signal) => {
			const step = script[Math.min(loads.length, script.length - 1)];
			loads.push(Date.now());
			signals.push(signal);
			return step instanceof Error ? Promise.reject(step) : Promise.resolve(step);
		},
		onRun: (value) => runs.push(value),
		onError: (error, info) => errors.push({ error, fatal: info.fatal }),
		isHidden: tab.isHidden,
		subscribeVisibility: tab.subscribeVisibility,
		...options
	});
	return { follower, tab, loads, signals, runs, errors };
}

/** A follower whose fetches stay in flight until the test settles them. */
function manual() {
	const tab = visibility();
	const pending: {
		signal: AbortSignal;
		resolve: (value: OrchestrationChatRun) => void;
		reject: (error: unknown) => void;
	}[] = [];
	const runs: OrchestrationChatRun[] = [];
	const errors: unknown[] = [];
	const follower = new RunFollower({
		load: (signal) =>
			new Promise<OrchestrationChatRun>((resolve, reject) => {
				pending.push({ signal, resolve, reject });
			}),
		onRun: (value) => runs.push(value),
		onError: (error) => errors.push(error),
		isHidden: tab.isHidden,
		subscribeVisibility: tab.subscribeVisibility
	});
	return { follower, tab, pending, runs, errors };
}

const gaps = (times: number[]) => times.slice(1).map((time, index) => time - times[index]);
const advance = (ms: number) => vi.advanceTimersByTimeAsync(ms);

beforeEach(() => {
	vi.useFakeTimers();
	vi.setSystemTime(0);
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

describe('what is followed', () => {
	it('looks at once, and again after two seconds, while the run is moving', async () => {
		const { follower, loads, runs } = scripted([MOVING]);
		follower.start();
		expect(loads).toHaveLength(1);
		await advance(0);
		expect(runs).toHaveLength(1);
		await advance(1999);
		expect(loads).toHaveLength(1);
		await advance(1);
		expect(loads).toHaveLength(2);
		follower.stop();
	});

	it.each(['planning', 'queued', 'running', 'waiting_children'])(
		'keeps looking at a run that is %s',
		async (status) => {
			const { follower, loads } = scripted([withRun(MOVING, { status })]);
			follower.start();
			await advance(60_000);
			expect(loads.length).toBeGreaterThan(5);
			follower.stop();
		}
	);

	it.each(['awaiting_approval', 'uncertain'])(
		'looks once at a run that is %s, and then waits to be asked',
		async (status) => {
			const { follower, loads, runs } = scripted([withRun(MOVING, { status })]);
			follower.start();
			await advance(10 * 60_000);
			expect(loads).toHaveLength(1);
			expect(runs).toHaveLength(1);
			expect(vi.getTimerCount()).toBe(0);
			follower.stop();
		}
	);

	it.each([...TERMINAL_STATUSES])(
		'stops looking once the run is %s, with nothing left scheduled',
		async (status) => {
			const ended = withRun(run('completed'), { status });
			const { follower, loads, runs } = scripted([MOVING, ended]);
			follower.start();
			await advance(2000);
			expect(runs.map((value) => value.status)).toEqual([MOVING.status, status]);
			expect(vi.getTimerCount()).toBe(0);
			const seen = loads.length;
			await advance(10 * 60_000);
			expect(loads).toHaveLength(seen);
			expect(follower.run?.status).toBe(status);
			follower.stop();
		}
	);

	it('looks once at a run that has already ended', async () => {
		const { follower, loads } = scripted([run('closed-child')]);
		follower.start();
		await advance(60_000);
		expect(loads).toHaveLength(1);
	});

	it('does not follow a status it has never seen', async () => {
		const { follower, loads } = scripted([withRun(MOVING, { status: 'paused_for_review' })]);
		follower.start();
		await advance(60_000);
		expect(loads).toHaveLength(1);
	});

	it('picks a waiting run up again when asked, and follows it once it is moving', async () => {
		const { follower, loads } = scripted([run('awaiting-approval'), run('queued')]);
		follower.start();
		await advance(60_000);
		expect(loads).toHaveLength(1);
		// The owner approved: the panel asks for a fresh read.
		await follower.refresh();
		await advance(10_000);
		expect(loads.length).toBeGreaterThan(2);
		follower.stop();
	});
});

describe('how often', () => {
	it('backs off while nothing changes, from two seconds to never more than ten', async () => {
		const { follower, loads } = scripted([MOVING]);
		follower.start();
		await advance(180_000);
		const between = gaps(loads);
		expect(between.slice(0, 10)).toEqual([
			2000, 2500, 3100, 3900, 4900, 6100, 7600, 9500, 10000, 10000
		]);
		expect(Math.max(...between)).toBe(10_000);
		expect(between.slice(8).every((gap) => gap === 10_000)).toBe(true);
		follower.stop();
	});

	it('starts again from two seconds as soon as the run moves', async () => {
		const { follower, loads } = scripted([MOVING, MOVING, MOVING, MOVED, MOVED, MOVED_AGAIN]);
		follower.start();
		await advance(30_000);
		// MOVING (first look), unchanged, unchanged, then MOVED: the delay after that read starts over.
		expect(gaps(loads).slice(0, 5)).toEqual([2000, 2500, 3100, 2000, 2500]);
		follower.stop();
	});

	it('has one look scheduled at a time, however often it is asked to refresh', async () => {
		const { follower } = scripted([MOVING]);
		follower.start();
		await advance(0);
		expect(vi.getTimerCount()).toBe(1);
		await follower.refresh();
		await follower.refresh();
		expect(vi.getTimerCount()).toBe(1);
		await advance(30_000);
		expect(vi.getTimerCount()).toBe(1);
		follower.stop();
		expect(vi.getTimerCount()).toBe(0);
	});

	it('reads straight away when asked, and then looks again two seconds later', async () => {
		const { follower, loads } = scripted([MOVING]);
		follower.start();
		await advance(60_000);
		const before = loads.length;
		await follower.refresh();
		expect(loads).toHaveLength(before + 1);
		const refreshedAt = loads[loads.length - 1];
		await advance(10_000);
		expect(loads[before + 1] - refreshedAt).toBe(2000);
		follower.stop();
	});

	// The delay starts again from two seconds when the owner asks, even when the read finds nothing
	// new: the follower forgets what the last look saw, so the read counts as new.
	it('starts the delay again from two seconds after a refresh that finds nothing new, and backs off as before', async () => {
		const { follower, loads } = scripted([MOVING]);
		follower.start();
		// Long enough for the delay to have reached its ceiling.
		await advance(120_000);
		const ceiling = gaps(loads).slice(-3);
		expect(ceiling).toEqual([10_000, 10_000, 10_000]);
		const before = loads.length;
		await follower.refresh();
		await advance(30_000);
		// From the look the refresh made: the same ramp a run's first looks have.
		expect(gaps(loads.slice(before)).slice(0, 4)).toEqual([2000, 2500, 3100, 3900]);
		follower.stop();
	});

	it('does so every time it is asked, not only the first', async () => {
		const { follower, loads } = scripted([MOVING]);
		follower.start();
		await advance(60_000);
		for (let ask = 0; ask < 3; ask += 1) {
			const before = loads.length;
			await follower.refresh();
			const asked = loads[before];
			await advance(2000);
			expect(loads[before + 1] - asked, `ask ${ask}`).toBe(2000);
		}
		follower.stop();
	});
});

describe('a tab that is hidden', () => {
	it('looks once, then waits for the tab to be shown, and reads at once when it is', async () => {
		const { follower, tab, loads } = scripted([MOVING], {}, true);
		follower.start();
		await advance(60_000);
		expect(loads).toHaveLength(1);
		expect(vi.getTimerCount()).toBe(0);
		tab.set(false);
		await advance(0);
		expect(loads).toHaveLength(2);
		await advance(10_000);
		expect(loads.length).toBeGreaterThan(2);
		follower.stop();
	});

	it('stops looking while the tab is hidden, and catches up when it is shown', async () => {
		const { follower, tab, loads } = scripted([MOVING]);
		follower.start();
		await advance(5000);
		const before = loads.length;
		tab.set(true);
		expect(vi.getTimerCount()).toBe(0);
		await advance(5 * 60_000);
		expect(loads).toHaveLength(before);
		tab.set(false);
		await advance(0);
		expect(loads).toHaveLength(before + 1);
		expect(vi.getTimerCount()).toBe(1);
		follower.stop();
	});

	it('does not schedule from a read that arrives while the tab is hidden', async () => {
		const { follower, tab, pending } = manual();
		follower.start();
		tab.set(true);
		pending[0].resolve(MOVING);
		await advance(0);
		expect(vi.getTimerCount()).toBe(0);
		follower.stop();
	});

	it('does not read a run that ended while the tab was away', async () => {
		const { follower, tab, loads } = scripted([run('completed')]);
		follower.start();
		await advance(0);
		tab.set(true);
		tab.set(false);
		await advance(60_000);
		expect(loads).toHaveLength(1);
	});

	it('does read a run that was waiting on the owner, which may have been decided in another tab', async () => {
		const { follower, tab, loads } = scripted([run('awaiting-approval')]);
		follower.start();
		await advance(0);
		tab.set(true);
		tab.set(false);
		await advance(0);
		expect(loads).toHaveLength(2);
		follower.stop();
	});

	it('uses the page’s own visibility when it is not given any', async () => {
		const added: (() => void)[] = [];
		const removed: (() => void)[] = [];
		const page = { hidden: true };
		vi.stubGlobal('document', {
			get hidden() {
				return page.hidden;
			},
			addEventListener: (_event: string, listener: () => void) => added.push(listener),
			removeEventListener: (_event: string, listener: () => void) => removed.push(listener)
		});
		const loads: number[] = [];
		const follower = new RunFollower({
			load: () => {
				loads.push(Date.now());
				return Promise.resolve(MOVING);
			},
			onRun: () => undefined
		});
		follower.start();
		await advance(30_000);
		expect(loads).toHaveLength(1);
		expect(added).toHaveLength(1);
		page.hidden = false;
		added[0]();
		await advance(0);
		expect(loads).toHaveLength(2);
		follower.stop();
		expect(removed).toEqual(added);
	});

	it('works with no page at all, as in a test or on the server', async () => {
		const loads: number[] = [];
		const follower = new RunFollower({
			load: () => {
				loads.push(Date.now());
				return Promise.resolve(MOVING);
			},
			onRun: () => undefined
		});
		follower.start();
		await advance(5000);
		expect(loads.length).toBeGreaterThan(1);
		follower.stop();
	});
});

describe('when a look fails', () => {
	it('keeps going through an error that may pass, saying so, and backs off', async () => {
		const failure = new HttpError(503);
		const { follower, loads, errors, runs } = scripted([MOVING, failure]);
		follower.start();
		await advance(120_000);
		expect(errors.length).toBeGreaterThan(5);
		expect(errors.every((entry) => entry.fatal === false && entry.error === failure)).toBe(true);
		// One good read, then nothing but failures.
		expect(runs).toHaveLength(1);
		const retries = gaps(loads).slice(1);
		for (const gap of retries) {
			expect(gap).toBeGreaterThanOrEqual(2000);
			expect(gap).toBeLessThanOrEqual(10_000);
		}
		expect(retries).toEqual([...retries].sort((a, b) => a - b));
		expect(retries[retries.length - 1]).toBe(10_000);
		follower.stop();
	});

	it.each([undefined, 400, 408, 409, 410, 429, 500, 502, 503, 504])(
		'treats status %s as an error that may pass',
		async (status) => {
			const { follower, loads, errors } = scripted([MOVING, new HttpError(status), MOVING]);
			follower.start();
			await advance(30_000);
			expect(errors[0].fatal).toBe(false);
			expect(follower.running).toBe(true);
			expect(loads.length).toBeGreaterThan(3);
			follower.stop();
		}
	);

	it('recovers when a look works again, and starts again from two seconds when the run has moved', async () => {
		const { follower, loads, errors, runs } = scripted([
			MOVING,
			new HttpError(500),
			new Error('offline'),
			MOVED,
			MOVED_AGAIN
		]);
		follower.start();
		await advance(60_000);
		expect(errors).toHaveLength(2);
		expect(runs.length).toBeGreaterThanOrEqual(3);
		// After MOVED came a different read, so the next look is two seconds later.
		expect(gaps(loads)[3]).toBe(2000);
		follower.stop();
	});

	it('tries again when the very first look fails, so a page opened offline recovers', async () => {
		const { follower, loads, runs } = scripted([new Error('Failed to fetch'), MOVING]);
		follower.start();
		await advance(60_000);
		expect(runs.length).toBeGreaterThanOrEqual(1);
		expect(loads.length).toBeGreaterThan(2);
		follower.stop();
	});

	it('does not retry the very first look while the tab is hidden', async () => {
		const { follower, tab, loads } = scripted([new Error('Failed to fetch'), MOVING], {}, true);
		follower.start();
		await advance(60_000);
		expect(loads).toHaveLength(1);
		tab.set(false);
		await advance(0);
		expect(loads).toHaveLength(2);
		follower.stop();
	});

	it('does not start a retry loop when a manual read fails on a run that is waiting on the owner', async () => {
		const { follower, loads, errors } = scripted([run('awaiting-approval'), new HttpError(500)]);
		follower.start();
		await advance(0);
		await follower.refresh();
		expect(errors).toHaveLength(1);
		await advance(5 * 60_000);
		expect(loads).toHaveLength(2);
	});

	it('treats a fetch that throws before it returns a promise as an error that may pass', async () => {
		const errors: boolean[] = [];
		let calls = 0;
		const follower = new RunFollower({
			load: () => {
				calls += 1;
				throw new Error('could not even start');
			},
			onRun: () => undefined,
			onError: (_error, info) => errors.push(info.fatal),
			isHidden: () => false,
			subscribeVisibility: () => () => undefined
		});
		follower.start();
		await advance(30_000);
		expect(calls).toBeGreaterThan(2);
		expect(errors.every((fatal) => fatal === false)).toBe(true);
		follower.stop();
	});

	it('needs no error handler', async () => {
		const { follower, loads } = scripted([new HttpError(500), MOVING], { onError: undefined });
		follower.start();
		await advance(30_000);
		expect(loads.length).toBeGreaterThan(1);
		follower.stop();
	});
});

describe('when the run is gone or off limits', () => {
	it.each([401, 403, 404])(
		'stops for good on %s, tells the panel it has, and looks no more',
		async (status) => {
			const failure = new HttpError(status);
			const { follower, loads, errors, tab } = scripted([MOVING, failure]);
			follower.start();
			await advance(10_000);
			expect(errors).toEqual([{ error: failure, fatal: true }]);
			expect(follower.running).toBe(false);
			expect(vi.getTimerCount()).toBe(0);
			expect(tab.state.listeners.size).toBe(0);
			const seen = loads.length;
			await advance(10 * 60_000);
			expect(loads).toHaveLength(seen);
		}
	);

	it('stops on the first look too, such as a run opened by a link that no longer works', async () => {
		const { follower, loads, errors } = scripted([new HttpError(404)]);
		follower.start();
		await advance(60_000);
		expect(loads).toHaveLength(1);
		expect(errors[0].fatal).toBe(true);
		expect(follower.running).toBe(false);
	});

	it('can be started again by the Refresh button, and then follows the run as before', async () => {
		const { follower, loads, errors, runs, tab } = scripted([new HttpError(401), MOVING]);
		follower.start();
		await advance(60_000);
		expect(follower.running).toBe(false);
		expect(loads).toHaveLength(1);
		await follower.refresh();
		expect(follower.running).toBe(true);
		expect(tab.state.listeners.size).toBe(1);
		await advance(10_000);
		expect(errors).toHaveLength(1);
		expect(runs.length).toBeGreaterThan(1);
		expect(loads.length).toBeGreaterThan(3);
		follower.stop();
	});

	describe('isFatalFollowError', () => {
		it('is true for 401, 403 and 404, whatever carries the status', () => {
			for (const status of [401, 403, 404]) {
				expect(isFatalFollowError({ status })).toBe(true);
				expect(isFatalFollowError(new HttpError(status))).toBe(true);
			}
		});

		it('is false for everything else, including things that are not errors at all', () => {
			for (const value of [
				{ status: 400 },
				{ status: 410 },
				{ status: 500 },
				{ status: '404' },
				{ status: null },
				{},
				new Error('offline'),
				new TypeError('Failed to fetch'),
				new DOMException('aborted', 'AbortError'),
				null,
				undefined,
				'404',
				404
			]) {
				expect(isFatalFollowError(value), String(JSON.stringify(value))).toBe(false);
			}
		});
	});
});

describe('stopping', () => {
	it('cancels the look that is scheduled and releases the tab', async () => {
		const { follower, loads, tab } = scripted([MOVING]);
		follower.start();
		await advance(0);
		expect(vi.getTimerCount()).toBe(1);
		expect(tab.state.listeners.size).toBe(1);
		follower.stop();
		expect(vi.getTimerCount()).toBe(0);
		expect(tab.state.listeners.size).toBe(0);
		expect(follower.running).toBe(false);
		const seen = loads.length;
		await advance(60_000);
		expect(loads).toHaveLength(seen);
	});

	it('cancels a fetch in flight, and ignores its answer if it arrives anyway', async () => {
		const { follower, pending, runs, errors } = manual();
		follower.start();
		expect(pending).toHaveLength(1);
		expect(pending[0].signal.aborted).toBe(false);
		follower.stop();
		expect(pending[0].signal.aborted).toBe(true);
		pending[0].resolve(MOVING);
		await advance(10_000);
		expect(runs).toHaveLength(0);
		expect(errors).toHaveLength(0);
		expect(vi.getTimerCount()).toBe(0);
		expect(follower.run).toBeNull();
	});

	it('does not report the error of a fetch it cancelled', async () => {
		const { follower, pending, errors } = manual();
		follower.start();
		follower.stop();
		pending[0].reject(new DOMException('aborted', 'AbortError'));
		await advance(10_000);
		expect(errors).toHaveLength(0);
		expect(vi.getTimerCount()).toBe(0);
	});

	it('can be started again, and follows from there', async () => {
		const { follower, loads } = scripted([MOVING]);
		follower.start();
		await advance(0);
		follower.stop();
		follower.start();
		expect(follower.running).toBe(true);
		await advance(5000);
		expect(loads.length).toBeGreaterThan(2);
		follower.stop();
	});

	it('is safe to stop twice, or before it started', () => {
		const { follower } = scripted([MOVING]);
		expect(() => {
			follower.stop();
			follower.stop();
		}).not.toThrow();
		expect(follower.running).toBe(false);
	});
});

describe('starting', () => {
	it('does nothing the second time it is told to start', async () => {
		const { follower, loads, tab } = scripted([MOVING]);
		follower.start();
		follower.start();
		follower.start();
		await advance(0);
		expect(loads).toHaveLength(1);
		expect(tab.state.listeners.size).toBe(1);
		expect(vi.getTimerCount()).toBe(1);
		follower.stop();
	});

	it('has no run until the first read, and then the last one it read', async () => {
		const { follower } = scripted([MOVING, MOVED]);
		expect(follower.run).toBeNull();
		expect(follower.running).toBe(false);
		follower.start();
		await advance(0);
		expect(follower.run).toBe(MOVING);
		await advance(2000);
		expect(follower.run).toBe(MOVED);
		follower.stop();
	});
});

describe('two reads at once', () => {
	it('keeps only the newest: asking again cancels the fetch in flight and ignores its answer', async () => {
		const { follower, pending, runs } = manual();
		follower.start();
		const second = follower.refresh();
		expect(pending).toHaveLength(2);
		expect(pending[0].signal.aborted).toBe(true);
		expect(pending[1].signal.aborted).toBe(false);
		pending[1].resolve(MOVED);
		await second;
		// The cancelled fetch answers late, with an older run.
		pending[0].resolve(MOVING);
		await advance(0);
		expect(runs).toEqual([MOVED]);
		expect(follower.run).toBe(MOVED);
		expect(vi.getTimerCount()).toBe(1);
		follower.stop();
	});

	it('does not let the cancelled fetch’s failure schedule or report anything', async () => {
		const { follower, pending, errors } = manual();
		follower.start();
		const second = follower.refresh();
		pending[0].reject(new HttpError(500));
		pending[1].resolve(MOVING);
		await second;
		await advance(0);
		expect(errors).toHaveLength(0);
		expect(vi.getTimerCount()).toBe(1);
		follower.stop();
	});
});
