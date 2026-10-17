/**
 * The read that starts when a fold is first opened: when it asks, when it does not ask
 * again, what it keeps while it reads again, and that a late or stopped read changes nothing.
 * Driven with a stub for the read, so there is no network and every timing is in the test.
 */
import { describe, expect, it, vi } from 'vitest';

import { IDLE, LazyLoad, failureMessage, shown, traceReadDue, type Load } from '../load';

/** A read the test settles by hand, remembering the signal it was given. */
function deferred<T>() {
	let resolve!: (value: T) => void;
	let reject!: (error: unknown) => void;
	const promise = new Promise<T>((ok, bad) => {
		resolve = ok;
		reject = bad;
	});
	return { promise, resolve, reject };
}

function harness<T>(initial?: Load<T>) {
	const reads: { signal: AbortSignal; pending: ReturnType<typeof deferred<T>> }[] = [];
	const states: Load<T>[] = [];
	const loader = new LazyLoad<T>(
		(signal) => {
			const pending = deferred<T>();
			reads.push({ signal, pending });
			return pending.promise;
		},
		(state) => states.push(state),
		initial
	);
	return { loader, reads, states };
}

/** Let the promise callbacks run. */
const settle = () => new Promise((done) => setTimeout(done, 0));

describe('a read nobody has asked for', () => {
	it('starts idle and reads nothing until it is opened', () => {
		const { loader, reads, states } = harness<string>();
		expect(loader.state).toEqual({ status: 'idle' });
		expect(reads).toHaveLength(0);
		expect(states).toEqual([]);
		expect(shown(loader.state)).toBeNull();
	});

	it('has an idle state that fits any kind of read', () => {
		const text: Load<string> = IDLE;
		const number: Load<number> = IDLE;
		expect(text).toEqual(number);
	});

	it('has one idle state that everything shares, so it cannot be changed', () => {
		expect(Object.isFrozen(IDLE)).toBe(true);
		expect(() => {
			(IDLE as { status: string }).status = 'loaded';
		}).toThrow();
		expect(IDLE.status).toBe('idle');
	});
});

describe('opening', () => {
	it('reads once, shows that it is loading, then shows what arrived', async () => {
		const { loader, reads, states } = harness<string>();
		loader.open();
		expect(reads).toHaveLength(1);
		expect(states).toEqual([{ status: 'loading', previous: null }]);
		reads[0].pending.resolve('the text');
		await settle();
		expect(states.at(-1)).toEqual({ status: 'loaded', value: 'the text' });
		expect(loader.state).toEqual({ status: 'loaded', value: 'the text' });
		expect(shown(loader.state)).toBe('the text');
	});

	it('does not read again when opened again, while it loads or once it has loaded', async () => {
		const { loader, reads } = harness<string>();
		loader.open();
		loader.open();
		loader.open();
		expect(reads).toHaveLength(1);
		reads[0].pending.resolve('x');
		await settle();
		loader.open();
		loader.open();
		expect(reads).toHaveLength(1);
	});

	it('reads again when opened after a failure, since that is the way to retry', async () => {
		const { loader, reads, states } = harness<string>();
		loader.open();
		reads[0].pending.reject(new Error('The network is down'));
		await settle();
		expect(states.at(-1)).toEqual({
			status: 'failed',
			message: 'The network is down',
			previous: null
		});
		loader.open();
		expect(reads).toHaveLength(2);
		reads[1].pending.resolve('back');
		await settle();
		expect(loader.state).toEqual({ status: 'loaded', value: 'back' });
	});

	it('does not read again for a value it was given to start with', () => {
		const { loader, reads } = harness<string>({ status: 'loaded', value: 'given' });
		loader.open();
		expect(reads).toHaveLength(0);
		expect(shown(loader.state)).toBe('given');
	});

	it('says why a read failed in words, whatever was thrown', async () => {
		for (const [thrown, message] of [
			[new Error('  Not found  '), 'Not found'],
			['plain text', 'plain text'],
			[new Error(''), 'The read failed.'],
			[{ status: 500 }, 'The read failed.'],
			[null, 'The read failed.']
		] as const) {
			const { loader, reads } = harness<string>();
			loader.open();
			reads[0].pending.reject(thrown);
			await settle();
			expect(loader.state, JSON.stringify(thrown)).toMatchObject({ status: 'failed', message });
		}
		expect(failureMessage(undefined)).toBe('The read failed.');
	});

	it('treats a read that throws before it returns a promise as a failed read', () => {
		const states: Load<string>[] = [];
		const loader = new LazyLoad<string>(
			() => {
				throw new Error('could not even start');
			},
			(state) => states.push(state)
		);
		expect(() => loader.open()).not.toThrow();
		expect(states[0]).toEqual({ status: 'loading', previous: null });
	});
});

describe('reading again', () => {
	it('keeps what was shown while the new read is out, and when it fails', async () => {
		const { loader, reads, states } = harness<string>();
		loader.open();
		reads[0].pending.resolve('first');
		await settle();
		loader.reload();
		expect(states.at(-1)).toEqual({ status: 'loading', previous: 'first' });
		expect(shown(loader.state)).toBe('first');
		reads[1].pending.reject(new Error('gone'));
		await settle();
		expect(states.at(-1)).toEqual({ status: 'failed', message: 'gone', previous: 'first' });
		expect(shown(loader.state)).toBe('first');
		loader.reload();
		reads[2].pending.resolve('second');
		await settle();
		expect(loader.state).toEqual({ status: 'loaded', value: 'second' });
	});

	it('reads even when the last read has not finished, and aborts that one', () => {
		const { loader, reads } = harness<string>();
		loader.open();
		loader.reload();
		expect(reads).toHaveLength(2);
		expect(reads[0].signal.aborted).toBe(true);
		expect(reads[1].signal.aborted).toBe(false);
	});

	it('ignores a slow early read that finishes after a later one', async () => {
		const { loader, reads, states } = harness<string>();
		loader.open();
		loader.reload();
		reads[1].pending.resolve('newer');
		await settle();
		reads[0].pending.resolve('older');
		await settle();
		expect(loader.state).toEqual({ status: 'loaded', value: 'newer' });
		expect(states.filter((state) => state.status === 'loaded')).toHaveLength(1);
	});

	it('ignores a failure of an early read that finishes after a later one', async () => {
		const { loader, reads } = harness<string>();
		loader.open();
		loader.reload();
		reads[1].pending.resolve('newer');
		await settle();
		reads[0].pending.reject(new Error('aborted'));
		await settle();
		expect(loader.state).toEqual({ status: 'loaded', value: 'newer' });
	});
});

describe('stopping', () => {
	it('aborts the read in flight and changes nothing when it finishes', async () => {
		const onChange = vi.fn();
		const pending = deferred<string>();
		let signal: AbortSignal | undefined;
		const loader = new LazyLoad<string>((given) => {
			signal = given;
			return pending.promise;
		}, onChange);
		loader.open();
		onChange.mockClear();
		loader.stop();
		expect(signal?.aborted).toBe(true);
		pending.resolve('late');
		await settle();
		expect(onChange).not.toHaveBeenCalled();
		expect(loader.state).toMatchObject({ status: 'loading' });
	});

	it('reads nothing more once stopped, however it is asked', () => {
		const { loader, reads } = harness<string>();
		loader.stop();
		loader.open();
		loader.reload();
		expect(reads).toHaveLength(0);
	});
});

describe('what an open line does about the trace under it', () => {
	// `readAt` is how many model calls the session had finished when the trace was last asked
	// for. The component calls this only for a line that is open, so a closed line reads nothing.
	it('reads a trace that was never read, or whose read failed', () => {
		expect(traceReadDue({ status: 'idle', readAt: null, calls: 0 })).toBe('open');
		expect(traceReadDue({ status: 'failed', readAt: 2, calls: 2 })).toBe('open');
	});

	it('leaves a trace alone that was read at the present count', () => {
		expect(traceReadDue({ status: 'loaded', readAt: 2, calls: 2 })).toBeNull();
		expect(traceReadDue({ status: 'loading', readAt: 0, calls: 0 })).toBeNull();
	});

	it('reads again when a call has finished since, also when that happened while the line was closed', () => {
		// Opened before the task started (read at 0), closed, three calls finish, opened again.
		expect(traceReadDue({ status: 'loaded', readAt: 0, calls: 3 })).toBe('reload');
		// A read still on its way that was asked for at an older count is replaced.
		expect(traceReadDue({ status: 'loading', readAt: 1, calls: 2 })).toBe('reload');
	});

	it('reads again after Refresh was pressed while the line was closed', () => {
		// Refresh sets `readAt` to null: out of date whatever the count.
		expect(traceReadDue({ status: 'loaded', readAt: null, calls: 2 })).toBe('reload');
	});
});
