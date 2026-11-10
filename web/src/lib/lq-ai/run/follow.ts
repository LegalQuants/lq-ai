/**
 * Follows one run until it stops moving, with no fixed limit on how long.
 *
 * Framework-free so the timing rules can be tested with fake timers. The run
 * component creates one per run, starts it on mount and stops it on destroy.
 *
 * Rules (see `polling.ts`): look at once; while the run is planning, queued,
 * running or waiting on tasks, look again after 2 s, backing off to at most 10 s
 * while nothing changes; pause while the tab is hidden and look straight away
 * when it is shown again; keep going through transient errors; stop for good on
 * 401, 403 and 404.
 */
import type { OrchestrationChatRun } from '../api/orchestration';
import { nextPollDelay, pollDecision, runFingerprint } from './polling';
import { isActiveStatus } from './status';

export interface FollowerOptions {
	/** Fetch the run. Must honour the abort signal. */
	load: (signal: AbortSignal) => Promise<OrchestrationChatRun>;
	/** Called with every run read that was fetched. */
	onRun: (run: OrchestrationChatRun) => void;
	/** Called when a fetch failed. `fatal` means the follower has stopped. */
	onError?: (error: unknown, info: { fatal: boolean }) => void;
	/** Whether the tab is hidden. Defaults to `document.hidden`. */
	isHidden?: () => boolean;
	/** Subscribe to the tab being shown or hidden. Defaults to `visibilitychange`. */
	subscribeVisibility?: (listener: () => void) => () => void;
}

/** A run that is gone or off limits will not come back by asking again. */
export function isFatalFollowError(error: unknown): boolean {
	const status = (error as { status?: unknown } | null)?.status;
	return status === 401 || status === 403 || status === 404;
}

function documentHidden(): boolean {
	return typeof document !== 'undefined' && document.hidden === true;
}

function subscribeDocumentVisibility(listener: () => void): () => void {
	if (typeof document === 'undefined') return () => undefined;
	document.addEventListener('visibilitychange', listener);
	return () => document.removeEventListener('visibilitychange', listener);
}

export class RunFollower {
	private latest: OrchestrationChatRun | null = null;
	private timer: ReturnType<typeof setTimeout> | undefined;
	private controller: AbortController | undefined;
	private stopped = true;
	private unchanged = 0;
	private failures = 0;
	private fingerprint = '';
	private unsubscribe: (() => void) | undefined;

	constructor(private readonly options: FollowerOptions) {}

	/** The last run read this follower fetched. */
	get run(): OrchestrationChatRun | null {
		return this.latest;
	}

	get running(): boolean {
		return !this.stopped;
	}

	/** Begin following. A no-op when already following. */
	start(): void {
		if (!this.stopped) return;
		void this.refresh();
	}

	/** Stop for good: cancel the pending look and any fetch in flight. */
	stop(): void {
		this.stopped = true;
		clearTimeout(this.timer);
		this.timer = undefined;
		this.controller?.abort();
		this.controller = undefined;
		this.unsubscribe?.();
		this.unsubscribe = undefined;
	}

	/**
	 * Look now and start the delay again from two seconds. Also restarts a
	 * follower that gave up, so a Refresh button can recover from an error.
	 */
	async refresh(): Promise<void> {
		this.unchanged = 0;
		this.failures = 0;
		// Forget what the last look saw, so this one counts as new and the next
		// look comes two seconds later even when the run has not moved.
		this.fingerprint = '';
		if (this.stopped) {
			this.stopped = false;
			this.unsubscribe = (this.options.subscribeVisibility ?? subscribeDocumentVisibility)(() =>
				this.visibilityChanged()
			);
		}
		await this.look();
	}

	private hidden(): boolean {
		return (this.options.isHidden ?? documentHidden)();
	}

	private visibilityChanged(): void {
		if (this.stopped) return;
		if (this.hidden()) {
			clearTimeout(this.timer);
			this.timer = undefined;
			return;
		}
		// Shown again: catch up at once if the run could have moved while we were away.
		if (!this.latest || isActiveStatus(this.latest.status)) {
			this.unchanged = 0;
			void this.look();
		}
	}

	private async look(): Promise<void> {
		if (this.stopped) return;
		clearTimeout(this.timer);
		this.timer = undefined;
		this.controller?.abort();
		const controller = new AbortController();
		this.controller = controller;
		try {
			const run = await this.options.load(controller.signal);
			if (this.stopped || controller.signal.aborted) return;
			const fingerprint = runFingerprint(run);
			this.unchanged = fingerprint === this.fingerprint ? this.unchanged + 1 : 0;
			this.fingerprint = fingerprint;
			this.failures = 0;
			this.latest = run;
			this.options.onRun(run);
		} catch (error) {
			if (this.stopped || controller.signal.aborted) return;
			const fatal = isFatalFollowError(error);
			this.failures += 1;
			this.options.onError?.(error, { fatal });
			if (fatal) {
				this.stop();
				return;
			}
		}
		this.schedule();
	}

	private schedule(): void {
		clearTimeout(this.timer);
		this.timer = undefined;
		if (this.stopped) return;
		const status = this.latest?.status;
		if (status !== undefined) {
			// A run that is not moving on its own is not looked at again until asked.
			if (pollDecision({ status, hidden: this.hidden() }) !== 'poll') return;
		} else if (this.failures === 0 || this.hidden()) {
			return;
		}
		const attempts = this.failures > 0 ? this.failures : this.unchanged;
		this.timer = setTimeout(() => void this.look(), nextPollDelay(attempts));
	}
}
