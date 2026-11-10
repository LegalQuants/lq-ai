/**
 * A read that starts when someone first looks at something.
 *
 * The run message shows how a run was set up, and the strip above the composer shows the
 * text of a system prompt, only once a fold is opened: nothing is fetched for a run or a
 * prompt that nobody inspects. This is the state of one such read and the small machine
 * that moves it along. It has no component in it, so a test drives it with a stub for the
 * read and no network, and the components that use it only render the state it holds.
 */

/** Where a read stands. While it is read again, or when that fails, the last value is kept. */
export type Load<T> =
	| { status: 'idle' }
	| { status: 'loading'; previous: T | null }
	| { status: 'loaded'; value: T }
	| { status: 'failed'; message: string; previous: T | null };

/** A read that has not been asked for. Assignable to any `Load`, and shared, so it cannot be changed. */
export const IDLE: Load<never> = Object.freeze({ status: 'idle' as const });

/** What there is to show: the value, or the last one while it is read again or the read failed. */
export function shown<T>(state: Load<T>): T | null {
	switch (state.status) {
		case 'loaded':
			return state.value;
		case 'loading':
		case 'failed':
			return state.previous;
		default:
			return null;
	}
}

/** Why a read failed, as a sentence fragment to show. Never an object printed as text. */
export function failureMessage(error: unknown): string {
	if (error instanceof Error && error.message.trim() !== '') return error.message.trim();
	if (typeof error === 'string' && error.trim() !== '') return error.trim();
	return 'The read failed.';
}

/**
 * What a line that is open should do about the trace under it.
 *
 * `readAt` is how many model calls the session had finished when the trace was last asked
 * for, or null when it has not been asked for since it went out of date (never, or Refresh
 * was pressed while the line was closed). `calls` is how many it has finished now. A read
 * that was never made, or failed, is made; one made at another count is made again, because
 * a reply has been recorded since; otherwise there is nothing to do. A closed line is never
 * asked: it reads nothing, and is brought up to date when it is opened.
 */
export function traceReadDue(input: {
	status: Load<unknown>['status'];
	readAt: number | null;
	calls: number;
}): 'open' | 'reload' | null {
	if (input.status === 'idle' || input.status === 'failed') return 'open';
	return input.readAt === input.calls ? null : 'reload';
}

/**
 * One lazily started read. `open` starts it the first time, and again after a failure
 * (opening the fold a second time is a retry); `reload` reads again whatever the state.
 * A read that has been overtaken by a later one, or that finishes after `stop`, changes
 * nothing, and `stop` aborts what is in flight.
 */
export class LazyLoad<T> {
	private current: Load<T>;
	private ticket = 0;
	private controller: AbortController | null = null;
	private stopped = false;

	constructor(
		private readonly read: (signal: AbortSignal) => Promise<T>,
		private readonly onChange: (state: Load<T>) => void,
		initial: Load<T> = IDLE
	) {
		this.current = initial;
	}

	get state(): Load<T> {
		return this.current;
	}

	/** Read now unless a read has been made and has not failed. Safe to call on every opening. */
	open(): void {
		if (this.current.status === 'idle' || this.current.status === 'failed') this.start();
	}

	/** Read again, replacing any read in flight; what was shown stays until the new read lands. */
	reload(): void {
		this.start();
	}

	/** Abort what is in flight and ignore anything that arrives. Used when the fold goes away. */
	stop(): void {
		this.stopped = true;
		this.ticket += 1;
		this.controller?.abort();
		this.controller = null;
	}

	private set(next: Load<T>): void {
		this.current = next;
		this.onChange(next);
	}

	private start(): void {
		if (this.stopped) return;
		this.controller?.abort();
		const controller = new AbortController();
		this.controller = controller;
		this.ticket += 1;
		const ticket = this.ticket;
		const previous = shown(this.current);
		this.set({ status: 'loading', previous });
		let pending: Promise<T>;
		try {
			pending = this.read(controller.signal);
		} catch (error) {
			pending = Promise.reject(error);
		}
		pending.then(
			(value) => {
				if (ticket !== this.ticket || this.stopped) return;
				this.controller = null;
				this.set({ status: 'loaded', value });
			},
			(error: unknown) => {
				if (ticket !== this.ticket || this.stopped) return;
				this.controller = null;
				this.set({ status: 'failed', message: failureMessage(error), previous });
			}
		);
	}
}
